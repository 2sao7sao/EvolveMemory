from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from evals.metrics import AccuracyMetric
from memory_system import (
    ContextCompiler,
    DialogueMemoryExtractor,
    EventSkillRegistry,
    MemoryItem,
    MemoryLayer,
    MemoryRecord,
    MemoryType,
    MemoryUseGate,
    ProfileAccumulator,
    ProfileEvidenceExtractor,
    ProfileInferencer,
    ResponsePolicyEngine,
    RuleMemoryProposalExtractor,
    TurnPreprocessor,
)
from memory_system.engine import MemoryStore

DEFAULT_CASES_DIR = Path(__file__).resolve().parent / "cases"


def run_gate_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    tz = ZoneInfo("Asia/Shanghai")
    extractor = DialogueMemoryExtractor()
    inferencer = ProfileInferencer()
    gate = MemoryUseGate()
    metric = AccuracyMetric()
    failures: list[dict[str, object]] = []

    for case in _read_jsonl(cases_dir / "gate_eval.jsonl"):
        store = MemoryStore()
        timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=tz)
        for index, turn in enumerate(case["turns"], start=1):
            source = f"{case['id']}:turn_{index}"
            store.extend(extractor.extract(turn, source=source, timestamp=timestamp))
            store.extend(inferencer.infer(store, timestamp))
        decisions = gate.select(case["query"], store.active_memories(now=timestamp), now=timestamp)
        actual = {decision.memory.key: decision.action.value for decision in decisions.decisions}
        actual.update({decision.memory.key: decision.action.value for decision in decisions.suppressed})
        for key, expected_action in case["expected_gate"].items():
            actual_action = actual.get(key)
            metric.add(expected_action, actual_action)
            if actual_action != expected_action:
                failures.append(
                    {
                        "case_id": case["id"],
                        "key": key,
                        "expected": expected_action,
                        "actual": actual_action,
                    }
                )

    return {
        "suite": "gate_eval",
        "metrics": {"gate_action": metric.to_dict()},
        "failures": failures,
    }


def run_product_replay_eval() -> dict[str, object]:
    from memory_system.demo import run_product_demo

    report = run_product_demo()
    failures = [
        {
            "metric": metric.key,
            "expected": 1.0,
            "actual": metric.value,
        }
        for metric in report.metrics.values()
        if metric.value < 1.0
    ]
    return {
        "suite": "product_replay_eval",
        "metrics": {
            metric.key: {
                "value": round(metric.value, 4),
                "correct": metric.numerator,
                "total": metric.denominator,
            }
            for metric in report.metrics.values()
        },
        "failures": failures,
    }


def run_profile_evidence_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    tz = ZoneInfo("Asia/Shanghai")
    metric = AccuracyMetric()
    failures: list[dict[str, object]] = []
    for case in _read_jsonl(cases_dir / "profile_evidence_eval.jsonl"):
        records = []
        for index, turn_text in enumerate(case["turns"], start=1):
            turn = TurnPreprocessor().preprocess(
                text=turn_text,
                timestamp=datetime(2026, 5, 1, 9, index, tzinfo=tz),
                turn_id=f"{case['id']}:turn_{index}",
            )
            records.extend(RuleMemoryProposalExtractor().propose(turn, user_id="eval-user"))
        evidence = ProfileEvidenceExtractor().extract(records)
        actual = {(item.dimension, item.value) for item in evidence if item.polarity == "support"}
        for expected in case["expected_evidence"]:
            expected_pair = (expected["dimension"], expected["value"])
            passed = expected_pair in actual
            metric.add(True, passed)
            if not passed:
                failures.append({"case_id": case["id"], "expected": expected_pair, "actual": sorted(actual)})
    return {"suite": "profile_evidence_eval", "metrics": {"profile_evidence": metric.to_dict()}, "failures": failures}


