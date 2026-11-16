"""API regressions for persisted controls and scope; all storage is temporary."""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as api
from memory_system.models import Authority, MemoryLayer, MemoryRecord, Sensitivity


NOW = "2026-11-16T12:00:00+00:00"


class V2ControlsTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.multiple(
            api, SQLITE_DB_PATH=Path(self.temp.name) / "memory.sqlite3",
            JSON_SESSION_DIR=Path(self.temp.name) / "sessions", STORAGE_BACKEND="json",
            manager=api.SessionManager(),
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = TestClient(api.app)
        self.root = "/v2/users/alice"

    def ingest(self, text="回答直接一点，先给结论。", **values):
        result = self.client.post(self.root + "/turns/ingest", json={
            "session_id": "thread", "text": text, "timestamp": NOW, **values,
        })
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def settings(self, **values):
        result = self.client.put(self.root + "/memory/settings", json=values)
        self.assertEqual(result.status_code, 200, result.text)

    def query(self, **values):
        result = self.client.post(self.root + "/memory/query", json={
            "session_id": "thread", "query": "怎么回答代码 review 问题？", "timestamp": NOW,
            "options": {"include_debug": True}, **values,
        })
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def prompt(self, **values):
        result = self.client.post(self.root + "/prompt-context", json={
            "session_id": "thread", "query": "怎么回答代码 review 问题？", "timestamp": NOW, **values,
        })
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_disabled_ingest_never_reappears_after_reenable(self):
        self.settings(memory_enabled=False)
        ingested = self.ingest()
        for key in ("persisted_records", "profile_evidence", "persisted_profile_records", "persisted_event_states"):
            self.assertEqual(ingested[key], [], key)
        self.assertEqual(ingested["legacy_active_memory_delta"]["created"], 0)
        self.settings(memory_enabled=True)
        self.assertEqual(self.query()["candidates"], [])
        self.assertEqual(self.prompt()["memory_context"]["style_policy"], [])
        self.assertEqual(api.build_normalized_repository().export_user_memory(user_id="alice")["audit_events"], [])
        self.assertFalse((Path(self.temp.name) / "sessions").exists())

    def test_dry_run_and_do_not_remember_have_no_derived_writes(self):
        self.ingest(options={"auto_write": False})
        self.ingest("不要记住：回答直接一点。")
        exported = api.build_normalized_repository().export_user_memory(user_id="alice")
        for key in ("memory_records", "profile_evidence", "review_queue", "audit_events"):
            self.assertEqual(exported[key], [], key)

    def test_fine_grained_controls_filter_both_read_paths_and_debug(self):
        self.ingest()
        self.assertTrue(self.query()["compiled_context"]["style_policy"])
        self.settings(disabled_keys=["communication_style"])
        self.assertNotIn("communication_style", str(self.query()))
        self.assertNotIn("Answer directly", self.prompt()["assembled_prompt"])
        self.settings(disabled_layers=["preference"])
        self.assertEqual(self.query()["candidates"], [])
        self.assertEqual(self.prompt()["memory_context"]["style_policy"], [])
        self.settings(disabled_keys=[], disabled_layers=[])
        self.assertTrue(self.query()["compiled_context"]["style_policy"])

    def test_temporary_requirements_do_not_persist_even_with_remember(self):
        for text in ("这次回答直接一点。", "记住：本轮回答直接一点。", "这个对话回答直接一点。"):
            with self.subTest(text=text):
                result = self.ingest(text)
                self.assertTrue(result["operations"])
                self.assertTrue(all(item["operation"] == "ephemeral_only" for item in result["operations"]))
                self.assertEqual(result["persisted_records"], [])
                self.assertEqual(result["profile_evidence"], [])
                self.assertEqual(result["legacy_active_memory_delta"]["created"], 0)
        self.assertEqual(self.query()["candidates"], [])

    def test_today_event_is_not_mistaken_for_temporary_instruction(self):
        result = self.ingest("今天我准备面试。")
        self.assertTrue(result["persisted_records"])

    def test_missing_session_does_not_mean_all_sessions(self):
        self.ingest()
        self.assertEqual(self.query(session_id=None)["candidates"], [])
        self.assertEqual(self.prompt(session_id=None)["memory_context"]["style_policy"], [])
        self.ingest("先给结论。", session_id=None)
        keys = [item["key"] for item in self.query(session_id=None)["candidates"]]
        self.assertIn("response_opening", keys)
        self.assertNotIn("communication_style", keys)

    def test_session_records_are_bound_to_project_even_with_same_thread_id(self):
        self.ingest(project_id="A")
        self.assertTrue(self.query(project_id="A")["candidates"])
        self.assertEqual(self.query(project_id="B")["candidates"], [])
        self.assertEqual(self.query()["candidates"], [])
        self.assertEqual(self.prompt(project_id="B")["memory_context"]["style_policy"], [])

    def test_project_sharing_requires_opt_in_and_preserves_metadata(self):
        denied = self.client.post(self.root + "/turns/ingest", json={
            "session_id": "thread", "project_id": "A", "memory_scope": "project",
            "text": "回答直接一点。", "timestamp": NOW,
        })
        self.assertEqual(denied.status_code, 422)
        self.settings(enabled_project_ids=["A"])
        self.ingest(project_id="A", domain="coding", memory_scope="project")
        candidates = self.query(session_id="other-thread", project_id="A")["candidates"]
        self.assertTrue(candidates)
        self.assertTrue(all(item["project_id"] == "A" and item["scope"] == "project" for item in candidates))
        self.assertTrue(all(item["source_turn_ids"] for item in candidates))
        self.assertEqual(self.query(session_id="other-thread", project_id="B")["candidates"], [])
        self.assertEqual(self.query(session_id=None)["candidates"], [])
        self.settings(enabled_project_ids=[])
        self.assertEqual(self.query(project_id="A")["candidates"], [])

    def test_global_sharing_is_explicit_and_can_be_revoked(self):
        self.settings(allow_global_memory=True)
        self.ingest(memory_scope="global")
        self.assertTrue(self.query(session_id="another")["candidates"])
        self.settings(allow_global_memory=False)
        self.assertEqual(self.query()["candidates"], [])
        self.assertEqual(self.prompt()["memory_context"]["style_policy"], [])

    def test_profile_requires_approval_and_settings_still_override_approval(self):
        self.ingest("回答直接一点。")
        self.ingest("再提醒一下，回答直接一点。")
        repository = api.build_normalized_repository()
        pending = repository.list_review_items(user_id="alice")
        self.assertTrue(pending)
        self.assertFalse(any(item["type"] == "profile" for item in self.query()["candidates"]))
        self.settings(allow_inferred_profile=False)
        blocked = self.client.post(self.root + f"/memory/review-queue/{pending[0]['id']}/resolve", json={"approve": True, "timestamp": NOW})
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(repository.get_review_item(pending[0]["id"])["status"], "pending")
        self.settings(allow_inferred_profile=True)
        approved = self.client.post(self.root + f"/memory/review-queue/{pending[0]['id']}/resolve", json={"approve": True, "timestamp": NOW})
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertTrue(approved.json()["persisted_records"][0]["metadata"]["user_review_approved"])
        self.assertTrue(any(item["type"] == "profile" for item in self.query()["candidates"]))
        self.settings(allow_inferred_profile=False)
        self.assertFalse(any(item["type"] == "profile" for item in self.query()["candidates"]))

    def test_disabled_source_does_not_contribute_to_profile_in_other_project(self):
        self.ingest("回答直接一点。", project_id="A")
        result = self.ingest("回答直接一点。", project_id="B")
        self.assertEqual(result["profile_candidates"], [])
        self.assertEqual(self.query(project_id="A", session_id="other")["candidates"], [])

    def test_expired_profile_source_cannot_influence_either_context_path(self):
        first = self.ingest("回答直接一点。")
        self.ingest("再提醒一下，回答直接一点。")
        repository = api.build_normalized_repository()
        pending = repository.list_review_items(user_id="alice")[0]
        approved = self.client.post(self.root + f"/memory/review-queue/{pending['id']}/resolve", json={"approve": True, "timestamp": NOW})
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertIn("directness_preference_level", str(self.query()))
        source = repository.get_record(first["persisted_records"][0]["id"])
        source.valid_to = datetime.fromisoformat(NOW) - timedelta(seconds=1)
        repository.upsert_record(source)
        self.assertNotIn("directness_preference_level", str(self.query()))
        self.assertNotIn("directness_preference_level", str(self.prompt()))

    def test_scope_revocation_blocks_correction_and_event_opt_in(self):
        self.settings(enabled_project_ids=["A"], allow_global_memory=True)
        project = self.ingest(project_id="A", memory_scope="project")["persisted_records"][0]
        global_record = self.ingest(memory_scope="global")["persisted_records"][0]
        event = self.ingest("我最近准备面试。", project_id="A", memory_scope="project")["persisted_event_states"][0]
        self.settings(enabled_project_ids=[], allow_global_memory=False)
        for record in (project, global_record):
            result = self.client.post(self.root + f"/memory/{record['id']}/correct", json={"value": "slow", "evidence": "慢慢讲。"})
            self.assertEqual(result.status_code, 409)
        enabled = self.client.put(self.root + f"/memory/events/{event['memory_id']}/followup", json={"enabled": True})
        self.assertEqual(enabled.status_code, 409)

    def test_deleted_record_cannot_be_revived_by_stale_correction(self):
        record = self.ingest()["persisted_records"][0]
        self.client.post(self.root + f"/memory/{record['id']}/delete", json={})
        result = self.client.post(self.root + f"/memory/{record['id']}/correct", json={"value": "slow", "evidence": "慢慢讲。"})
        self.assertEqual(result.status_code, 404)
        self.assertNotIn(record["id"], [item["memory_id"] for item in self.query()["candidates"]])

    def test_events_require_per_event_opt_in_and_master_read_setting(self):
        result = self.ingest("我最近准备面试。")
        event = result["persisted_event_states"][0]
        kwargs = {"query": "面试怎么准备？"}
        self.assertEqual(self.query(**kwargs)["compiled_context"]["event_followups"], [])
        enabled = self.client.put(self.root + f"/memory/events/{event['memory_id']}/followup", json={"enabled": True, "timestamp": NOW})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertTrue(self.query(**kwargs)["compiled_context"]["event_followups"])
        self.settings(allow_event_followup=False)
        self.assertEqual(self.query(**kwargs)["compiled_context"]["event_followups"], [])
        self.assertEqual(self.prompt(**kwargs)["memory_context"]["event_followups"], [])
        self.settings(allow_event_followup=True)
        disabled = self.client.put(self.root + f"/memory/events/{event['memory_id']}/followup", json={"enabled": False, "timestamp": NOW})
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(self.query(**kwargs)["compiled_context"]["event_followups"], [])

    def test_v2_never_implicitly_reads_or_writes_legacy_store(self):
        legacy = self.client.post("/sessions/alice:thread/ingest", json={"text": "回答直接一点。", "timestamp": NOW})
        self.assertEqual(legacy.status_code, 200)
        self.assertTrue(legacy.json()["accepted_memories"])
        self.assertEqual(self.query()["candidates"], [])
        self.assertEqual(self.prompt()["memory_context"]["style_policy"], [])
        result = self.ingest("先给结论。")
        self.assertEqual(result["legacy_active_memory_delta"]["created"], 0)
        self.assertNotIn("communication_style", str(self.query()))

    def test_sensitive_setting_filters_existing_records_before_ranking(self):
        record = MemoryRecord(
            user_id="alice", session_id="thread", layer=MemoryLayer.PREFERENCE,
            key="communication_style", value="direct", normalized_value="direct", confidence=1,
            authority=Authority.USER_EXPLICIT, sensitivity=Sensitivity.SENSITIVE,
            valid_from=datetime.fromisoformat(NOW), observed_at=datetime.fromisoformat(NOW),
        )
        api.build_normalized_repository().upsert_record(record)
        self.assertEqual(self.query()["candidates"], [])
        self.assertEqual(self.prompt()["memory_context"]["style_policy"], [])
        self.settings(allow_sensitive_memory=True)
        self.assertTrue(self.query()["candidates"])

    def test_master_off_blocks_review_and_correction_but_allows_deletion(self):
        stored = self.ingest()["persisted_records"][0]
        self.settings(memory_enabled=False)
        corrected = self.client.post(self.root + f"/memory/{stored['id']}/correct", json={"value": "slow", "evidence": "慢慢讲。"})
        self.assertEqual(corrected.status_code, 409)
        deleted = self.client.post(self.root + f"/memory/{stored['id']}/delete", json={})
        self.assertEqual(deleted.status_code, 200)
        self.settings(memory_enabled=True)
        self.assertNotIn(stored["id"], [item["memory_id"] for item in self.query()["candidates"]])


if __name__ == "__main__":
    unittest.main()
