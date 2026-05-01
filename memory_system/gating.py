from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable

from .schema import MemoryItem, MemoryType, StateDynamics


class MemoryLayer(str, Enum):
    FACT = "fact_memory"
    PROFILE = "inferred_profile"
    EVENT = "event_memory"


class MemoryUseAction(str, Enum):
    USE_DIRECTLY = "use_directly"
    STYLE_ONLY = "style_only"
    FOLLOW_UP = "follow_up"
    SUPPRESS = "suppress"


@dataclass
class MemoryGateDecision:
    memory: MemoryItem
    layer: MemoryLayer
    action: MemoryUseAction
    score: float
    factors: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "memory": self.memory.to_dict(),
            "layer": self.layer.value,
            "action": self.action.value,
            "score": round(self.score, 3),
            "factors": {key: round(value, 3) for key, value in self.factors.items()},
            "rationale": self.rationale,
        }


@dataclass
class MemoryGateResult:
    decisions: list[MemoryGateDecision]
    suppressed: list[MemoryGateDecision]

    @property
    def selected(self) -> list[MemoryItem]:
        return [decision.memory for decision in self.decisions]

    def to_dict(self) -> dict[str, object]:
        return {
            "selected": [decision.to_dict() for decision in self.decisions],
            "suppressed": [decision.to_dict() for decision in self.suppressed],
        }