def run_response_policy_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    metric = AccuracyMetric()
    failures: list[dict[str, object]] = []
    timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    for case in _read_jsonl(cases_dir / "response_policy_eval.jsonl"):
        memories = [
            MemoryItem(
                memory_type=MemoryType(item["type"]),
                key=item["key"],
                value=item["value"],
                confidence=item.get("confidence", 0.8),
                source="eval",
                evidence=item["key"],
                valid_from=timestamp,
            )
            for item in case["memories"]
        ]
        policy = ResponsePolicyEngine().build_from_memories(memories).to_dict()
        for key, expected in case["expected_policy"].items():
            actual = policy.get(key)
            metric.add(expected, actual)
            if actual != expected:
                failures.append({"case_id": case["id"], "field": key, "expected": expected, "actual": actual})
    return {"suite": "response_policy_eval", "metrics": {"response_policy": metric.to_dict()}, "failures": failures}


def run_event_skill_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    metric = AccuracyMetric()
    failures: list[dict[str, object]] = []
    timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    for case in _read_jsonl(cases_dir / "event_skill_eval.jsonl"):
        record = MemoryRecord(
            user_id="eval-user",
            layer=MemoryLayer.EPISODIC_EVENT,
            key=case["record"]["key"],
            value=case["record"]["value"],
            confidence=0.86,
            valid_from=timestamp,
            observed_at=timestamp,
            metadata={"evidence": case["record"].get("evidence", case["record"]["value"])},
        )
        actual = {event.event_type for event in EventSkillRegistry().detect([record])}
        for expected in case["expected_event_types"]:
            passed = expected in actual
            metric.add(True, passed)
            if not passed:
                failures.append({"case_id": case["id"], "expected": expected, "actual": sorted(actual)})
    return {"suite": "event_skill_eval", "metrics": {"event_skill": metric.to_dict()}, "failures": failures}


def run_prompt_context_safety_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    metric = AccuracyMetric()
    failures: list[dict[str, object]] = []
    timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    for case in _read_jsonl(cases_dir / "prompt_context_safety_eval.jsonl"):
        memories = [
            MemoryItem(
                memory_type=MemoryType.PROFILE,
                key=item["key"],
                value=item["value"],
                confidence=0.8,
                source="eval",
                evidence=item["evidence"],
                valid_from=timestamp,
                allowed_use=["style"],
            )
            for item in case["profile_memories"]
        ]
        gate_result = MemoryUseGate().select(case["query"], memories, now=timestamp)
        policy = ResponsePolicyEngine().build_from_memories(memories)
        context = ContextCompiler().compile(query=case["query"], gate_result=gate_result, response_policy=policy)
        direct_text = "\n".join(context.direct_facts)
        style_text = "\n".join(context.style_policy)
        direct_safe = direct_text == ""
        style_present = bool(style_text)
        metric.add(True, direct_safe and style_present)
        if not (direct_safe and style_present):
            failures.append({"case_id": case["id"], "direct_facts": context.direct_facts, "style_policy": context.style_policy})
    return {"suite": "prompt_context_safety_eval", "metrics": {"prompt_context_safety": metric.to_dict()}, "failures": failures}


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite",
        default="gate_eval",
        choices=[
            "gate_eval",
            "product_replay_eval",
            "profile_evidence_eval",
            "response_policy_eval",
            "event_skill_eval",
            "prompt_context_safety_eval",
        ],
    )
    parser.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR))
    args = parser.parse_args()
    if args.suite == "gate_eval":
        result = run_gate_eval(Path(args.cases_dir))
    elif args.suite == "product_replay_eval":
        result = run_product_replay_eval()
    elif args.suite == "profile_evidence_eval":
        result = run_profile_evidence_eval(Path(args.cases_dir))
    elif args.suite == "response_policy_eval":
        result = run_response_policy_eval(Path(args.cases_dir))
    elif args.suite == "event_skill_eval":
        result = run_event_skill_eval(Path(args.cases_dir))
    elif args.suite == "prompt_context_safety_eval":
        result = run_prompt_context_safety_eval(Path(args.cases_dir))
    else:
        raise ValueError(f"Unsupported suite: {args.suite}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
