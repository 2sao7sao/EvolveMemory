from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from memory_system import (
    DialogueMemoryExtractor,
    DiskSessionRepository,
    MemoryStore,
    ProfileInferencer,
    PromptContextBuilder,
    QueryMemoryRetriever,
    ResponsePolicyEngine,
    SessionMemoryRuntime,
)
from app import app


class MemorySystemTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tz = ZoneInfo("Asia/Shanghai")
        self.extractor = DialogueMemoryExtractor()
        self.store = MemoryStore()
        self.inferencer = ProfileInferencer()
        self.retriever = QueryMemoryRetriever()
        self.policy_engine = ResponsePolicyEngine()
        self.prompt_builder = PromptContextBuilder()

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
        self.assertEqual(
            query_payload["response_policy"]["decision_mode"],
            "give_recommendation",
        )

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
        self.assertIn("[Current User Query]", payload["assembled_prompt"])


if __name__ == "__main__":
    unittest.main()
