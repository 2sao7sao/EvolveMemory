from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from evals.runner import run_gate_eval

from .service import SessionMemoryRuntime

DEMO_TURNS = [
    "我最近准备面试，有点焦虑。",
    "回答直接一点，先给结论。",
]

DEMO_QUERIES = {
    "interview_help": "面试怎么准备？",
    "coding_no_mention": "今天只帮我 review Python 代码，不用提面试。",
}


@dataclass(frozen=True)
class ProductMetric:
    key: str
    value: float
    numerator: int
    denominator: int
    explanation: str


@dataclass(frozen=True)
class AdaptiveMemoryDemoReport:
    active_memory_count: int
    accepted_candidate_count: int
    candidate_count: int
    gate_eval_correct: int
    gate_eval_total: int
    interview_actions: dict[str, str]
    coding_actions: dict[str, str]
    coding_suppressed: dict[str, str]
    prompt_contains_visible_memory: bool
    retired_keys: list[str]
    remaining_keys_after_correction: list[str]
    metrics: dict[str, ProductMetric]

    @property
    def passed(self) -> bool:
        return all(metric.value >= 1.0 for metric in self.metrics.values())


def run_product_demo() -> AdaptiveMemoryDemoReport:
    tz = ZoneInfo("Asia/Shanghai")
    timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=tz)
    runtime = SessionMemoryRuntime(session_id="demo-user")
    candidate_count = 0
    accepted_candidate_count = 0

    for index, turn in enumerate(DEMO_TURNS, start=1):
        result = runtime.ingest_turn(turn, source=f"turn_{index}", timestamp=timestamp)
        candidate_count += len(result["candidates"])
        accepted_candidate_count += len(result["accepted_memories"])

    active_before_correction = runtime.active_memories(timestamp)
    interview_query = runtime.query(DEMO_QUERIES["interview_help"], timestamp)
    coding_query = runtime.query(DEMO_QUERIES["coding_no_mention"], timestamp)
    prompt_context = runtime.prompt_context(DEMO_QUERIES["coding_no_mention"], timestamp)
    gate_eval = run_gate_eval()
    gate_metric = gate_eval["metrics"]["gate_action"]

    retired_keys = _retire_sensitive_correction(runtime, timestamp)
    remaining_keys = [item["key"] for item in runtime.active_memories(timestamp)]

    interview_actions = _selected_actions(interview_query)
    coding_actions = _selected_actions(coding_query)
    coding_suppressed = _suppressed_actions(coding_query)
    prompt_contains_visible_memory = bool(prompt_context["relevant_memory_lines"])
    metrics = _build_metrics(
        gate_eval_correct=int(gate_metric["correct"]),
        gate_eval_total=int(gate_metric["total"]),
        interview_actions=interview_actions,
        coding_actions=coding_actions,
        coding_suppressed=coding_suppressed,
        prompt_contains_visible_memory=prompt_contains_visible_memory,
        retired_keys=retired_keys,
        remaining_keys=remaining_keys,
    )

    return AdaptiveMemoryDemoReport(
        active_memory_count=len(active_before_correction),
        accepted_candidate_count=accepted_candidate_count,
        candidate_count=candidate_count,
        gate_eval_correct=int(gate_metric["correct"]),
        gate_eval_total=int(gate_metric["total"]),
        interview_actions=interview_actions,
        coding_actions=coding_actions,
        coding_suppressed=coding_suppressed,
        prompt_contains_visible_memory=prompt_contains_visible_memory,
        retired_keys=retired_keys,
        remaining_keys_after_correction=remaining_keys,
        metrics=metrics,
    )


