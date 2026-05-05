from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from math import sqrt
from typing import Protocol

from .models import MemoryLayer
from .schema import MemoryItem


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


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, text: str) -> list[float]:
        ...


class DeterministicHashEmbeddingProvider:
    """Small deterministic embedding stub for tests and offline demos.

    It is not a semantic embedding model. It keeps the hybrid retrieval boundary
    executable without adding network calls or model dependencies.
    """

    name = "deterministic_hash_embedding"

    def __init__(self, dimensions: int = 32) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0 for _ in range(self.dimensions)]
        for token in self._tokens(text):
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimensions
            vector[index] += 1.0
        norm = sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _tokens(self, text: str) -> list[str]:
        return [token for token in text.lower().replace("，", " ").replace("。", " ").split() if token]


@dataclass(frozen=True)
class HybridRetrievalScore:
    memory: MemoryItem
    score: float
    factors: dict[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "memory": self.memory.to_dict(),
            "score": round(self.score, 3),
            "factors": {key: round(value, 3) for key, value in self.factors.items()},
        }


class HybridMemoryScorer:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider or DeterministicHashEmbeddingProvider()

    def score(
        self,
        query: str,
        memories: list[MemoryItem],
        *,
        now: datetime,
        plan: RetrievalPlan,
    ) -> list[HybridRetrievalScore]:
        query_embedding = self.embedding_provider.embed(query)
        scores = [
            self._score_memory(query, query_embedding, memory, now=now, plan=plan)
            for memory in memories
        ]
        return sorted(scores, key=lambda item: item.score, reverse=True)

    def _score_memory(
        self,
        query: str,
        query_embedding: list[float],
        memory: MemoryItem,
        *,
        now: datetime,
        plan: RetrievalPlan,
    ) -> HybridRetrievalScore:
        text = f"{memory.key} {memory.value} {memory.evidence}"
        factors = {
            "keyword": self._keyword_overlap(query, text),
            "embedding": self._cosine(query_embedding, self.embedding_provider.embed(text)),
            "freshness": self._freshness(memory, now),
            "layer_prior": self._layer_prior(memory, plan),
        }
        score = (
            0.34 * factors["keyword"]
            + 0.30 * factors["embedding"]
            + 0.18 * factors["freshness"]
            + 0.18 * factors["layer_prior"]
        )
        return HybridRetrievalScore(memory=memory, score=score, factors=factors)

    def _keyword_overlap(self, query: str, text: str) -> float:
        query_tokens = set(query.lower().replace("，", " ").replace("。", " ").split())
        text_tokens = set(text.lower().replace("，", " ").replace("。", " ").split())
        if not query_tokens or not text_tokens:
            return 0.0
        return len(query_tokens & text_tokens) / len(query_tokens)

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))

    def _freshness(self, memory: MemoryItem, now: datetime) -> float:
        age_days = max((now - memory.valid_from).days, 0)
        return max(0.2, 1.0 - age_days / 365)

    def _layer_prior(self, memory: MemoryItem, plan: RetrievalPlan) -> float:
        if not plan.include_layers:
            return 0.72
        layer = self._layer(memory)
        return 0.95 if layer in plan.include_layers else 0.25

    def _layer(self, memory: MemoryItem) -> MemoryLayer:
        if memory.memory_type.value == "event":
            return MemoryLayer.EPISODIC_EVENT
        if memory.memory_type.value == "preference":
            return MemoryLayer.PREFERENCE
        if memory.memory_type.value == "profile":
            return MemoryLayer.INFERRED_PROFILE
        return MemoryLayer.SEMANTIC_FACT
