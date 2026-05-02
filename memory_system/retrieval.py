from __future__ import annotations

from dataclasses import dataclass, field

from .models import MemoryLayer


@dataclass(frozen=True)
class QueryIntent:
    name: str
    confidence: float
    cues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "confidence": round(self.confidence, 3),
            "cues": list(self.cues),
        }


@dataclass(frozen=True)
class RetrievalPlan:
    intent: QueryIntent
    retrieval_modes: list[str]
    candidate_limit: int
    include_layers: list[MemoryLayer] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent.to_dict(),
            "retrieval_modes": list(self.retrieval_modes),
            "candidate_limit": self.candidate_limit,
            "include_layers": [layer.value for layer in self.include_layers],
            "reasons": list(self.reasons),
        }


class QueryIntentClassifier:
    CAREER_CUES = ("面试", "求职", "简历", "offer", "工作", "职业", "跳槽")
    RELATIONSHIP_CUES = ("恋爱", "分手", "关系", "伴侣", "结婚", "单身")
    EMOTION_CUES = ("焦虑", "压力", "难受", "情绪", "迷茫", "崩溃")
    STYLE_CUES = ("怎么回答", "说法", "风格", "简洁", "详细", "直接", "沟通")
    MEMORY_CUES = ("记得", "记住", "忘掉", "删除记忆", "别记", "你知道我")

    def classify(self, query: str) -> QueryIntent:
        scored = [
            ("memory_management", self._matches(query, self.MEMORY_CUES)),
            ("career_advice", self._matches(query, self.CAREER_CUES)),
            ("relationship", self._matches(query, self.RELATIONSHIP_CUES)),
            ("emotional_support", self._matches(query, self.EMOTION_CUES)),
            ("style_preference", self._matches(query, self.STYLE_CUES)),
        ]
        scored.sort(key=lambda item: len(item[1]), reverse=True)
        name, cues = scored[0]
        if not cues:
            return QueryIntent(name="general", confidence=0.45, cues=[])
        confidence = min(0.95, 0.58 + 0.12 * len(cues))
        return QueryIntent(name=name, confidence=confidence, cues=cues)

    def _matches(self, query: str, cues: tuple[str, ...]) -> list[str]:
        return [cue for cue in cues if cue in query]


class RetrievalPlanner:
    def plan(self, query: str, *, max_prompt_memories: int) -> RetrievalPlan:
        intent = QueryIntentClassifier().classify(query)
        modes = ["normalized_sqlite", "keyword", "temporal", "recent"]
        include_layers: list[MemoryLayer] = []
        reasons = [f"intent={intent.name}"]
        if intent.name == "career_advice":
            include_layers = [
                MemoryLayer.EPISODIC_EVENT,
                MemoryLayer.SEMANTIC_FACT,
                MemoryLayer.PREFERENCE,
                MemoryLayer.INFERRED_PROFILE,
            ]
            modes.append("event_state")
            reasons.append("career queries need event progress and work state")
        elif intent.name == "relationship":
            include_layers = [MemoryLayer.SEMANTIC_FACT, MemoryLayer.PREFERENCE]
            reasons.append("relationship queries use stricter direct fact retrieval")
        elif intent.name == "emotional_support":
            include_layers = [
                MemoryLayer.SEMANTIC_FACT,
                MemoryLayer.PREFERENCE,
                MemoryLayer.INFERRED_PROFILE,
            ]
            reasons.append("emotional queries emphasize current state and style policy")
        elif intent.name == "style_preference":
            include_layers = [MemoryLayer.PREFERENCE, MemoryLayer.INFERRED_PROFILE]
            reasons.append("style queries should avoid unrelated personal facts")
        elif intent.name == "memory_management":
            include_layers = []
            reasons.append("memory-management queries need broad inspection")
        return RetrievalPlan(
            intent=intent,
            retrieval_modes=modes,
            candidate_limit=max(max_prompt_memories * 2, 12),
            include_layers=include_layers,
            reasons=reasons,
        )
