"""Host contracts using fake memory and fake completions; never calls a provider."""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from memory_system.conversation import ConversationHost, validate_grounded_proposals
from memory_system.providers import ChatResult


NOW = datetime(2026, 11, 16, tzinfo=timezone.utc).isoformat()


class FakeProvider:
    def __init__(self, extraction=None, selection=None, semantic_review=None, retraction_review=None):
        self.calls = []
        self.extraction = extraction if extraction is not None else {"candidate_memories": []}
        self.selection = selection
        self.semantic_review = semantic_review
        self.retraction_review = retraction_review
        self.answers = 0

    def complete(self, messages, **options):
        request = {"messages": deepcopy(messages), **deepcopy(options)}
        self.calls.append(request)
        if options.get("json_mode"):
            payload = json.loads(messages[-1]["content"])
            if "assertions_to_compare" in payload:
                result = self.retraction_review if self.retraction_review is not None else {
                    "decisions": [{"memory_id": item["memory_id"], "relation": "contradicts",
                                   "reason": "fake independent contradiction check",
                                   "old_span": str(item["assertion"]["value"]),
                                   "new_span": payload["current_user_turn"]}
                                  for item in payload["assertions_to_compare"]]}
            elif "proposal_candidates" in payload:
                result = self.semantic_review if self.semantic_review is not None else {
                    "decisions": [{"candidate_index": i, "relation": "supports",
                        "evidence_kind": "sustained_preference" if c.get("layer") == "preference" else "project_fact",
                        "retention": c.get("retention", "turn"), "reason": "fake contract judgment"}
                        for i, c in enumerate(payload["proposal_candidates"])], "memory_retractions": []}
            elif "candidates" in payload:
                result = self.selection if self.selection is not None else {
                    "memory_ids": [item["memory_id"] for item in payload["candidates"][:10]]}
            else:
                result = self.extraction
            content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        else:
            self.answers += 1
            content = f"fake-answer-{self.answers}"
        return ChatResult(content=content, model="fake-local", response_id=f"fake-{len(self.calls)}",
                          usage={}, latency_ms=0, finish_reason="stop",
                          request_metadata={"request_body": request})


class FakeGateway:
    def __init__(self, candidates=None, compiled="governed-context-sentinel"):
        self.candidates = candidates or []
        self.compiled = compiled
        self.ingests = []
        self.queries = []
        self.prompts = []
        self.final_denied_ids = set()

    def slots(self):
        return [{"key": "detail_preference", "type": "preference",
                 "description": "Response depth", "examples": ["concise", "detailed"]}]

    def selected(self, candidate_memory_ids):
        if candidate_memory_ids is None:
            return deepcopy(self.candidates)
        return deepcopy([item for item in self.candidates if item["memory_id"] in candidate_memory_ids
                         and item["memory_id"] not in self.final_denied_ids])

    def query(self, text, session_id, timestamp, *, limit=20, candidate_memory_ids=None):
        self.queries.append({"text": text, "session_id": session_id, "timestamp": timestamp,
                             "limit": limit, "candidate_memory_ids": deepcopy(candidate_memory_ids)})
        return {"candidates": self.selected(candidate_memory_ids), "model_candidates": self.selected(candidate_memory_ids), "audit_only": "unsent-audit-sentinel"}

    def ingest(self, text, session_id, timestamp, turn_id, payload):
        self.ingests.append({"text": text, "session_id": session_id, "timestamp": timestamp,
                             "turn_id": turn_id, "payload": deepcopy(payload)})
        return {"operations": [], "persisted_records": []}

    def prompt(self, text, session_id, timestamp, *, candidate_memory_ids=None):
        self.prompts.append({"text": text, "session_id": session_id, "timestamp": timestamp,
                             "candidate_memory_ids": deepcopy(candidate_memory_ids)})
        compiled = self.compiled if self.selected(candidate_memory_ids) else "no-stored-memory"
        return {"system_guidance": "governed-guidance-sentinel", "assembled_prompt": compiled,
                "memory_context": {"source_notes": self.selected(candidate_memory_ids)}}

    def export(self):
        raise AssertionError("The conversation host must not read an audit export to answer.")


def candidate(key, value, evidence, **extra):
    return {"layer": "semantic_fact", "key": key, "value": value, "confidence": .9,
            "authority": "user_explicit", "sensitivity": "personal", "evidence": evidence, "retention": "durable", **extra}


