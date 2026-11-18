"""Regression tests for GitHub issue #14.

A negated preference ("I don't think shorter is always better") must not become
positive profile evidence, and an explicit one-off instruction ("this time",
"this round") must not accumulate into a long-term profile.
"""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

import app as api
from memory_system.models import Authority, MemoryLayer, MemoryRecord
from memory_system.profiles import (
    ProfileAccumulator, ProfileEvidence, ProfileEvidenceExtractor,
    is_supported_profile_evidence,
)
from memory_system.semantic_review import apply_semantic_review


NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat()

T08_TEXT = "我今天还剩十分钟。把结果列表最后一处最值得收尾的小问题挑出来，给一个动作和一个完成判据就好。"
T08_EVIDENCE = "给一个动作和一个完成判据就好"
T11_TEXT = "撤销成功后，按钮旁边需要一条自然的提示。直接给一句可用文案，别再展开机制解释。"
T11_EVIDENCE = "直接给一句可用文案"
T13_TEXT = (
    "也纠正一下可能从前几轮得出的印象：我不是一概觉得越短越好，之前有几次只是忙。"
    "在项目评审里，我更喜欢先有结论，再看到主要风险和下一步；需要理解原理时，必要解释不要省。"
    "照这个方式继续，不用再逐项问我是否确认某个画像。"
)
T13_EVIDENCE = "我不是一概觉得越短越好，之前有几次只是忙"


def preference(turn_id: str, **changes: object) -> MemoryRecord:
    payload = {
        "user_id": "mapping-test", "session_id": "thread", "scope": "session",
        "layer": MemoryLayer.PREFERENCE, "key": "detail_preference", "value": "concise",
        "normalized_value": "concise", "confidence": 0.95, "authority": Authority.USER_EXPLICIT,
        "valid_from": NOW, "observed_at": NOW, "source_turn_ids": [turn_id],
        "metadata": {"evidence": "I generally prefer concise answers."},
    }
    payload.update(changes)
    return MemoryRecord.model_validate(payload)


class NegatedEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = ProfileEvidenceExtractor()
        self.accumulator = ProfileAccumulator()

    def test_negated_preference_quote_is_counter_evidence_not_support(self) -> None:
        record = preference("t13", metadata={"evidence": T13_EVIDENCE})
        evidence = self.extractor.extract([record])

        self.assertNotIn("support", {item.polarity for item in evidence})
        self.assertEqual(
            {(item.dimension, item.value, item.polarity) for item in evidence},
            {("detail_tolerance", "low", "counter")},
        )
        second = preference("t13-b", metadata={"evidence": T13_EVIDENCE})
        self.assertEqual(
            self.accumulator.accumulate(evidence + self.extractor.extract([second]), now=NOW),
            [],
        )
        # Evidence already persisted from the wrong polarity is no longer eligible.
        self.assertFalse(is_supported_profile_evidence(replace(evidence[0], polarity="support"), record))
        # An affirmative quote still supports the profile.
        positive = preference("positive", metadata={"evidence": "我更喜欢简洁一点的回答。"})
        positive_evidence = self.extractor.extract([positive])
        self.assertIn("support", {item.polarity for item in positive_evidence})
        self.assertTrue(is_supported_profile_evidence(
            next(item for item in positive_evidence if item.value == "low"), positive))

    def test_task_shaped_quote_never_counts_as_preference_evidence(self) -> None:
        record = preference("t08", metadata={"evidence": T08_EVIDENCE})
        self.assertEqual(self.extractor.extract([record]), [])
        legacy = ProfileEvidence(
            user_id="mapping-test", session_id="thread", dimension="detail_tolerance",
            value="low", confidence=0.72, weight=0.78, polarity="support",
            source_memory_id=record.id, source_key="detail_preference",
            quote=T08_EVIDENCE, observed_at=NOW, source_turn_id="t08",
        )
        self.assertFalse(is_supported_profile_evidence(legacy, record))

    def test_semantic_review_rejects_preference_supported_by_a_negated_quote(self) -> None:
        candidate = {
            "layer": "preference", "key": "detail_preference", "value": "concise",
            "retention": "durable", "evidence": T13_EVIDENCE,
        }
        decision = {
            "candidate_index": 0, "relation": "supports",
            "evidence_kind": "sustained_preference", "retention": "durable",
        }
        accepted, rejected = apply_semantic_review(
            [candidate], {"decisions": [decision], "memory_retractions": []},
            text=T13_TEXT, existing_assertions=[],
        )
        self.assertEqual(accepted["candidate_memories"], [])
        self.assertEqual(rejected[0]["reason"], "negated_evidence_not_support")
        positive = {**candidate, "evidence": "我更喜欢简洁一点的回答"}
        accepted, rejected = apply_semantic_review(
            [positive], {"decisions": [decision], "memory_retractions": []},
            text=positive["evidence"], existing_assertions=[],
        )
        self.assertEqual(len(accepted["candidate_memories"]), 1)
        self.assertEqual(rejected, [])


class OneOffRequestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = patch.multiple(
            api, SQLITE_DB_PATH=Path(self.temp.name) / "memory.sqlite3",
            JSON_SESSION_DIR=Path(self.temp.name) / "sessions",
        )
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(api.app)
        self.root = "/v2/users/alice"

    def ingest(self, text: str, turn_id: str) -> dict:
        response = self.client.post(self.root + "/turns/ingest", json={
            "text": text, "session_id": "thread", "timestamp": NOW_ISO, "turn_id": turn_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_explicit_one_off_short_answer_requests_do_not_become_profiles(self) -> None:
        first = self.ingest("这次简洁一点，只针对这个例子。", "t08")
        self.assertTrue(all(item["operation"] == "ephemeral_only" for item in first["operations"]))
        self.assertEqual(first["persisted_records"], [])
        second = self.ingest("本轮就简洁一点。", "t11")
        self.assertEqual(second["persisted_records"], [])
        self.assertEqual(second["profile_candidates"], [])
        self.assertEqual(second["profile_evidence"], [])

    def test_durable_request_still_accumulates(self) -> None:
        self.ingest("以后都简洁一点。", "one")
        result = self.ingest("以后都简洁一点。", "two")
        self.assertTrue(any(
            item["key"] == "detail_tolerance" and item["value"] == "low"
            for item in result["profile_candidates"]
        ))


class Issue14ScenarioTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = patch.multiple(
            api, SQLITE_DB_PATH=Path(self.temp.name) / "memory.sqlite3",
            JSON_SESSION_DIR=Path(self.temp.name) / "sessions",
        )
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(api.app)
        self.root = "/v2/users/alice"

    def candidate(self, evidence: str) -> dict:
        return {
            "layer": "preference", "key": "detail_preference", "value": "concise",
            "normalized_value": "concise", "confidence": 0.72,
            "authority": "user_implicit", "sensitivity": "personal",
            "evidence": evidence, "retention": "durable",
            "evidence_kind": "sustained_preference",
            "exclusive_group": "detail_preference",
            "coexistence_rule": "mutually_exclusive",
        }

    def ingest_llm(self, text: str, turn_id: str, evidence: str) -> dict:
        response = self.client.post(self.root + "/turns/ingest", json={
            "text": text, "session_id": "thread", "timestamp": NOW_ISO, "turn_id": turn_id,
            "options": {"extractor": "llm_payload",
                        "llm_payload": {"candidate_memories": [self.candidate(evidence)]}},
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def query(self) -> dict:
        response = self.client.post(self.root + "/memory/query", json={
            "query": "帮我评审这个处理规则", "session_id": "thread", "timestamp": NOW_ISO})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_t08_t11_t13_do_not_create_low_detail_profiles(self) -> None:
        t08 = self.ingest_llm(T08_TEXT, "T08", T08_EVIDENCE)
        t11 = self.ingest_llm(T11_TEXT, "T11", T11_EVIDENCE)
        t13 = self.ingest_llm(T13_TEXT, "T13", T13_EVIDENCE)
        low_detail = {"detail_tolerance", "cognitive_load_preference"}
        for result in (t08, t11, t13):
            self.assertEqual(
                [item for item in result["profile_candidates"] if item["key"] in low_detail], [],
            )
        self.assertTrue(all(item["polarity"] == "counter" for item in t13["profile_evidence"]))
        repository = api.build_normalized_repository()
        self.assertEqual(
            [record for record in repository.list_records(user_id="alice")
             if record.layer == MemoryLayer.INFERRED_PROFILE and record.key in low_detail],
            [],
        )
        self.assertFalse(any(
            item["type"] == "profile" and item["key"] in low_detail
            for item in self.query()["candidates"]
        ))
        # A profile store already polluted by T08-style evidence is revalidated on read.
        source = t08["persisted_records"][0]
        repository.add_profile_evidence(ProfileEvidence(
            user_id="alice", session_id="thread", dimension="detail_tolerance", value="low",
            confidence=0.9, weight=0.9, polarity="support",
            source_memory_id=UUID(source["id"]), source_key="detail_preference",
            quote=T08_EVIDENCE, observed_at=NOW, source_turn_id="T08",
        ))
        self.assertFalse(any(
            item["type"] == "profile" and item["key"] in low_detail
            for item in self.query()["candidates"]
        ))


if __name__ == "__main__":
    unittest.main()
