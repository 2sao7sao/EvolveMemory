from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from memory_system.controls import apply_read_controls
from memory_system.models import Authority, MemoryLayer, MemoryOperationType, MemoryRecord, Sensitivity
from memory_system.persistence import NormalizedSQLiteMemoryRepository
from memory_system.profiles import (
    ProfileAccumulator, ProfileEvidence, ProfileEvidenceExtractor,
    has_autonomous_profile_qualification, is_user_corrected_profile,
)
from memory_system.settings import PROFILE_POLICY_VERSION, UserMemorySettings
from memory_system.writing import WeightedMemoryWriteEvaluatorV2, WritePolicyContext


NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def source_record(**changes: object) -> MemoryRecord:
    payload = dict(user_id="reader", session_id="session-a", layer=MemoryLayer.PREFERENCE,
                   key="communication_style", value="direct", normalized_value="direct",
                   confidence=0.95, authority=Authority.USER_EXPLICIT,
                   valid_from=NOW - timedelta(days=1), observed_at=NOW,
                   source_turn_ids=["turn-a"], metadata={"evidence": "Please be direct."})
    payload.update(changes)
    return MemoryRecord(**payload)


def evidence(turn: str | None, *, value: str = "high", dimension: str = "directness_preference_level",
             when: datetime = NOW, polarity: str = "support", **changes: object) -> ProfileEvidence:
    payload = dict(user_id="reader", session_id="session-a", dimension=dimension, value=value,
                   confidence=0.95, weight=0.82, polarity=polarity, source_memory_id=uuid4(),
                   source_turn_id=turn, source_key="communication_style", quote="Please be direct.",
                   observed_at=when)
    payload.update(changes)
    return ProfileEvidence(**payload)


def qualified_record(items: list[ProfileEvidence] | None = None) -> MemoryRecord:
    hypotheses = ProfileAccumulator().accumulate(items or [evidence("turn-a"), evidence("turn-b")], now=NOW)
    assert len(hypotheses) == 1
    assert hypotheses[0].autonomous_qualified
    return hypotheses[0].to_record(user_id="reader", session_id="session-a", observed_at=NOW)


class AutonomousProfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = NormalizedSQLiteMemoryRepository(Path(self.directory.name) / "memory.sqlite3")
        self.evaluator = WeightedMemoryWriteEvaluatorV2()

    def test_default_qualified_real_turns_write_and_adapt_without_review(self) -> None:
        self.assertEqual(UserMemorySettings().review_required_for_layers, [])
        source = source_record()
        self.repo.upsert_record(source)
        for turn in ("turn-a", "turn-b", "turn-b"):
            turn_source = source.model_copy(update={"source_turn_ids": [turn]})
            self.repo.add_profile_evidence_batch(ProfileEvidenceExtractor().extract([turn_source]))
        stored_evidence = self.repo.list_profile_evidence(user_id="reader")
        self.assertEqual(len(stored_evidence), 2)
        profile = qualified_record(stored_evidence)
        operation = self.evaluator.evaluate(profile, context=WritePolicyContext(
            qualified_profile_ids=frozenset({profile.id}),
        ))
        self.assertEqual(operation.operation, MemoryOperationType.CREATE)
        self.repo.apply_operation(operation, created_at=NOW)
        saved = self.repo.get_record(str(profile.id))
        self.assertTrue(has_autonomous_profile_qualification(saved))
        self.assertNotIn("user_review_approved", saved.metadata)
        self.assertEqual(apply_read_controls([saved], UserMemorySettings()), [saved])
        self.assertEqual(self.repo.list_review_items(user_id="reader"), [])

    def test_confidence_and_forged_metadata_cannot_self_qualify(self) -> None:
        profile = qualified_record()
        profile.confidence = 1.0
        profile.metadata.update(user_review_approved=True, profile_qualification={
            "policy_version": PROFILE_POLICY_VERSION, "method": "scoped_turn_evidence",
            "distinct_turn_count": 1000,
        })
        operation = self.evaluator.evaluate(profile, context=WritePolicyContext(user_command="remember"))
        self.assertEqual(operation.operation, MemoryOperationType.EPHEMERAL_ONLY)
        self.assertNotIn("user_review_approved", operation.candidate.metadata)
        self.assertNotIn("profile_qualification", operation.candidate.metadata)
        self.repo.apply_operation(operation)
        self.assertEqual(self.repo.list_records(user_id="reader"), [])
        self.assertEqual(self.repo.list_review_items(user_id="reader"), [])

    def test_same_turn_across_retries_and_records_is_one_observation(self) -> None:
        items = [evidence("same-turn") for _ in range(10)]
        self.assertEqual(ProfileAccumulator().accumulate(items, now=NOW), [])
        self.assertEqual(ProfileAccumulator(min_evidence_count=1).accumulate(items, now=NOW), [])
        items.append(evidence("second-turn"))
        hypothesis = ProfileAccumulator().accumulate(items, now=NOW)[0]
        self.assertEqual(hypothesis.evidence_count, 2)
        self.assertEqual(hypothesis.source_turn_ids, ["same-turn", "second-turn"])

    def test_unidentified_legacy_and_future_turns_do_not_qualify(self) -> None:
        self.assertEqual(ProfileAccumulator().accumulate([evidence(None), evidence(None)], now=NOW), [])
        self.assertEqual(ProfileAccumulator().accumulate([
            evidence("now"), evidence("future", when=NOW + timedelta(days=1)),
        ], now=NOW), [])

    def test_explicit_review_choice_still_queues_qualified_profile(self) -> None:
        profile = qualified_record()
        settings = UserMemorySettings(review_required_for_layers=[MemoryLayer.INFERRED_PROFILE],
                                      review_required_for_layers_explicit=True)
        operation = self.evaluator.evaluate(profile, context=WritePolicyContext(
            settings=settings, qualified_profile_ids=frozenset({profile.id}),
        ))
        self.assertEqual(operation.operation, MemoryOperationType.ASK_USER_CONFIRMATION)
        self.assertTrue(operation.requires_user_review)

    def test_profile_hard_controls_still_override_qualification(self) -> None:
        profile = qualified_record()
        for settings in (
            UserMemorySettings(memory_enabled=False),
            UserMemorySettings(allow_inferred_profile=False),
            UserMemorySettings(disabled_layers=[MemoryLayer.INFERRED_PROFILE]),
            UserMemorySettings(disabled_keys=[profile.key]),
        ):
            with self.subTest(settings=settings):
                operation = self.evaluator.evaluate(profile, context=WritePolicyContext(
                    settings=settings, qualified_profile_ids=frozenset({profile.id}),
                ))
                self.assertEqual(operation.operation, MemoryOperationType.REJECT)
                self.assertEqual(apply_read_controls([profile], settings), [])

    def test_qualified_sensitive_profile_keeps_opt_in_and_review(self) -> None:
        profile = qualified_record()
        profile.sensitivity = Sensitivity.SENSITIVE
        trusted = frozenset({profile.id})
        blocked = self.evaluator.evaluate(profile, context=WritePolicyContext(qualified_profile_ids=trusted))
        self.assertEqual(blocked.operation, MemoryOperationType.REJECT)
        allowed = self.evaluator.evaluate(profile, context=WritePolicyContext(
            settings=UserMemorySettings(allow_sensitive_memory=True), qualified_profile_ids=trusted,
        ))
        self.assertEqual(allowed.operation, MemoryOperationType.ASK_USER_CONFIRMATION)

    def test_qualification_does_not_bypass_project_global_or_temporary_scope(self) -> None:
        for scope in ("project", "domain", "global"):
            with self.subTest(scope=scope):
                profile = qualified_record()
                profile.scope = scope
                profile.project_id = "project-a"
                profile.domain = "coding"
                operation = self.evaluator.evaluate(profile, context=WritePolicyContext(
                    qualified_profile_ids=frozenset({profile.id}),
                ))
                self.assertEqual(operation.operation, MemoryOperationType.REJECT)
        profile = qualified_record()
        for scope in ("turn", "session"):
            with self.subTest(temporary_scope=scope):
                operation = self.evaluator.evaluate(profile, context=WritePolicyContext(
                    scope=scope, user_command="remember", qualified_profile_ids=frozenset({profile.id}),
                ))
                self.assertEqual(operation.operation, MemoryOperationType.EPHEMERAL_ONLY)

    def test_updated_evidence_supersedes_inferred_profile_without_confirmation(self) -> None:
        old = qualified_record()
        saved_operation = self.evaluator.evaluate(old, context=WritePolicyContext(qualified_profile_ids=frozenset({old.id})))
        self.repo.apply_operation(saved_operation)
        new = qualified_record([evidence("new-a", value="low"), evidence("new-b", value="low")])
        update = self.evaluator.evaluate(new, [saved_operation.candidate], WritePolicyContext(
            qualified_profile_ids=frozenset({new.id}),
        ))
        self.assertEqual(update.operation, MemoryOperationType.SUPERSEDE)
        self.repo.apply_operation(update)
        self.assertEqual([item.id for item in self.repo.list_records(user_id="reader")], [new.id])
        self.assertEqual(self.repo.list_review_items(user_id="reader"), [])

    def test_automatic_inference_does_not_undo_user_correction_or_queue_interrupt(self) -> None:
        old = qualified_record()
        old.authority = Authority.USER_EXPLICIT
        old.metadata["user_review_approved"] = True
        new = qualified_record([evidence("new-a", value="low"), evidence("new-b", value="low")])
        operation = self.evaluator.evaluate(new, [old], WritePolicyContext(qualified_profile_ids=frozenset({new.id})))
        self.assertEqual(operation.operation, MemoryOperationType.EPHEMERAL_ONLY)
        self.assertFalse(operation.requires_user_review)

    def test_recent_turn_window_can_replace_a_large_old_majority(self) -> None:
        old = [evidence(f"old-{i}", value="high", when=NOW - timedelta(days=1, seconds=i)) for i in range(100)]
        self.assertEqual(ProfileAccumulator().accumulate(old, now=NOW)[0].value, "high")
        recent = [evidence(f"new-{i}", value="low", when=NOW - timedelta(seconds=i)) for i in range(6)]
        hypotheses = ProfileAccumulator().accumulate(old + recent, now=NOW)
        self.assertEqual(len(hypotheses), 1)
        self.assertEqual(hypotheses[0].value, "low")
        self.assertEqual(hypotheses[0].evidence_count, 6)

    def test_counter_evidence_and_read_clock_can_remove_qualification(self) -> None:
        items = [evidence("support-a"), evidence("support-b")]
        self.assertEqual(len(ProfileAccumulator().accumulate(items, now=NOW)), 1)
        self.assertEqual(ProfileAccumulator().accumulate(items, now=NOW + timedelta(days=365)), [])
        self.assertEqual(ProfileAccumulator().accumulate(items + [evidence("counter", polarity="counter")], now=NOW), [])

    def test_competing_equally_supported_values_abstain(self) -> None:
        items = [evidence("high-a"), evidence("high-b"),
                 evidence("low-a", value="low"), evidence("low-b", value="low")]
        self.assertEqual(ProfileAccumulator().accumulate(items, now=NOW), [])

    def test_users_cannot_supply_each_others_second_turn(self) -> None:
        items = [evidence("a", user_id="reader"), evidence("b", user_id="someone-else")]
        self.assertEqual(ProfileAccumulator().accumulate(items, now=NOW), [])
        hypothesis = ProfileAccumulator().accumulate([evidence("a"), evidence("b")], now=NOW)[0]
        with self.assertRaisesRegex(ValueError, "different user"):
            hypothesis.to_record(user_id="someone-else", session_id=None, observed_at=NOW)

    def test_legacy_default_migration_records_ambiguity_and_is_idempotent(self) -> None:
        old = {"review_required_for_layers": ["inferred_profile"], "memory_enabled": False}
        migrated = UserMemorySettings.from_dict(old)
        self.assertEqual(migrated.review_required_for_layers, [])
        self.assertFalse(migrated.memory_enabled)
        self.assertEqual(migrated.legacy_review_required_for_layers, [MemoryLayer.INFERRED_PROFILE])
        self.assertEqual(migrated.review_policy_migration, "legacy_default_replaced_origin_unknown")
        self.assertEqual(UserMemorySettings.from_dict(migrated.to_dict()), migrated)

    def test_explicit_and_custom_legacy_review_choices_are_preserved(self) -> None:
        for payload in (
            {"review_required_for_layers": ["inferred_profile"], "review_required_for_layers_explicit": True},
            {"review_required_for_layers": ["preference", "inferred_profile"]},
            {"profile_policy_version": PROFILE_POLICY_VERSION,
             "review_required_for_layers": ["inferred_profile"], "review_required_for_layers_explicit": True},
        ):
            with self.subTest(payload=payload):
                settings = UserMemorySettings.from_dict(payload)
                self.assertIn(MemoryLayer.INFERRED_PROFILE, settings.review_required_for_layers)
                self.assertTrue(settings.review_required_for_layers_explicit)
                self.assertEqual(UserMemorySettings.from_dict(settings.to_dict()), settings)

    def test_old_manual_approval_remains_readable_but_unqualified_profile_does_not(self) -> None:
        approved = qualified_record()
        approved.metadata["user_review_approved"] = True
        self.assertEqual(apply_read_controls([approved], UserMemorySettings()), [approved])
        unqualified = qualified_record()
        self.assertEqual(apply_read_controls([unqualified], UserMemorySettings()), [])

    def test_explicit_profile_correction_replaces_inference_authority_and_provenance(self) -> None:
        original = qualified_record()
        operation = self.evaluator.evaluate(original, context=WritePolicyContext(
            qualified_profile_ids=frozenset({original.id}),
        ))
        self.repo.apply_operation(operation, created_at=NOW)
        corrected = self.repo.correct_record(
            str(original.id), user_id="reader", value="low",
            evidence="That inference is wrong; I prefer a softer tone.", corrected_at=NOW,
        )
        saved = self.repo.get_record(str(corrected.id))
        self.assertTrue(is_user_corrected_profile(saved))
        self.assertFalse(has_autonomous_profile_qualification(saved))
        for old_claim in ("profile_qualification", "source_memory_ids", "evidence_ids",
                          "counter_evidence_ids", "user_review_approved", "support_weight"):
            self.assertNotIn(old_claim, saved.metadata)
        self.assertEqual(saved.evidence_ids, [])
        self.assertEqual(saved.source_turn_ids, [f"user_correction:{saved.id}"])
        self.assertEqual(apply_read_controls([saved], UserMemorySettings()), [saved])
        historical = self.repo.get_record(str(original.id))
        self.assertIn("profile_qualification", historical.metadata)
        self.assertEqual(historical.value, "high")
        self.assertEqual(saved.value, "low")
        self.assertEqual(apply_read_controls([saved], UserMemorySettings(allow_inferred_profile=False)), [])

    def test_external_profile_cannot_forge_user_correction_read_qualification(self) -> None:
        profile = qualified_record()
        profile.authority = Authority.USER_EXPLICIT
        profile.supersedes = uuid4()
        profile.metadata.update(correction=True, correction_origin="user_memory_correction",
                                corrected_from=str(profile.supersedes))
        self.assertTrue(is_user_corrected_profile(profile))
        operation = self.evaluator.evaluate(profile)
        self.assertEqual(operation.operation, MemoryOperationType.EPHEMERAL_ONLY)
        self.assertFalse(is_user_corrected_profile(operation.candidate))
        self.assertEqual(apply_read_controls([operation.candidate], UserMemorySettings()), [])


if __name__ == "__main__":
    unittest.main()
