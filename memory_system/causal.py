from __future__ import annotations

from .math_core import ScoreBreakdown, clamp
from .schema import MemoryItem, MemoryType


class CausalRelevanceScorer:
    """Detects high-impact memories that lexical retrieval can under-rank."""

    ALCOHOL_TERMS = ("喝酒", "饮酒", "酒精", "啤酒", "红酒", "聚会")
    MEDICAL_RISK_TERMS = ("过敏", "头孢", "药", "药物", "禁忌", "alcohol", "allergy")
    CAREER_TERMS = ("面试", "求职", "找工作", "简历", "offer", "失业", "职业")
    EXAM_TERMS = ("考试", "考研", "高考", "备考", "复习")
    RELATIONSHIP_TERMS = ("恋爱", "分手", "结婚", "对象", "关系")
    STYLE_TERMS = ("怎么回答", "解释", "说法", "风格", "详细", "简洁")

    def score(self, query: str, memory: MemoryItem) -> ScoreBreakdown:
        haystack = f"{memory.key} {memory.value} {memory.evidence}".lower()
        query_lower = query.lower()
        score = 0.12
        rationale = ["default weak causal relevance"]

        if self._has_any(query_lower, self.ALCOHOL_TERMS) and self._has_any(
            haystack,
            self.MEDICAL_RISK_TERMS,
        ):
            score = 1.0
            rationale = ["health or medication constraint can change the safe answer"]
        elif self._has_any(query_lower, self.CAREER_TERMS) and (
            memory.key in {"work_status", "profession", "life_event", "project_event"}
            or str(memory.value) in {"prepare_interview", "job_seeking", "lost_job", "between_jobs"}
        ):
            score = 0.9
            rationale = ["career query depends on current work or event state"]
        elif self._has_any(query_lower, self.EXAM_TERMS) and (
            str(memory.value) == "prepare_exam" or "exam" in haystack or "高考" in haystack
        ):
            score = 0.86
            rationale = ["exam-related memory anchors planning and timing"]
        elif self._has_any(query_lower, self.RELATIONSHIP_TERMS) and (
            memory.key == "relationship_status" or str(memory.value) == "breakup"
        ):
            score = 0.78
            rationale = ["relationship query depends on relationship state"]
        elif self._has_any(query_lower, self.STYLE_TERMS) and memory.memory_type in {
            MemoryType.PREFERENCE,
            MemoryType.PROFILE,
        }:
            score = 0.72
            rationale = ["style query depends on preference or profile memory"]

        return ScoreBreakdown(
            name="causal_relevance",
            score=clamp(score),
            probability=clamp(score),
            factors={"causal_relevance": score},
            formula="C(m,q)=rule_risk_or_dependency(m,q)",
            rationale=rationale,
            version="causal-v1.0",
        )

    def _has_any(self, text: str, terms: tuple[str, ...]) -> bool:
        return any(term.lower() in text for term in terms)
