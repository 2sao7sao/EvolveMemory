from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RateMetric:
    numerator: int = 0
    denominator: int = 0

    def add(self, passed: bool) -> None:
        self.denominator += 1
        if passed:
            self.numerator += 1

    @property
    def value(self) -> float:
        if self.denominator == 0:
            return 0.0
        return self.numerator / self.denominator

    def to_dict(self, key: str = "rate") -> dict[str, float | int]:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            key: round(self.value, 4),
        }


@dataclass
class PrecisionRecallF1Metric:
    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0

    def add(self, *, expected: bool, actual: bool) -> None:
        if expected and actual:
            self.true_positive += 1
        elif actual:
            self.false_positive += 1
        elif expected:
            self.false_negative += 1

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 0.0

    @property
    def f1(self) -> float:
        denominator = self.precision + self.recall
        return 2 * self.precision * self.recall / denominator if denominator else 0.0

    def to_dict(self) -> dict[str, float | int]:
        return {
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


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
