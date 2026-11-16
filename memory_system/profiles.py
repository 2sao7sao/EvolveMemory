from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from .models import AllowedUse, Authority, MemoryLayer, MemoryRecord, Sensitivity
from .settings import PROFILE_POLICY_VERSION


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
    source_turn_id: str | None = None

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
            "source_turn_id": self.source_turn_id,
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
            source_turn_id=payload.get("source_turn_id") or None,
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
    counter_weight: float
    evidence_ids: list[UUID]
    rationale: str
    counter_evidence_ids: list[UUID] = field(default_factory=list)
    supporting_quotes: list[str] = field(default_factory=list)
    source_turn_ids: list[str] = field(default_factory=list)
    source_memory_ids: list[UUID] = field(default_factory=list)
    source_user_id: str | None = None
    autonomous_qualified: bool = False

    def to_record(
        self,
        *,
        user_id: str,
        session_id: str | None,
        observed_at: datetime,
    ) -> MemoryRecord:
        if self.source_user_id is not None and self.source_user_id != user_id:
            raise ValueError("profile evidence belongs to a different user")
        return MemoryRecord(
            user_id=user_id,
            session_id=session_id,
            layer=MemoryLayer.INFERRED_PROFILE,
            key=self.dimension,
            value=self.value,
            normalized_value=self.value,
            confidence=self.confidence,
            authority=Authority.ASSISTANT_INFERRED,
            source_turn_ids=list(self.source_turn_ids),
            sensitivity=(
                Sensitivity.SENSITIVE
                if self.dimension == "emotional_support_need"
                else Sensitivity.PERSONAL
            ),
            allowed_use=[AllowedUse.STYLE],
            valid_from=observed_at,
            observed_at=observed_at,
            exclusive_group=self.dimension,
            coexistence_rule="mutually_exclusive",
            tags=["inferred_profile", "evidence_accumulated"],
            metadata={
                "evidence_count": self.evidence_count,
                "support_weight": round(self.support_weight, 3),
                "counter_weight": round(self.counter_weight, 3),
                "evidence_ids": [str(item) for item in self.evidence_ids],
                "counter_evidence_ids": [str(item) for item in self.counter_evidence_ids],
                "rationale": self.rationale,
                "supporting_quotes": list(self.supporting_quotes),
                "source_memory_ids": [str(item) for item in self.source_memory_ids],
                "profile_version": "evidence-accumulator-v2",
            },
        )


