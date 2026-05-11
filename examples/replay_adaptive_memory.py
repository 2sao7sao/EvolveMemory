from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_system.demo import format_demo_report, run_product_demo  # noqa: E402


def main() -> None:
    report = run_product_demo()
    print(format_demo_report(report), end="")
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
