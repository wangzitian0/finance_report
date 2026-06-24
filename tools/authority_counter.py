#!/usr/bin/env python3
"""CODE/LLM authority counter (EPIC-026 AC26.9).

Prints the per-package (EPIC) CODE/LLM distribution and band — a live, on-demand
view (no committed snapshot: the declared-vs-detected reconciliation gate,
tools/check_authority_reconcile.py, is the enforced check; this is the human view).

    python tools/authority_counter.py            # print the table
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.authority.authority_classifier import classify_repo  # noqa: E402


def render_table(result: dict) -> str:
    lines = [f"{'EPIC':<10}{'#AC':>5}{'CODE':>6}{'LLM':>5}{'?':>5}{'LLM%':>7}  band"]
    for epic, b in result["packages"].items():
        lines.append(
            f"{epic:<10}{b['total']:>5}{b['code']:>6}{b['llm']:>5}{b['unknown']:>5}"
            f"{b['llm_share']:>6}%  {b['band']}"
        )
    o = result["overall"]
    lines.append("-" * 46)
    lines.append(
        f"{'ALL':<10}{o['total']:>5}{o['code']:>6}{o['llm']:>5}{o['unknown']:>5}{o['llm_share']:>6}%"
    )
    lines.append("\nclassified by test shape: cassette/replay -> LLM, else CODE. '?' = test file unresolved.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    print(render_table(classify_repo(ROOT_DIR)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
