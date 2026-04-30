from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from memory_system import (
    DialogueMemoryExtractor,
    MemoryStore,
    ProfileInferencer,
    ResponsePolicyEngine,
)
from memory_system.engine import pretty_memories


DEFAULT_TURNS = [
    "我29岁，硕士毕业，现在单身，最近在找工作。",
    "这段时间压力很大，也有点焦虑。",
    "回答直接一点，先给结论，别太啰嗦，最好分步骤。",
    "我平时喜欢滑雪，最近在学钓鱼。",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the memory system prototype.")
    parser.add_argument(
        "--turn",
        action="append",
        help="A dialogue turn to ingest. Can be passed multiple times.",
    )
    args = parser.parse_args()

    turns = args.turn or DEFAULT_TURNS
    store = MemoryStore()
    extractor = DialogueMemoryExtractor()
    inferencer = ProfileInferencer()
    policy_engine = ResponsePolicyEngine()
    tz = ZoneInfo("Asia/Shanghai")

    for index, turn in enumerate(turns, start=1):
        timestamp = datetime(2026, 4, 16, 9, index, tzinfo=tz)
        candidates = extractor.extract(turn, source=f"turn_{index}", timestamp=timestamp)
        if candidates:
            print(f"\nTurn {index}: {turn}")
            print(pretty_memories(candidates))
        store.extend(candidates)
        store.extend(inferencer.infer(store, timestamp))

    active = store.active_memories(now=datetime(2026, 4, 16, 12, 0, tzinfo=tz))
    policy = policy_engine.build(store, datetime(2026, 4, 16, 12, 0, tzinfo=tz))

    print("\nActive memories")
    print(pretty_memories(active))

    print("\nResponse policy")
    print(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
