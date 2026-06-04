"""Staleness and lifecycle engine for memory decay, fatigue, and retirement."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any


class LifecycleStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REINFORCED = "reinforced"
    FATIGUED = "fatigued"
    STALE = "stale"
    NEEDS_CLARIFICATION = "needs_clarification"
    RETIRED = "retired"
    DELETED = "deleted"


LIFECYCLE_DIRECT_ALLOWED = {LifecycleStatus.ACTIVE, LifecycleStatus.REINFORCED}
LIFECYCLE_STYLE_ALLOWED = {
    LifecycleStatus.ACTIVE,
    LifecycleStatus.REINFORCED,
    LifecycleStatus.FATIGUED,
    LifecycleStatus.STALE,
}
LIFECYCLE_CLARIFY_ALLOWED = {
    LifecycleStatus.FATIGUED,
    LifecycleStatus.STALE,
    LifecycleStatus.NEEDS_CLARIFICATION,
}


class StalenessEngine:
    """Compute lifecycle status and stale score for a memory record."""

    def __init__(
        self,
        *,
        stale_threshold_days: int = 90,
        fatigue_threshold: int = 5,
    ) -> None:
        self.stale_threshold_days = stale_threshold_days
        self.fatigue_threshold = fatigue_threshold

    def compute_stale_score(
        self,
        *,
        age_days: int,
        layer: str,
        last_used_days_ago: int | None = None,
        recurrence_count: int = 0,
        correction_count: int = 0,
        reinforcement_recent: bool = False,
        valid_to: datetime | None = None,
        now: datetime | None = None,
    ) -> float:
        if valid_to and now and valid_to < now:
            return 1.0

        base = age_days / max(self.stale_threshold_days, 1)

        if layer in ("preference", "procedural_memory"):
            base *= 0.4
        elif layer == "episodic_event":
            base *= 1.2

        if reinforcement_recent:
            base *= 0.3

        if last_used_days_ago is not None:
            base += (last_used_days_ago / 180) * 0.3

        if correction_count > 0:
            base += 0.15 * correction_count

        base -= 0.05 * min(recurrence_count, 5)

        return max(0.0, min(1.0, base))

    def lifecycle_status(
        self,
        *,
        stale_score: float,
        recurrence_count: int = 0,
        use_count: int = 0,
        correction_count: int = 0,
        followup_count: int = 0,
    ) -> LifecycleStatus:
        if stale_score >= 0.85:
            return LifecycleStatus.STALE
        if stale_score >= 0.6:
            return LifecycleStatus.NEEDS_CLARIFICATION
        if followup_count >= self.fatigue_threshold:
            return LifecycleStatus.FATIGUED
        if recurrence_count >= 3 and stale_score < 0.3:
            return LifecycleStatus.REINFORCED
        return LifecycleStatus.ACTIVE

    def allowed_use(self, status: LifecycleStatus) -> dict[str, bool]:
        return {
            "direct": status in LIFECYCLE_DIRECT_ALLOWED,
            "style_only": status in LIFECYCLE_STYLE_ALLOWED,
            "follow_up": status in LIFECYCLE_DIRECT_ALLOWED,
            "clarify": status in LIFECYCLE_CLARIFY_ALLOWED,
            "suppress": status in (LifecycleStatus.RETIRED, LifecycleStatus.DELETED),
        }

    def should_retire(self, stale_score: float, age_days: int, retention_days: int) -> bool:
        if age_days > retention_days:
            return True
        return stale_score >= 0.95
