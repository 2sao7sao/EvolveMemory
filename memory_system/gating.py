from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable

from .models import MemoryLayer, PromptVisibility, memory_item_layer
from .schema import MemoryItem, MemoryType, StateDynamics


class MemoryUseAction(str, Enum):
    USE_DIRECTLY = "use_directly"
    STYLE_ONLY = "style_only"
    FOLLOW_UP = "follow_up"
    CLARIFY = "clarify"
    HIDDEN_CONSTRAINT = "hidden_constraint"
    SUMMARIZE_ONLY = "summarize_only"
    SUPPRESS = "suppress"


@dataclass
class MemoryGateDecision:
    memory: MemoryItem
    layer: MemoryLayer
    action: MemoryUseAction
    score: float
    factors: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    prompt_visibility: PromptVisibility = PromptVisibility.VISIBLE
    safe_to_mention: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "memory": self.memory.to_dict(),
            "layer": self.layer.value,
            "action": self.action.value,
            "score": round(self.score, 3),
            "factors": {key: round(value, 3) for key, value in self.factors.items()},
            "rationale": self.rationale,
            "prompt_visibility": self.prompt_visibility.value,
            "safe_to_mention": self.safe_to_mention,
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
            "query_relevance": self._relevance(query, memory),
            "freshness": self._freshness(memory, now),
            "authority": self._authority(memory),
            "utility": self._utility(query, memory, layer),
            "privacy_safety": self._privacy(memory, query),
            "user_preference_alignment": self._preference_alignment(memory),
            "token_efficiency": self._token_efficiency(memory),
            "contradiction_safety": 1.0,
        }
        score = (
            0.22 * factors["query_relevance"]
            + 0.14 * factors["freshness"]
            + 0.14 * factors["authority"]
            + 0.16 * factors["utility"]
            + 0.14 * factors["privacy_safety"]
            + 0.08 * factors["user_preference_alignment"]
            + 0.06 * factors["token_efficiency"]
            + 0.06 * factors["contradiction_safety"]
        )
        action = self._action(memory, layer, score, factors)
        prompt_visibility, safe_to_mention = self._visibility(action, memory, factors)
        return MemoryGateDecision(
            memory=memory,
            layer=layer,
            action=action,
            score=score,
            factors=factors,
            rationale=self._rationale(memory, layer, action, factors),
            prompt_visibility=prompt_visibility,
            safe_to_mention=safe_to_mention,
        )

    def _layer(self, memory: MemoryItem) -> MemoryLayer:
        return memory_item_layer(memory)

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
        if memory.key == "current_emotional_state" and self._has_any(query, self.WORK_TERMS):
            return 0.62
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
        if layer == MemoryLayer.INFERRED_PROFILE:
            return 0.78
        if layer == MemoryLayer.EPISODIC_EVENT and self._event_needs_progress(memory):
            return 0.9 if self._has_any(query, self.WORK_TERMS + self.RELATION_TERMS) else 0.76
        if memory.key in {"work_status", "current_emotional_state", "current_bandwidth"}:
            return 0.86
        if "sensitive" in memory.tags:
            return 0.52
        return 0.66

    def _privacy(self, memory: MemoryItem, query: str) -> float:
        if "sensitive" not in memory.tags:
            return 1.0
        if memory.key == "current_emotional_state" and self._has_any(query, self.WORK_TERMS):
            return 0.65
        return 0.85 if self._relevance(query, memory) >= 0.8 else 0.28

    def _preference_alignment(self, memory: MemoryItem) -> float:
        if memory.memory_type in {MemoryType.PREFERENCE, MemoryType.PROFILE}:
            return 0.95
        return 0.7

    def _token_efficiency(self, memory: MemoryItem) -> float:
        text = f"{memory.key} {memory.value} {memory.evidence}"
        if len(text) <= 80:
            return 1.0
        if len(text) <= 180:
            return 0.72
        return 0.45

    def _action(
        self,
        memory: MemoryItem,
        layer: MemoryLayer,
        score: float,
        factors: dict[str, float],
    ) -> MemoryUseAction:
        relevance = factors["query_relevance"]
        privacy = factors["privacy_safety"]
        if memory.valid_to is not None and memory.valid_to <= memory.valid_from:
            return MemoryUseAction.SUPPRESS
        if privacy < 0.35 and relevance < 0.75:
            return MemoryUseAction.SUPPRESS
        if score < 0.48:
            return MemoryUseAction.SUPPRESS
        if layer == MemoryLayer.INFERRED_PROFILE:
            return MemoryUseAction.STYLE_ONLY
        if memory.memory_type == MemoryType.PREFERENCE:
            if memory.key in {"followup_preference", "decision_preference"}:
                return MemoryUseAction.HIDDEN_CONSTRAINT
            return MemoryUseAction.STYLE_ONLY
        if "sensitive" in memory.tags and relevance < 0.78:
            return MemoryUseAction.SUMMARIZE_ONLY
        if layer == MemoryLayer.EPISODIC_EVENT and self._event_needs_progress(memory):
            return MemoryUseAction.FOLLOW_UP
        return MemoryUseAction.USE_DIRECTLY

    def _visibility(
        self,
        action: MemoryUseAction,
        memory: MemoryItem,
        factors: dict[str, float],
    ) -> tuple[PromptVisibility, bool]:
        if action == MemoryUseAction.SUPPRESS:
            return PromptVisibility.BLOCKED, False
        if action == MemoryUseAction.HIDDEN_CONSTRAINT:
            return PromptVisibility.HIDDEN, False
        if action in {MemoryUseAction.STYLE_ONLY, MemoryUseAction.SUMMARIZE_ONLY}:
            return PromptVisibility.POLICY_ONLY, False
        if "sensitive" in memory.tags and factors["query_relevance"] < 0.86:
            return PromptVisibility.POLICY_ONLY, False
        return PromptVisibility.VISIBLE, True

    def _rationale(
        self,
        memory: MemoryItem,
        layer: MemoryLayer,
        action: MemoryUseAction,
        factors: dict[str, float],
    ) -> list[str]:
        rationale = [f"{layer.value} selected as {action.value}"]
        if factors["query_relevance"] >= 0.8:
            rationale.append("high query relevance")
        if factors["freshness"] >= 0.8:
            rationale.append("fresh enough for current context")
        if layer == MemoryLayer.EPISODIC_EVENT and self._event_needs_progress(memory):
            rationale.append("event is likely still evolving and may need progress follow-up")
        if factors["privacy_safety"] < 0.5:
            rationale.append("sensitive memory requires stronger relevance before use")
        return rationale

    def _event_needs_progress(self, memory: MemoryItem) -> bool:
        return memory.memory_type == MemoryType.EVENT and str(memory.value) in self.EVENT_PROGRESS_VALUES

    def _has_any(self, text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)
