"""CLI: python scripts/run_evals.py"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("PYTHONPATH", str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src"))

from evals.harness import run_eval_suite


def main() -> int:
    report = run_eval_suite()
    print(json.dumps(report, indent=2))
    print(
        f"\n{report['cases_passed']}/{report['cases_total']} cases · "
        f"score={report['score']} · provider={report['llm_provider']}"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
