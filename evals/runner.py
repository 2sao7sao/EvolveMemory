from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from evals.metrics import AccuracyMetric
from memory_system import DialogueMemoryExtractor, MemoryUseGate, ProfileInferencer
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


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="gate_eval", choices=["gate_eval"])
    parser.add_argument("--cases-dir", default=str(DEFAULT_CASES_DIR))
    args = parser.parse_args()
    if args.suite == "gate_eval":
        result = run_gate_eval(Path(args.cases_dir))
    else:
        raise ValueError(f"Unsupported suite: {args.suite}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