class MemoryUseGate:
    """Decides how active memories may influence the current answer."""

    WORK_TERMS = ("工作", "求职", "找工作", "面试", "职业", "简历", "offer")
    RELATION_TERMS = ("恋爱", "分手", "伴侣", "关系", "结婚")
    EMOTION_TERMS = ("焦虑", "压力", "情绪", "难受", "迷茫")
    STYLE_TERMS = ("怎么回答", "说法", "沟通", "风格", "详细", "简洁", "直接")
    EVENT_PROGRESS_VALUES = {
        "prepare_interview",
        "prepare_exam",
        "job_seeking",
        "lost_job",
        "started_new_job",
        "breakup",
        "moved_home",
    }

    def select(
        self,
        query: str,
        memories: Iterable[MemoryItem],
        *,
        now: datetime,
        limit: int = 12,
    ) -> MemoryGateResult:
        selected: list[MemoryGateDecision] = []
        suppressed: list[MemoryGateDecision] = []
        for memory in memories:
            decision = self.evaluate(query, memory, now=now)
            if decision.action == MemoryUseAction.SUPPRESS:
                suppressed.append(decision)
            else:
                selected.append(decision)
        selected.sort(key=lambda item: item.score, reverse=True)
        suppressed.sort(key=lambda item: item.score, reverse=True)
        return MemoryGateResult(decisions=selected[:limit], suppressed=suppressed)

    def evaluate(self, query: str, memory: MemoryItem, *, now: datetime) -> MemoryGateDecision:
        layer = self._layer(memory)
        factors = {
            "relevance": self._relevance(query, memory),
            "freshness": self._freshness(memory, now),
            "authority": self._authority(memory),
            "utility": self._utility(query, memory, layer),
            "privacy": self._privacy(memory, query),
        }
        score = (
            0.32 * factors["relevance"]
            + 0.2 * factors["freshness"]
            + 0.18 * factors["authority"]
            + 0.22 * factors["utility"]
            + 0.08 * factors["privacy"]
        )
        action = self._action(memory, layer, score, factors)
        return MemoryGateDecision(
            memory=memory,
            layer=layer,
            action=action,
            score=score,
            factors=factors,
            rationale=self._rationale(memory, layer, action, factors),
        )

    def _layer(self, memory: MemoryItem) -> MemoryLayer:
        if memory.memory_type == MemoryType.EVENT:
            return MemoryLayer.EVENT
        if memory.memory_type == MemoryType.PROFILE:
            return MemoryLayer.PROFILE
        return MemoryLayer.FACT

    def _relevance(self, query: str, memory: MemoryItem) -> float:
        haystack = f"{memory.key} {memory.value} {memory.evidence}"
        if str(memory.value) in query or memory.evidence in query or memory.key in query:
            return 1.0
        if self._has_any(query, self.WORK_TERMS) and self._has_any(haystack, self.WORK_TERMS):
            return 0.9
        if self._has_any(query, self.RELATION_TERMS) and self._has_any(haystack, self.RELATION_TERMS):
            return 0.88
        if self._has_any(query, self.EMOTION_TERMS) and (
            "emotion" in memory.key or self._has_any(haystack, self.EMOTION_TERMS)
        ):
            return 0.86
        if self._has_any(query, self.STYLE_TERMS) and memory.memory_type in {
            MemoryType.PREFERENCE,
            MemoryType.PROFILE,
        }:
            return 0.82
        if memory.memory_type == MemoryType.PREFERENCE:
            return 0.72
        if memory.memory_type == MemoryType.PROFILE:
            return 0.62
        if memory.memory_type == MemoryType.EVENT and self._event_needs_progress(memory):
            return 0.68
        return 0.36

    def _freshness(self, memory: MemoryItem, now: datetime) -> float:
        age_days = max((now - memory.valid_from).days, 0)
        if memory.dynamics == StateDynamics.STATIC:
            return 0.92
        if memory.dynamics == StateDynamics.SEMI_STATIC:
            return max(0.42, 1.0 - age_days / 365)
        if memory.dynamics == StateDynamics.FLUID:
            return max(0.18, 1.0 - age_days / 60)
        if memory.memory_type == MemoryType.PROFILE:
            return max(0.5, 1.0 - age_days / 180)
        return max(0.35, 1.0 - age_days / 120)

    def _authority(self, memory: MemoryItem) -> float:
        base = memory.confidence
        if memory.confirmed_by_user:
            base += 0.12
        if memory.memory_type == MemoryType.PROFILE:
            base -= 0.12
        return min(max(base, 0.0), 1.0)

    def _utility(self, query: str, memory: MemoryItem, layer: MemoryLayer) -> float:
        if memory.memory_type == MemoryType.PREFERENCE:
            return 0.94
        if layer == MemoryLayer.PROFILE:
            return 0.78
        if layer == MemoryLayer.EVENT and self._event_needs_progress(memory):
            return 0.9 if self._has_any(query, self.WORK_TERMS + self.RELATION_TERMS) else 0.76
        if memory.key in {"work_status", "current_emotional_state", "current_bandwidth"}:
            return 0.86
        if "sensitive" in memory.tags:
            return 0.52
        return 0.66

    def _privacy(self, memory: MemoryItem, query: str) -> float:
        if "sensitive" not in memory.tags:
            return 1.0
        return 0.85 if self._relevance(query, memory) >= 0.8 else 0.28

    def _action(
        self,
        memory: MemoryItem,
        layer: MemoryLayer,
        score: float,
        factors: dict[str, float],
    ) -> MemoryUseAction:
        if factors["privacy"] < 0.35 and factors["relevance"] < 0.75:
            return MemoryUseAction.SUPPRESS
        if score < 0.48:
            return MemoryUseAction.SUPPRESS
        if layer == MemoryLayer.PROFILE or memory.memory_type == MemoryType.PREFERENCE:
            return MemoryUseAction.STYLE_ONLY
        if layer == MemoryLayer.EVENT and self._event_needs_progress(memory):
            return MemoryUseAction.FOLLOW_UP
        return MemoryUseAction.USE_DIRECTLY

    def _rationale(
        self,
        memory: MemoryItem,
        layer: MemoryLayer,
        action: MemoryUseAction,
        factors: dict[str, float],
    ) -> list[str]:
        rationale = [f"{layer.value} selected as {action.value}"]
        if factors["relevance"] >= 0.8:
            rationale.append("high query relevance")
        if factors["freshness"] >= 0.8:
            rationale.append("fresh enough for current context")
        if layer == MemoryLayer.EVENT and self._event_needs_progress(memory):
            rationale.append("event is likely still evolving and may need progress follow-up")
        if factors["privacy"] < 0.5:
            rationale.append("sensitive memory requires stronger relevance before use")
        return rationale

    def _event_needs_progress(self, memory: MemoryItem) -> bool:
        return memory.memory_type == MemoryType.EVENT and str(memory.value) in self.EVENT_PROGRESS_VALUES

    def _has_any(self, text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)
