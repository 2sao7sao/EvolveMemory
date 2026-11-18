"""Capacity facts remain usable without silently overriding answer preferences.

These contracts cover the shared response-policy engine, standalone stored-fact
reads, and the v2 query/prompt routes used by the live host. The separate legacy
ProfileInferencer ingestion mappings are not changed or validated here.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as api
from memory_system.engine import ResponsePolicyEngine
from memory_system.models import MemoryLayer, MemoryRecord
from memory_system.schema import MemoryItem, MemoryType
from memory_system.service import SessionMemoryRuntime


NOW = datetime(2026, 11, 20, 9, tzinfo=timezone.utc)


def memory(key, value, kind=MemoryType.PREFERENCE):
    return MemoryItem(memory_type=kind, key=key, value=value, confidence=.95,
                      source="synthetic-test", evidence=f"Explicit test evidence for {key}",
                      valid_from=NOW, valid_to=NOW + timedelta(days=1),
                      authority="user_explicit", memory_id=f"test-{key}")


class BandwidthPolicyTest(unittest.TestCase):
    def test_capacity_alone_does_not_define_answer_shape(self):
        baseline = ResponsePolicyEngine().build_from_memories([]).to_dict()
        for state in ("busy", "available"):
            with self.subTest(state=state):
                actual = ResponsePolicyEngine().build_from_memories([
                    memory("current_bandwidth", state, MemoryType.STATE)]).to_dict()
                self.assertEqual(actual, baseline)

    def test_busy_preserves_learning_and_explicit_answer_preferences(self):
        sets = [
            [memory("learning_preference", "example_first")],
            [memory("learning_preference", "principle_first"), memory("detail_preference", "detailed")],
            [memory("detail_preference", "concise"), memory("response_opening", "answer_first"),
             memory("communication_pace", "slow")],
            [memory("pace_preference", "slow", MemoryType.PROFILE)],
        ]
        for preferences in sets:
            with self.subTest(keys=[item.key for item in preferences]):
                expected = ResponsePolicyEngine().build_from_memories(preferences).to_dict()
                actual = ResponsePolicyEngine().build_from_memories([
                    *preferences, memory("current_bandwidth", "busy", MemoryType.STATE)]).to_dict()
                self.assertEqual(actual, expected)

    def test_standalone_runtime_keeps_capacity_fact_without_compiling_style_override(self):
        runtime = SessionMemoryRuntime()
        # Exercise stored-fact read paths without invoking legacy profile inference.
        runtime.store.extend([memory("current_bandwidth", "busy", MemoryType.STATE),
                              memory("learning_preference", "example_first")])
        query = "我现在很忙，怎么回答这个学习问题？"
        result = runtime.query(query, NOW)
        prompt = runtime.prompt_context(query, NOW)
        self.assertIn("current_bandwidth", [item["key"] for item in result["relevant_memories"]])
        self.assertIn("current_bandwidth: busy", prompt["compiled_context"]["direct_facts"])
        self.assertEqual(result["response_policy"], prompt["response_policy"])
        self.assertEqual(result["response_policy"]["detail_level"], "medium")
        self.assertEqual(result["response_policy"]["structure"], "balanced")
        self.assertEqual(result["response_policy"]["pace"], "medium")
        self.assertIn("Introduce concepts through examples before abstraction.", prompt["assembled_prompt"])


class V2BandwidthPolicyTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        override = patch.multiple(api, SQLITE_DB_PATH=Path(temp.name) / "memory.sqlite3",
                                  JSON_SESSION_DIR=Path(temp.name) / "sessions")
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(api.app)
        self.root = "/v2/users/policy-test"
        response = self.client.put(self.root + "/memory/settings", json={"enabled_project_ids": ["lab"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.repository = api.build_normalized_repository()
        for key, value, layer in (("current_bandwidth", "busy", MemoryLayer.SEMANTIC_FACT),
                                  ("learning_preference", "example_first", MemoryLayer.PREFERENCE)):
            self.repository.upsert_record(MemoryRecord(
                user_id="policy-test", session_id="source-session", project_id="lab", scope="project",
                layer=layer, key=key, value=value, confidence=.95,
                source_turn_ids=["synthetic-source"], valid_from=NOW,
                valid_to=NOW + timedelta(days=1), observed_at=NOW))

    def read_both(self, query):
        body = {"session_id": "new-session", "project_id": "lab", "query": query,
                "timestamp": NOW.isoformat()}
        responses = [self.client.post(self.root + path, json=body)
                     for path in ("/memory/query", "/prompt-context")]
        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
        result, prompt = [response.json() for response in responses]
        self.assertEqual(result["response_policy"], prompt["response_policy"])
        self.assertEqual(result["response_policy"], prompt["memory_context"]["response_policy"])
        self.assertIn("current_bandwidth", [item["key"] for item in result["candidates"]])
        self.assertIn("current_bandwidth: busy", prompt["memory_context"]["direct_facts"])
        return result, prompt

    def test_busy_does_not_force_learning_order_depth_or_pace_for_any_query_language(self):
        before = self.repository.export_user_memory(user_id="policy-test")
        for query in ("Explain how a checksum detects corruption.", "为什么会出现校验碰撞？", "请解释消息重放的原理。"):
            with self.subTest(query=query):
                result, prompt = self.read_both(query)
                self.assertEqual(result["response_policy"]["structure"], "balanced")
                self.assertEqual(result["response_policy"]["detail_level"], "medium")
                self.assertEqual(result["response_policy"]["pace"], "medium")
                self.assertIn("Introduce concepts through examples before abstraction.", prompt["assembled_prompt"])
                self.assertNotIn("structure=answer_first", prompt["assembled_prompt"])
                self.assertNotIn("detail_level=low", prompt["assembled_prompt"])
                self.assertNotIn("pace=fast", prompt["assembled_prompt"])
        self.assertEqual(before, self.repository.export_user_memory(user_id="policy-test"))

    def test_current_detail_instruction_still_controls_this_answer_without_writing(self):
        before = self.repository.export_user_memory(user_id="policy-test")
        for query, expected in (("这次详细解释这个机制。", "high"), ("这次简洁一点。", "low")):
            with self.subTest(query=query):
                result, prompt = self.read_both(query)
                self.assertEqual(result["response_policy"]["detail_level"], expected)
                self.assertIn(f"detail_level={expected}", prompt["assembled_prompt"])
        self.assertEqual(before, self.repository.export_user_memory(user_id="policy-test"))


if __name__ == "__main__":
    unittest.main()
