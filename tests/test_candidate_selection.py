"""A model-selected ID is a read filter, never authority to access a memory.

Synthetic records exercise the API boundary; no live scenario is seeded and no
provider is called. Real model relevance/answer quality is tested separately.
"""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as api
from memory_system.models import AllowedUse, MemoryLayer, MemoryRecord, MemoryStatus, Sensitivity


NOW = datetime.fromisoformat("2026-11-16T12:00:00+00:00")


class CandidateSelectionTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        override = patch.multiple(api, SQLITE_DB_PATH=Path(temp.name) / "memory.sqlite3",
                                  JSON_SESSION_DIR=Path(temp.name) / "sessions")
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(api.app)
        self.root = "/v2/users/alice"
        self.repository = api.build_normalized_repository()
        self.settings(enabled_project_ids=["project-a"])

    def settings(self, **values):
        response = self.client.put(self.root + "/memory/settings", json=values)
        self.assertEqual(response.status_code, 200, response.text)

    def record(self, key="project_constraint", value="project controlled fact", **changes):
        fields = dict(user_id="alice", session_id="thread", project_id="project-a", scope="project",
                      layer=MemoryLayer.SEMANTIC_FACT, key=key, value=value, confidence=.95,
                      source_turn_ids=[f"source-{key}"], valid_from=NOW - timedelta(days=1), observed_at=NOW)
        fields.update(changes)
        record = MemoryRecord(**fields)
        self.repository.upsert_record(record)
        return str(record.id)

    def read(self, *, ids=None, prompt=False, query="继续检查项目的约束。", **changes):
        body = {"session_id": "thread", "project_id": "project-a", "query": query,
                "timestamp": NOW.isoformat(), "options": {"max_prompt_memories": 50,
                "candidate_memory_ids": ids, "include_debug": True}, **changes}
        path = "/prompt-context" if prompt else "/memory/query"
        response = self.client.post(self.root + path, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_selected(self, ids, expected, **changes):
        query = self.read(ids=ids, **changes)
        prompt = self.read(ids=ids, prompt=True, **changes)
        self.assertEqual({item["memory_id"] for item in query["candidates"]}, set(expected))
        self.assertEqual(query["compiled_context"], prompt["memory_context"])
        self.assertEqual(query["response_policy"], prompt["response_policy"])
        return query, prompt

    def test_selection_only_narrows_and_query_prompt_share_the_snapshot(self):
        first = self.record("project_first", "project fact first")
        second = self.record("project_second", "project fact second")
        before = self.repository.export_user_memory(user_id="alice")
        self.assert_selected(None, [first, second])
        query, prompt = self.assert_selected([second, "missing-id", second], [second])
        self.assertIn("project fact second", prompt["assembled_prompt"])
        self.assertNotIn("project fact first", str(query))
        self.assertNotIn("project fact first", prompt["assembled_prompt"])
        self.assertEqual(before, self.repository.export_user_memory(user_id="alice"))

    def test_empty_selection_keeps_current_instruction_without_reading_or_writing_history(self):
        self.record("detail_preference", "concise", layer=MemoryLayer.PREFERENCE)
        before = self.repository.export_user_memory(user_id="alice")
        query, prompt = self.assert_selected([], [], query="这次详细解释原理。")
        self.assertEqual(query["response_policy"]["detail_level"], "high")
        self.assertIn("Explain in detail", prompt["assembled_prompt"])
        self.assertNotIn("Keep the response concise", prompt["assembled_prompt"])
        self.assertEqual(before, self.repository.export_user_memory(user_id="alice"))

    def test_ids_cannot_cross_user_project_session_domain_or_global_boundaries(self):
        allowed = self.record()
        blocked = [
            self.record("other_user", user_id="bob"),
            self.record("other_project", project_id="project-b"),
            self.record("other_session", scope="session", session_id="another-thread"),
            self.record("unscoped_session", scope="session", session_id=None),
            self.record("other_session_project", scope="session", project_id="project-b"),
            self.record("other_domain", scope="domain", domain="another-domain"),
            self.record("global_disabled", scope="global", session_id=None, project_id=None),
        ]
        self.assert_selected([allowed, *blocked], [allowed])
        self.assert_selected(blocked, [])
        self.assert_selected([allowed], [], project_id="project-b")
        self.assert_selected([allowed], [], project_id=None)
        self.settings(enabled_project_ids=[])
        self.assert_selected([allowed], [])

    def test_revoked_global_permission_cannot_be_restored_by_id(self):
        global_id = self.record("global_fact", scope="global", session_id=None, project_id=None)
        self.settings(allow_global_memory=True)
        self.assert_selected([global_id], [global_id])
        self.settings(allow_global_memory=False)
        self.assert_selected([global_id], [])

    def test_ids_do_not_restore_disabled_deleted_expired_future_or_hidden_memories(self):
        allowed = self.record()
        blocked = [
            self.record("blocked_key"),
            self.record("blocked_layer", layer=MemoryLayer.PROCEDURAL_MEMORY),
            self.record("deleted", status=MemoryStatus.DELETED),
            self.record("expired", valid_to=NOW),
            self.record("future", valid_from=NOW + timedelta(seconds=1)),
            self.record("sensitive", sensitivity=Sensitivity.SENSITIVE),
            self.record("never_prompt", allowed_use=[AllowedUse.NEVER_PROMPT]),
        ]
        self.settings(disabled_keys=["blocked_key"], disabled_layers=["procedural_memory"])
        self.assert_selected([allowed, *blocked], [allowed])
        self.assert_selected(blocked, [])
        self.settings(memory_enabled=False)
        self.assert_selected([allowed, *blocked], [])

    def test_profile_source_validation_precedes_id_filter(self):
        source = self.record("communication_style", "direct", layer=MemoryLayer.PREFERENCE)
        profile = self.record("directness_preference_level", "high", layer=MemoryLayer.INFERRED_PROFILE,
                              metadata={"user_review_approved": True, "source_memory_ids": [source]})
        self.assert_selected([profile], [profile])
        self.settings(disabled_keys=["communication_style"])
        self.assert_selected([profile], [])

    def test_automatic_profile_is_revalidated_against_all_sources_before_selection(self):
        for turn, text in (("one", "回答直接一点。"), ("two", "再提醒一下，回答直接一点。")):
            response = self.client.post(self.root + "/turns/ingest", json={
                "text": text, "session_id": "thread", "project_id": "project-a", "memory_scope": "project",
                "turn_id": turn, "timestamp": NOW.isoformat()})
            self.assertEqual(response.status_code, 200, response.text)
        profiles = response.json()["persisted_profile_records"]
        self.assertTrue(profiles)
        profile_id = profiles[0]["id"]
        self.assert_selected([profile_id], [profile_id])
        self.assert_selected([profile_id], [], timestamp=(NOW + timedelta(days=180)).isoformat())

    def test_pool_retains_older_project_reason_among_many_preferences_and_selects_it(self):
        reason = self.record("project_decision_reason", "project choice was made because offline processing is required",
                             valid_from=NOW - timedelta(days=20), observed_at=NOW - timedelta(days=20))
        all_ids = {reason}
        for index in range(30):
            all_ids.add(self.record(f"contextual_test_preference_{index}", f"style choice {index}",
                                    layer=MemoryLayer.PREFERENCE))
        query = "继续。"
        pool = self.read(query=query)
        self.assertEqual({item["memory_id"] for item in pool["candidates"]}, all_ids)
        selected, prompt = self.assert_selected([reason], [reason], query=query)
        self.assertIn("offline processing is required", prompt["assembled_prompt"])
        self.assertEqual(selected["candidates"][0]["source_turn_ids"], ["source-project_decision_reason"])

    def test_project_style_misclassification_does_not_remove_selected_fact(self):
        fact = self.record("project_name_collision", "project duplicate names require identity validation")
        query, prompt = self.assert_selected([fact], [fact], query="名称相同，就直接跳过吗？")
        self.assertEqual(query["retrieval_plan"]["intent"]["name"], "style_preference")
        self.assertIn("project duplicate names", prompt["assembled_prompt"])

    def test_selector_id_count_is_bounded_on_both_endpoints(self):
        for path in ("/memory/query", "/prompt-context"):
            response = self.client.post(self.root + path, json={"query": "继续。", "options": {
                "candidate_memory_ids": [str(index) for index in range(51)]}})
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
