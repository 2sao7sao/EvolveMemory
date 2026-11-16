from __future__ import annotations

import json
import sqlite3
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_system.models import (
    Authority,
    MemoryLayer,
    MemoryOperation,
    MemoryOperationType,
    MemoryRecord,
    MemoryStatus,
    Sensitivity,
)
from memory_system.persistence import NormalizedSQLiteMemoryRepository
from memory_system.profiles import ProfileAccumulator, ProfileEvidence, ProfileEvidenceExtractor
from memory_system.schema import MemoryItem, MemoryType
from memory_system.settings import UserMemorySettings
from memory_system.writing import WeightedMemoryWriteEvaluatorV2, WritePolicyContext


NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def record(**overrides: object) -> MemoryRecord:
    values: dict[str, object] = {
        "tenant_id": "tenant-a", "user_id": "user-a", "session_id": "session-a",
        "project_id": "project-a", "scope": "project", "layer": MemoryLayer.PREFERENCE,
        "key": "communication_style", "value": "direct", "normalized_value": "direct",
        "confidence": 0.95, "authority": Authority.USER_EXPLICIT,
        "valid_from": NOW, "observed_at": NOW,
        "exclusive_group": "communication_style", "coexistence_rule": "mutually_exclusive",
        "source_turn_ids": ["turn-a"], "metadata": {"evidence": "Prefer direct answers."},
    }
    values.update(overrides)
    return MemoryRecord.model_validate(values)


class ScopePersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "memory.sqlite3"
        self.repo = NormalizedSQLiteMemoryRepository(self.path)

    def test_old_database_migration_preserves_records_and_is_idempotent(self) -> None:
        # Recreate the pre-scope schema, including an existing record, rather than
        # silently starting with a fresh database that already has the columns.
        old_path = Path(self.directory.name) / "old.sqlite3"
        old_schema = """
            CREATE TABLE memory_records (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                session_id TEXT, layer TEXT NOT NULL, key TEXT NOT NULL,
                value_json TEXT NOT NULL, normalized_value_json TEXT,
                confidence REAL NOT NULL, authority TEXT NOT NULL, sensitivity TEXT NOT NULL,
                allowed_use_json TEXT NOT NULL, evidence_ids_json TEXT NOT NULL,
                source_turn_ids_json TEXT NOT NULL, source_text_hash TEXT,
                valid_from TEXT NOT NULL, valid_to TEXT, observed_at TEXT NOT NULL,
                last_confirmed_at TEXT, last_used_at TEXT, status TEXT NOT NULL,
                version INTEGER NOT NULL, supersedes TEXT, superseded_by TEXT,
                exclusive_group TEXT, coexistence_rule TEXT NOT NULL, tags_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """
        existing = record(project_id=None, scope="session")
        with sqlite3.connect(old_path) as conn:
            conn.execute(old_schema)
            conn.execute(
                """INSERT INTO memory_records VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )""",
                (str(existing.id), "tenant-a", "user-a", "session-a", "preference",
                 "communication_style", '"direct"', '"direct"', 0.95, "user_explicit",
                 "personal", '["style"]', "[]", '["turn-a"]', None,
                 NOW.isoformat(), None, NOW.isoformat(), None, None, "active", 1,
                 None, None, "communication_style", "mutually_exclusive", "[]",
                 '{"evidence": "legacy evidence"}', NOW.isoformat(), NOW.isoformat()),
            )
        for _ in range(2):
            migrated = NormalizedSQLiteMemoryRepository(old_path)
            saved = migrated.get_record(str(existing.id))
            self.assertEqual((saved.scope, saved.project_id, saved.domain), ("session", None, None))
            self.assertEqual(saved.metadata["evidence"], "legacy evidence")
            self.assertEqual(len(migrated.list_records_scoped(
                tenant_id="tenant-a", user_id="user-a", scope="session", session_id="session-a",
            )), 1)

    def test_scope_roundtrip_and_update_keep_provenance(self) -> None:
        candidate = record(scope="domain", domain="coding")
        self.repo.upsert_record(candidate)
        saved = self.repo.get_record(str(candidate.id))
        self.assertEqual(saved.model_dump(), candidate.model_dump())
        candidate.confidence = 0.99
        candidate.source_turn_ids.append("turn-b")
        self.repo.upsert_record(candidate)
        self.assertEqual(self.repo.get_record(str(candidate.id)).model_dump(), candidate.model_dump())

    def test_scoped_reads_require_exact_identity_and_null_session(self) -> None:
        candidates = [
            record(scope="session", session_id=None, project_id=None),
            record(scope="session", session_id="session-a", project_id=None),
            record(scope="session", session_id=None, project_id="project-a"),
            record(scope="session", session_id=None, project_id=None, tenant_id="tenant-b"),
            record(scope="session", session_id=None, project_id=None, user_id="user-b"),
            record(scope="global", session_id="source-session", project_id=None),
        ]
        for candidate in candidates:
            self.repo.upsert_record(candidate)
        exact = self.repo.list_records_scoped(
            user_id="user-a", tenant_id="tenant-a", scope="session", session_id=None,
        )
        self.assertEqual([item.id for item in exact], [candidates[0].id])
        # Management defaults remain intentionally broader than the prompt-read API.
        self.assertEqual(len(self.repo.list_records(user_id="user-a")), 5)
        global_records = self.repo.list_records_scoped(
            user_id="user-a", tenant_id="tenant-a", scope="global",
            session_id="unrelated", project_id="unrelated",
        )
        self.assertEqual([item.id for item in global_records], [candidates[-1].id])

    def test_project_and_domain_queries_do_not_cross_project_boundaries(self) -> None:
        candidates = [
            record(), record(project_id="project-b"),
            record(scope="domain", domain="coding"),
            record(scope="domain", domain="coding", project_id="project-b"),
            record(scope="domain", domain="coding", project_id=None),
            record(scope="domain", domain="writing"),
            record(status=MemoryStatus.RETIRED),
        ]
        for candidate in candidates:
            self.repo.upsert_record(candidate)
        for scope, project_id, domain, expected in [
            ("project", "project-a", None, candidates[0]),
            ("domain", "project-a", "coding", candidates[2]),
            ("domain", None, "coding", candidates[4]),
        ]:
            with self.subTest(scope=scope, project_id=project_id):
                found = self.repo.list_records_scoped(
                    tenant_id="tenant-a", user_id="user-a", scope=scope,
                    project_id=project_id, domain=domain,
                )
                self.assertEqual([item.id for item in found], [expected.id])
        for scope in ("turn", "unknown", "project", "domain"):
            with self.subTest(invalid_scope=scope), self.assertRaises(ValueError):
                self.repo.list_records_scoped(user_id="user-a", scope=scope)

    def test_conflicts_and_duplicate_evidence_stay_in_same_scope(self) -> None:
        evaluator = WeightedMemoryWriteEvaluatorV2()
        candidate = record()
        other_boundaries = [
            record(tenant_id="tenant-b"), record(user_id="user-b"),
            record(project_id="project-b"), record(scope="session"),
            record(scope="domain", domain="coding"), record(scope="global"),
        ]
        for other in other_boundaries:
            for value in ("direct", "detailed"):
                other.value = other.normalized_value = value
                with self.subTest(boundary=other.scope_identity(), value=value):
                    operation = evaluator.evaluate(candidate, [other])
                    self.assertEqual(operation.operation, MemoryOperationType.CREATE)
                    self.assertIsNone(operation.target_memory_id)
        same_project_other_session = record(session_id="session-b")
        operation = evaluator.evaluate(candidate, [same_project_other_session])
        self.assertEqual(operation.operation, MemoryOperationType.ADD_EVIDENCE_ONLY)
        changed = record(value="detailed", normalized_value="detailed")
        self.assertEqual(evaluator.evaluate(changed, [candidate]).operation,
                         MemoryOperationType.SUPERSEDE)

    def test_session_domain_and_global_conflict_boundaries(self) -> None:
        evaluator = WeightedMemoryWriteEvaluatorV2()
        for candidate, other, expected in [
            (record(scope="session"), record(scope="session", session_id="session-b"), False),
            (record(scope="session"), record(scope="session", project_id="project-b"), False),
            (record(scope="domain", domain="coding"),
             record(scope="domain", domain="writing"), False),
            (record(scope="domain", domain="coding"),
             record(scope="domain", domain="coding", project_id="project-b"), False),
            (record(scope="domain", domain="coding"),
             record(scope="domain", domain="coding", session_id="session-b"), True),
            (record(scope="global"), record(scope="global", project_id="project-b", session_id=None), True),
        ]:
            with self.subTest(candidate=candidate.scope_identity(), other=other.scope_identity()):
                operation = evaluator.evaluate(candidate, [other])
                self.assertEqual(operation.operation, MemoryOperationType.ADD_EVIDENCE_ONLY
                                 if expected else MemoryOperationType.CREATE)

    def test_repository_rejects_forged_cross_scope_targets_without_mutation(self) -> None:
        existing = record()
        self.repo.upsert_record(existing)
        for candidate in (record(project_id="project-b"), record(user_id="user-b"),
                          record(tenant_id="tenant-b"), record(scope="session")):
            for operation_type in (MemoryOperationType.SUPERSEDE, MemoryOperationType.ADD_EVIDENCE_ONLY):
                with self.subTest(operation=operation_type, boundary=candidate.scope_identity()), self.assertRaises(ValueError):
                    self.repo.apply_operation(MemoryOperation(
                        operation=operation_type, candidate=candidate,
                        target_memory_id=existing.id, reason="forged target", score=0.9,
                    ))
        moved = existing.model_copy(update={"project_id": "project-b"})
        with self.assertRaises(ValueError):
            self.repo.upsert_record(moved)
        self.assertEqual(self.repo.get_record(str(existing.id)).model_dump(), existing.model_dump())
        self.assertEqual(len(self.repo.list_records(user_id="user-a")), 1)

    def test_same_key_in_two_projects_does_not_overwrite_other_project(self) -> None:
        evaluator = WeightedMemoryWriteEvaluatorV2()
        project_a = record()
        self.repo.apply_operation(evaluator.evaluate(project_a))
        project_b = record(project_id="project-b", value="detailed", normalized_value="detailed")
        self.repo.apply_operation(evaluator.evaluate(project_b, self.repo.list_records(user_id="user-a")))
        updated_a = record(value="balanced", normalized_value="balanced", session_id="new-session")
        self.repo.apply_operation(evaluator.evaluate(updated_a, self.repo.list_records(user_id="user-a")))
        active = self.repo.list_records(user_id="user-a")
        self.assertEqual({(item.project_id, item.value) for item in active},
                         {("project-a", "balanced"), ("project-b", "detailed")})
        self.assertEqual(self.repo.get_record(str(project_b.id)).model_dump(), project_b.model_dump())
        self.assertEqual(self.repo.get_record(str(project_a.id)).status, MemoryStatus.SUPERSEDED)

    def test_legacy_review_target_cannot_cross_owner_or_scope(self) -> None:
        target = record()
        self.repo.upsert_record(target)
        self.repo.upsert_user_settings("user-a", UserMemorySettings(enabled_project_ids=["project-b"]))
        candidate = record(project_id="project-b")
        # Old queued entries may bypass the newer apply_operation boundary check.
        review = self.repo.enqueue_review(MemoryOperation(
            operation=MemoryOperationType.ASK_USER_CONFIRMATION, candidate=candidate,
            target_memory_id=target.id, reason="old queued conflict", score=0.9,
        ))
        with self.assertRaisesRegex(ValueError, "scope boundaries"):
            self.repo.resolve_review_item(str(review["id"]), approve=True)
        self.assertEqual(self.repo.get_review_item(str(review["id"]))["status"], "pending")
        self.assertEqual(self.repo.get_record(str(target.id)).model_dump(), target.model_dump())
        self.assertIsNone(self.repo.get_record(str(candidate.id)))

    def test_review_approval_metadata_survives_storage(self) -> None:
        self.repo.upsert_user_settings("user-a", UserMemorySettings(enabled_project_ids=["project-a"]))
        candidate = record(layer=MemoryLayer.INFERRED_PROFILE)
        operation = WeightedMemoryWriteEvaluatorV2().evaluate(candidate)
        self.repo.apply_operation(operation, created_at=NOW)
        review = self.repo.list_review_items(user_id="user-a")[0]
        saved = self.repo.resolve_review_item(str(review["id"]), approve=True, resolved_at=NOW)[0]
        reloaded = self.repo.get_record(str(saved.id))
        self.assertIs(reloaded.metadata["user_review_approved"], True)
        self.assertEqual(reloaded.metadata["review_id"], review["id"])
        self.assertEqual(reloaded.metadata["review_approved_at"], NOW.isoformat())
        self.assertEqual(reloaded.scope_identity(), candidate.scope_identity())

    def test_settings_changed_after_review_prevent_approval_and_keep_pending(self) -> None:
        for settings in (
            UserMemorySettings(memory_enabled=False),
            UserMemorySettings(disabled_keys=["communication_style"]),
            UserMemorySettings(disabled_layers=[MemoryLayer.INFERRED_PROFILE]),
            UserMemorySettings(allow_inferred_profile=False),
        ):
            with self.subTest(settings=settings):
                candidate = record(layer=MemoryLayer.INFERRED_PROFILE)
                self.repo.upsert_user_settings("user-a", UserMemorySettings())
                self.repo.apply_operation(WeightedMemoryWriteEvaluatorV2().evaluate(candidate))
                review = next(item for item in self.repo.list_review_items(user_id="user-a")
                              if json.loads(item["candidate_json"])["id"] == str(candidate.id))
                self.repo.upsert_user_settings("user-a", settings)
                with self.assertRaisesRegex(ValueError, "current memory settings"):
                    self.repo.resolve_review_item(str(review["id"]), approve=True)
                self.assertEqual(self.repo.get_review_item(str(review["id"]))["status"], "pending")
                self.assertIsNone(self.repo.get_record(str(candidate.id)))

    def test_sensitive_setting_cannot_be_bypassed_by_remember_or_review(self) -> None:
        for sensitivity in (Sensitivity.SENSITIVE, Sensitivity.RESTRICTED):
            with self.subTest(sensitivity=sensitivity):
                candidate = record(sensitivity=sensitivity)
                evaluator = WeightedMemoryWriteEvaluatorV2()
                result = evaluator.evaluate(candidate, context=WritePolicyContext(
                    user_command="remember", user_consent=True,
                ))
                self.assertEqual(result.operation, MemoryOperationType.REJECT)
                allowed = UserMemorySettings(allow_sensitive_memory=True)
                operation = evaluator.evaluate(candidate, context=WritePolicyContext(
                    settings=allowed, user_consent=True,
                ))
                self.assertEqual(operation.operation, MemoryOperationType.ASK_USER_CONFIRMATION)
                self.repo.apply_operation(operation)
                review = next(item for item in self.repo.list_review_items(user_id="user-a")
                              if json.loads(item["candidate_json"])["id"] == str(candidate.id))
                with self.assertRaisesRegex(ValueError, "current memory settings"):
                    self.repo.resolve_review_item(str(review["id"]), approve=True)

    def test_scope_opt_out_blocks_pending_review_approval(self) -> None:
        for scope, project_id, domain in (
            ("project", "project-a", None),
            ("domain", "project-a", "coding"),
            ("global", None, None),
        ):
            with self.subTest(scope=scope):
                candidate = record(scope=scope, project_id=project_id, domain=domain,
                                   layer=MemoryLayer.INFERRED_PROFILE)
                self.repo.apply_operation(WeightedMemoryWriteEvaluatorV2().evaluate(candidate))
                review = next(item for item in self.repo.list_review_items(user_id="user-a")
                              if json.loads(item["candidate_json"])["id"] == str(candidate.id))
                with self.assertRaisesRegex(ValueError, "current memory settings"):
                    self.repo.resolve_review_item(str(review["id"]), approve=True)
                self.assertEqual(self.repo.get_review_item(str(review["id"]))["status"], "pending")
                self.repo.upsert_user_settings("user-a", UserMemorySettings(
                    enabled_project_ids=["project-a"], allow_global_memory=True,
                ))
                persisted = self.repo.resolve_review_item(str(review["id"]), approve=True)
                self.assertEqual([item.id for item in persisted], [candidate.id])
                self.repo.upsert_user_settings("user-a", UserMemorySettings())

    def test_profile_confirmation_is_required_even_if_review_list_is_empty(self) -> None:
        candidate = record(layer=MemoryLayer.INFERRED_PROFILE)
        settings = UserMemorySettings(review_required_for_layers=[])
        evaluator = WeightedMemoryWriteEvaluatorV2()
        existing = candidate.model_copy(deep=True)
        for previous in ([], [existing]):
            result = evaluator.evaluate(candidate, previous, WritePolicyContext(settings=settings))
            self.assertEqual(result.operation, MemoryOperationType.ASK_USER_CONFIRMATION)
        blocked = replace(settings, allow_inferred_profile=False)
        candidate.metadata["user_review_approved"] = True
        self.assertEqual(evaluator.evaluate(candidate, context=WritePolicyContext(settings=blocked)).operation,
                         MemoryOperationType.REJECT)

    def test_explicit_remember_does_not_promote_temporary_scope(self) -> None:
        for scope in ("turn", "session"):
            with self.subTest(scope=scope):
                result = WeightedMemoryWriteEvaluatorV2().evaluate(record(), context=WritePolicyContext(
                    scope=scope, user_command="remember",
                ))
                self.assertEqual(result.operation, MemoryOperationType.EPHEMERAL_ONLY)
                self.assertEqual(self.repo.apply_operation(result), [])
        self.assertEqual(self.repo.list_records(user_id="user-a"), [])

    def test_memory_item_roundtrip_retains_scope_and_review_metadata(self) -> None:
        item = MemoryItem(
            memory_type=MemoryType.PREFERENCE, key="communication_style", value="direct",
            confidence=0.95, source="turn-a", evidence="Prefer direct answers.", valid_from=NOW,
            user_id="user-a", tenant_id="tenant-a", session_id="session-a",
            project_id="project-a", domain="coding", scope="domain",
            authority="user_implicit", source_turn_ids=["turn-a", "turn-b"],
            source_text_hash="source-hash", metadata={"user_review_approved": True},
        )
        restored = MemoryItem.from_dict(item.to_dict())
        self.assertEqual(restored, item)
        normalized = MemoryRecord.from_memory_item(restored, user_id="user-a", tenant_id="tenant-a")
        self.assertEqual(normalized.scope_identity(), ("tenant-a", "user-a", "domain", "coding", "project-a"))
        self.assertEqual(normalized.authority, Authority.USER_IMPLICIT)
        self.assertEqual(normalized.source_turn_ids, ["turn-a", "turn-b"])
        self.assertIs(normalized.metadata["user_review_approved"], True)
        payload = item.to_dict()
        for key in ("user_id", "tenant_id", "session_id", "project_id", "domain", "scope",
                    "authority", "source_turn_ids", "source_text_hash", "metadata"):
            payload.pop(key)
        legacy = MemoryItem.from_dict(payload)
        self.assertIsNone(legacy.scope)
        self.assertEqual(legacy.metadata, {})

    def test_profile_evidence_distinguishes_turns_on_real_merged_memory(self) -> None:
        source = record()
        self.repo.upsert_record(source)
        extractor = ProfileEvidenceExtractor()
        returned_ids = []
        for turn_id in ("turn-1", "turn-2", "turn-2"):
            current_turn = source.model_copy(deep=True)
            current_turn.source_turn_ids = [turn_id]
            extracted = extractor.extract([current_turn])
            self.assertEqual(extracted[0].source_turn_id, turn_id)
            returned_ids.append(self.repo.add_profile_evidence_batch(extracted)[0].id)
        saved = self.repo.list_profile_evidence(user_id="user-a")
        self.assertEqual(len(saved), 2)
        self.assertEqual({item.source_memory_id for item in saved}, {source.id})
        self.assertEqual({item.source_turn_id for item in saved}, {"turn-1", "turn-2"})
        self.assertNotEqual(returned_ids[0], returned_ids[1])
        self.assertEqual(returned_ids[1], returned_ids[2])
        hypothesis = ProfileAccumulator().accumulate(saved)[0]
        self.assertEqual(hypothesis.evidence_count, 2)
        self.assertTrue(all(self.repo.get_record(str(item.source_memory_id)) for item in saved))

    def test_profile_evidence_does_not_expand_ambiguous_aggregated_turns(self) -> None:
        source = record(source_turn_ids=["turn-1", "turn-2"])
        extracted = ProfileEvidenceExtractor().extract([source])
        self.assertEqual(len(extracted), 1)
        self.assertIsNone(extracted[0].source_turn_id)
        self.repo.add_profile_evidence_batch(extracted)
        self.repo.add_profile_evidence_batch(ProfileEvidenceExtractor().extract([source]))
        self.assertEqual(len(self.repo.list_profile_evidence(user_id="user-a")), 1)
        restored = ProfileEvidence.from_dict(extracted[0].to_dict())
        self.assertEqual(restored, extracted[0])

    def test_old_profile_evidence_unique_constraint_migrates_without_loss(self) -> None:
        old_path = Path(self.directory.name) / "old-profile.sqlite3"
        old_evidence = ProfileEvidenceExtractor().extract([record(), record()])
        old_evidence[0].metadata["source_turn_id"] = "legacy-turn"
        with sqlite3.connect(old_path) as conn:
            conn.execute("""
                CREATE TABLE profile_evidence (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT,
                    dimension TEXT NOT NULL, value TEXT NOT NULL, confidence REAL NOT NULL,
                    weight REAL NOT NULL, polarity TEXT NOT NULL, source_memory_id TEXT NOT NULL,
                    source_key TEXT NOT NULL, quote TEXT NOT NULL, observed_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(user_id, dimension, value, source_memory_id)
                )
            """)
            conn.execute("CREATE INDEX idx_profile_evidence_user_dimension ON profile_evidence(user_id, dimension, observed_at)")
            for item in old_evidence:
                payload = item.to_dict()
                conn.execute("""
                    INSERT INTO profile_evidence VALUES (
                        :id, :user_id, :session_id, :dimension, :value, :confidence,
                        :weight, :polarity, :source_memory_id, :source_key, :quote,
                        :observed_at, :metadata_json
                    )
                """, {**payload, "metadata_json": json.dumps(item.metadata)})
        for _ in range(2):
            migrated = NormalizedSQLiteMemoryRepository(old_path)
            saved = {item.id: item for item in migrated.list_profile_evidence(user_id="user-a")}
            self.assertEqual(set(saved), {item.id for item in old_evidence})
            self.assertEqual(saved[old_evidence[0].id].source_turn_id, "legacy-turn")
            self.assertIsNone(saved[old_evidence[1].id].source_turn_id)
            for original in old_evidence:
                self.assertEqual(saved[original.id].metadata, original.metadata)
                self.assertEqual(saved[original.id].quote, original.quote)
        repeated = replace(old_evidence[0], source_turn_id="legacy-turn")
        migrated.add_profile_evidence(replace(repeated, id=record().id))
        self.assertEqual(len(migrated.list_profile_evidence(user_id="user-a")), 2)
        migrated.add_profile_evidence(replace(repeated, id=record().id, source_turn_id="new-turn"))
        self.assertEqual(len(migrated.list_profile_evidence(user_id="user-a")), 3)

    def _queue_review(self, candidate: MemoryRecord, target: MemoryRecord | None = None) -> str:
        queued = self.repo.enqueue_review(MemoryOperation(
            operation=MemoryOperationType.ASK_USER_CONFIRMATION, candidate=candidate,
            target_memory_id=target.id if target else None, reason="needs approval", score=0.9,
        ), created_at=NOW)
        return str(queued["id"])

    def test_correction_cannot_revive_inactive_records(self) -> None:
        for status in (MemoryStatus.DELETED, MemoryStatus.SUPERSEDED, MemoryStatus.RETIRED,
                       MemoryStatus.SUPPRESSED, MemoryStatus.STALE, MemoryStatus.NEEDS_REVIEW):
            with self.subTest(status=status):
                original = record(status=status)
                self.repo.upsert_record(original)
                corrected = self.repo.correct_record(
                    str(original.id), user_id="user-a", value="new", evidence="correction",
                    corrected_at=NOW,
                )
                self.assertIsNone(corrected)
                self.assertEqual(self.repo.get_record(str(original.id)).model_dump(), original.model_dump())
        self.assertEqual(self.repo.list_records(user_id="user-a"), [])

    def test_delete_cancels_target_and_derived_pending_reviews(self) -> None:
        source = record()
        self.repo.upsert_record(source)
        targeted = self._queue_review(record(value="new", normalized_value="new"), source)
        derived = self._queue_review(record(layer=MemoryLayer.INFERRED_PROFILE,
            metadata={"source_memory_ids": [str(source.id)]}))
        unrelated = self._queue_review(record(key="unrelated"))
        self.assertTrue(self.repo.mark_record_deleted(str(source.id), user_id="user-a", updated_at=NOW))
        for review_id in (targeted, derived):
            review = self.repo.get_review_item(review_id)
            self.assertEqual(review["status"], "cancelled")
            self.assertEqual(review["resolved_at"], NOW.isoformat())
            self.assertEqual(self.repo.resolve_review_item(review_id, approve=True), [])
        self.assertEqual(self.repo.get_review_item(unrelated)["status"], "pending")
        audit = self.repo.list_audit_events(user_id="user-a")[0]
        self.assertEqual(set(json.loads(audit["after_json"])["cancelled_review_ids"]), {targeted, derived})
        self.assertEqual(self.repo.list_records(user_id="user-a"), [])

    def test_forget_all_cancels_pending_without_any_active_memory(self) -> None:
        first = self._queue_review(record(session_id="first"))
        second = self._queue_review(record(session_id="second"))
        unbound = self._queue_review(record(session_id=None))
        other_user = self._queue_review(record(user_id="user-b", session_id="first"))
        self.assertEqual(self.repo.forget_all(user_id="user-a", session_id="first", updated_at=NOW), 0)
        self.assertEqual(self.repo.get_review_item(first)["status"], "cancelled")
        self.assertEqual(self.repo.get_review_item(second)["status"], "pending")
        self.assertEqual(self.repo.get_review_item(unbound)["status"], "pending")
        self.assertEqual(self.repo.forget_all(user_id="user-a", session_id=None, updated_at=NOW), 0)
        self.assertEqual(self.repo.get_review_item(second)["status"], "cancelled")
        self.assertEqual(self.repo.get_review_item(unbound)["status"], "cancelled")
        self.assertEqual(self.repo.get_review_item(other_user)["status"], "pending")
        self.assertEqual(len(self.repo.list_audit_events(user_id="user-a")), 2)

    def test_old_review_cannot_replace_inactive_or_missing_target(self) -> None:
        self.repo.upsert_user_settings("user-a", UserMemorySettings(enabled_project_ids=["project-a"]))
        for status in (MemoryStatus.DELETED, MemoryStatus.SUPERSEDED, None):
            with self.subTest(status=status):
                target = record()
                review_id = self._queue_review(record(value="new", normalized_value="new"), target)
                if status is not None:
                    target.status = status
                    self.repo.upsert_record(target)
                with self.assertRaisesRegex(ValueError, "no longer active"):
                    self.repo.resolve_review_item(review_id, approve=True, resolved_at=NOW)
                self.assertEqual(self.repo.get_review_item(review_id)["status"], "pending")
        self.assertEqual(self.repo.list_records(user_id="user-a"), [])

    def test_profile_review_requires_live_allowed_sources_in_same_scope(self) -> None:
        allowed = UserMemorySettings(enabled_project_ids=["project-a", "project-b"])
        cases = [
            ("missing", {}, allowed),
            ("deleted", {"status": MemoryStatus.DELETED}, allowed),
            ("superseded", {"status": MemoryStatus.SUPERSEDED}, allowed),
            ("expired", {"valid_to": NOW}, allowed),
            ("future", {"valid_from": NOW + timedelta(days=1)}, allowed),
            ("other_user", {"user_id": "user-b"}, allowed),
            ("other_project", {"project_id": "project-b"}, allowed),
            ("disabled_key", {}, replace(allowed, disabled_keys=["communication_style"])),
            ("disabled_layer", {}, replace(allowed, disabled_layers=[MemoryLayer.PREFERENCE])),
            ("sensitive", {"sensitivity": Sensitivity.SENSITIVE}, allowed),
        ]
        for name, changes, settings in cases:
            with self.subTest(case=name):
                source = record(**changes)
                if name != "missing":
                    self.repo.upsert_record(source)
                candidate = record(layer=MemoryLayer.INFERRED_PROFILE, key="directness_preference_level",
                    metadata={"source_memory_ids": [str(source.id)]})
                review_id = self._queue_review(candidate)
                self.repo.upsert_user_settings("user-a", settings)
                with self.assertRaisesRegex(ValueError, "review source is unavailable"):
                    self.repo.resolve_review_item(review_id, approve=True, resolved_at=NOW)
                self.assertEqual(self.repo.get_review_item(review_id)["status"], "pending")
                self.assertIsNone(self.repo.get_record(str(candidate.id)))
        source = record(valid_to=NOW + timedelta(days=1))
        self.repo.upsert_record(source)
        candidate = record(layer=MemoryLayer.INFERRED_PROFILE, key="directness_preference_level",
            metadata={"source_memory_ids": [str(source.id)]})
        review_id = self._queue_review(candidate)
        self.repo.upsert_user_settings("user-a", allowed)
        result = self.repo.resolve_review_item(review_id, approve=True, resolved_at=NOW)
        self.assertEqual([item.id for item in result], [candidate.id])

    def test_reviewed_update_replaces_existing_scoped_memory_after_approval(self) -> None:
        for layer in (MemoryLayer.INFERRED_PROFILE, MemoryLayer.PREFERENCE):
            for new_value in ("direct", "detailed"):
                with self.subTest(layer=layer, value=new_value):
                    user_id = f"user-{layer.value}-{new_value}"
                    settings = UserMemorySettings(
                        enabled_project_ids=["project-a"], review_required_for_layers=[layer],
                    )
                    self.repo.upsert_user_settings(user_id, settings)
                    original = record(user_id=user_id, layer=layer,
                                      metadata={"user_review_approved": True})
                    self.repo.upsert_record(original)
                    candidate = record(user_id=user_id, layer=layer, session_id="new-session",
                                       value=new_value, normalized_value=new_value)
                    operation = WeightedMemoryWriteEvaluatorV2().evaluate(
                        candidate, [original], WritePolicyContext(settings=settings),
                    )
                    self.assertEqual(operation.operation, MemoryOperationType.ASK_USER_CONFIRMATION)
                    self.assertEqual(operation.target_memory_id, original.id)
                    self.repo.apply_operation(operation, created_at=NOW)
                    self.assertEqual([item.id for item in self.repo.list_records(user_id=user_id)],
                                     [original.id])
                    review = self.repo.list_review_items(user_id=user_id)[0]
                    self.repo.resolve_review_item(str(review["id"]), approve=True, resolved_at=NOW)
                    active = self.repo.list_records(user_id=user_id)
                    self.assertEqual([item.id for item in active], [candidate.id])
                    self.assertEqual(active[0].value, new_value)
                    self.assertEqual(active[0].supersedes, original.id)
                    self.assertEqual(self.repo.get_record(str(original.id)).status, MemoryStatus.SUPERSEDED)


if __name__ == "__main__":
    unittest.main()
