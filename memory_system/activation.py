from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import log

from .math_core import ScoreBreakdown, clamp, logistic
from .schema import MemoryItem, MemoryType, StateDynamics


class MemoryLifecycle(str, Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    VOLATILE_STATE = "volatile_state"
    EPISODIC_EVENT = "episodic_event"
    INFERRED_PROFILE = "inferred_profile"
    PROCEDURAL = "procedural"


@dataclass(frozen=True)
class LifecycleConfig:
    base_log_prior: float
    decay_per_day: float
    reinforcement_weight: float = 0.16
    anomaly_weight: float = 0.24
    fatigue_weight: float = 0.18


@dataclass(frozen=True)
class StateTemporalAnomaly:
    category: str
    expected_ttl_days: tuple[int, int]
    recurrence_count: int
    first_seen: datetime
    last_seen: datetime
    duration_ratio: float
    recurrence_factor: float
    severity_prior: float
    score: float
    phase: str

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "expected_ttl_days": list(self.expected_ttl_days),
            "recurrence_count": self.recurrence_count,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "duration_ratio": round(self.duration_ratio, 4),
            "recurrence_factor": round(self.recurrence_factor, 4),
            "severity_prior": round(self.severity_prior, 4),
            "score": round(self.score, 4),
            "phase": self.phase,
        }


class StateTemporalAnomalyDetector:
    """Scores whether a state has outlived its normal lifecycle."""

    TTL_BY_KEY: dict[str, tuple[int, int]] = {
        "current_emotional_state": (3, 21),
        "current_bandwidth": (1, 14),
        "work_status": (30, 180),
        "relationship_status": (30, 365),
        "life_event": (14, 90),
        "interest_short_term": (14, 60),
    }
    TTL_BY_VALUE: dict[str, tuple[int, int]] = {
        "lost_job": (30, 180),
        "between_jobs": (30, 180),
        "prepare_interview": (7, 45),
        "prepare_exam": (30, 365),
        "breakup": (30, 180),
        "anxious": (3, 21),
        "stressed": (3, 21),
        "busy": (1, 14),
    }
    SEVERITY_BY_KEY: dict[str, float] = {
        "current_emotional_state": 0.72,
        "work_status": 0.62,
        "life_event": 0.58,
        "relationship_status": 0.52,
        "current_bandwidth": 0.42,
    }

    def score(
        self,
        memory: MemoryItem,
        *,
        now: datetime,
        recurrence_count: int = 1,
        first_seen: datetime | None = None,
        last_seen: datetime | None = None,
    ) -> StateTemporalAnomaly:
        first_seen = first_seen or memory.valid_from
        last_seen = last_seen or memory.last_updated or memory.valid_from
        ttl = self._expected_ttl(memory)
        age_days = max((now - first_seen).total_seconds() / 86400, 0.0)
        duration_ratio = age_days / max(ttl[1], 1)
        recurrence_factor = log(1 + max(recurrence_count - 1, 0))
        severity_prior = self.SEVERITY_BY_KEY.get(memory.key, 0.35)
        raw_score = (
            0.5 * duration_ratio
            + 0.3 * recurrence_factor
            + 0.2 * severity_prior
        )
        phase = self._phase(raw_score, duration_ratio)
        return StateTemporalAnomaly(
            category=memory.key,
            expected_ttl_days=ttl,
            recurrence_count=recurrence_count,
            first_seen=first_seen,
            last_seen=last_seen,
            duration_ratio=duration_ratio,
            recurrence_factor=recurrence_factor,
            severity_prior=severity_prior,
            score=raw_score,
            phase=phase,
        )

    def _expected_ttl(self, memory: MemoryItem) -> tuple[int, int]:
        return self.TTL_BY_VALUE.get(str(memory.value), self.TTL_BY_KEY.get(memory.key, (30, 365)))

    def _phase(self, anomaly_score: float, duration_ratio: float) -> str:
        if anomaly_score >= 1.5:
            return "escalated"
        if anomaly_score >= 1.0:
            return "anomalous"
        if duration_ratio >= 1.0:
            return "extended"
        return "active"