class ConversationHostTest(unittest.TestCase):
    def turn(self, host, index, *, session="session-a", text=None):
        return host.turn(text=text or f"user-sentinel-{index}", turn_id=f"turn-{index}",
                         session_id=session, timestamp=NOW)

    def json_calls(self, provider, kind):
        return [json.loads(call["messages"][-1]["content"]) for call in provider.calls
                if call.get("json_mode") and kind in json.loads(call["messages"][-1]["content"])]

    def test_both_extraction_and_answer_receive_only_two_recent_pairs(self):
        provider = FakeProvider()
        memory = FakeGateway([{"memory_id": "fact", "key": "project_fact", "value": "persisted"}])
        host = ConversationHost(provider, memory=memory, history_pairs=2)
        for index in range(1, 5):
            trace = self.turn(host, index)
        expected = [
            {"role": "user", "content": "user-sentinel-2"},
            {"role": "assistant", "content": "fake-answer-2"},
            {"role": "user", "content": "user-sentinel-3"},
            {"role": "assistant", "content": "fake-answer-3"},
        ]
        extraction = self.json_calls(provider, "current_user_turn")[-1]
        self.assertEqual(extraction["recent_context"], expected)
        self.assertEqual(self.json_calls(provider, "candidates")[-1]["recent_context"], expected)
        self.assertEqual(provider.calls[-1]["messages"][1:-1], expected)
        self.assertEqual(trace["recent_context"], expected)
        self.assertNotIn("user-sentinel-1", json.dumps(provider.calls[-3:], ensure_ascii=False))
        self.assertEqual(len(host.history), 4)

    def test_session_change_clears_history_for_extraction_and_answer(self):
        provider = FakeProvider()
        memory = FakeGateway([{"memory_id": "fact", "key": "project_fact", "value": "persisted"}])
        host = ConversationHost(provider, memory=memory)
        self.turn(host, 1)
        trace = self.turn(host, 2, session="session-b")
        extraction = self.json_calls(provider, "current_user_turn")[-1]
        self.assertEqual(extraction["recent_context"], [])
        self.assertEqual(self.json_calls(provider, "candidates")[-1]["recent_context"], [])
        self.assertEqual(trace["recent_context"], [])
        self.assertEqual(len(provider.calls[-1]["messages"]), 2)
        self.assertNotIn("user-sentinel-1", json.dumps(provider.calls[-3:]))
        self.assertEqual(memory.ingests[-1]["session_id"], "session-b")

    def test_semantic_correction_retracts_old_assertion_without_reinforcing_or_reversing_it(self):
        quote = "不是一概越短越好"
        memory = FakeGateway([{"memory_id": "old", "key": "detail_preference", "type": "preference",
                              "value": "Keep the response concise.",
                              "assertion": {"key": "detail_preference", "value": "concise"}}])
        provider = FakeProvider({"candidate_memories": [candidate("detail_preference", "concise", quote,
            layer="preference")]}, semantic_review={"decisions": [{"candidate_index": 0,
                "relation": "contradicts", "evidence_kind": "correction", "retention": "durable"}],
            "memory_retractions": [{"memory_id": "old", "evidence": quote, "reason": "overgeneralization"}]})
        trace = self.turn(ConversationHost(provider, memory=memory), 1, text=quote)
        self.assertEqual(memory.ingests[0]["payload"]["candidate_memories"], [])
        self.assertEqual(memory.ingests[0]["payload"]["memory_retractions"][0]["memory_id"], "old")
        sent = self.json_calls(provider, "proposal_candidates")[0]
        self.assertEqual(sent["current_user_turn"], quote)
        self.assertEqual(sent["proposal_candidates"][0]["value"], "concise")
        self.assertEqual(trace["semantic_review"]["request_metadata"]["request_body"], provider.calls[1])

    def test_invalid_project_replacement_does_not_retract_the_existing_fact_first(self):
        text = "第一轮改为仅本人试用。"
        old = {"memory_id": "old-scope", "key": "project_pilot_scope", "type": "state",
               "value": "本人及两位协作者试用", "authority": "user_explicit",
               "assertion": {"key": "project_pilot_scope", "value": "本人及两位协作者试用"}}
        memory = FakeGateway([old])
        provider = FakeProvider({"candidate_memories": [candidate(
            "project_pilot_scope", "仅本人试用", "不在当前原文里的引用")]}, semantic_review={
                "decisions": [{"candidate_index": 0, "relation": "supports",
                    "evidence_kind": "project_fact", "retention": "durable"}],
                "memory_retractions": [{"memory_id": "old-scope", "evidence": text,
                                       "reason": "project scope updated"}]})
        trace = self.turn(ConversationHost(provider, memory=memory), 1, text=text)
        payload = memory.ingests[0]["payload"]
        self.assertEqual(payload["candidate_memories"], [])
        self.assertEqual(payload.get("memory_retractions", []), [])
        self.assertIn("evidence_not_in_current_user_turn", [item["reason"] for item in trace["rejected_proposals"]])
        self.assertIn("replacement_uses_governed_supersession", [item["reason"] for item in trace["rejected_proposals"]])
        self.assertEqual(self.json_calls(provider, "assertions_to_compare"), [])
        self.assertEqual(memory.candidates, [old])

    def test_failed_independent_retraction_review_preserves_valid_new_fact(self):
        text = "不是任何时候都要短。我已完成导入页。"
        verdicts = [
            "broken-json",
            {"decisions": []},
            {"decisions": [{"memory_id": "old", "relation": "compatible", "reason": "can coexist"}]},
            {"decisions": [{"memory_id": "old", "relation": "uncertain", "reason": "insufficient"}]},
            {"decisions": [{"memory_id": "unknown", "relation": "contradicts", "reason": "wrong id"}]},
            {"decisions": [{"memory_id": "old", "relation": "contradicts"},
                           {"memory_id": "old", "relation": "compatible"}]},
        ]
        for verdict in verdicts:
            with self.subTest(verdict=verdict):
                memory = FakeGateway([{"memory_id": "old", "key": "detail_preference", "type": "preference",
                    "value": "Keep the response concise.", "authority": "user_implicit",
                    "assertion": {"key": "detail_preference", "value": "concise"}}])
                provider = FakeProvider({"candidate_memories": [candidate(
                    "project_import_progress", "导入页已完成", "我已完成导入页", retention="until_changed")]},
                    semantic_review={"decisions": [{"candidate_index": 0, "relation": "supports",
                        "evidence_kind": "project_fact", "retention": "until_changed"}],
                        "memory_retractions": [{"memory_id": "old", "evidence": "不是任何时候都要短",
                                               "reason": "prior preference may be too broad"}]},
                    retraction_review=verdict)
                trace = self.turn(ConversationHost(provider, memory=memory), 1, text=text)
                payload = memory.ingests[0]["payload"]
                self.assertEqual([(item["key"], item["value"]) for item in payload["candidate_memories"]],
                                 [("project_import_progress", "导入页已完成")])
                self.assertEqual(payload.get("memory_retractions", []), [])
                self.assertEqual(trace["status"], "completed")
                self.assertTrue(trace["rejected_proposals"])
                sent = self.json_calls(provider, "assertions_to_compare")[0]
                self.assertEqual(sent["assertions_to_compare"][0]["assertion"],
                                 {"key": "detail_preference", "value": "concise"})
                self.assertNotIn("Keep the response concise.", json.dumps(sent))
                self.assertEqual(set(sent["assertions_to_compare"][0]), {"memory_id", "assertion"})
                self.assertNotIn("prior preference may be too broad", json.dumps(sent))

    def test_invalid_raw_extraction_cannot_erase_existing_project_fact(self):
        text = "第一轮改为仅本人试用。"
        memory = FakeGateway([{"memory_id": "old-scope", "key": "project_pilot_scope", "type": "state",
            "value": "三人试用", "assertion": {"key": "project_pilot_scope", "value": "三人试用"}}])
        provider = FakeProvider({"candidate_memories": [candidate(
            "project_pilot_scope", "仅本人试用", text, confidence="invalid")]},
            semantic_review={"decisions": [], "memory_retractions": [
                {"memory_id": "old-scope", "evidence": text, "reason": "scope changed"}]})
        trace = self.turn(ConversationHost(provider, memory=memory), 1, text=text)
        self.assertEqual(trace["extraction_error"]["reason"], "invalid_extraction")
        self.assertEqual(memory.ingests[0]["payload"]["candidate_memories"], [])
        self.assertEqual(memory.ingests[0]["payload"].get("memory_retractions", []), [])
        self.assertEqual(trace["status"], "completed")

    def test_malformed_semantic_review_does_not_default_to_original_extraction(self):
        provider = FakeProvider({"candidate_memories": [candidate("project_decision", "A", "选A")]},
                                semantic_review="broken-json")
        memory = FakeGateway()
        trace = self.turn(ConversationHost(provider, memory=memory), 1, text="选A")
        self.assertEqual(memory.ingests[0]["payload"], {"candidate_memories": []})
        self.assertEqual(trace["rejected_proposals"][0]["reason"], "invalid_semantic_review")

    def test_missing_retention_fails_closed(self):
        proposed = candidate("project_once", "原文", "原文")
        proposed.pop("retention")
        accepted, rejected = validate_grounded_proposals({"candidate_memories": [proposed]}, "原文", NOW)
        self.assertEqual(accepted["candidate_memories"], [])
        self.assertEqual(rejected[0]["reason"], "invalid_retention")

    def test_revocation_between_query_and_final_prompt_cannot_readd_evidence(self):
        class RevokingGateway(FakeGateway):
            def prompt(inner, *args, **kwargs):
                inner.final_denied_ids.add("revoked")
                return super(RevokingGateway, inner).prompt(*args, **kwargs)
        memory = RevokingGateway([{"memory_id": "revoked", "key": "project_fact",
            "value": "old-value-sentinel", "evidence": "old-quote-sentinel"}])
        provider = FakeProvider()
        self.turn(ConversationHost(provider, memory=memory), 1)
        system = provider.calls[-1]["messages"][0]["content"]
        self.assertIn("no-stored-memory", system)
        self.assertNotIn("old-value-sentinel", system)
        self.assertNotIn("old-quote-sentinel", system)

    def test_all_model_stages_use_safe_projection_not_raw_query_records(self):
        class SafeProjectionGateway(FakeGateway):
            def query(inner, *args, **kwargs):
                result = super(SafeProjectionGateway, inner).query(*args, **kwargs)
                result["model_candidates"] = [{"memory_id": "private", "key": "current_emotional_state",
                    "value": "Use only as aggregate context"}]
                return result
            def prompt(inner, *args, **kwargs):
                return {"assembled_prompt": "Use only as aggregate context",
                        "memory_context": {"source_notes": [{"memory_id": "private",
                            "value": "Use only as aggregate context"}]}}
        provider = FakeProvider()
        memory = SafeProjectionGateway([{"memory_id": "private", "value": "private-value-sentinel",
                                        "evidence": "private-evidence-sentinel"}])
        self.turn(ConversationHost(provider, memory=memory), 1)
        sent = json.dumps(provider.calls)
        self.assertNotIn("private-value-sentinel", sent)
        self.assertNotIn("private-evidence-sentinel", sent)

    def test_recent_only_arm_does_not_extract_or_request_memory(self):
        provider = FakeProvider()
        host = ConversationHost(provider, memory=None, history_pairs=0)
        self.turn(host, 1)
        trace = self.turn(host, 2)
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(all(not call.get("json_mode") for call in provider.calls))
        self.assertEqual(len(provider.calls[-1]["messages"]), 2)
        self.assertFalse(trace["memory_enabled"])
        self.assertNotIn("extraction", trace)

    def test_grounded_project_fact_uses_governed_context_and_exact_sent_request_trace(self):
        fact = {"key": "project_test_decision", "value": "仅验证通用事实交付契约",
                "authority": "user_explicit", "memory_id": "memory-test",
                "source_turn_ids": ["earlier-turn"], "private_debug": "unsent-debug-sentinel"}
        memory = FakeGateway([fact], compiled="仅验证通用事实交付契约 [source:earlier-turn]")
        provider = FakeProvider()
        trace = self.turn(ConversationHost(provider, memory=memory), 1, text="继续解释原来的选择。")
        extraction = json.loads(provider.calls[0]["messages"][-1]["content"])
        self.assertEqual(extraction["available_memory_summary"][0]["value"], fact["value"])
        answer_messages = provider.calls[-1]["messages"]
        self.assertIn(memory.compiled, answer_messages[0]["content"])
        self.assertEqual(trace["answer"]["request_metadata"]["request_body"]["messages"], answer_messages)
        self.assertNotIn("unsent-debug-sentinel", json.dumps(provider.calls, ensure_ascii=False))
        self.assertNotIn("unsent-audit-sentinel", json.dumps(provider.calls, ensure_ascii=False))
        self.assertEqual(memory.ingests[0]["turn_id"], "turn-1")
        self.assertEqual(trace["selected_memory_ids"], ["memory-test"])
        self.assertEqual(memory.queries[-1]["candidate_memory_ids"], ["memory-test"])
        self.assertEqual(memory.prompts[-1]["candidate_memory_ids"], ["memory-test"])

    def test_selector_only_uses_governed_pool_ids_and_final_sources(self):
        selected = {"memory_id": "allowed", "key": "project_choice", "value": "project choice",
                    "authority": "user_explicit", "evidence": "allowed-source-quote",
                    "source_turn_ids": ["allowed-source"]}
        unrelated = {"memory_id": "unselected", "key": "project_other", "value": "other topic",
                     "evidence": "unselected-source-quote", "source_turn_ids": ["unselected-source"]}
        revoked = {"memory_id": "revoked", "key": "project_revoked", "value": "revoked topic",
                   "evidence": "revoked-source-quote", "source_turn_ids": ["revoked-source"]}
        memory = FakeGateway([selected, unrelated, revoked], compiled="compiled-selected-project-choice")
        memory.final_denied_ids.add("revoked")
        provider = FakeProvider(selection={"memory_ids": ["allowed", "unknown-id", "allowed", 3, "revoked"]})
        trace = self.turn(ConversationHost(provider, memory=memory), 1)
        self.assertEqual(trace["selected_memory_ids"], ["allowed", "revoked"])
        self.assertEqual(trace["selection_rejected_ids"], ["unknown-id", 3])
        self.assertEqual(memory.queries[-1]["candidate_memory_ids"], ["allowed", "revoked"])
        self.assertEqual(memory.prompts[-1]["candidate_memory_ids"], ["allowed", "revoked"])
        system = provider.calls[-1]["messages"][0]["content"]
        self.assertIn(memory.compiled, system)
        self.assertIn("allowed-source-quote", system)
        self.assertNotIn("unselected-source-quote", system)
        self.assertNotIn("revoked-source-quote", system)
        selector = self.json_calls(provider, "candidates")[0]
        self.assertEqual(set(selector), {"query", "timestamp", "recent_context", "candidates"})
        self.assertEqual({item["memory_id"] for item in selector["candidates"]}, {"allowed", "unselected", "revoked"})

    def test_invalid_selector_output_fails_closed_without_fallback_to_pool(self):
        for result in ("not JSON", {}, {"memory_ids": "allowed"}, {"memory_ids": ["unknown-only"]}):
            with self.subTest(result=result):
                memory = FakeGateway([{"memory_id": "allowed", "key": "project_secret",
                                       "value": "stored-only-sentinel", "evidence": "source-only-sentinel"}])
                provider = FakeProvider(selection=result)
                trace = self.turn(ConversationHost(provider, memory=memory), 1)
                self.assertEqual(trace["selected_memory_ids"], [])
                self.assertEqual(memory.queries[-1]["candidate_memory_ids"], [])
                self.assertEqual(memory.prompts[-1]["candidate_memory_ids"], [])
                self.assertEqual(trace["retrieval_after"]["candidates"], [])
                self.assertNotIn("stored-only-sentinel", provider.calls[-1]["messages"][0]["content"])
                self.assertNotIn("source-only-sentinel", provider.calls[-1]["messages"][0]["content"])

    def test_selector_is_bounded_to_ten_distinct_known_ids(self):
        memory = FakeGateway([{"memory_id": f"id-{i}"} for i in range(20)])
        provider = FakeProvider(selection={"memory_ids": ["id-0"] * 3 + [f"id-{i}" for i in range(20)]})
        trace = self.turn(ConversationHost(provider, memory=memory), 1)
        self.assertEqual(trace["selected_memory_ids"], [f"id-{i}" for i in range(10)])
        self.assertEqual([item["limit"] for item in memory.queries], [50, 50, 12])

    def test_turn_only_requests_and_expiry_free_states_are_not_stored(self):
        proposed = {"candidate_memories": [
            candidate("project_once", "本轮回答", "本轮回答", retention="turn"),
            candidate("project_bad_retention", "本轮回答", "本轮回答", retention="forever"),
            candidate("project_state", "持续状态", "持续状态", retention="state"),
            candidate("current_bandwidth", "busy", "很忙"),
            candidate("project_decision", "已明确决定", "已明确决定", retention="durable"),
        ]}
        accepted, rejected = validate_grounded_proposals(proposed, "本轮回答，持续状态，很忙，已明确决定。", NOW)
        self.assertEqual([item["key"] for item in accepted["candidate_memories"]], ["project_decision"])
        self.assertEqual([item["reason"] for item in rejected], ["turn_only_not_stored", "invalid_retention",
                         "transient_state_requires_expiry", "transient_state_requires_expiry"])

    def test_bandwidth_and_preference_values_are_canonical_with_contextual_exception(self):
        expiry = "2026-11-17T00:00:00+00:00"
        proposed = {"candidate_memories": [
            candidate("current_bandwidth", "最近非常忙", "最近非常忙", retention="state", valid_to=expiry),
            candidate("current_bandwidth", "busy", "最近非常忙", retention="state", valid_to=expiry),
            candidate("detail_preference", "请详细一点", "请详细一点", layer="preference"),
            candidate("detail_preference", "detailed", "请详细一点", layer="preference"),
            candidate("unknown_preference", "detailed", "请详细一点", layer="preference"),
            candidate("contextual_review_preference", "评审时详细解释", "评审时详细解释", layer="preference",
                      authority="user_implicit", confidence=.99),
        ]}
        accepted, rejected = validate_grounded_proposals(proposed, "最近非常忙，请详细一点，评审时详细解释。", NOW)
        self.assertEqual([item["key"] for item in accepted["candidate_memories"]],
                         ["current_bandwidth", "detail_preference", "contextual_review_preference"])
        self.assertEqual(accepted["candidate_memories"][-1]["confidence"], .75)
        self.assertEqual([item["reason"] for item in rejected],
                         ["invalid_bandwidth_value", "invalid_preference_slot_value", "invalid_preference_slot_value"])

    def test_fabricated_evidence_and_external_authority_are_rejected_before_ingest(self):
        text = "这个项目只讨论方案，不执行部署。"
        proposed = {"candidate_memories": [
            candidate("project_scope", "只讨论方案", "只讨论方案"),
            candidate("project_fake", "已部署", "已经成功部署"),
            candidate("project_authority", "只讨论方案", "只讨论方案", authority="system"),
        ]}
        memory = FakeGateway()
        trace = self.turn(ConversationHost(FakeProvider(proposed), memory=memory), 1, text=text)
        accepted = memory.ingests[0]["payload"]["candidate_memories"]
        self.assertEqual([item["key"] for item in accepted], ["project_scope"])
        self.assertEqual({item["reason"] for item in trace["rejected_proposals"]}, {
            "evidence_not_in_current_user_turn", "extractor_cannot_assign_external_authority",
        })

    def test_naive_expired_timestamps_and_direct_profiles_do_not_enter_ingest_payload(self):
        proposed = {"candidate_memories": [
            candidate("project_naive", "短期状态", "短期状态", valid_to="2026-11-17T00:00:00"),
            candidate("project_expired", "短期状态", "短期状态", valid_to="2026-11-15T00:00:00+00:00"),
            candidate("detail_tolerance", "high", "短期状态", layer="inferred_profile"),
        ]}
        accepted, rejected = validate_grounded_proposals(proposed, "短期状态", NOW)
        self.assertEqual(accepted["candidate_memories"], [])
        self.assertEqual(len(rejected), 3)

    def test_bad_extraction_is_visible_and_does_not_create_a_repaired_memory(self):
        memory = FakeGateway()
        trace = self.turn(ConversationHost(FakeProvider("not JSON"), memory=memory), 1)
        self.assertEqual(memory.ingests[0]["payload"], {"candidate_memories": []})
        self.assertEqual(trace["rejected_proposals"][0]["reason"], "invalid_extraction")
        self.assertEqual(trace["extraction"]["content"], "not JSON")
        self.assertEqual(trace["answer"]["content"], "fake-answer-1")

    def test_runner_only_passes_public_turn_fields_not_rubric_or_future_script(self):
        # Check the actual runner call boundary without executing its key/file/
        # network setup. The offline renderer may read the full fixture.
        runner = Path(__file__).resolve().parents[1] / "examples/run_live_conversation.py"
        calls = [node for node in ast.walk(ast.parse(runner.read_text()))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name)
                 and node.func.value.id == "host" and node.func.attr == "turn"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args, [])
        self.assertEqual({item.arg for item in calls[0].keywords},
                         {"text", "turn_id", "session_id", "timestamp"})
        for item in calls[0].keywords:
            if item.arg == "timestamp":
                self.assertIsInstance(item.value, ast.Name)
                self.assertEqual(item.value.id, "timestamp")
            else:
                self.assertIsInstance(item.value, ast.Subscript)
                self.assertEqual(item.value.value.id, "turn")
                self.assertIn(item.value.slice.value, {"text", "id", "session_id"})


if __name__ == "__main__":
    unittest.main()
