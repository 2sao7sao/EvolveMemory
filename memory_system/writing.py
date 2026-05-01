from __future__ import annotations

from dataclasses import dataclass, field

from .models import (
    Authority,
    MemoryLayer,
    MemoryOperation,
    MemoryOperationType,
    MemoryRecord,
    Sensitivity,
)
from .settings import UserMemorySettings


AUTHORITY_RANK = {
    Authority.SYSTEM: 5,
    Authority.USER_EXPLICIT: 4,
    Authority.EXTERNAL_SOURCE: 3,
    Authority.USER_IMPLICIT: 2,
    Authority.ASSISTANT_INFERRED: 1,
}


@dataclass(frozen=True)
class WritePolicyContext:
    user_command: str | None = None
    user_consent: bool = False
    settings: UserMemorySettings = field(default_factory=UserMemorySettings)


@dataclass(frozen=True)
class Contradiction:
    conflict_type: str
    existing: MemoryRecord
    reason: str


class ContradictionDetector:
    def detect(
        self,
        candidate: MemoryRecord,
        existing_records: list[MemoryRecord],
    ) -> Contradiction | None:
        for existing in existing_records:
            if existing.status.value != "active":
                continue
            if self._is_duplicate(candidate, existing):
                return Contradiction("duplicate", existing, "same key and normalized value")
            if self._exclusive_conflict(candidate, existing):
                return Contradiction(
                    "exclusive_slot_conflict",
                    existing,
                    f"{candidate.exclusive_group} already has active value",
                )
        return None

    def _is_duplicate(self, candidate: MemoryRecord, existing: MemoryRecord) -> bool:
        return (
            candidate.layer == existing.layer
            and candidate.key == existing.key
            and candidate.normalized_value == existing.normalized_value
        )

    def _exclusive_conflict(self, candidate: MemoryRecord, existing: MemoryRecord) -> bool:
        return (
            candidate.exclusive_group is not None
            and candidate.exclusive_group == existing.exclusive_group
            and candidate.key == existing.key
            and candidate.normalized_value != existing.normalized_value
        )


