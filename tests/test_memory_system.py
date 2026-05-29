from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import app
from evals.runner import run_product_replay_eval
from memory_system import (
    CareerEventSkill,
    DialogueMemoryExtractor,
    DiskSessionRepository,
    EventSkillRegistry,
    HybridMemoryScorer,
    LLMMemoryProposalExtractor,
    LLMProposalSchemaValidator,
    LLMProposalValidationError,
    MemoryCommand,
    MemoryCommandDetector,
    MemoryItem,
    MemoryLayer,
    MemoryOperationPlanner,
    MemoryRecord,
    MemorySlotRegistry,
    MemoryStore,
    MemoryType,
    MemoryUseAction,
    MemoryUseGate,
    MemoryWriteEvaluator,
    NormalizedSQLiteMemoryRepository,
    ProjectEventSkill,
    ProfileAccumulator,
    ProfileEvidenceExtractor,
    ProfileInferencer,
    PromptContextBuilder,
    QueryIntentClassifier,
    QueryMemoryRetriever,
    RelationshipEventSkill,
    ResponsePolicyEngine,
    RetrievalPlanner,
    RuleMemoryProposalExtractor,
    Sensitivity,
    SessionMemoryRuntime,
    SQLiteSessionRepository,
    StateDynamics,
    StructuredMemoryParser,
    TurnPreprocessor,
    WeightedMemoryWriteEvaluatorV2,
    WritePolicyContext,
)
from memory_system.demo import format_demo_report, run_product_demo


class MemorySystemTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tz = ZoneInfo("Asia/Shanghai")
        self.extractor = DialogueMemoryExtractor()
        self.registry = MemorySlotRegistry.default()
        self.store = MemoryStore()
        self.inferencer = ProfileInferencer()
        self.write_evaluator = MemoryWriteEvaluator()
        self.retriever = QueryMemoryRetriever()
        self.use_gate = MemoryUseGate()
        self.policy_engine = ResponsePolicyEngine()
        self.prompt_builder = PromptContextBuilder()
        self.structured_parser = StructuredMemoryParser()

    def test_exclusive_state_replacement(self) -> None:
        first = self.extractor.extract(
            "我现在单身。",
            source="turn_1",
            timestamp=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
        )
        second = self.extractor.extract(
            "我已经恋爱了。",
            source="turn_2",
            timestamp=datetime(2026, 4, 16, 10, 0, tzinfo=self.tz),
        )
        self.store.extend(first)
        self.store.extend(second)

        active = self.store.active_memories(now=datetime(2026, 4, 16, 11, 0, tzinfo=self.tz))
        relationships = [item for item in active if item.key == "relationship_status"]

        self.assertEqual(len(relationships), 1)
        self.assertEqual(relationships[0].value, "dating")

    def test_policy_prefers_direct_concise_answer(self) -> None:
        turns = [
            "最近找工作很焦虑。",
            "回答直接一点，先给结论，别太啰嗦。",
        ]
        for index, turn in enumerate(turns, start=1):
            timestamp = datetime(2026, 4, 16, 9, index, tzinfo=self.tz)
            self.store.extend(
                self.extractor.extract(turn, source=f"turn_{index}", timestamp=timestamp)
            )
            self.store.extend(self.inferencer.infer(self.store, timestamp))

        policy = self.policy_engine.build(
            self.store,
            datetime(2026, 4, 16, 12, 0, tzinfo=self.tz),
        )

        self.assertEqual(policy.structure, "answer_first")
        self.assertEqual(policy.detail_level, "low")
        self.assertEqual(policy.decision_mode, "give_recommendation")
        self.assertEqual(policy.empathy_level, "high")

    def test_opening_and_step_by_step_can_coexist(self) -> None:
        turns = [
            "先给结论。",
            "然后分步骤讲。",
        ]
        for index, turn in enumerate(turns, start=1):
            timestamp = datetime(2026, 4, 16, 9, index, tzinfo=self.tz)
            self.store.extend(
                self.extractor.extract(turn, source=f"turn_{index}", timestamp=timestamp)
            )
            self.store.extend(self.inferencer.infer(self.store, timestamp))

        policy = self.policy_engine.build(
            self.store,
            datetime(2026, 4, 16, 12, 0, tzinfo=self.tz),
        )

        self.assertEqual(policy.structure, "answer_first_then_steps")

    def test_retrieval_prioritizes_work_memories_for_work_query(self) -> None:
        turns = [
            "我最近在找工作，而且有点焦虑。",
            "我平时喜欢滑雪。",
            "回答直接一点，先给结论。",
        ]
        for index, turn in enumerate(turns, start=1):
            timestamp = datetime(2026, 4, 16, 9, index, tzinfo=self.tz)
            self.store.extend(
                self.extractor.extract(turn, source=f"turn_{index}", timestamp=timestamp)
            )
            self.store.extend(self.inferencer.infer(self.store, timestamp))

        relevant = self.retriever.retrieve(
            "给我一点求职建议",
            self.store.active_memories(now=datetime(2026, 4, 16, 12, 0, tzinfo=self.tz)),
        )
        keys = [item.key for item in relevant]

        self.assertIn("work_status", keys)
        self.assertIn("communication_style", keys)

    def test_memory_use_gate_suppresses_sensitive_irrelevant_facts(self) -> None:
        memory = MemoryItem(
            memory_type=MemoryType.STATE,
            key="age",
            value="29",
            confidence=0.95,
            source="turn_1",
            evidence="29岁",
            valid_from=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
            confirmed_by_user=True,
            dynamics=StateDynamics.SEMI_STATIC,
            tags=["sensitive"],
        )

        result = self.use_gate.select(
            "给我一点求职建议",
            [memory],
            now=datetime(2026, 4, 16, 12, 0, tzinfo=self.tz),
        )

        self.assertFalse(result.selected)
        self.assertEqual(result.suppressed[0].action, MemoryUseAction.SUPPRESS)

    def test_memory_use_gate_marks_ongoing_events_for_followup(self) -> None:
        event = self.extractor.extract(
            "我最近准备面试。",
            source="turn_1",
            timestamp=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
        )[0]

        result = self.use_gate.select(
            "面试怎么准备？",
            [event],
            now=datetime(2026, 4, 17, 9, 0, tzinfo=self.tz),
        )

        self.assertEqual(result.decisions[0].action, MemoryUseAction.FOLLOW_UP)
        self.assertEqual(result.decisions[0].layer, MemoryLayer.EPISODIC_EVENT)

    def test_memory_use_gate_respects_explicit_no_mention_request(self) -> None:
        event = self.extractor.extract(
            "我最近准备面试。",
            source="turn_1",
            timestamp=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
        )[0]

        result = self.use_gate.select(
            "今天只帮我 review Python 代码，不用提面试。",
            [event],
            now=datetime(2026, 4, 17, 9, 0, tzinfo=self.tz),
        )

        self.assertFalse(result.selected)
        self.assertEqual(result.suppressed[0].action, MemoryUseAction.SUPPRESS)

    def test_memory_use_gate_enforces_never_prompt_allowed_use(self) -> None:
        memory = MemoryItem(
            memory_type=MemoryType.STATE,
            key="restricted_note",
            value="do_not_surface",
            confidence=0.95,
            source="turn_1",
            evidence="private evidence",
            valid_from=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
            allowed_use=["never_prompt"],
            sensitivity="restricted",
        )

        result = self.use_gate.select(
            "这个信息可以用吗？",
            [memory],
            now=datetime(2026, 4, 16, 12, 0, tzinfo=self.tz),
        )

        self.assertFalse(result.selected)
        self.assertEqual(result.suppressed[0].action, MemoryUseAction.SUPPRESS)

    def test_memory_record_adapter_maps_legacy_item_to_phase2_layer(self) -> None:
        item = self.extractor.extract(
            "回答直接一点。",
            source="turn_1",
            timestamp=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
        )[0]

        record = MemoryRecord.from_memory_item(item, user_id="user-1", session_id="session-1")

        self.assertEqual(record.layer, MemoryLayer.PREFERENCE)
        self.assertEqual(record.allowed_use[0].value, "style")
        self.assertEqual(record.metadata["legacy_type"], "preference")

    def test_write_evaluator_v2_rejects_do_not_remember_command(self) -> None:
        item = self.extractor.extract(
            "回答直接一点。",
            source="turn_1",
            timestamp=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
        )[0]
        record = MemoryRecord.from_memory_item(item, user_id="user-1")

        operation = WeightedMemoryWriteEvaluatorV2().evaluate(
            record,
            context=WritePolicyContext(user_command="do_not_remember"),
        )

        self.assertEqual(operation.operation.value, "reject")
        self.assertEqual(operation.score, 0.0)

    def test_write_evaluator_v2_supersedes_exclusive_conflict(self) -> None:
        old_item = self.extractor.extract(
            "我现在单身。",
            source="turn_1",
            timestamp=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
        )[0]
        new_item = self.extractor.extract(
            "我已经恋爱了。",
            source="turn_2",
            timestamp=datetime(2026, 4, 16, 10, 0, tzinfo=self.tz),
        )[0]
        old_record = MemoryRecord.from_memory_item(old_item, user_id="user-1")
        new_record = MemoryRecord.from_memory_item(new_item, user_id="user-1")

        operation = WeightedMemoryWriteEvaluatorV2().evaluate(new_record, [old_record])

        self.assertEqual(operation.operation.value, "supersede")
        self.assertEqual(operation.target_memory_id, old_record.id)

    def test_write_evaluator_v2_routes_low_confidence_sensitive_memory_to_review(self) -> None:
        item = MemoryItem(
            memory_type=MemoryType.STATE,
            key="current_emotional_state",
            value="anxious",
            confidence=0.6,
            source="turn_1",
            evidence="可能有点焦虑",
            valid_from=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
            confirmed_by_user=True,
            dynamics=StateDynamics.FLUID,
            tags=["sensitive"],
        )
        record = MemoryRecord.from_memory_item(item, user_id="user-1")

        operation = WeightedMemoryWriteEvaluatorV2().evaluate(record)

        self.assertEqual(operation.operation.value, "ask_user_confirmation")
        self.assertTrue(operation.requires_user_review)

    def test_operation_planner_simulates_prior_candidates_for_duplicates(self) -> None:
        item = self.extractor.extract(
            "回答直接一点。",
            source="turn_1",
            timestamp=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
        )[0]
        first = MemoryRecord.from_memory_item(item, user_id="user-1")
        second = MemoryRecord.from_memory_item(item, user_id="user-1")

        operations = MemoryOperationPlanner().plan([first, second], [])

        self.assertEqual(operations[0].operation.value, "create")
        self.assertEqual(operations[1].operation.value, "add_evidence_only")
        self.assertEqual(operations[1].target_memory_id, first.id)

    def test_turn_preprocessor_detects_memory_commands(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        turn = TurnPreprocessor().preprocess(
            text="记住，我喜欢你先给结论。",
            timestamp=timestamp,
        )
        do_not_remember = MemoryCommandDetector().detect("别记我的感情状态。")

        self.assertEqual(turn.language, "zh-CN")
        self.assertEqual(turn.memory_command, MemoryCommand.REMEMBER)
        self.assertIn("turn_", turn.turn_id)
        self.assertEqual(do_not_remember, MemoryCommand.DO_NOT_REMEMBER)

    def test_rule_memory_proposal_extractor_respects_do_not_remember(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        turn = TurnPreprocessor().preprocess(
            text="别记，我现在单身。",
            timestamp=timestamp,
        )

        proposals = RuleMemoryProposalExtractor().propose(turn, user_id="user-1")

        self.assertEqual(proposals, [])

    def test_rule_memory_proposal_extractor_outputs_phase2_records(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        turn = TurnPreprocessor().preprocess(
            text="我最近准备面试，有点焦虑。回答直接一点。",
            timestamp=timestamp,
            turn_id="turn_1",
        )

        proposals = RuleMemoryProposalExtractor().propose(
            turn,
            user_id="user-1",
            session_id="session-1",
        )
        by_key = {proposal.key: proposal for proposal in proposals}

        self.assertEqual(by_key["life_event"].layer, MemoryLayer.EPISODIC_EVENT)
        self.assertEqual(by_key["current_emotional_state"].sensitivity.value, "sensitive")
        self.assertEqual(by_key["communication_style"].metadata["language"], "zh-CN")
        self.assertEqual(by_key["communication_style"].source_text_hash, turn.text_hash)

    def test_llm_proposal_validator_repairs_legacy_payload(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        turn = TurnPreprocessor().preprocess(
            text="我最近准备面试。",
            timestamp=timestamp,
            turn_id="turn_1",
        )
        payload = {
            "memories": [
                {
                    "type": "event",
                    "key": "life_event",
                    "value": "prepare_interview",
                    "confidence": 1.4,
                    "evidence": "准备面试",
                }
            ]
        }

        validated = LLMProposalSchemaValidator().repair_and_validate(payload)
        records = LLMMemoryProposalExtractor().parse_response_payload(
            payload,
            turn=turn,
            user_id="user-1",
            session_id="session-1",
        )

        self.assertEqual(validated["candidate_memories"][0]["layer"], "episodic_event")
        self.assertEqual(validated["candidate_memories"][0]["confidence"], 1.0)
        self.assertEqual(records[0].layer, MemoryLayer.EPISODIC_EVENT)
        self.assertEqual(records[0].metadata["extractor_version"], "llm-proposal-v0")

    def test_llm_proposal_validator_rejects_invalid_tags(self) -> None:
        payload = {
            "candidate_memories": [
                {
                    "layer": "preference",
                    "key": "communication_style",
                    "value": "direct",
                    "confidence": 0.86,
                    "authority": "assistant_inferred",
                    "sensitivity": "personal",
                    "evidence": "回答直接一点",
                    "tags": [""],
                }
            ]
        }

        with self.assertRaises(LLMProposalValidationError):
            LLMProposalSchemaValidator().repair_and_validate(payload)

    def test_llm_proposal_validator_rejects_third_party_confusion(self) -> None:
        payload = {
            "candidate_memories": [
                {
                    "layer": "semantic_fact",
                    "key": "relationship_status",
                    "value": "single",
                    "confidence": 0.86,
                    "authority": "assistant_inferred",
                    "sensitivity": "personal",
                    "evidence": "朋友现在单身",
                }
            ]
        }

        with self.assertRaises(LLMProposalValidationError):
            LLMProposalSchemaValidator().repair_and_validate(payload)

    def test_llm_proposal_validator_upgrades_sensitivity_and_preserves_valid_to(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        turn = TurnPreprocessor().preprocess(
            text="我现在单身。",
            timestamp=timestamp,
            turn_id="turn_sensitive",
        )
        payload = {
            "candidate_memories": [
                {
                    "layer": "semantic_fact",
                    "key": "relationship_status",
                    "value": "single",
                    "normalized_value": "",
                    "confidence": 0.86,
                    "authority": "assistant_inferred",
                    "sensitivity": "personal",
                    "evidence": "我现在单身",
                    "validity": {"valid_to": "2026-06-01T09:00:00+08:00"},
                }
            ]
        }

        records = LLMMemoryProposalExtractor().parse_response_payload(
            payload,
            turn=turn,
            user_id="user-1",
        )

        self.assertEqual(records[0].sensitivity, Sensitivity.SENSITIVE)
        self.assertEqual(records[0].normalized_value, "single")
        self.assertEqual(records[0].valid_to, datetime(2026, 6, 1, 9, 0, tzinfo=self.tz))

    def test_llm_proposal_extractor_returns_no_candidates_for_forget_command(self) -> None:
        turn = TurnPreprocessor().preprocess(
            text="不要记，我现在单身。",
            timestamp=datetime(2026, 5, 1, 9, 0, tzinfo=self.tz),
            turn_id="turn_private",
        )
        payload = {
            "candidate_memories": [
                {
                    "layer": "semantic_fact",
                    "key": "relationship_status",
                    "value": "single",
                    "confidence": 0.9,
                    "authority": "user_explicit",
                    "sensitivity": "sensitive",
                    "evidence": "我现在单身",
                }
            ]
        }

        records = LLMMemoryProposalExtractor().parse_response_payload(
            payload,
            turn=turn,
            user_id="user-1",
        )

        self.assertEqual(records, [])

    def test_career_event_skill_detects_and_updates_interview_event(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        turn = TurnPreprocessor().preprocess(
            text="我最近准备面试。",
            timestamp=timestamp,
            turn_id="turn_1",
        )
        proposals = RuleMemoryProposalExtractor().propose(turn, user_id="user-1")
        skill = CareerEventSkill()

        events = skill.detect(proposals)
        should_follow_up = skill.should_follow_up(
            events[0],
            query="面试怎么准备？",
            now=datetime(2026, 5, 2, 9, 0, tzinfo=self.tz),
        )
        updated = skill.update_state(events[0], proposals[0])

        self.assertEqual(events[0].event_type, "career.interview_preparation")
        self.assertEqual(events[0].stage, "preparing")
        self.assertTrue(should_follow_up)
        self.assertEqual(updated.status, "progressing")

    def test_prompt_builder_outputs_assembled_prompt(self) -> None:
        turns = [
            "我最近在找工作。",
            "回答直接一点，先给结论。",
        ]
        for index, turn in enumerate(turns, start=1):
            timestamp = datetime(2026, 4, 16, 9, index, tzinfo=self.tz)
            self.store.extend(
                self.extractor.extract(turn, source=f"turn_{index}", timestamp=timestamp)
            )
            self.store.extend(self.inferencer.infer(self.store, timestamp))

        relevant = self.retriever.retrieve(
            "给我一点求职建议",
            self.store.active_memories(now=datetime(2026, 4, 16, 12, 0, tzinfo=self.tz)),
        )
        policy = self.policy_engine.build_from_memories(relevant)
        context = self.prompt_builder.build("给我一点求职建议", relevant, policy)

        self.assertIn("[Relevant User Memory]", context["assembled_prompt"])
        self.assertIn("[Response Policy]", context["assembled_prompt"])
        self.assertIn("work_status", context["assembled_prompt"])

    def test_prompt_builder_does_not_render_policy_only_memory_as_raw_memory(self) -> None:
        memory = MemoryItem(
            memory_type=MemoryType.PROFILE,
            key="directness_preference_level",
            value="high",
            confidence=0.82,
            source="profile",
            evidence="raw-private-quote",
            valid_from=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
            allowed_use=["style"],
        )
        gate_result = self.use_gate.select(
            "怎么回答更适合我？",
            [memory],
            now=datetime(2026, 4, 16, 12, 0, tzinfo=self.tz),
        )
        policy = self.policy_engine.build_from_memories(gate_result.selected)
        compiled = self.prompt_builder.context_compiler.compile(
            query="怎么回答更适合我？",
            gate_result=gate_result,
            response_policy=policy,
        )

        context = self.prompt_builder.build(
            "怎么回答更适合我？",
            gate_result.selected,
            policy,
            memory_gate=gate_result.to_dict(),
            compiled_context=compiled.to_dict(),
        )

        self.assertNotIn("raw-private-quote", context["assembled_prompt"])
        self.assertNotIn(
            "- directness_preference_level: high\n[Response Policy]",
            context["assembled_prompt"],
        )

    def test_product_demo_reports_adaptive_memory_metrics(self) -> None:
        report = run_product_demo()

        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["gate_action_accuracy"].value, 1.0)
        self.assertEqual(report.metrics["explicit_suppression_rate"].value, 1.0)
        self.assertEqual(report.metrics["style_continuity_rate"].value, 1.0)
        self.assertEqual(report.metrics["prompt_safety_rate"].value, 1.0)
        self.assertEqual(report.metrics["correction_retirement_rate"].value, 1.0)
        self.assertIn("Product metrics", format_demo_report(report))

    def test_product_replay_eval_has_no_failures(self) -> None:
        result = run_product_replay_eval()

        self.assertEqual(result["failures"], [])
        self.assertEqual(result["metrics"]["gate_action_accuracy"]["value"], 1.0)

    def test_disk_repository_persists_memories(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = DiskSessionRepository(Path(temp_dir))
            runtime = SessionMemoryRuntime(session_id="persist-user", repository=repo)
            timestamp = datetime(2026, 4, 16, 9, 0, tzinfo=self.tz)
            runtime.ingest_turn("我最近在找工作，回答直接一点。", "turn_1", timestamp)

            reloaded = SessionMemoryRuntime(session_id="persist-user", repository=repo)
            active = reloaded.active_memories(timestamp)
            keys = [item["key"] for item in active]

            self.assertIn("work_status", keys)
            self.assertIn("communication_style", keys)

    def test_sqlite_repository_persists_memories(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = SQLiteSessionRepository(Path(temp_dir) / "memory.sqlite3")
            runtime = SessionMemoryRuntime(session_id="sqlite-user", repository=repo)
            timestamp = datetime(2026, 4, 16, 9, 0, tzinfo=self.tz)
            runtime.ingest_turn("我最近在找工作，回答直接一点。", "turn_1", timestamp)

            reloaded = SessionMemoryRuntime(session_id="sqlite-user", repository=repo)
            active = reloaded.active_memories(timestamp)
            keys = [item["key"] for item in active]

            self.assertIn("work_status", keys)
            self.assertIn("communication_style", keys)

    def test_normalized_sqlite_repository_persists_memory_records(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = NormalizedSQLiteMemoryRepository(Path(temp_dir) / "memory.sqlite3")
            item = self.extractor.extract(
                "回答直接一点。",
                source="turn_1",
                timestamp=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
            )[0]
            record = MemoryRecord.from_memory_item(
                item,
                user_id="user-1",
                session_id="session-1",
            )

            repo.upsert_record(record)
            loaded = repo.get_record(str(record.id))
            active = repo.list_records(user_id="user-1")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.key, "communication_style")
            self.assertEqual(active[0].layer, MemoryLayer.PREFERENCE)
            self.assertTrue(repo.mark_deleted(str(record.id)))
            self.assertEqual(repo.list_records(user_id="user-1"), [])

    def test_normalized_sqlite_repository_migrates_active_store(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = NormalizedSQLiteMemoryRepository(Path(temp_dir) / "memory.sqlite3")
            timestamp = datetime(2026, 4, 16, 9, 0, tzinfo=self.tz)
            self.store.extend(
                self.extractor.extract(
                    "我最近准备面试，回答直接一点。",
                    source="turn_1",
                    timestamp=timestamp,
                )
            )

            records = repo.migrate_store(
                store=self.store,
                user_id="user-1",
                session_id="session-1",
            )
            keys = [record.key for record in repo.list_records(user_id="user-1")]

            self.assertEqual(len(records), 2)
            self.assertIn("life_event", keys)
            self.assertIn("communication_style", keys)

    def test_normalized_sqlite_repository_applies_write_operations(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = NormalizedSQLiteMemoryRepository(Path(temp_dir) / "memory.sqlite3")
            timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
            turn = TurnPreprocessor().preprocess(
                text="记住，回答直接一点。",
                timestamp=timestamp,
                turn_id="turn_1",
            )
            records = RuleMemoryProposalExtractor().propose(
                turn,
                user_id="user-1",
                session_id="session-1",
            )
            operations = MemoryOperationPlanner().plan(
                records,
                [],
                WritePolicyContext(user_command="remember"),
            )

            persisted = repo.apply_operations(operations, created_at=timestamp)
            active = repo.list_records(user_id="user-1", session_id="session-1")
            audit = repo.list_audit_events(user_id="user-1")

            self.assertTrue(persisted)
            self.assertEqual(active[0].key, "communication_style")
            self.assertEqual(audit[0]["action"], "create")

    def test_normalized_sqlite_repository_review_queue_approval(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = NormalizedSQLiteMemoryRepository(Path(temp_dir) / "memory.sqlite3")
            timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
            record = MemoryRecord(
                user_id="user-1",
                session_id="session-1",
                layer=MemoryLayer.SEMANTIC_FACT,
                key="relationship_status",
                value="single",
                normalized_value="single",
                confidence=0.6,
                sensitivity=Sensitivity.SENSITIVE,
                valid_from=timestamp,
                observed_at=timestamp,
                exclusive_group="relationship_status",
                coexistence_rule="mutually_exclusive",
                metadata={"evidence": "我现在单身"},
            )
            operation = WeightedMemoryWriteEvaluatorV2().evaluate(record)

            repo.apply_operations([operation], created_at=timestamp)
            review_items = repo.list_review_items(user_id="user-1")
            persisted = repo.resolve_review_item(
                str(review_items[0]["id"]),
                approve=True,
                user_id="user-1",
                resolved_at=timestamp,
            )

            self.assertEqual(operation.operation.value, "ask_user_confirmation")
            self.assertEqual(len(review_items), 1)
            self.assertTrue(persisted)
            self.assertEqual(repo.list_records(user_id="user-1")[0].key, "relationship_status")

    def test_normalized_sqlite_repository_persists_event_states(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = NormalizedSQLiteMemoryRepository(Path(temp_dir) / "memory.sqlite3")
            timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
            turn = TurnPreprocessor().preprocess(
                text="我最近准备面试。",
                timestamp=timestamp,
                turn_id="turn_1",
            )
            records = RuleMemoryProposalExtractor().propose(
                turn,
                user_id="user-1",
                session_id="session-1",
            )
            event = CareerEventSkill().detect(records)[0]

            repo.upsert_event_state(event, user_id="user-1")
            loaded = repo.list_event_states(user_id="user-1")

            self.assertEqual(loaded[0].event_type, "career.interview_preparation")
            self.assertEqual(loaded[0].stage, "preparing")

    def test_event_skill_registry_detects_learning_and_life_events(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        turn = TurnPreprocessor().preprocess(
            text="我准备考研，最近分手了。",
            timestamp=timestamp,
            turn_id="turn_1",
        )
        records = RuleMemoryProposalExtractor().propose(
            turn,
            user_id="user-1",
            session_id="session-1",
        )

        event_types = {event.event_type for event in EventSkillRegistry().detect(records)}

        self.assertIn("learning.exam_preparation", event_types)
        self.assertIn("life.relationship_change", event_types)

    def test_normalized_sqlite_repository_corrects_record_and_exports_audit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = NormalizedSQLiteMemoryRepository(Path(temp_dir) / "memory.sqlite3")
            timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
            turn = TurnPreprocessor().preprocess(
                text="记住，回答直接一点。",
                timestamp=timestamp,
                turn_id="turn_1",
            )
            records = RuleMemoryProposalExtractor().propose(
                turn,
                user_id="user-1",
                session_id="session-1",
            )
            operations = MemoryOperationPlanner().plan(
                records,
                [],
                WritePolicyContext(user_command="remember"),
            )
            created = repo.apply_operations(operations, created_at=timestamp)[0]

            corrected = repo.correct_record(
                str(created.id),
                user_id="user-1",
                value="slow",
                evidence="我更正一下，慢慢讲。",
                corrected_at=timestamp,
            )
            export = repo.export_user_memory(user_id="user-1")

            self.assertIsNotNone(corrected)
            self.assertEqual(corrected.value, "slow")
            self.assertEqual(repo.list_records(user_id="user-1")[0].value, "slow")
            self.assertTrue(export["audit_events"])

    def test_query_intent_classifier_and_retrieval_planner(self) -> None:
        intent = QueryIntentClassifier().classify("面试怎么准备？")
        plan = RetrievalPlanner().plan("面试怎么准备？", max_prompt_memories=8)

        self.assertEqual(intent.name, "career_advice")
        self.assertIn("event_state", plan.retrieval_modes)
        self.assertIn(MemoryLayer.EPISODIC_EVENT, plan.include_layers)

    def test_profile_evidence_accumulates_before_inferred_profile(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        first = TurnPreprocessor().preprocess(
            text="回答直接一点。",
            timestamp=timestamp,
            turn_id="turn_1",
        )
        second = TurnPreprocessor().preprocess(
            text="直接给建议。",
            timestamp=timestamp,
            turn_id="turn_2",
        )
        records = (
            RuleMemoryProposalExtractor().propose(first, user_id="user-1")
            + RuleMemoryProposalExtractor().propose(second, user_id="user-1")
        )
        evidence = ProfileEvidenceExtractor().extract(records)
        hypotheses = ProfileAccumulator().accumulate(evidence)

        self.assertTrue(evidence)
        self.assertEqual(hypotheses, [])

        third = TurnPreprocessor().preprocess(
            text="再提醒一下，回答直接一点。",
            timestamp=timestamp,
            turn_id="turn_3",
        )
        more_records = RuleMemoryProposalExtractor().propose(third, user_id="user-1")
        accumulated = ProfileAccumulator().accumulate(
            evidence + ProfileEvidenceExtractor().extract(more_records)
        )

        self.assertTrue(accumulated)
        self.assertEqual(accumulated[0].dimension, "directness_preference_level")
        self.assertTrue(accumulated[0].supporting_quotes)

    def test_profile_accumulator_uses_counter_evidence_to_avoid_sticky_profiles(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        concise_records = []
        detailed_records = []
        for index in range(2):
            concise_turn = TurnPreprocessor().preprocess(
                text="别太啰嗦。",
                timestamp=timestamp,
                turn_id=f"concise_{index}",
            )
            detailed_turn = TurnPreprocessor().preprocess(
                text="多给细节。",
                timestamp=timestamp,
                turn_id=f"detailed_{index}",
            )
            concise_records.extend(
                RuleMemoryProposalExtractor().propose(concise_turn, user_id="user-1")
            )
            detailed_records.extend(
                RuleMemoryProposalExtractor().propose(detailed_turn, user_id="user-1")
            )

        evidence = ProfileEvidenceExtractor().extract(concise_records + detailed_records)
        hypotheses = ProfileAccumulator().accumulate(evidence)

        self.assertFalse([item for item in hypotheses if item.dimension == "detail_tolerance"])

    def test_richer_profile_evidence_drives_response_policy(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        records = []
        for index, text in enumerate(["给我清单。", "用清单列步骤。"], start=1):
            turn = TurnPreprocessor().preprocess(
                text=text,
                timestamp=timestamp,
                turn_id=f"plan_{index}",
            )
            records.extend(RuleMemoryProposalExtractor().propose(turn, user_id="user-1"))

        evidence = ProfileEvidenceExtractor().extract(records)
        hypotheses = ProfileAccumulator().accumulate(evidence)
        profile = hypotheses[0].to_record(
            user_id="user-1",
            session_id=None,
            observed_at=timestamp,
        )
        policy = ResponsePolicyEngine().build_from_memories([
            MemoryItem(
                memory_type=MemoryType.PROFILE,
                key=profile.key,
                value=profile.value,
                confidence=profile.confidence,
                source="profile",
                evidence=profile.metadata["rationale"],
                valid_from=timestamp,
            )
        ])

        self.assertEqual(hypotheses[0].dimension, "planning_orientation")
        self.assertIn("repeated", hypotheses[0].rationale)
        self.assertEqual(policy.structure, "checklist")

    def test_response_policy_consumes_new_profile_dimensions_with_precedence(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        memories = [
            MemoryItem(
                memory_type=MemoryType.PROFILE,
                key="learning_style",
                value="example_first",
                confidence=0.8,
                source="profile",
                evidence="repeated learning signals",
                valid_from=timestamp,
            ),
            MemoryItem(
                memory_type=MemoryType.PROFILE,
                key="collaboration_style",
                value="challenge",
                confidence=0.8,
                source="profile",
                evidence="repeated critique requests",
                valid_from=timestamp,
            ),
            MemoryItem(
                memory_type=MemoryType.STATE,
                key="current_bandwidth",
                value="busy",
                confidence=0.8,
                source="turn",
                evidence="很忙",
                valid_from=timestamp,
            ),
            MemoryItem(
                memory_type=MemoryType.PROFILE,
                key="pace_preference",
                value="slow",
                confidence=0.8,
                source="profile",
                evidence="slow pace",
                valid_from=timestamp,
            ),
        ]

        policy = ResponsePolicyEngine().build_from_memories(memories)

        self.assertEqual(policy.example_density, "high")
        self.assertEqual(policy.challenge_level, "high")
        self.assertEqual(policy.pace, "fast")

    def test_context_compiler_keeps_new_profile_guidance_policy_only(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        memory = MemoryItem(
            memory_type=MemoryType.PROFILE,
            key="learning_style",
            value="example_first",
            confidence=0.8,
            source="profile",
            evidence="examples",
            valid_from=timestamp,
            allowed_use=["style"],
        )
        gate_result = MemoryUseGate().select("解释这个概念", [memory], now=timestamp)
        context = self.prompt_builder.context_compiler.compile(
            query="解释这个概念",
            gate_result=gate_result,
            response_policy=ResponsePolicyEngine().build_from_memories([memory]),
        )

        self.assertEqual(context.direct_facts, [])
        self.assertIn("examples", " ".join(context.style_policy).lower())

    def test_project_and_relationship_event_skills(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        project = MemoryRecord(
            user_id="user-1",
            layer=MemoryLayer.EPISODIC_EVENT,
            key="project_event",
            value="项目架构评审卡住了",
            confidence=0.86,
            valid_from=timestamp,
            observed_at=timestamp,
            metadata={"evidence": "项目架构评审卡住了"},
        )
        relationship = MemoryRecord(
            user_id="user-1",
            layer=MemoryLayer.EPISODIC_EVENT,
            key="life_event",
            value="breakup",
            confidence=0.86,
            valid_from=timestamp,
            observed_at=timestamp,
            metadata={"evidence": "分手了"},
        )

        project_event = ProjectEventSkill().detect([project])[0]
        relationship_event = RelationshipEventSkill().detect([relationship])[0]

        self.assertEqual(project_event.event_type, "project.review")
        self.assertEqual(relationship_event.event_type, "relationship.transition")
        self.assertEqual(relationship_event.followup_policy.cooldown_days, 21)
        self.assertEqual(relationship_event.followup_policy.max_followups_per_event, 1)

    def test_retrieval_planner_includes_mental_model_layers_for_project_and_learning(self) -> None:
        project_plan = RetrievalPlanner().plan("这个项目架构怎么实现？", max_prompt_memories=8)
        learning_plan = RetrievalPlanner().plan("用例子解释这个概念", max_prompt_memories=8)

        self.assertEqual(project_plan.intent.name, "project_work")
        self.assertIn(MemoryLayer.EPISODIC_EVENT, project_plan.include_layers)
        self.assertIn(MemoryLayer.INFERRED_PROFILE, learning_plan.include_layers)
        self.assertIn(MemoryLayer.PROCEDURAL_MEMORY, learning_plan.include_layers)

    def test_hybrid_memory_scorer_scores_keyword_embedding_and_layer_prior(self) -> None:
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=self.tz)
        memory = MemoryItem(
            memory_type=MemoryType.EVENT,
            key="life_event",
            value="prepare_interview",
            confidence=0.8,
            source="turn_1",
            evidence="准备面试",
            valid_from=timestamp,
        )
        plan = RetrievalPlanner().plan("面试怎么准备？", max_prompt_memories=8)

        scores = HybridMemoryScorer().score("面试怎么准备？", [memory], now=timestamp, plan=plan)

        self.assertEqual(scores[0].memory.key, "life_event")
        self.assertGreater(scores[0].factors["keyword"], 0)
        self.assertGreater(scores[0].factors["layer_prior"], 0.9)

    def test_write_policy_rejects_low_value_memory(self) -> None:
        memory = MemoryItem(
            memory_type=MemoryType.STATE,
            key="throwaway_detail",
            value="temporary",
            confidence=0.2,
            source="turn_1",
            evidence="随口一提",
            valid_from=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
            dynamics=StateDynamics.FLUID,
        )

        decision = self.write_evaluator.evaluate(memory)

        self.assertFalse(decision.should_write)
        self.assertLess(decision.score, decision.threshold)

    def test_runtime_correction_replaces_exclusive_memory(self) -> None:
        timestamp = datetime(2026, 4, 16, 9, 0, tzinfo=self.tz)
        runtime = SessionMemoryRuntime()
        runtime.ingest_turn("我现在单身。", "turn_1", timestamp)
        runtime.correct_memory(
            memory_type=MemoryType.STATE,
            key="relationship_status",
            value="dating",
            evidence="我刚才说错了，现在是恋爱中",
            timestamp=datetime(2026, 4, 16, 10, 0, tzinfo=self.tz),
            dynamics=StateDynamics.SEMI_STATIC,
        )

        active = runtime.active_memories(datetime(2026, 4, 16, 11, 0, tzinfo=self.tz))
        relationships = [item for item in active if item["key"] == "relationship_status"]
        actions = [event["action"] for event in runtime.audit_log()]

        self.assertEqual(len(relationships), 1)
        self.assertEqual(relationships[0]["value"], "dating")
        self.assertIn("correct", actions)
        self.assertIn("retire", actions)

    def test_structured_memory_parser_supports_model_payloads(self) -> None:
        payload = {
            "memories": [
                {
                    "type": "preference",
                    "key": "detail_preference",
                    "value": "concise",
                    "confidence": 0.91,
                    "evidence": "别太啰嗦",
                    "exclusive_group": "detail_preference",
                }
            ]
        }

        memories = self.structured_parser.parse(
            payload,
            source="llm_extractor",
            timestamp=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
        )

        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0].memory_type, MemoryType.PREFERENCE)
        self.assertEqual(memories[0].key, "detail_preference")
        self.assertEqual(memories[0].exclusive_group, "detail_preference")

    def test_slot_registry_defines_exclusive_state_rules(self) -> None:
        relationship = self.registry.get("relationship_status")
        current_emotion = self.registry.get("current_emotional_state")

        self.assertIsNotNone(relationship)
        self.assertEqual(relationship.exclusive_group, "relationship_status")
        self.assertEqual(relationship.coexistence_rule, "mutually_exclusive")
        self.assertEqual(current_emotion.default_valid_days, 14)

    def test_registry_applies_defaults_to_memory(self) -> None:
        memory = MemoryItem(
            memory_type=MemoryType.STATE,
            key="current_emotional_state",
            value="anxious",
            confidence=0.8,
            source="turn_1",
            evidence="焦虑",
            valid_from=datetime(2026, 4, 16, 9, 0, tzinfo=self.tz),
        )

        enriched = self.registry.apply_defaults(memory)

        self.assertEqual(enriched.exclusive_group, "current_emotional_state")
        self.assertEqual(enriched.dynamics, StateDynamics.FLUID)
        self.assertIsNotNone(enriched.valid_to)
        self.assertIn("sensitive", enriched.tags)


class MemoryApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.post("/sessions/test-user/reset")

    def test_ingest_and_query_api(self) -> None:
        response = self.client.post(
            "/sessions/test-user/ingest",
            json={"text": "我最近在找工作，回答直接一点，先给结论。"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["active_memories"])

        query_response = self.client.post(
            "/sessions/test-user/query",
            json={"query": "给我一点求职建议"},
        )
        self.assertEqual(query_response.status_code, 200)
        query_payload = query_response.json()

        self.assertTrue(query_payload["relevant_memories"])
        self.assertTrue(query_payload["memory_gate"]["selected"])
        self.assertTrue(query_payload["compiled_context"]["style_policy"])
        self.assertEqual(
            query_payload["response_policy"]["decision_mode"],
            "give_recommendation",
        )

    def test_health_reports_storage_backend(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertIn("storage_backend", response.json())

    def test_prompt_context_api(self) -> None:
        self.client.post(
            "/sessions/test-user/ingest",
            json={"text": "我最近在找工作，回答直接一点，先给结论。"},
        )
        response = self.client.post(
            "/sessions/test-user/prompt-context",
            json={"query": "给我一点求职建议"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("assembled_prompt", payload)
        self.assertIn("[Memory Use Gate]", payload["assembled_prompt"])
        self.assertIn("[Direct User Facts]", payload["assembled_prompt"])
        self.assertIn("[Current User Query]", payload["assembled_prompt"])

    def test_structured_ingest_and_audit_api(self) -> None:
        response = self.client.post(
            "/sessions/test-user/ingest-structured",
            json={
                "payload": {
                    "memories": [
                        {
                            "type": "preference",
                            "key": "response_opening",
                            "value": "answer_first",
                            "confidence": 0.9,
                            "evidence": "先给结论",
                            "exclusive_group": "response_opening",
                        }
                    ]
                }
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["accepted_memories"])

        audit_response = self.client.get("/sessions/test-user/audit")
        self.assertEqual(audit_response.status_code, 200)
        self.assertTrue(audit_response.json()["audit_events"])

    def test_correct_memory_api(self) -> None:
        self.client.post(
            "/sessions/test-user/ingest",
            json={"text": "我现在单身。"},
        )
        response = self.client.post(
            "/sessions/test-user/memories/correct",
            json={
                "memory_type": "state",
                "key": "relationship_status",
                "value": "dating",
                "evidence": "我刚才说错了，现在是恋爱中",
                "dynamics": "semi_static",
            },
        )
        self.assertEqual(response.status_code, 200)
        relationships = [
            item
            for item in response.json()["active_memories"]
            if item["key"] == "relationship_status"
        ]
        self.assertEqual(len(relationships), 1)
        self.assertEqual(relationships[0]["value"], "dating")

    def test_memory_slots_api(self) -> None:
        response = self.client.get("/memory-slots")

        self.assertEqual(response.status_code, 200)
        keys = [slot["key"] for slot in response.json()["slots"]]
        self.assertIn("relationship_status", keys)
        self.assertIn("response_opening", keys)

    def test_v2_ingest_and_memory_query_api(self) -> None:
        session_id = f"phase2-{uuid4().hex}"
        ingest = self.client.post(
            "/v2/users/test-user/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "我最近准备面试，有点焦虑。回答直接一点，先给结论。",
                "options": {"return_candidates": True},
            },
        )
        self.assertEqual(ingest.status_code, 200)
        ingest_payload = ingest.json()
        self.assertEqual(ingest_payload["preprocessed_turn"]["language"], "zh-CN")
        self.assertTrue(ingest_payload["candidate_memories"])
        self.assertTrue(ingest_payload["operations"])
        self.assertTrue(ingest_payload["event_states"])
        self.assertTrue(ingest_payload["persisted_records"])
        self.assertTrue(ingest_payload["persisted_event_states"])

        query = self.client.post(
            "/v2/users/test-user/memory/query",
            json={
                "session_id": session_id,
                "query": "面试怎么准备？",
                "options": {"max_prompt_memories": 8, "include_debug": True},
            },
        )

        self.assertEqual(query.status_code, 200)
        payload = query.json()
        self.assertIn("compiled_context", payload)
        self.assertIn("normalized_sqlite", payload["retrieval_plan"]["retrieval_modes"])
        self.assertEqual(payload["retrieval_plan"]["intent"]["name"], "career_advice")
        self.assertTrue(payload["gate"]["selected"])
        self.assertTrue(payload["compiled_context"]["event_followups"])

        events = self.client.get("/v2/users/test-user/memory/events")
        self.assertEqual(events.status_code, 200)
        self.assertTrue(events.json()["event_states"])

        audit = self.client.get("/v2/users/test-user/memory/audit")
        self.assertEqual(audit.status_code, 200)
        self.assertTrue(audit.json()["audit_events"])

    def test_v2_settings_api_can_disable_memory_key(self) -> None:
        user_id = f"settings-user-{uuid4().hex}"
        session_id = f"settings-session-{uuid4().hex}"
        settings = self.client.put(
            f"/v2/users/{user_id}/memory/settings",
            json={"disabled_keys": ["communication_style"]},
        )
        self.assertEqual(settings.status_code, 200)
        self.assertIn("communication_style", settings.json()["settings"]["disabled_keys"])

        ingest = self.client.post(
            f"/v2/users/{user_id}/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "回答直接一点。",
                "options": {"return_candidates": True},
            },
        )

        self.assertEqual(ingest.status_code, 200)
        self.assertEqual(ingest.json()["operations"][0]["operation"], "reject")
        self.assertEqual(ingest.json()["persisted_records"], [])

    def test_v2_delete_and_forget_all_do_not_fallback_to_legacy_memory(self) -> None:
        user_id = f"delete-user-{uuid4().hex}"
        session_id = f"delete-session-{uuid4().hex}"
        ingest = self.client.post(
            f"/v2/users/{user_id}/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "记住，回答直接一点。",
                "options": {"return_candidates": True},
            },
        )
        self.assertEqual(ingest.status_code, 200)
        memory_id = ingest.json()["persisted_records"][0]["id"]

        deleted = self.client.post(
            f"/v2/users/{user_id}/memory/{memory_id}/delete",
            json={"reason": "test delete"},
        )
        self.assertEqual(deleted.status_code, 200)

        query = self.client.post(
            f"/v2/users/{user_id}/memory/query",
            json={"session_id": session_id, "query": "我喜欢你怎么回答？"},
        )
        self.assertEqual(query.status_code, 200)
        self.assertEqual(query.json()["candidates"], [])

        second_ingest = self.client.post(
            f"/v2/users/{user_id}/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "记住，先给结论。",
                "options": {"return_candidates": True},
            },
        )
        self.assertEqual(second_ingest.status_code, 200)
        forget = self.client.post(
            f"/v2/users/{user_id}/memory/forget-all",
            json={"session_id": session_id, "reason": "test forget all"},
        )
        self.assertGreaterEqual(forget.json()["deleted_count"], 1)
        final_query = self.client.post(
            f"/v2/users/{user_id}/memory/query",
            json={"session_id": session_id, "query": "我喜欢你怎么回答？"},
        )
        self.assertEqual(final_query.status_code, 200)
        self.assertEqual(final_query.json()["candidates"], [])

    def test_v2_correct_memory_and_audit_export_api(self) -> None:
        user_id = f"correct-user-{uuid4().hex}"
        session_id = f"correct-session-{uuid4().hex}"
        ingest = self.client.post(
            f"/v2/users/{user_id}/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "记住，回答直接一点。",
                "options": {"return_candidates": True},
            },
        )
        self.assertEqual(ingest.status_code, 200)
        memory_id = ingest.json()["persisted_records"][0]["id"]

        corrected = self.client.post(
            f"/v2/users/{user_id}/memory/{memory_id}/correct",
            json={"value": "slow", "evidence": "我更正一下，慢慢讲。"},
        )
        self.assertEqual(corrected.status_code, 200)
        self.assertEqual(corrected.json()["corrected_memory"]["value"], "slow")

        export = self.client.get(f"/v2/users/{user_id}/memory/audit/export")
        self.assertEqual(export.status_code, 200)
        self.assertTrue(export.json()["memory_records"])
        self.assertTrue(export.json()["audit_events"])

    def test_v2_profile_evidence_accumulation_api(self) -> None:
        user_id = f"profile-user-{uuid4().hex}"
        session_id = f"profile-session-{uuid4().hex}"
        first = self.client.post(
            f"/v2/users/{user_id}/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "回答直接一点。",
                "options": {"return_candidates": True},
            },
        )
        second = self.client.post(
            f"/v2/users/{user_id}/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "再提醒一下，回答直接一点。",
                "options": {"return_candidates": True},
            },
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["profile_evidence"])
        self.assertTrue(second.json()["profile_candidates"])
        self.assertEqual(
            second.json()["profile_operations"][0]["operation"],
            "ask_user_confirmation",
        )

        evidence = self.client.get(f"/v2/users/{user_id}/memory/profile-evidence")
        self.assertEqual(evidence.status_code, 200)
        self.assertGreaterEqual(len(evidence.json()["profile_evidence"]), 2)

        queue = self.client.get(f"/v2/users/{user_id}/memory/review-queue")
        self.assertTrue(
            any(
                "directness_preference_level" in item["candidate_json"]
                for item in queue.json()["review_items"]
            )
        )

    def test_v2_review_queue_contains_before_after_diff(self) -> None:
        user_id = f"diff-user-{uuid4().hex}"
        session_id = f"diff-session-{uuid4().hex}"
        self.client.put(
            f"/v2/users/{user_id}/memory/settings",
            json={"review_required_for_layers": ["preference"]},
        )
        ingest = self.client.post(
            f"/v2/users/{user_id}/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "记住，回答直接一点。",
                "options": {"return_candidates": True},
            },
        )
        self.assertEqual(ingest.status_code, 200)
        self.assertEqual(ingest.json()["operations"][0]["operation"], "ask_user_confirmation")

        queue = self.client.get(f"/v2/users/{user_id}/memory/review-queue")
        self.assertEqual(queue.status_code, 200)
        item = queue.json()["review_items"][0]

        self.assertIn("candidate", item)
        self.assertIn("before_after_diff", item)

    def test_v2_ingest_accepts_llm_payload_extractor(self) -> None:
        session_id = f"phase2-llm-{uuid4().hex}"
        response = self.client.post(
            "/v2/users/test-user/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "回答直接一点。",
                "options": {
                    "extractor": "llm_payload",
                    "return_candidates": True,
                    "llm_payload": {
                        "candidate_memories": [
                            {
                                "layer": "preference",
                                "key": "communication_style",
                                "value": "direct",
                                "confidence": 0.9,
                                "authority": "user_explicit",
                                "sensitivity": "personal",
                                "evidence": "回答直接一点",
                            }
                        ]
                    },
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["candidate_memories"][0]["metadata"]["extractor_version"], "llm-proposal-v0")
        self.assertEqual(payload["operations"][0]["operation"], "create")
        self.assertTrue(payload["persisted_records"])

    def test_v2_ingest_invalid_llm_payload_returns_422(self) -> None:
        response = self.client.post(
            "/v2/users/test-user/turns/ingest",
            json={
                "session_id": f"phase2-llm-invalid-{uuid4().hex}",
                "role": "user",
                "text": "回答直接一点。",
                "options": {
                    "extractor": "llm_payload",
                    "llm_payload": {"candidate_memories": [{"key": "communication_style"}]},
                },
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("candidate missing required fields", response.json()["detail"])

    def test_v2_ingest_llm_sensitive_candidate_enters_review_queue(self) -> None:
        user_id = f"llm-review-user-{uuid4().hex}"
        session_id = f"llm-review-session-{uuid4().hex}"
        response = self.client.post(
            f"/v2/users/{user_id}/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "我现在单身。",
                "options": {
                    "extractor": "llm_payload",
                    "return_candidates": True,
                    "llm_payload": {
                        "candidate_memories": [
                            {
                                "layer": "semantic_fact",
                                "key": "relationship_status",
                                "value": "single",
                                "confidence": 0.86,
                                "authority": "assistant_inferred",
                                "sensitivity": "personal",
                                "evidence": "我现在单身",
                            }
                        ]
                    },
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["candidate_memories"][0]["sensitivity"], "sensitive")
        self.assertEqual(payload["operations"][0]["operation"], "ask_user_confirmation")

        queue = self.client.get(f"/v2/users/{user_id}/memory/review-queue")
        self.assertEqual(queue.status_code, 200)
        self.assertTrue(queue.json()["review_items"])

    def test_v2_ingest_honors_do_not_remember_command(self) -> None:
        ingest = self.client.post(
            "/v2/users/test-user/turns/ingest",
            json={
                "session_id": "phase2-private",
                "role": "user",
                "text": "别记，我现在单身。",
                "options": {"return_candidates": True},
            },
        )
        self.assertEqual(ingest.status_code, 200)
        ingest_payload = ingest.json()
        self.assertEqual(
            ingest_payload["preprocessed_turn"]["memory_command"],
            "do_not_remember",
        )
        self.assertEqual(ingest_payload["candidate_memories"], [])
        self.assertEqual(ingest_payload["operations"], [])

        query = self.client.post(
            "/v2/users/test-user/memory/query",
            json={
                "session_id": "phase2-private",
                "query": "我的感情状态是什么？",
            },
        )

        self.assertEqual(query.status_code, 200)
        self.assertEqual(query.json()["candidates"], [])

    def test_v2_review_queue_approval_api(self) -> None:
        session_id = f"phase2-review-{uuid4().hex}"
        ingest = self.client.post(
            "/v2/users/test-user/turns/ingest",
            json={
                "session_id": session_id,
                "role": "user",
                "text": "我现在单身。",
                "options": {"return_candidates": True},
            },
        )
        self.assertEqual(ingest.status_code, 200)
        self.assertEqual(ingest.json()["operations"][0]["operation"], "ask_user_confirmation")

        pending_query = self.client.post(
            "/v2/users/test-user/memory/query",
            json={
                "session_id": session_id,
                "query": "我的感情状态是什么？",
            },
        )
        self.assertEqual(pending_query.status_code, 200)
        self.assertEqual(pending_query.json()["candidates"], [])

        queue = self.client.get("/v2/users/test-user/memory/review-queue")
        self.assertEqual(queue.status_code, 200)
        review_items = [
            item
            for item in queue.json()["review_items"]
            if "relationship_status" in item["candidate_json"]
        ]
        self.assertTrue(review_items)

        resolved = self.client.post(
            f"/v2/users/test-user/memory/review-queue/{review_items[0]['id']}/resolve",
            json={"approve": True},
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["status"], "approved")
        self.assertTrue(resolved.json()["persisted_records"])


if __name__ == "__main__":
    unittest.main()
