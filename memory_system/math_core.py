from __future__ import annotations

from dataclasses import dataclass, field
from math import exp
from typing import Mapping


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def logistic(value: float) -> float:
    if value >= 0:
        z = exp(-value)
        return 1 / (1 + z)
    z = exp(value)
    return z / (1 + z)


def weighted_sum(
    factors: Mapping[str, float],
    weights: Mapping[str, float],
    *,
    default: float = 0.0,
) -> float:
    return sum(weights[key] * factors.get(key, default) for key in weights)


@dataclass(frozen=True)
class ScoreBreakdown:
    name: str
    score: float
    factors: dict[str, float]
    weights: dict[str, float] = field(default_factory=dict)
    probability: float | None = None
    utility: float | None = None
    threshold: float | None = None
    formula: str = ""
    rationale: list[str] = field(default_factory=list)
    version: str = "math-v1.0"

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "score": round(self.score, 4),
            "factors": {key: round(value, 4) for key, value in self.factors.items()},
            "weights": {key: round(value, 4) for key, value in self.weights.items()},
            "formula": self.formula,
            "rationale": list(self.rationale),
            "version": self.version,
        }
        if self.probability is not None:
            payload["probability"] = round(self.probability, 4)
        if self.utility is not None:
            payload["utility"] = round(self.utility, 4)
        if self.threshold is not None:
            payload["threshold"] = round(self.threshold, 4)
        return payload
