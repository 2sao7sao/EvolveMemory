from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone

from memory_system.models import Authority, MemoryLayer, MemoryRecord
from memory_system.profiles import (
    ProfileAccumulator, ProfileEvidenceExtractor, is_supported_profile_evidence,
)


NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


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


class ProfileMappingSemanticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = ProfileEvidenceExtractor()
        self.accumulator = ProfileAccumulator()

    def test_detail_preference_changes_only_the_detail_dimension(self) -> None:
        for value, supported, countered in (("concise", "low", "high"), ("detailed", "high", "low")):
            with self.subTest(value=value):
                records = [preference(str(i), value=value, normalized_value=value) for i in range(2)]
                evidence = self.extractor.extract(records)
                self.assertEqual({(item.dimension, item.value, item.polarity) for item in evidence}, {
                    ("detail_tolerance", supported, "support"),
                    ("detail_tolerance", countered, "counter"),
                })
                self.assertTrue(all(item.dimension != "cognitive_load_preference" for item in evidence))
                hypotheses = self.accumulator.accumulate(evidence, now=NOW)
                self.assertEqual([(item.dimension, item.value) for item in hypotheses], [("detail_tolerance", supported)])
                self.assertEqual(hypotheses[0].evidence_count, 2)
                self.assertTrue(hypotheses[0].autonomous_qualified)

    def test_repeated_busy_states_do_not_create_stable_profiles(self) -> None:
        records = [preference(str(i), layer=MemoryLayer.SEMANTIC_FACT,
                              key="current_bandwidth", value="busy", normalized_value="busy",
                              metadata={"evidence": "I am busy this week."}) for i in range(8)]
        evidence = self.extractor.extract(records)
        self.assertEqual(evidence, [])
        self.assertEqual(self.accumulator.accumulate(evidence, now=NOW), [])

    def test_temporary_state_task_and_contextual_markers_never_promote(self) -> None:
        for marker in (
            {"retention": "turn"}, {"retention": "state"},
            {"evidence_kind": "current_state"}, {"evidence_kind": "current_task"},
            {"evidence_kind": "contextual_preference"},
            {"retention": "durable", "evidence_kind": "contextual_preference"},
        ):
            with self.subTest(marker=marker):
                records = [preference(str(i), metadata={"evidence": "Be concise for this task.", **marker})
                           for i in range(8)]
                self.assertEqual(self.extractor.extract(records), [])

    def test_turn_scope_never_promotes_even_when_metadata_claims_durable(self) -> None:
        records = [preference(str(i), scope="turn", metadata={"retention": "durable"}) for i in range(2)]
        self.assertEqual(self.extractor.extract(records), [])

    def test_session_history_and_explicit_durable_preferences_remain_eligible(self) -> None:
        for metadata in ({"evidence": "Be concise."},
                         {"retention": "durable", "evidence_kind": "stable_preference"}):
            with self.subTest(metadata=metadata):
                records = [preference(str(i), metadata=metadata) for i in range(2)]
                evidence = self.extractor.extract(records)
                self.assertEqual(len(evidence), 4)
                hypotheses = self.accumulator.accumulate(evidence, now=NOW)
                self.assertEqual([(item.dimension, item.value) for item in hypotheses], [("detail_tolerance", "low")])

    def test_same_dimension_counter_signals_still_withdraw_qualification(self) -> None:
        records = [preference(f"concise-{i}") for i in range(2)] + [
            preference(f"detailed-{i}", value="detailed", normalized_value="detailed") for i in range(2)
        ]
        evidence = self.extractor.extract(records)
        self.assertEqual({item.dimension for item in evidence}, {"detail_tolerance"})
        self.assertEqual(self.accumulator.accumulate(evidence, now=NOW), [])

    def test_repeated_same_turn_does_not_qualify_detail_profile(self) -> None:
        records = [preference("same-turn") for _ in range(4)]
        self.assertEqual(self.accumulator.accumulate(self.extractor.extract(records), now=NOW), [])

    def test_old_removed_mapping_evidence_is_ineligible_without_rewriting_history(self) -> None:
        source = preference("old-turn")
        detail = self.extractor.extract([source])[0]
        legacy_low_load = replace(detail, dimension="cognitive_load_preference", value="low_load")
        self.assertFalse(is_supported_profile_evidence(legacy_low_load, source))
        self.assertTrue(is_supported_profile_evidence(detail, source))
        # A valid counter observation is not forced to inherit the mapping polarity.
        self.assertTrue(is_supported_profile_evidence(replace(detail, polarity="counter"), source))
        detailed = preference("old-detailed", value="detailed", normalized_value="detailed")
        old_deep_dive = replace(self.extractor.extract([detailed])[0],
                               dimension="cognitive_load_preference", value="deep_dive")
        self.assertFalse(is_supported_profile_evidence(old_deep_dive, detailed))

    def test_existing_busy_and_contextual_evidence_is_ineligible_on_revalidation(self) -> None:
        source = preference("old-turn")
        detail = self.extractor.extract([source])[0]
        busy = source.model_copy(update={"key": "current_bandwidth", "value": "busy"})
        old_busy = replace(detail, source_key="current_bandwidth", dimension="pace_preference", value="fast")
        self.assertFalse(is_supported_profile_evidence(old_busy, busy))
        for metadata in ({"retention": "state"}, {"retention": "turn"},
                         {"evidence_kind": "contextual_preference"}):
            with self.subTest(metadata=metadata):
                self.assertFalse(is_supported_profile_evidence(detail, source.model_copy(update={"metadata": metadata})))
        self.assertFalse(is_supported_profile_evidence(detail, source.model_copy(update={"scope": "turn"})))

    def test_evidence_must_reference_its_actual_owner_and_source(self) -> None:
        source = preference("source-turn")
        detail = self.extractor.extract([source])[0]
        self.assertFalse(is_supported_profile_evidence(detail, preference("unrelated-source")))
        self.assertFalse(is_supported_profile_evidence(replace(detail, user_id="other-user"), source))
        self.assertFalse(is_supported_profile_evidence(replace(detail, source_key="another-key"), source))


if __name__ == "__main__":
    unittest.main()
