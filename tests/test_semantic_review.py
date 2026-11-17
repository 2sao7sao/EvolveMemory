"""Structural review contracts; these do not test a model's semantic accuracy."""
from copy import deepcopy
import unittest

from memory_system.semantic_review import apply_semantic_review


def proposal(key="detail_preference", value="concise", **changes):
    item = {"layer": "preference", "key": key, "value": value, "retention": "durable"}
    item.update(changes)
    return item


def verdict(index=0, **changes):
    item = {"candidate_index": index, "relation": "supports",
            "evidence_kind": "sustained_preference", "retention": "durable"}
    item.update(changes)
    return item


class SemanticReviewTest(unittest.TestCase):
    def review(self, candidates, decisions, retractions=None, existing=None):
        return apply_semantic_review(candidates, {"decisions": decisions,
            "memory_retractions": retractions or []}, text="不是一概越短越好",
            existing_assertions=existing or [])

    def test_counter_judgment_never_becomes_support_or_opposite_preference(self):
        original = proposal()
        before = deepcopy(original)
        result, rejected = self.review([original], [verdict(relation="contradicts", evidence_kind="correction")],
            [{"memory_id": "old", "evidence": "不是一概越短越好", "reason": "correction"}],
            [{"memory_id": "old", "type": "preference", "key": "detail_preference"}])
        self.assertEqual(result["candidate_memories"], [])
        self.assertEqual(result["memory_retractions"][0]["memory_id"], "old")
        self.assertEqual(rejected[0]["reason"], "semantic_evidence_contradicts")
        self.assertEqual(original, before)

    def test_task_instruction_cannot_accumulate_even_if_extractor_says_durable(self):
        for kind in ("current_task", "correction"):
            with self.subTest(kind=kind):
                result, rejected = self.review([proposal()], [verdict(evidence_kind=kind)])
                self.assertEqual(result["candidate_memories"], [])
                self.assertEqual(rejected[0]["reason"], "current_request_not_lasting_evidence")

    def test_contextual_judgment_cannot_lose_context_in_generic_enum(self):
        result, rejected = self.review([proposal()], [verdict(evidence_kind="contextual_preference")])
        self.assertEqual(result["candidate_memories"], [])
        self.assertEqual(rejected[0]["reason"], "context_would_be_lost_in_generic_preference")
        result, _ = self.review([proposal("contextual_review", "评审先结论再展开风险")],
                                [verdict(evidence_kind="contextual_preference")])
        self.assertEqual(result["candidate_memories"][0]["evidence_kind"], "contextual_preference")

    def test_supported_implicit_preference_is_allowed_without_confirmation(self):
        result, rejected = self.review([proposal("communication_style", "direct", authority="user_implicit")],
            [verdict(evidence_kind="behavior_observation")])
        self.assertEqual(result["candidate_memories"][0]["authority"], "user_implicit")
        self.assertEqual(rejected, [])

    def test_wrong_layer_cannot_turn_contextual_preference_into_direct_fact(self):
        for kind in ("sustained_preference", "contextual_preference", "behavior_observation"):
            with self.subTest(kind=kind):
                result, rejected = self.review([proposal(layer="semantic_fact")], [verdict(evidence_kind=kind)])
                self.assertEqual(result["candidate_memories"], [])
                self.assertEqual(rejected[0]["reason"], "preference_evidence_requires_preference_layer")

    def test_review_cannot_promote_turn_or_state_lifetime(self):
        result, _ = self.review([proposal(retention="turn")], [verdict(retention="state", evidence_kind="current_state")])
        self.assertEqual(result["candidate_memories"], [])
        result, _ = self.review([proposal(retention="state")], [verdict(retention="durable")])
        self.assertEqual(result["candidate_memories"][0]["retention"], "state")

    def test_state_mapping_is_explicit_typed_review_not_prose_guessing(self):
        state = proposal("current_bandwidth", "今天很忙", layer="semantic_fact", retention="state")
        for value in ("busy", "available"):
            result, _ = self.review([state], [verdict(evidence_kind="current_state", retention="state", normalized_value=value)])
            self.assertEqual(result["candidate_memories"][0]["value"], value)
            self.assertEqual(result["candidate_memories"][0]["normalized_value"], value)
        result, rejected = self.review([state], [verdict(evidence_kind="current_state", retention="state", normalized_value="可能很忙")])
        self.assertEqual(result["candidate_memories"], [])
        self.assertEqual(rejected[0]["reason"], "invalid_review_state")

    def test_missing_duplicate_or_insufficient_verdict_cannot_default_to_support(self):
        for decisions in ([], [verdict(), verdict()], [verdict(relation="insufficient")]):
            with self.subTest(decisions=decisions):
                result, rejected = self.review([proposal()], decisions)
                self.assertEqual(result["candidate_memories"], [])
                self.assertTrue(rejected)

    def test_retraction_requires_known_source_and_current_evidence(self):
        existing = [{"memory_id": "known", "type": "preference"}, {"memory_id": "profile", "type": "profile"}]
        result, rejected = self.review([], [], [
            {"memory_id": "unknown", "evidence": "不是一概越短越好"},
            {"memory_id": "known", "evidence": "invented correction"},
            {"memory_id": "known", "evidence": ""},
            {"memory_id": "profile", "evidence": "不是一概越短越好"},
        ], existing)
        self.assertEqual(result["memory_retractions"], [])
        self.assertEqual(len(rejected), 4)
