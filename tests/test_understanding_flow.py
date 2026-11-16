"""End-to-end context contracts; these do not assert real-model answer quality."""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as api
from memory_system.models import MemoryLayer
from memory_system.profiles import ProfileEvidence


NOW = "2026-11-16T12:00:00+00:00"


class UnderstandingFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = patch.multiple(api, SQLITE_DB_PATH=Path(self.temp.name) / "memory.sqlite3",
                                  JSON_SESSION_DIR=Path(self.temp.name) / "sessions")
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(api.app)
        self.root = "/v2/users/alice"

    def ingest(self, text, **kw):
        response = self.client.post(self.root + "/turns/ingest", json={
            "text": text, "session_id": "thread", "timestamp": NOW, **kw})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def query(self, query="怎么回答这个工程问题？", *, prompt=False, **kw):
        path = "/prompt-context" if prompt else "/memory/query"
        response = self.client.post(self.root + path, json={
            "query": query, "session_id": "thread", "timestamp": NOW, **kw})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_automatic_profile_needs_no_review_and_is_used_silently(self):
        first = self.ingest("回答直接一点。", turn_id="one")
        self.assertEqual(first["profile_candidates"], [])
        second = self.ingest("再提醒一下，回答直接一点。", turn_id="two")
        self.assertTrue(second["persisted_profile_records"])
        repository = api.build_normalized_repository()
        self.assertEqual(repository.list_review_items(user_id="alice"), [])
        self.assertTrue(any(item["type"] == "profile" for item in self.query()["candidates"]))
        prompt = self.query(prompt=True)
        self.assertEqual(prompt["memory_context"]["clarification_prompts"], [])
        self.assertIn("Answer directly while staying warm.", prompt["assembled_prompt"])
        self.assertNotIn("directness_preference_level=high", prompt["assembled_prompt"])
        self.assertNotIn("再提醒一下", prompt["assembled_prompt"])
        self.assertIn("do not announce remembered preferences", prompt["system_guidance"])

    def test_retry_of_same_host_turn_is_not_independent_support(self):
        self.ingest("回答直接一点。", turn_id="one")
        retry = self.ingest("回答直接一点。", turn_id="one")
        self.assertEqual(retry["profile_candidates"], [])
        repository = api.build_normalized_repository()
        self.assertEqual(len(repository.list_profile_evidence(user_id="alice")), 1)
        self.assertEqual(repository.list_review_items(user_id="alice"), [])

    def test_ingest_preserves_quoted_preference_boundaries(self):
        result = self.ingest("我现在先讲原理。\n> 先举例", turn_id="one")
        preferences = [item for item in result["persisted_records"] if item["key"] == "learning_preference"]
        self.assertEqual([item["value"] for item in preferences], ["principle_first"])

    def test_current_detail_overrides_old_style_without_changing_memory(self):
        self.ingest("简洁一点。", turn_id="one")
        self.ingest("再提醒一下，简洁一点。", turn_id="two")
        repository = api.build_normalized_repository()
        before = repository.export_user_memory(user_id="alice")
        query = self.query("这次详细解释这个原理。")
        prompt = self.query("这次详细解释这个原理。", prompt=True)
        self.assertEqual(query["response_policy"]["detail_level"], "high")
        self.assertEqual(prompt["response_policy"], query["response_policy"])
        self.assertNotIn("Keep the response concise", prompt["assembled_prompt"])
        self.assertEqual(repository.export_user_memory(user_id="alice"), before)
        self.assertEqual(self.query()["response_policy"]["detail_level"], "low")

    def test_corrected_preference_stops_old_profile_and_learns_new_pattern(self):
        self.ingest("简洁一点。", turn_id="one")
        self.ingest("再提醒一下，简洁一点。", turn_id="two")
        self.ingest("更新一下，以后多给细节。", turn_id="three")
        prompt = self.query(prompt=True)
        self.assertEqual(prompt["response_policy"]["detail_level"], "high")
        self.assertNotIn("Keep the response concise", prompt["assembled_prompt"])
        self.ingest("解释时多给细节。", turn_id="four")
        profiles = [item for item in self.query()["candidates"] if item["type"] == "profile"]
        self.assertTrue(any(item["key"] == "detail_tolerance" and item["value"] == "high" for item in profiles))

    def test_do_not_remember_does_not_disable_current_instruction(self):
        self.ingest("简洁一点。", turn_id="one")
        repository = api.build_normalized_repository()
        before = repository.export_user_memory(user_id="alice")
        for prompt in (False, True):
            result = self.query("不要记住这句话，这次详细解释原理。", prompt=prompt)
            self.assertEqual(result["response_policy"]["detail_level"], "high")
        self.assertEqual(repository.export_user_memory(user_id="alice"), before)

    def test_profiles_decay_at_query_time_with_no_new_ingest(self):
        self.ingest("回答直接一点。", turn_id="one")
        self.ingest("再提醒一下，回答直接一点。", turn_id="two")
        future = (datetime.fromisoformat(NOW) + timedelta(days=180)).isoformat()
        self.assertFalse(any(item["type"] == "profile" for item in self.query(timestamp=future)["candidates"]))

    def test_new_counter_evidence_can_withdraw_profile_without_replacement(self):
        self.ingest("回答直接一点。", turn_id="one")
        result = self.ingest("再提醒一下，回答直接一点。", turn_id="two")
        repository = api.build_normalized_repository()
        source = result["persisted_records"][0]
        # A later model/host observation is tied to a live authorized source.
        from uuid import UUID
        repository.add_profile_evidence(ProfileEvidence(
            user_id="alice", session_id="thread", dimension="directness_preference_level",
            value="high", confidence=1, weight=1, polarity="counter",
            source_memory_id=UUID(source["id"]), source_key=source["key"],
            quote="这个情境需要委婉一些", observed_at=datetime.fromisoformat(NOW), source_turn_id="counter",
        ))
        self.assertFalse(any(item["type"] == "profile" for item in self.query()["candidates"]))
        self.assertNotIn("directness_preference_level", self.query(prompt=True)["assembled_prompt"])

    def test_auto_profile_disable_and_source_deletion_apply_to_both_reads(self):
        first = self.ingest("回答直接一点。", turn_id="one")
        self.ingest("再提醒一下，回答直接一点。", turn_id="two")
        self.client.put(self.root + "/memory/settings", json={"allow_inferred_profile": False})
        self.assertFalse(any(item["type"] == "profile" for item in self.query()["candidates"]))
        self.client.put(self.root + "/memory/settings", json={"allow_inferred_profile": True})
        source_id = first["persisted_records"][0]["id"]
        self.client.post(self.root + f"/memory/{source_id}/delete", json={"timestamp": NOW})
        self.assertEqual(self.query()["candidates"], [])
        self.assertEqual(self.query(prompt=True)["memory_context"]["style_policy"], [])

    def test_recomputed_profile_refreshes_provenance_without_inflated_count(self):
        for index in range(3):
            self.ingest("回答直接一点。", turn_id=str(index))
        records = api.build_normalized_repository().list_records(user_id="alice")
        profile = next(item for item in records if item.layer == MemoryLayer.INFERRED_PROFILE)
        self.assertEqual(profile.metadata["evidence_count"], 3)
        self.assertEqual(len(profile.metadata["evidence_ids"]), 3)
        self.assertEqual(len(profile.source_turn_ids), 3)

    def test_explicit_profile_correction_is_used_and_old_signals_do_not_recreate_it(self):
        self.ingest("简洁一点。", turn_id="one")
        result = self.ingest("再提醒一下，简洁一点。", turn_id="two")
        profile = next(item for item in result["persisted_profile_records"] if item["key"] == "detail_tolerance")
        corrected = self.client.post(self.root + f"/memory/{profile['id']}/correct", json={
            "value": "high", "evidence": "你理解错了，我需要完整深入的解释", "timestamp": NOW})
        self.assertEqual(corrected.status_code, 200, corrected.text)
        for prompt in (False, True):
            read = self.query(prompt=prompt)
            self.assertEqual(read["response_policy"]["detail_level"], "high")
        self.assertNotIn("Keep the response concise", self.query(prompt=True)["assembled_prompt"])
        self.ingest("先给结论。", turn_id="three")
        self.assertEqual(self.query()["response_policy"]["detail_level"], "high")
        repository = api.build_normalized_repository()
        self.assertEqual(repository.list_review_items(user_id="alice"), [])

    def test_remaining_independent_sources_can_still_support_profile_after_delete(self):
        first = self.ingest("先给结论。", turn_id="one")
        self.ingest("分步骤解释。", turn_id="two")
        self.ingest("还是分步骤。", turn_id="three")
        source_id = first["persisted_records"][0]["id"]
        self.client.post(self.root + f"/memory/{source_id}/delete", json={"timestamp": NOW})
        profiles = [item for item in self.query()["candidates"] if item["type"] == "profile"]
        profile = next(item for item in profiles if item["key"] == "structure_preference_level")
        self.assertNotIn(source_id, profile["metadata"]["source_memory_ids"])
        self.assertEqual(profile["metadata"]["evidence_count"], 2)

    def test_profile_correction_changes_prompt_tone_as_well_as_stored_value(self):
        self.ingest("回答直接一点。", turn_id="one")
        result = self.ingest("再提醒一下，回答直接一点。", turn_id="two")
        profile = result["persisted_profile_records"][0]
        corrected = self.client.post(self.root + f"/memory/{profile['id']}/correct", json={
            "value": "low", "evidence": "委婉一些会更舒服", "timestamp": NOW})
        self.assertEqual(corrected.status_code, 200, corrected.text)
        prompt = self.query(prompt=True)
        self.assertEqual(prompt["response_policy"]["tone"], "gentle_and_tactful")
        self.assertIn("Use a gentle, tactful tone", prompt["assembled_prompt"])
        self.assertNotIn("Answer directly while staying warm", prompt["assembled_prompt"])


if __name__ == "__main__":
    unittest.main()
