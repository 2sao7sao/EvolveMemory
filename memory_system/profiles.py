from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from .models import Authority, MemoryLayer, MemoryRecord, Sensitivity


@dataclass(frozen=True)
class ProfileEvidence:
    user_id: str
    dimension: str
    value: str
    confidence: float
    weight: float
    polarity: str
    source_memory_id: UUID
    source_key: str
    quote: str
    observed_at: datetime
    session_id: str | None = None
    id: UUID = field(default_factory=uuid4)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "dimension": self.dimension,
            "value": self.value,
            "confidence": self.confidence,
            "weight": self.weight,
            "polarity": self.polarity,
            "source_memory_id": str(self.source_memory_id),
            "source_key": self.source_key,
            "quote": self.quote,
            "observed_at": self.observed_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProfileEvidence":
        return cls(
            id=UUID(payload["id"]),
            user_id=payload["user_id"],
            session_id=payload.get("session_id"),
            dimension=payload["dimension"],
            value=payload["value"],
            confidence=float(payload["confidence"]),
            weight=float(payload["weight"]),
            polarity=payload["polarity"],
            source_memory_id=UUID(payload["source_memory_id"]),
            source_key=payload["source_key"],
            quote=payload["quote"],
            observed_at=datetime.fromisoformat(payload["observed_at"]),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(frozen=True)
class ProfileHypothesis:
    dimension: str
    value: str
    confidence: float
    evidence_count: int
    support_weight: float
    evidence_ids: list[UUID]
    rationale: str

    def to_record(
        self,
        *,
        user_id: str,
        session_id: str | None,
        observed_at: datetime,
    ) -> MemoryRecord:
        return MemoryRecord(
            user_id=user_id,
            session_id=session_id,
            layer=MemoryLayer.INFERRED_PROFILE,
            key=self.dimension,
            value=self.value,
            normalized_value=self.value,
            confidence=self.confidence,
            authority=Authority.ASSISTANT_INFERRED,
            sensitivity=(
                Sensitivity.SENSITIVE
                if self.dimension == "emotional_support_need"
                else Sensitivity.PERSONAL
            ),
            valid_from=observed_at,
            observed_at=observed_at,
            exclusive_group=self.dimension,
            coexistence_rule="mutually_exclusive",
            tags=["inferred_profile", "evidence_accumulated"],
            metadata={
                "evidence_count": self.evidence_count,
                "support_weight": round(self.support_weight, 3),
                "evidence_ids": [str(item) for item in self.evidence_ids],
                "rationale": self.rationale,
                "profile_version": "evidence-accumulator-v1",
            },
        )


class ProfileEvidenceExtractor:
    def extract(self, records: list[MemoryRecord]) -> list[ProfileEvidence]:
        evidence: list[ProfileEvidence] = []
        for record in records:
            mapped = self._map_record(record)
            if mapped is None:
                continue
            dimension, value, weight = mapped
            evidence.append(
                ProfileEvidence(
                    user_id=record.user_id,
                    session_id=record.session_id,
                    dimension=dimension,
                    value=value,
                    confidence=record.confidence,
                    weight=weight,
                    polarity="support",
                    source_memory_id=record.id,
                    source_key=record.key,
                    quote=str(record.metadata.get("evidence", record.value)),
                    observed_at=record.observed_at,
                    metadata={
                        "source_layer": record.layer.value,
                        "source_authority": record.authority.value,
                    },
                )
            )
        return evidence

    def _map_record(self, record: MemoryRecord) -> tuple[str, str, float] | None:
        if record.key == "communication_style" and record.value == "direct":
            return ("directness_preference_level", "high", 0.82)
        if record.key == "detail_preference" and record.value == "concise":
            return ("detail_tolerance", "low", 0.78)
        if record.key == "detail_preference" and record.value == "detailed":
            return ("detail_tolerance", "high", 0.78)
        if record.key in {"response_opening", "explanation_structure"}:
            return ("structure_preference_level", "high", 0.72)
        if record.key == "decision_preference" and record.value == "recommend":
            return ("decision_style", "decisive", 0.74)
        if record.key == "communication_pace" and record.value == "slow":
            return ("pace_preference", "slow", 0.72)
        if record.key == "current_bandwidth" and record.value == "busy":
            return ("pace_preference", "fast", 0.48)
        if record.key == "current_emotional_state" and record.value in {"anxious", "stressed"}:
            return ("emotional_support_need", "elevated", 0.52)
        return None


class ProfileAccumulator:
    def __init__(self, min_evidence_count: int = 2, min_support_weight: float = 1.2) -> None:
        self.min_evidence_count = min_evidence_count
        self.min_support_weight = min_support_weight

    def accumulate(self, evidence: list[ProfileEvidence]) -> list[ProfileHypothesis]:
        grouped: dict[tuple[str, str], list[ProfileEvidence]] = {}
        for item in evidence:
            if item.polarity != "support":
                continue
            grouped.setdefault((item.dimension, item.value), []).append(item)

        hypotheses: list[ProfileHypothesis] = []
        for (dimension, value), items in grouped.items():
            support_weight = sum(item.weight * item.confidence for item in items)
            if len(items) < self.min_evidence_count or support_weight < self.min_support_weight:
                continue
            confidence = min(0.93, 0.45 + support_weight / 2.4)
            hypotheses.append(
                ProfileHypothesis(
                    dimension=dimension,
                    value=value,
                    confidence=confidence,
                    evidence_count=len(items),
                    support_weight=support_weight,
                    evidence_ids=[item.id for item in items],
                    rationale=(
                        f"{dimension}={value} inferred from "
                        f"{len(items)} supporting evidence items"
                    ),
                )
            )
        return sorted(hypotheses, key=lambda item: item.confidence, reverse=True)
