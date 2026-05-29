from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from evals.metrics import AccuracyMetric, PrecisionRecallF1Metric, RateMetric
from memory_system import (
    Authority,
    ContextCompiler,
    DialogueMemoryExtractor,
    EventSkillRegistry,
    HybridMemoryScorer,
    LLMMemoryProposalExtractor,
    LLMProposalValidationError,
    MemoryItem,
    MemoryLayer,
    MemoryOperationPlanner,
    MemoryRecord,
    MemoryType,
    MemoryUseGate,
    NormalizedSQLiteMemoryRepository,
    ProfileAccumulator,
    ProfileEvidenceExtractor,
    ProfileInferencer,
    ResponsePolicyEngine,
    RetrievalPlanner,
    RuleMemoryProposalExtractor,
    Sensitivity,
    TurnPreprocessor,
    WritePolicyContext,
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


def run_extraction_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    tz = ZoneInfo("Asia/Shanghai")
    metric = AccuracyMetric()
    failures: list[dict[str, object]] = []
    extractor = LLMMemoryProposalExtractor()
    for case in _read_jsonl(cases_dir / "extraction_eval.jsonl"):
        turn = TurnPreprocessor().preprocess(
            text=case["turn"],
            timestamp=datetime(2026, 5, 1, 9, 0, tzinfo=tz),
            turn_id=f"{case['id']}:turn_1",
        )
        try:
            records = extractor.parse_response_payload(case["payload"], turn=turn, user_id="eval-user")
            errored = False
        except LLMProposalValidationError as exc:
            records = []
            errored = True
            error = str(exc)
        expected_error = case.get("expect_error", False)
        metric.add(expected_error, errored)
        if expected_error != errored:
            failures.append({"case_id": case["id"], "expected_error": expected_error, "actual_error": errored, "error": locals().get("error")})
            continue
        expected_keys = set(case.get("expected_keys", []))
        actual_keys = {record.key for record in records}
        for key in expected_keys:
            passed = key in actual_keys
            metric.add(True, passed)
            if not passed:
                failures.append({"case_id": case["id"], "expected_key": key, "actual_keys": sorted(actual_keys)})
        for key, expected in case.get("expected_sensitivity", {}).items():
            actual = next((record.sensitivity.value for record in records if record.key == key), None)
            metric.add(expected, actual)
            if actual != expected:
                failures.append({"case_id": case["id"], "key": key, "expected_sensitivity": expected, "actual": actual})
        if "expected_count" in case:
            metric.add(case["expected_count"], len(records))
            if len(records) != case["expected_count"]:
                failures.append({"case_id": case["id"], "expected_count": case["expected_count"], "actual_count": len(records)})
    return {"suite": "extraction_eval", "metrics": {"extraction": metric.to_dict()}, "failures": failures}


def run_write_decision_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    metric = AccuracyMetric()
    failures: list[dict[str, object]] = []
    timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    for case in _read_jsonl(cases_dir / "write_decision_eval.jsonl"):
        existing = [_record_from_case(item, timestamp=timestamp) for item in case.get("existing", [])]
        candidates = [_record_from_case(item, timestamp=timestamp) for item in case["candidates"]]
        operations = MemoryOperationPlanner().plan(
            candidates,
            existing,
            WritePolicyContext(user_command=case.get("user_command")),
        )
        actual = [operation.operation.value for operation in operations]
        expected = case["expected_operations"]
        metric.add(expected, actual)
        if actual != expected:
            failures.append({"case_id": case["id"], "expected": expected, "actual": actual})
    return {"suite": "write_decision_eval", "metrics": {"write_decision": metric.to_dict()}, "failures": failures}


def run_retrieval_privacy_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    metric = PrecisionRecallF1Metric()
    failures: list[dict[str, object]] = []
    timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    for case in _read_jsonl(cases_dir / "retrieval_privacy_eval.jsonl"):
        memories = [
            MemoryItem(
                memory_type=MemoryType(item["type"]),
                key=item["key"],
                value=item["value"],
                confidence=item.get("confidence", 0.86),
                source="eval",
                evidence=item.get("evidence", item["key"]),
                valid_from=timestamp,
                tags=item.get("tags", []),
                allowed_use=item.get("allowed_use", []),
                sensitivity=item.get("sensitivity", "personal"),
            )
            for item in case["memories"]
        ]
        result = MemoryUseGate().select(case["query"], memories, now=timestamp)
        selected = {decision.memory.key: decision.action.value for decision in result.decisions}
        selected.update({decision.memory.key: decision.action.value for decision in result.suppressed})
        for key, expected_action in case["expected_actions"].items():
            actual = selected.get(key)
            metric.add(expected=True, actual=actual == expected_action)
            if actual != expected_action:
                failures.append({"case_id": case["id"], "key": key, "expected": expected_action, "actual": actual})
    return {"suite": "retrieval_privacy_eval", "metrics": {"privacy_actions": metric.to_dict()}, "failures": failures}


def run_retrieval_math_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    metric = RateMetric()
    failures: list[dict[str, object]] = []
    timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    for case in _read_jsonl(cases_dir / "retrieval_math_eval.jsonl"):
        memories = [
            MemoryItem(
                memory_type=MemoryType(item["type"]),
                key=item["key"],
                value=item["value"],
                confidence=item.get("confidence", 0.86),
                source="eval",
                evidence=item.get("evidence", item["key"]),
                valid_from=timestamp,
            )
            for item in case["memories"]
        ]
        plan = RetrievalPlanner().plan(case["query"], max_prompt_memories=8)
        scores = HybridMemoryScorer().score(case["query"], memories, now=timestamp, plan=plan)
        top = scores[0] if scores else None
        factors = top.factors if top else {}
        passed = top is not None and top.memory.key == case["expected_top_key"]
        for factor, minimum in case.get("expected_min_factors", {}).items():
            passed = passed and factors.get(factor, 0.0) >= minimum
        metric.add(passed)
        if not passed:
            failures.append(
                {
                    "case_id": case["id"],
                    "expected_top_key": case["expected_top_key"],
                    "actual_top_key": top.memory.key if top else None,
                    "factors": factors,
                }
            )
    return {
        "suite": "retrieval_math_eval",
        "metrics": {"retrieval_math": metric.to_dict("pass_rate")},
        "failures": failures,
    }


def run_v2_ingest_eval(cases_dir: Path = DEFAULT_CASES_DIR) -> dict[str, object]:
    metric = RateMetric()
    failures: list[dict[str, object]] = []
    timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    with TemporaryDirectory() as tmpdir:
        repository = NormalizedSQLiteMemoryRepository(Path(tmpdir) / "eval.sqlite3")
        extractor = LLMMemoryProposalExtractor()
        for case in _read_jsonl(cases_dir / "v2_ingest_eval.jsonl"):
            turn = TurnPreprocessor().preprocess(
                text=case["turn"],
                timestamp=timestamp,
                turn_id=f"{case['id']}:turn_1",
            )
            try:
                candidates = extractor.parse_response_payload(
                    case["payload"],
                    turn=turn,
                    user_id=case["user_id"],
                    session_id=case.get("session_id"),
                )
                operations = MemoryOperationPlanner().plan(
                    candidates,
                    repository.list_records(user_id=case["user_id"], session_id=case.get("session_id")),
                    WritePolicyContext(settings=repository.get_user_settings(case["user_id"])),
                )
                persisted = repository.apply_operations(operations, created_at=timestamp)
                actual_operations = [operation.operation.value for operation in operations]
                passed = actual_operations == case["expected_operations"] and len(persisted) == case.get("expected_persisted", len(persisted))
            except LLMProposalValidationError:
                actual_operations = []
                persisted = []
                passed = case.get("expect_error", False)
            metric.add(passed)
            if not passed:
                failures.append({"case_id": case["id"], "expected_operations": case.get("expected_operations"), "actual_operations": actual_operations, "persisted": len(persisted)})
    return {"suite": "v2_ingest_eval", "metrics": {"v2_ingest": metric.to_dict("pass_rate")}, "failures": failures}


def _record_from_case(item: dict[str, object], *, timestamp: datetime) -> MemoryRecord:
    return MemoryRecord(
        user_id=str(item.get("user_id", "eval-user")),
        session_id=item.get("session_id") if isinstance(item.get("session_id"), str) else None,
        layer=MemoryLayer(str(item.get("layer", MemoryLayer.SEMANTIC_FACT.value))),
        key=str(item["key"]),
        value=item["value"],
        normalized_value=item.get("normalized_value", item["value"]),
        confidence=float(item.get("confidence", 0.86)),
        authority=Authority(str(item.get("authority", Authority.USER_EXPLICIT.value))),
        sensitivity=Sensitivity(str(item.get("sensitivity", Sensitivity.PERSONAL.value))),
        valid_from=timestamp,
        observed_at=timestamp,
        exclusive_group=item.get("exclusive_group") if isinstance(item.get("exclusive_group"), str) else None,
        coexistence_rule=str(item.get("coexistence_rule", "coexist")),
        tags=list(item.get("tags", [])),
        metadata={"evidence": str(item.get("evidence", item["value"]))},
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


SUITES = {
    "gate_eval": run_gate_eval,
    "product_replay_eval": lambda _cases_dir: run_product_replay_eval(),
    "profile_evidence_eval": run_profile_evidence_eval,
    "response_policy_eval": run_response_policy_eval,
    "event_skill_eval": run_event_skill_eval,
    "prompt_context_safety_eval": run_prompt_context_safety_eval,
    "extraction_eval": run_extraction_eval,
    "write_decision_eval": run_write_decision_eval,
    "retrieval_privacy_eval": run_retrieval_privacy_eval,
    "retrieval_math_eval": run_retrieval_math_eval,
    "v2_ingest_eval": run_v2_ingest_eval,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite",
        default="gate_eval",
        choices=[*SUITES.keys(), "all"],
    )
    parser.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR))
    args = parser.parse_args()
    cases_dir = Path(args.cases_dir)
    if args.suite == "all":
        result = {
            "suite": "all",
            "metrics": {},
            "failures": [],
            "suites": [runner(cases_dir) for runner in SUITES.values()],
        }
        result["metrics"] = {
            suite["suite"]: suite["metrics"] for suite in result["suites"]
        }
        result["failures"] = [
            failure
            for suite in result["suites"]
            for failure in suite["failures"]
        ]
    else:
        result = SUITES[args.suite](cases_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