class ProfileEvidenceExtractor:
    def extract(self, records: list[MemoryRecord]) -> list[ProfileEvidence]:
        evidence: list[ProfileEvidence] = []
        for record in records:
            mapped = self._map_record(record)
            if not mapped:
                continue
            # A merged record can contain several historical turns but only one
            # quote. Do not manufacture independent evidence from that aggregate.
            source_turns = set(record.source_turn_ids)
            source_turn_id = next(iter(source_turns)) if len(source_turns) == 1 else None
            for dimension, value, weight, polarity in mapped:
                evidence.append(
                    ProfileEvidence(
                        user_id=record.user_id,
                        session_id=record.session_id,
                        dimension=dimension,
                        value=value,
                        confidence=record.confidence,
                        weight=weight,
                        polarity=polarity,
                        source_memory_id=record.id,
                        source_turn_id=source_turn_id,
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

    def _map_record(self, record: MemoryRecord) -> list[tuple[str, str, float, str]]:
        if record.key == "communication_style" and record.value == "direct":
            return [("directness_preference_level", "high", 0.82, "support")]
        if record.key == "detail_preference" and record.value == "concise":
            return [
                ("detail_tolerance", "low", 0.78, "support"),
                ("detail_tolerance", "high", 0.62, "counter"),
                ("cognitive_load_preference", "low_load", 0.66, "support"),
            ]
        if record.key == "detail_preference" and record.value == "detailed":
            return [
                ("detail_tolerance", "high", 0.78, "support"),
                ("detail_tolerance", "low", 0.62, "counter"),
                ("cognitive_load_preference", "deep_dive", 0.66, "support"),
            ]
        if record.key in {"response_opening", "explanation_structure"}:
            mapped = [("structure_preference_level", "high", 0.72, "support")]
            if record.key == "explanation_structure" and record.value == "step_by_step":
                mapped.append(("planning_orientation", "prefers_checklists", 0.68, "support"))
            return mapped
        if record.key == "planning_preference" and record.value == "checklist":
            return [("planning_orientation", "prefers_checklists", 0.82, "support")]
        if record.key == "decision_preference" and record.value == "recommend":
            return [
                ("decision_style", "decisive", 0.74, "support"),
                ("uncertainty_tolerance", "low", 0.58, "support"),
            ]
        if record.key == "decision_preference" and record.value == "options":
            return [
                ("decision_style", "option_seeking", 0.7, "support"),
                ("uncertainty_tolerance", "high", 0.56, "support"),
                ("uncertainty_tolerance", "low", 0.5, "counter"),
            ]
        if record.key == "learning_preference" and record.value == "example_first":
            return [("learning_style", "example_first", 0.8, "support")]
        if record.key == "learning_preference" and record.value == "principle_first":
            return [("learning_style", "principle_first", 0.78, "support")]
        if record.key == "collaboration_preference" and record.value == "socratic":
            return [("collaboration_style", "socratic", 0.76, "support")]
        if record.key == "collaboration_preference" and record.value == "challenge":
            return [("collaboration_style", "challenge", 0.76, "support")]
        if record.key == "communication_pace" and record.value == "slow":
            return [
                ("pace_preference", "slow", 0.72, "support"),
                ("pace_preference", "fast", 0.55, "counter"),
            ]
        if record.key == "current_bandwidth" and record.value == "busy":
            return [
                ("pace_preference", "fast", 0.48, "support"),
                ("cognitive_load_preference", "low_load", 0.62, "support"),
            ]
        if record.key == "current_emotional_state" and record.value in {"anxious", "stressed"}:
            return [
                ("emotional_support_need", "elevated", 0.52, "support"),
                ("risk_posture", "risk_averse", 0.42, "support"),
            ]
        return []


class ProfileAccumulator:
    """Bounded evidence heuristic, not a claim of validated psychological understanding.

    Eight recent distinct turns and a 30-day half-life prevent an unlimited pile
    of old observations from permanently outweighing new behavior. Both values
    are engineering defaults that need evaluation against longitudinal dialogue.
    """

    def __init__(
        self, min_evidence_count: int = 2, min_support_weight: float = 1.2,
        *, recent_turn_window: int = 8, half_life_days: float = 30.0,
    ) -> None:
        self.min_evidence_count = max(2, min_evidence_count)
        self.min_support_weight = min_support_weight
        self.recent_turn_window = max(self.min_evidence_count, recent_turn_window)
        self.half_life_days = max(1.0, half_life_days)

    def accumulate(
        self, evidence: list[ProfileEvidence], *, now: datetime | None = None,
    ) -> list[ProfileHypothesis]:
        current_at = now or max((item.observed_at for item in evidence), default=None)
        # Replayed evidence, multiple records from one utterance, and legacy
        # entries without a real turn id must not become independent observations.
        unique: dict[tuple[str, str, str, str, str], ProfileEvidence] = {}
        for item in evidence:
            if not item.source_turn_id or (current_at is not None and item.observed_at > current_at):
                continue
            identity = (item.user_id, item.dimension, item.value, item.polarity, item.source_turn_id)
            previous = unique.get(identity)
            if previous is None or self._decayed_weight(item, current_at) > self._decayed_weight(previous, current_at):
                unique[identity] = item
        dimensions: dict[tuple[str, str], list[ProfileEvidence]] = {}
        for item in unique.values():
            dimensions.setdefault((item.user_id, item.dimension), []).append(item)
        hypotheses: list[ProfileHypothesis] = []
        for (user_id, dimension), all_items in dimensions.items():
            turn_times: dict[str, datetime] = {}
            for item in all_items:
                turn_id = str(item.source_turn_id)
                turn_times[turn_id] = max(turn_times.get(turn_id, item.observed_at), item.observed_at)
            recent_turns = set(sorted(turn_times, key=lambda turn: (turn_times[turn], turn), reverse=True)
                               [:self.recent_turn_window])
            recent_items = [item for item in all_items if item.source_turn_id in recent_turns]
            alternatives: list[tuple[float, ProfileHypothesis]] = []
            for value in sorted({item.value for item in recent_items}):
                items = [item for item in recent_items if item.value == value]
                support_items = sorted((item for item in items if item.polarity == "support"),
                                       key=lambda item: item.observed_at, reverse=True)
                counter_items = [item for item in items if item.polarity == "counter"]
                support_weight = sum(self._decayed_weight(item, current_at) for item in support_items)
                counter_weight = sum(self._decayed_weight(item, current_at) for item in counter_items)
                net_weight = support_weight - counter_weight
                if len(support_items) < self.min_evidence_count or net_weight < self.min_support_weight:
                    continue
                hypothesis = ProfileHypothesis(
                    dimension=dimension, value=value,
                    confidence=min(0.93, 0.45 + net_weight / 2.4),
                    evidence_count=len(support_items), support_weight=support_weight,
                    counter_weight=counter_weight, evidence_ids=[item.id for item in support_items],
                    counter_evidence_ids=[item.id for item in counter_items],
                    rationale=self._rationale(dimension=dimension, value=value,
                                              support_items=support_items, counter_items=counter_items),
                    supporting_quotes=[item.quote for item in support_items[:5]],
                    source_turn_ids=sorted({str(item.source_turn_id) for item in support_items}),
                    source_memory_ids=sorted({item.source_memory_id for item in support_items + counter_items}, key=str),
                    source_user_id=user_id, autonomous_qualified=True,
                )
                alternatives.append((net_weight, hypothesis))
            alternatives.sort(key=lambda entry: entry[0], reverse=True)
            if alternatives and (len(alternatives) == 1 or alternatives[0][0] - alternatives[1][0] >= 0.15):
                hypotheses.append(alternatives[0][1])
        return sorted(hypotheses, key=lambda item: item.confidence, reverse=True)

    def _rationale(
        self,
        *,
        dimension: str,
        value: str,
        support_items: list[ProfileEvidence],
        counter_items: list[ProfileEvidence],
    ) -> str:
        source_keys = sorted({item.source_key for item in support_items})
        source_summary = ", ".join(source_keys[:3]) if source_keys else "profile evidence"
        counter_summary = (
            f" with {len(counter_items)} counter-signal(s) reducing confidence"
            if counter_items
            else ""
        )
        return (
            f"{dimension}={value} inferred from repeated {source_summary} signals "
            f"across {len(support_items)} supporting evidence item(s){counter_summary}"
        )

    def _decayed_weight(
        self,
        item: ProfileEvidence,
        current_at: datetime | None,
    ) -> float:
        if current_at is None:
            decay = 1.0
        else:
            age_days = max((current_at - item.observed_at).total_seconds() / 86400, 0)
            decay = 0.5 ** (age_days / self.half_life_days)
        return item.weight * item.confidence * decay


def has_autonomous_profile_qualification(record: MemoryRecord) -> bool:
    """Read a server-issued marker; write authorization must use trusted context.

    The HTTP entry point must also re-evaluate live source evidence on reads.
    A metadata marker supplied with an external proposal is never write authority.
    """
    qualification = record.metadata.get("profile_qualification")
    return (
        isinstance(qualification, dict)
        and qualification.get("policy_version") == PROFILE_POLICY_VERSION
        and qualification.get("method") == "scoped_turn_evidence"
        and isinstance(qualification.get("distinct_turn_count"), int)
        and qualification["distinct_turn_count"] >= 2
        and len(set(record.source_turn_ids)) >= 2
        and bool(record.metadata.get("source_memory_ids"))
    )


def is_user_corrected_profile(record: MemoryRecord) -> bool:
    """Recognize a persisted explicit correction, independently of old inference.

    New proposals must have correction markers removed at the write boundary;
    only the repository correction path issues this marker and lineage.
    """
    return (
        record.layer == MemoryLayer.INFERRED_PROFILE
        and record.authority == Authority.USER_EXPLICIT
        and record.metadata.get("correction") is True
        and record.metadata.get("correction_origin") == "user_memory_correction"
        and record.supersedes is not None
        and record.metadata.get("corrected_from") == str(record.supersedes)
    )
