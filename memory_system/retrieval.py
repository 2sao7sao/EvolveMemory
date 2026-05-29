from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from math import sqrt
import re
from typing import Protocol

from .activation import ActivationEngine
from .causal import CausalRelevanceScorer
from .gravity import SemanticGravityEngine
from .math_core import ScoreBreakdown, clamp, weighted_sum
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
    LEARNING_CUES = ("学习", "解释", "例子", "原理", "教程", "练习", "怎么理解")
    PROJECT_CUES = ("项目", "需求", "架构", "PR", "review", "上线", "发布", "实现")
    DECISION_CUES = ("怎么选", "帮我决定", "推荐", "取舍", "风险", "方案")
    CODE_REVIEW_CUES = ("代码", "bug", "测试", "重构", "实现", "review")

    def classify(self, query: str) -> QueryIntent:
        scored = [
            ("memory_management", self._matches(query, self.MEMORY_CUES)),
            ("career_advice", self._matches(query, self.CAREER_CUES)),
            ("relationship", self._matches(query, self.RELATIONSHIP_CUES)),
            ("emotional_support", self._matches(query, self.EMOTION_CUES)),
            ("project_work", self._matches(query, self.PROJECT_CUES)),
            ("learning", self._matches(query, self.LEARNING_CUES)),
            ("decision_support", self._matches(query, self.DECISION_CUES)),
            ("code_review", self._matches(query, self.CODE_REVIEW_CUES)),
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
        modes = [
            "normalized_sqlite",
            "hybrid",
            "keyword",
            "embedding",
            "temporal",
            "activation",
            "causal",
            "semantic_gravity",
            "recent",
        ]
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
        elif intent.name == "learning":
            include_layers = [
                MemoryLayer.PREFERENCE,
                MemoryLayer.INFERRED_PROFILE,
                MemoryLayer.PROCEDURAL_MEMORY,
            ]
            reasons.append("learning queries benefit from mental-model and procedural style policy")
        elif intent.name == "project_work":
            include_layers = [
                MemoryLayer.EPISODIC_EVENT,
                MemoryLayer.SEMANTIC_FACT,
                MemoryLayer.PREFERENCE,
                MemoryLayer.INFERRED_PROFILE,
                MemoryLayer.PROCEDURAL_MEMORY,
            ]
            modes.append("event_state")
            reasons.append("project queries need event progress, workflow preferences, and policy guidance")
        elif intent.name == "decision_support":
            include_layers = [MemoryLayer.PREFERENCE, MemoryLayer.INFERRED_PROFILE]
            reasons.append("decision queries need recommendation and uncertainty-tolerance policy")
        elif intent.name == "code_review":
            include_layers = [
                MemoryLayer.PREFERENCE,
                MemoryLayer.INFERRED_PROFILE,
                MemoryLayer.PROCEDURAL_MEMORY,
            ]
            reasons.append("code-review queries should retrieve collaboration and critique policy")
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
        return tokenize_text(text)


@dataclass(frozen=True)
class HybridRetrievalScore:
    memory: MemoryItem
    score: float
    factors: dict[str, float]
    breakdown: ScoreBreakdown | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "memory": self.memory.to_dict(),
            "score": round(self.score, 3),
            "factors": {key: round(value, 3) for key, value in self.factors.items()},
        }
        if self.breakdown is not None:
            payload["breakdown"] = self.breakdown.to_dict()
        return payload


class HybridMemoryScorer:
    RETRIEVAL_V2_WEIGHTS = {
        "keyword": 0.34,
        "embedding": 0.30,
        "freshness": 0.18,
        "layer_prior": 0.18,
    }
    RETRIEVAL_V3_WEIGHTS = {
        "keyword": 0.22,
        "embedding": 0.22,
        "freshness": 0.14,
        "layer_prior": 0.14,
        "activation": 0.14,
        "causal_relevance": 0.08,
        "semantic_gravity": 0.06,
    }

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        *,
        use_math_runtime: bool = True,
        activation_engine: ActivationEngine | None = None,
        causal_scorer: CausalRelevanceScorer | None = None,
        semantic_gravity_engine: SemanticGravityEngine | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider or DeterministicHashEmbeddingProvider()
        self.use_math_runtime = use_math_runtime
        self.activation_engine = activation_engine or ActivationEngine()
        self.causal_scorer = causal_scorer or CausalRelevanceScorer()
        self.semantic_gravity_engine = semantic_gravity_engine or SemanticGravityEngine()

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
        weights = self.RETRIEVAL_V2_WEIGHTS
        formula = "S_ret-v2=0.34K+0.30E+0.18F+0.18L"
        version = "retrieval-v2.0"
        rationale = ["hybrid keyword, embedding, freshness, and layer prior"]
        if self.use_math_runtime:
            activation = self.activation_engine.score(memory, now=now)
            causal = self.causal_scorer.score(query, memory)
            semantic_gravity = self.semantic_gravity_engine.score(memory, query=query)
            factors.update(
                {
                    "activation": activation.score,
                    "causal_relevance": causal.score,
                    "semantic_gravity": semantic_gravity.score,
                }
            )
            weights = self.RETRIEVAL_V3_WEIGHTS
            formula = "S_ret-v3=0.22K+0.22E+0.14F+0.14L+0.14A+0.08C+0.06G"
            version = "retrieval-v3.0"
            rationale = [
                "retrieval uses lexical and embedding match without treating retrieval as permission",
                *activation.rationale,
                *causal.rationale,
                *semantic_gravity.rationale,
            ]
        score = clamp(weighted_sum(factors, weights))
        breakdown = ScoreBreakdown(
            name="retrieval",
            score=score,
            probability=score,
            factors=factors,
            weights=weights,
            formula=formula,
            rationale=rationale,
            version=version,
        )
        return HybridRetrievalScore(
            memory=memory,
            score=score,
            factors=factors,
            breakdown=breakdown,
        )

    def _keyword_overlap(self, query: str, text: str) -> float:
        query_tokens = set(tokenize_text(query))
        text_tokens = set(tokenize_text(text))
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


def tokenize_text(text: str) -> list[str]:
    normalized = text.lower().replace("，", " ").replace("。", " ")
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized)
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            for size in (2, 3, 4):
                if len(token) < size:
                    continue
                expanded.extend(token[index : index + size] for index in range(len(token) - size + 1))
    return [token for token in expanded if token]
