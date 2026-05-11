from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_system import DialogueMemoryExtractor, MemoryUseGate, MemoryStore, ProfileInferencer


TURNS = [
    "我最近准备面试，有点焦虑。",
    "回答直接一点，先给结论。",
]

QUERIES = {
    "interview_help": "面试怎么准备？",
    "coding_no_mention": "今天只帮我 review Python 代码，不用提面试。",
}


def main() -> None:
    tz = ZoneInfo("Asia/Shanghai")
    timestamp = datetime(2026, 5, 1, 9, 0, tzinfo=tz)
    store = MemoryStore()
    extractor = DialogueMemoryExtractor()
    inferencer = ProfileInferencer()
    gate = MemoryUseGate()

    for index, turn in enumerate(TURNS, start=1):
        store.extend(extractor.extract(turn, source=f"turn_{index}", timestamp=timestamp))
        store.extend(inferencer.infer(store, timestamp))

    print("# Active memories")
    for memory in store.active_memories(now=timestamp):
        print(f"- {memory.key}: {memory.value} ({memory.memory_type.value})")

    for name, query in QUERIES.items():
        result = gate.select(query, store.active_memories(now=timestamp), now=timestamp)
        payload = {
            "query": query,
            "selected": [
                {"key": item.memory.key, "action": item.action.value, "safe_to_mention": item.safe_to_mention}
                for item in result.decisions
            ],
            "suppressed": [
                {"key": item.memory.key, "action": item.action.value}
                for item in result.suppressed
            ],
        }
        print(f"\n# Gate result: {name}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
