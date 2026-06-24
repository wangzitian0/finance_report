#!/usr/bin/env python3
"""CODE/LLM authority counter (EPIC-026 AC26.9).

Prints the per-package (EPIC) CODE/LLM distribution and band, and with
``--write`` refreshes the checked-in snapshot at docs/ssot/authority-distribution.json.

    python tools/authority_counter.py            # print table
    python tools/authority_counter.py --write     # refresh the snapshot
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.ssot.authority_classifier import classify_repo  # noqa: E402

SNAPSHOT = ROOT_DIR / "docs" / "ssot" / "authority-distribution.json"


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


def snapshot_text(result: dict) -> str:
    """Deterministic JSON snapshot (sorted, no timestamps) for check-in."""
    return json.dumps(result, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    result = classify_repo(ROOT_DIR)
    if "--write" in argv:
        SNAPSHOT.write_text(snapshot_text(result), encoding="utf-8")
        print(f"[AUTHORITY] wrote snapshot -> {SNAPSHOT.relative_to(ROOT_DIR)}")
        return 0
    print(render_table(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