def format_demo_report(report: AdaptiveMemoryDemoReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    lines = [
        "# EvolveMemory Adaptive Replay",
        "",
        f"status: {status}",
        f"active_memories_before_correction: {report.active_memory_count}",
        f"accepted_candidates: {report.accepted_candidate_count}/{report.candidate_count}",
        f"gate_eval: {report.gate_eval_correct}/{report.gate_eval_total}",
        "",
        "## 1. Interview query actions",
        _format_actions(report.interview_actions),
        "",
        "## 2. Coding query with explicit no-mention",
        _format_actions(report.coding_actions),
        "",
        "## 3. Suppressed memories",
        _format_actions(report.coding_suppressed),
        "",
        "## 4. Product metrics",
    ]
    for metric in report.metrics.values():
        lines.append(
            f"- {metric.key}: {metric.value:.2f} "
            f"({metric.numerator}/{metric.denominator}) - {metric.explanation}"
        )
    lines.extend(
        [
            "",
            "## 5. Correction result",
            f"- retired_keys: {', '.join(report.retired_keys) if report.retired_keys else 'none'}",
            "- remaining_after_correction: "
            + (", ".join(report.remaining_keys_after_correction) or "none"),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    report = run_product_demo()
    print(format_demo_report(report), end="")
    if not report.passed:
        raise SystemExit(1)


def _selected_actions(query_result: dict) -> dict[str, str]:
    return {
        item["memory"]["key"]: item["action"]
        for item in query_result["memory_gate"]["selected"]
    }


def _suppressed_actions(query_result: dict) -> dict[str, str]:
    return {
        item["memory"]["key"]: item["action"]
        for item in query_result["memory_gate"]["suppressed"]
    }


def _retire_sensitive_correction(
    runtime: SessionMemoryRuntime,
    timestamp: datetime,
) -> list[str]:
    keys = ["current_emotional_state", "emotional_support_need"]
    retired: list[str] = []
    for key in keys:
        result = runtime.retire_memory(
            key=key,
            timestamp=timestamp,
            reason="explicit user correction: do not remember anxiety",
        )
        if result["retired_memories"]:
            retired.append(key)
    return retired


def _build_metrics(
    *,
    gate_eval_correct: int,
    gate_eval_total: int,
    interview_actions: dict[str, str],
    coding_actions: dict[str, str],
    coding_suppressed: dict[str, str],
    prompt_contains_visible_memory: bool,
    retired_keys: list[str],
    remaining_keys: list[str],
) -> dict[str, ProductMetric]:
    style_expectations = [
        interview_actions.get("communication_style") == "style_only",
        interview_actions.get("response_opening") == "style_only",
        coding_actions.get("communication_style") == "style_only",
        coding_actions.get("response_opening") == "style_only",
    ]
    correction_targets = {"current_emotional_state", "emotional_support_need"}
    retired_targets = correction_targets & set(retired_keys)
    leaked_targets = correction_targets & set(remaining_keys)

    return {
        "gate_action_accuracy": ProductMetric(
            key="gate_action_accuracy",
            value=_ratio(gate_eval_correct, gate_eval_total),
            numerator=gate_eval_correct,
            denominator=gate_eval_total,
            explanation="expected memory-use actions matched by regression cases",
        ),
        "explicit_suppression_rate": ProductMetric(
            key="explicit_suppression_rate",
            value=float(coding_suppressed.get("life_event") == "suppress"),
            numerator=int(coding_suppressed.get("life_event") == "suppress"),
            denominator=1,
            explanation="event memory suppressed when the user says not to mention it",
        ),
        "style_continuity_rate": ProductMetric(
            key="style_continuity_rate",
            value=_ratio(sum(style_expectations), len(style_expectations)),
            numerator=sum(style_expectations),
            denominator=len(style_expectations),
            explanation="style preferences continue to shape answers without exposing facts",
        ),
        "prompt_safety_rate": ProductMetric(
            key="prompt_safety_rate",
            value=float(not prompt_contains_visible_memory),
            numerator=int(not prompt_contains_visible_memory),
            denominator=1,
            explanation="no direct visible memory is injected for the no-mention coding query",
        ),
        "correction_retirement_rate": ProductMetric(
            key="correction_retirement_rate",
            value=_ratio(len(retired_targets) - len(leaked_targets), len(correction_targets)),
            numerator=len(retired_targets) - len(leaked_targets),
            denominator=len(correction_targets),
            explanation="explicit correction retires sensitive state and derived profile memory",
        ),
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _format_actions(actions: dict[str, str]) -> str:
    if not actions:
        return "- none"
    return "\n".join(f"- {key}: {action}" for key, action in sorted(actions.items()))


if __name__ == "__main__":
    main()