class WeightedMemoryWriteEvaluatorV2:
    def __init__(self, threshold: float = 0.55) -> None:
        self.threshold = threshold

    def score(
        self,
        candidate: MemoryRecord,
        existing_records: list[MemoryRecord] | None = None,
        context: WritePolicyContext | None = None,
    ) -> tuple[float, dict[str, float]]:
        context = context or WritePolicyContext()
        existing_records = existing_records or []
        factors = {
            "confidence": candidate.confidence,
            "future_reuse": self._future_reuse(candidate),
            "personalization_gain": self._personalization_gain(candidate),
            "stability": self._stability(candidate),
            "user_authority": self._user_authority(candidate),
            "evidence_quality": self._evidence_quality(candidate),
            "novelty": self._novelty(candidate, existing_records),
            "actionability": self._actionability(candidate),
            "privacy_adjustment": self._privacy_adjustment(candidate, context),
        }
        score = (
            0.18 * factors["confidence"]
            + 0.16 * factors["future_reuse"]
            + 0.14 * factors["personalization_gain"]
            + 0.12 * factors["stability"]
            + 0.10 * factors["user_authority"]
            + 0.10 * factors["evidence_quality"]
            + 0.08 * factors["novelty"]
            + 0.07 * factors["actionability"]
            + 0.05 * factors["privacy_adjustment"]
        )
        if context.user_command == "remember":
            score = min(1.0, score + 0.25)
            factors["explicit_remember_boost"] = 0.25
        return score, factors

    def evaluate(
        self,
        candidate: MemoryRecord,
        existing_records: list[MemoryRecord] | None = None,
        context: WritePolicyContext | None = None,
    ) -> MemoryOperation:
        context = context or WritePolicyContext()
        existing_records = existing_records or []
        score, factors = self.score(candidate, existing_records, context)

        if not context.settings.memory_enabled:
            return self._operation(
                MemoryOperationType.REJECT,
                candidate,
                score,
                "memory disabled by user settings",
                factors,
            )
        if not context.settings.allows_key(candidate.key) or not context.settings.allows_layer(
            candidate.layer
        ):
            return self._operation(
                MemoryOperationType.REJECT,
                candidate,
                score,
                "memory key or layer disabled by user settings",
                factors,
            )
        if context.user_command == "do_not_remember":
            return self._operation(
                MemoryOperationType.REJECT,
                candidate,
                0.0,
                "explicit do-not-remember command",
                factors,
            )
        if candidate.sensitivity == Sensitivity.RESTRICTED and not context.user_consent:
            return self._operation(
                MemoryOperationType.ASK_USER_CONFIRMATION,
                candidate,
                score,
                "restricted memory requires explicit user consent",
                factors,
                requires_user_review=True,
            )
        if candidate.confidence < 0.45:
            return self._operation(
                MemoryOperationType.REJECT,
                candidate,
                score,
                "confidence below hard minimum",
                factors,
            )
        if candidate.confidence < 0.65 and candidate.sensitivity in {
            Sensitivity.SENSITIVE,
            Sensitivity.RESTRICTED,
        }:
            return self._operation(
                MemoryOperationType.ASK_USER_CONFIRMATION,
                candidate,
                score,
                "low-confidence sensitive memory requires review",
                factors,
                requires_user_review=True,
            )

        contradiction = ContradictionDetector().detect(candidate, existing_records)
        if contradiction is not None:
            return self._resolve_contradiction(candidate, contradiction, score, factors)

        if score < self.threshold:
            return self._operation(
                MemoryOperationType.REJECT,
                candidate,
                score,
                "below weighted write threshold",
                factors,
            )
        if candidate.sensitivity in context.settings.review_required_for_sensitivity:
            return self._operation(
                MemoryOperationType.ASK_USER_CONFIRMATION,
                candidate,
                score,
                "sensitivity policy requires review",
                factors,
                requires_user_review=True,
            )
        if candidate.layer in context.settings.review_required_for_layers:
            return self._operation(
                MemoryOperationType.ASK_USER_CONFIRMATION,
                candidate,
                score,
                "layer policy requires review",
                factors,
                requires_user_review=True,
            )
        return self._operation(
            MemoryOperationType.CREATE,
            candidate,
            score,
            "passes weighted write policy",
            factors,
        )

    def _resolve_contradiction(
        self,
        candidate: MemoryRecord,
        contradiction: Contradiction,
        score: float,
        factors: dict[str, float],
    ) -> MemoryOperation:
        existing = contradiction.existing
        if contradiction.conflict_type == "duplicate":
            return self._operation(
                MemoryOperationType.ADD_EVIDENCE_ONLY,
                candidate,
                score,
                "duplicate memory; append evidence instead of creating new record",
                factors,
                target_memory_id=existing.id,
            )
        if AUTHORITY_RANK[candidate.authority] >= AUTHORITY_RANK[existing.authority]:
            return self._operation(
                MemoryOperationType.SUPERSEDE,
                candidate,
                score,
                f"{contradiction.reason}; candidate authority is sufficient to supersede",
                factors,
                target_memory_id=existing.id,
            )
        return self._operation(
            MemoryOperationType.ASK_USER_CONFIRMATION,
            candidate,
            score,
            f"{contradiction.reason}; candidate authority is lower than existing memory",
            factors,
            target_memory_id=existing.id,
            requires_user_review=True,
        )

    def _operation(
        self,
        operation: MemoryOperationType,
        candidate: MemoryRecord,
        score: float,
        reason: str,
        factors: dict[str, float],
        *,
        target_memory_id=None,
        requires_user_review: bool = False,
    ) -> MemoryOperation:
        return MemoryOperation(
            operation=operation,
            candidate=candidate,
            target_memory_id=target_memory_id,
            reason=reason,
            score=max(0.0, min(1.0, score)),
            requires_user_review=requires_user_review,
            audit_metadata={"factors": factors, "policy_version": "write-v2.0"},
        )

    def _future_reuse(self, candidate: MemoryRecord) -> float:
        if candidate.layer in {MemoryLayer.PREFERENCE, MemoryLayer.PROCEDURAL_MEMORY}:
            return 0.95
        if candidate.layer == MemoryLayer.EPISODIC_EVENT:
            return 0.78
        if candidate.key in {"work_status", "profession", "current_emotional_state"}:
            return 0.86
        return 0.62

    def _personalization_gain(self, candidate: MemoryRecord) -> float:
        if candidate.layer in {MemoryLayer.PREFERENCE, MemoryLayer.INFERRED_PROFILE}:
            return 0.95
        if candidate.layer == MemoryLayer.EPISODIC_EVENT:
            return 0.82
        if candidate.sensitivity in {Sensitivity.SENSITIVE, Sensitivity.RESTRICTED}:
            return 0.62
        return 0.72

    def _stability(self, candidate: MemoryRecord) -> float:
        if candidate.layer in {MemoryLayer.PREFERENCE, MemoryLayer.PROCEDURAL_MEMORY}:
            return 0.88
        if candidate.layer == MemoryLayer.INFERRED_PROFILE:
            return 0.55
        if candidate.layer == MemoryLayer.EPISODIC_EVENT:
            return 0.68
        if candidate.valid_to is None:
            return 0.84
        return 0.62

    def _user_authority(self, candidate: MemoryRecord) -> float:
        return AUTHORITY_RANK[candidate.authority] / max(AUTHORITY_RANK.values())

    def _evidence_quality(self, candidate: MemoryRecord) -> float:
        evidence = str(candidate.metadata.get("evidence", ""))
        if evidence and candidate.source_turn_ids:
            return 0.9
        if evidence:
            return 0.7
        return 0.35

    def _novelty(self, candidate: MemoryRecord, existing_records: list[MemoryRecord]) -> float:
        for existing in existing_records:
            if existing.key == candidate.key and existing.normalized_value == candidate.normalized_value:
                return 0.25
        return 0.85

    def _actionability(self, candidate: MemoryRecord) -> float:
        if candidate.allowed_use:
            return 0.88
        if candidate.layer == MemoryLayer.EPISODIC_EVENT:
            return 0.82
        return 0.55

    def _privacy_adjustment(
        self,
        candidate: MemoryRecord,
        context: WritePolicyContext,
    ) -> float:
        if candidate.sensitivity == Sensitivity.PUBLIC:
            return 1.0
        if candidate.sensitivity == Sensitivity.PERSONAL:
            return 0.86
        if candidate.sensitivity == Sensitivity.SENSITIVE:
            return 0.72 if context.settings.allow_sensitive_memory else 0.42
        if candidate.sensitivity == Sensitivity.RESTRICTED:
            return 0.6 if context.user_consent else 0.05
        return 0.5


class MemoryOperationPlanner:
    def __init__(self, evaluator: WeightedMemoryWriteEvaluatorV2 | None = None) -> None:
        self.evaluator = evaluator or WeightedMemoryWriteEvaluatorV2()

    def plan(
        self,
        candidates: list[MemoryRecord],
        existing_records: list[MemoryRecord],
        context: WritePolicyContext | None = None,
    ) -> list[MemoryOperation]:
        planned: list[MemoryOperation] = []
        simulated_existing = list(existing_records)
        for candidate in candidates:
            operation = self.evaluator.evaluate(candidate, simulated_existing, context)
            planned.append(operation)
            if operation.operation in {
                MemoryOperationType.CREATE,
                MemoryOperationType.SUPERSEDE,
                MemoryOperationType.MERGE,
            }:
                simulated_existing.append(candidate)
        return planned
