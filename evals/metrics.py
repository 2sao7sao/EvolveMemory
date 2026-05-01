from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AccuracyMetric:
    correct: int = 0
    total: int = 0

    def add(self, expected: object, actual: object) -> None:
        self.total += 1
        if expected == actual:
            self.correct += 1

    @property
    def value(self) -> float:
        if self.total == 0:
            return 0.0
        return self.correct / self.total

    def to_dict(self) -> dict[str, float | int]:
        return {
            "correct": self.correct,
            "total": self.total,
            "accuracy": round(self.value, 4),
        }
