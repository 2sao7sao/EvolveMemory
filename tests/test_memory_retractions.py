"""Governed source retraction must repair existing stores, not only fresh runs."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

import app as api
from memory_system.models import (
    Authority, MemoryLayer, MemoryOperation, MemoryOperationType,
    MemoryRecord, MemoryStatus, Sensitivity,
)
from memory_system.profiles import ProfileEvidence
from memory_system.settings import UserMemorySettings


NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
CORRECTION = "我不是一概觉得越短越好，之前有几次只是忙。项目评审需要必要解释。"


class MemoryRetractionTest(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        override = patch.multiple(api, SQLITE_DB_PATH=Path(self.temp.name) / "memory.sqlite3")
        override.start()
        self.addCleanup(override.stop)
        self.client = TestClient(api.app)
        self.repo = api.build_normalized_repository()
        self.repo.upsert_user_settings("alice", UserMemorySettings(enabled_project_ids=["a", "b"]))

    def record(self, **changes):
        fields = dict(user_id="alice", session_id="thread", scope="project", project_id="a",
                      layer=MemoryLayer.PREFERENCE, key="detail_preference", value="concise",
                      normalized_value="concise", confidence=.75, authority=Authority.USER_IMPLICIT,
                      valid_from=NOW - timedelta(days=1), observed_at=NOW - timedelta(days=1),
                      exclusive_group="detail_preference", coexistence_rule="mutually_exclusive",
                      source_turn_ids=["old-1", "old-2", "old-3"],
                      metadata={"evidence": "给一个动作和一个完成判据就好"})
        fields.update(changes)
        return self.repo.upsert_record(MemoryRecord(**fields))

    def legacy_store(self):
        source = self.record()
        profiles = []
        for key, value in [("detail_tolerance", "low"), ("cognitive_load_preference", "low_load")]:
            ids = []
            for turn in ["old-1", "old-2", "old-3"]:
                evidence = ProfileEvidence(user_id="alice", session_id="thread", dimension=key,
                    value=value, confidence=.9, weight=.9, polarity="support", source_memory_id=source.id,
                    source_key=source.key, quote="给一个动作和一个完成判据就好", observed_at=source.observed_at,
                    source_turn_id=turn)
                self.repo.add_profile_evidence(evidence)
                ids.append(str(evidence.id))
            profiles.append(self.record(layer=MemoryLayer.INFERRED_PROFILE, key=key, value=value,
                normalized_value=value, authority=Authority.ASSISTANT_INFERRED, confidence=.93,
                exclusive_group=key, metadata={"source_memory_ids": [str(source.id)],
                    "evidence_ids": ids, "profile_qualification": {
                        "policy_version": "autonomous-v1", "method": "scoped_turn_evidence",
                        "distinct_turn_count": 3}}))
        return source, profiles

    def candidate(self, key="contextual_project_review_preference", value="项目评审需要必要解释", **extra):
        return {"layer": "preference", "key": key, "value": value, "normalized_value": value,
                "confidence": .9, "authority": "user_explicit", "sensitivity": "personal",
                "evidence": "项目评审需要必要解释", "retention": "durable",
                "evidence_kind": "contextual_preference", "exclusive_group": key,
                "coexistence_rule": "mutually_exclusive", **extra}

    def ingest(self, source=None, *, candidates=None, retractions=None, options=None, **extra):
        if retractions is None:
            retractions = [] if source is None else [{"memory_id": str(source.id),
                "evidence": "我不是一概觉得越短越好", "reason": "withdraw an overgeneralized preference"}]
        payload = {"candidate_memories": candidates or [], "memory_retractions": retractions}
        request = {"text": CORRECTION, "session_id": "thread", "project_id": "a", "memory_scope": "project",
                   "timestamp": NOW.isoformat(), "turn_id": "correction-turn",
                   "options": {"extractor": "llm_payload", "llm_payload": payload, **(options or {})}, **extra}
        return self.client.post("/v2/users/alice/turns/ingest", json=request)

    def query(self, *, prompt=False, timestamp=NOW):
        path = "prompt-context" if prompt else "memory/query"
        response = self.client.post(f"/v2/users/alice/{path}", json={"query": "继续项目评审",
            "session_id": "thread", "project_id": "a", "timestamp": timestamp.isoformat(),
            "options": {"max_prompt_memories": 50}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_existing_wrong_assertion_and_two_profiles_retire_and_do_not_revive(self):
        source, profiles = self.legacy_store()
        self.assertEqual([self.repo.get_record(str(p.id)).status for p in profiles], [MemoryStatus.ACTIVE] * 2)
        before_evidence = self.repo.list_profile_evidence(user_id="alice")
        result = self.ingest(source, candidates=[self.candidate()])
        self.assertEqual(result.status_code, 200, result.text)
        result = result.json()
        self.assertEqual(result["memory_retractions"][0]["status"], "retired")
        self.assertCountEqual(result["memory_retractions"][0]["retired_profile_ids"], [str(p.id) for p in profiles])
        for record in [source, *profiles]:
            self.assertEqual(self.repo.get_record(str(record.id)).status, MemoryStatus.RETIRED)
        self.assertEqual(self.repo.list_profile_evidence(user_id="alice"), before_evidence)
        self.assertEqual(result["persisted_records"][0]["key"], "contextual_project_review_preference")
        self.assertFalse(result["profile_evidence"])
        self.assertNotIn("Keep the response concise", self.query(prompt=True)["assembled_prompt"])
        self.assertFalse(any(item["type"] == "profile" for item in self.query()["candidates"]))
        later = self.ingest(candidates=[self.candidate("response_opening", "answer_first",
            evidence_kind="sustained_preference")], turn_id="later")
        self.assertEqual(later.status_code, 200, later.text)
        self.assertFalse(any(item["type"] == "profile" for item in self.query()["candidates"]))
        self.assertEqual(len([a for a in self.repo.list_audit_events(user_id="alice")
                              if a["action"] in {"source_retracted", "derived_profile_retired"}]), 3)

    def test_same_turn_replay_neither_recreates_value_nor_duplicates_audit(self):
        source, _ = self.legacy_store()
        duplicate = self.candidate("detail_preference", "concise", evidence="我不是一概觉得越短越好")
        first = self.ingest(source, candidates=[duplicate]).json()
        self.assertEqual(first["write_decisions"][0]["operation"], "reject")
        self.assertEqual(first["retraction_conflicts"][0]["reason"], "retracted_value_reproposed")
        audit = self.repo.list_audit_events(user_id="alice")
        evidence = self.repo.list_profile_evidence(user_id="alice")
        second = self.ingest(source, candidates=[duplicate]).json()
        self.assertEqual(second["memory_retractions"][0]["status"], "already_retracted")
        self.assertEqual(self.repo.list_audit_events(user_id="alice"), audit)
        self.assertEqual(self.repo.list_profile_evidence(user_id="alice"), evidence)
        self.assertFalse(second["persisted_records"])

    def test_owner_project_domain_session_and_global_boundaries(self):
        for changes in [{"user_id": "bob"}, {"project_id": "b"},
                        {"scope": "domain", "domain": "work"},
                        {"scope": "session", "session_id": "thread"}, {"scope": "global", "project_id": None}]:
            with self.subTest(changes=changes):
                source = self.record(**changes)
                response = self.ingest(source)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["memory_retractions"][0]["reason"], "source_scope_not_authorized")
                self.assertEqual(self.repo.get_record(str(source.id)).status, MemoryStatus.ACTIVE)

    def test_exact_unbound_session_cannot_retract_bound_session(self):
        source = self.record(scope="session", session_id="thread")
        result = self.ingest(source, memory_scope="session", session_id=None)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["memory_retractions"][0]["reason"], "source_scope_not_authorized")

    def test_disabled_master_key_layer_sensitive_and_revoked_project_do_not_mutate(self):
        for index, settings in enumerate([UserMemorySettings(enabled_project_ids=["a"], memory_enabled=False),
                         UserMemorySettings(enabled_project_ids=["a"], disabled_keys=["detail_preference"]),
                         UserMemorySettings(enabled_project_ids=["a"], disabled_layers=[MemoryLayer.PREFERENCE]),
                         UserMemorySettings(enabled_project_ids=["a"]), UserMemorySettings()]):
            with self.subTest(settings=settings):
                source = self.record(sensitivity=Sensitivity.SENSITIVE if index == 3 else Sensitivity.PERSONAL)
                self.repo.upsert_user_settings("alice", settings)
                response = self.ingest(source)
                self.assertIn(response.status_code, [200, 422])
                if response.status_code == 200:
                    self.assertEqual(response.json()["memory_retractions"][0]["status"], "rejected")
                self.assertEqual(self.repo.get_record(str(source.id)).status, MemoryStatus.ACTIVE)
                self.assertFalse(self.repo.list_audit_events(user_id="alice"))

    def test_dry_run_nonuser_no_extraction_and_ephemeral_leave_no_side_effects(self):
        source, _ = self.legacy_store()
        before = self.repo.export_user_memory(user_id="alice")
        for changes in [{"options": {"auto_write": False}}, {"options": {"extract_memory": False}},
                        {"role": "assistant"}, {"memory_scope": "turn"},
                        {"text": "不要记住这句话：" + CORRECTION}]:
            with self.subTest(changes=changes):
                response = self.ingest(source, **changes)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["memory_retractions"][0]["status"], "rejected")
                self.assertEqual(self.repo.export_user_memory(user_id="alice"), before)

    def test_evidence_is_current_nonempty_contiguous_and_source_must_be_current(self):
        source = self.record()
        for evidence in ["", "  ", "我不是 越短越好", "not in this turn", None]:
            with self.subTest(evidence=evidence):
                result = self.ingest(retractions=[{"memory_id": str(source.id), "evidence": evidence, "reason": "fix"}])
                self.assertEqual(result.json()["memory_retractions"][0]["reason"], "evidence_not_in_current_user_turn")
                self.assertEqual(self.repo.get_record(str(source.id)).status, MemoryStatus.ACTIVE)
        for changes in [{"valid_to": NOW}, {"valid_from": NOW + timedelta(hours=1)}, {"status": MemoryStatus.DELETED}]:
            with self.subTest(changes=changes):
                inactive = self.record(**changes)
                result = self.ingest(inactive).json()
                self.assertEqual(result["memory_retractions"][0]["status"], "rejected")
                self.assertEqual(self.repo.get_record(str(inactive.id)).status, inactive.status)

    def test_profile_only_retraction_is_rejected_without_removing_sources(self):
        source, profiles = self.legacy_store()
        result = self.ingest(profiles[0]).json()
        self.assertEqual(result["memory_retractions"][0]["reason"], "profile_retraction_requires_source")
        for record in [source, *profiles]:
            self.assertEqual(self.repo.get_record(str(record.id)).status, MemoryStatus.ACTIVE)

    def test_only_automatic_same_scope_dependants_retire_and_stale_reviews_cancel(self):
        source, profiles = self.legacy_store()
        for changes in [{"project_id": "b"}, {"user_id": "bob"},
                        {"authority": Authority.USER_EXPLICIT},
                        {"metadata": {**profiles[0].metadata, "user_review_approved": True}}]:
            sibling = profiles[0].model_copy(deep=True, update={"id": uuid4(), **changes})
            self.repo.upsert_record(sibling)
        pending = profiles[0].model_copy(deep=True, update={"id": uuid4()})
        self.repo.enqueue_review(MemoryOperation(operation=MemoryOperationType.ASK_USER_CONFIRMATION,
            candidate=pending, target_memory_id=source.id, reason="review", score=.7, requires_user_review=True),
            created_at=NOW)
        before_ids = {str(r.id) for r in self.repo.list_records(user_id="alice", status=MemoryStatus.ACTIVE)}
        result = self.ingest(source).json()
        self.assertEqual(result["memory_retractions"][0]["status"], "retired")
        after_ids = {str(r.id) for r in self.repo.list_records(user_id="alice", status=MemoryStatus.ACTIVE)}
        self.assertEqual(before_ids - after_ids, {str(source.id), *(str(p.id) for p in profiles)})
        self.assertTrue(self.repo.list_records(user_id="bob", status=MemoryStatus.ACTIVE))
        self.assertFalse(self.repo.list_review_items(user_id="alice"))
        self.assertEqual(self.repo.list_review_items(user_id="alice", status="cancelled")[0]["status"], "cancelled")

    def test_legacy_removed_mapping_cannot_requalify_on_reads_or_next_ingest(self):
        _, profiles = self.legacy_store()
        cognitive_id = str(profiles[1].id)
        self.assertNotIn(cognitive_id, [item["memory_id"] for item in self.query()["candidates"]])
        result = self.ingest(candidates=[self.candidate("detail_preference", "concise",
            evidence_kind="sustained_preference")]).json()
        self.assertFalse(any(p["key"] == "cognitive_load_preference" for p in result["profile_candidates"]))

    def test_retraction_limit_and_malformed_items_fail_without_mutation(self):
        source = self.record()
        item = {"memory_id": str(source.id), "evidence": "我不是一概觉得越短越好", "reason": "fix"}
        self.assertEqual(self.ingest(retractions=[item] * 11).status_code, 422)
        self.assertEqual(self.ingest(retractions={"id": str(source.id)}).status_code, 422)
        response = self.ingest(retractions=[None, {"memory_id": [str(source.id)]}])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(all(r["status"] == "rejected" for r in response.json()["memory_retractions"]))
        self.assertEqual(self.repo.get_record(str(source.id)).status, MemoryStatus.ACTIVE)

    def test_metadata_preserved_and_repeated_state_renews_expiry(self):
        def state(expiry):
            return self.candidate("current_bandwidth", "available", layer="semantic_fact",
                retention="state", evidence_kind="current_state", applicability="current work period",
                context={"project": "a"}, valid_to=expiry.isoformat())
        first = self.ingest(candidates=[state(NOW + timedelta(hours=1))], turn_id="state-1").json()
        second = self.ingest(candidates=[state(NOW + timedelta(hours=8))], turn_id="state-2",
                             timestamp=(NOW + timedelta(minutes=30)).isoformat()).json()
        self.assertEqual(second["write_decisions"][0]["operation"], "add_evidence_only")
        record = self.repo.get_record(first["persisted_records"][0]["id"])
        self.assertEqual(record.valid_to, NOW + timedelta(hours=8))
        self.assertEqual(record.observed_at, NOW + timedelta(minutes=30))
        self.assertEqual(record.metadata["evidence_kind"], "current_state")
        self.assertEqual(record.metadata["applicability"], "current work period")
        self.assertEqual(record.metadata["context"], {"project": "a"})
        self.assertEqual(second["profile_evidence"], [])
        self.assertIn(str(record.id), [item["memory_id"] for item in self.query(timestamp=NOW + timedelta(hours=2))["candidates"]])

    def test_malformed_semantic_metadata_is_rejected_before_any_retraction(self):
        source = self.record()
        for metadata in [{"retention": []}, {"evidence_kind": {}}, {"evidence_kind": "invented"}]:
            with self.subTest(metadata=metadata):
                result = self.ingest(source, candidates=[self.candidate(**metadata)])
                self.assertEqual(result.status_code, 422, result.text)
                self.assertEqual(self.repo.get_record(str(source.id)).status, MemoryStatus.ACTIVE)
                self.assertFalse(self.repo.list_audit_events(user_id="alice"))