class ActivationEngine:
    CONFIG_BY_LIFECYCLE: dict[MemoryLifecycle, LifecycleConfig] = {
        MemoryLifecycle.SHORT_TERM: LifecycleConfig(base_log_prior=0.28, decay_per_day=0.055),
        MemoryLifecycle.LONG_TERM: LifecycleConfig(base_log_prior=0.12, decay_per_day=0.006),
        MemoryLifecycle.VOLATILE_STATE: LifecycleConfig(base_log_prior=0.18, decay_per_day=0.075),
        MemoryLifecycle.EPISODIC_EVENT: LifecycleConfig(base_log_prior=0.22, decay_per_day=0.028),
        MemoryLifecycle.INFERRED_PROFILE: LifecycleConfig(base_log_prior=0.02, decay_per_day=0.012),
        MemoryLifecycle.PROCEDURAL: LifecycleConfig(base_log_prior=0.16, decay_per_day=0.004),
    }

    def __init__(
        self,
        anomaly_detector: StateTemporalAnomalyDetector | None = None,
    ) -> None:
        self.anomaly_detector = anomaly_detector or StateTemporalAnomalyDetector()

    def score(
        self,
        memory: MemoryItem,
        *,
        now: datetime,
        recurrence_count: int = 1,
        fatigue: float = 0.0,
        anomaly_score: float | None = None,
    ) -> ScoreBreakdown:
        lifecycle = self.lifecycle_for(memory)
        config = self.CONFIG_BY_LIFECYCLE[lifecycle]
        age_days = max((now - (memory.last_updated or memory.valid_from)).total_seconds() / 86400, 0.0)
        anomaly = (
            self.anomaly_detector.score(memory, now=now, recurrence_count=recurrence_count).score
            if anomaly_score is None and self._can_have_anomaly(memory)
            else anomaly_score or 0.0
        )
        log_activation = (
            config.base_log_prior
            + log(max(memory.confidence, 0.001))
            - config.decay_per_day * age_days
            + config.reinforcement_weight * log(1 + max(recurrence_count, 0))
            + config.anomaly_weight * anomaly
            - config.fatigue_weight * max(fatigue, 0.0)
        )
        activation = logistic(log_activation)
        factors = {
            "confidence": memory.confidence,
            "age_days": age_days,
            "recurrence": float(recurrence_count),
            "anomaly": anomaly,
            "fatigue": fatigue,
            "log_activation": log_activation,
        }
        return ScoreBreakdown(
            name="activation",
            score=clamp(activation),
            probability=clamp(activation),
            factors=factors,
            formula="log A_i(t)=alpha_l+log(c_i)-lambda_l*dt+rho*log(1+n_i)+omega*z_anom-eta*f_i",
            rationale=[
                f"lifecycle={lifecycle.value}",
                "anomaly boosts persistent or recurring volatile states" if anomaly > 0 else "no anomaly boost",
            ],
            version="activation-v1.0",
        )

    def lifecycle_for(self, memory: MemoryItem) -> MemoryLifecycle:
        if "procedural" in memory.tags:
            return MemoryLifecycle.PROCEDURAL
        if memory.memory_type == MemoryType.EVENT:
            return MemoryLifecycle.EPISODIC_EVENT
        if memory.memory_type == MemoryType.PROFILE:
            return MemoryLifecycle.INFERRED_PROFILE
        if memory.memory_type == MemoryType.PREFERENCE:
            return MemoryLifecycle.LONG_TERM
        if memory.dynamics == StateDynamics.FLUID:
            return MemoryLifecycle.VOLATILE_STATE
        if memory.dynamics in {StateDynamics.STATIC, StateDynamics.SEMI_STATIC}:
            return MemoryLifecycle.LONG_TERM
        return MemoryLifecycle.SHORT_TERM

    def _can_have_anomaly(self, memory: MemoryItem) -> bool:
        return memory.memory_type in {MemoryType.EVENT, MemoryType.STATE} or memory.dynamics == StateDynamics.FLUID
