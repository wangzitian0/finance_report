"""Fail-closed shrink-only gate for production package-base impurity debt."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.base_purity import discover_impurities

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE = REPO_ROOT / "common/meta/data/base-purity-baseline.json"


def violations(repo_root: Path, baseline_path: Path) -> list[str]:
    try:
        baseline = set(json.loads(baseline_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read base-purity baseline: {exc}"]
    current = set(discover_impurities(repo_root / "apps/backend/src"))
    return [
        *(f"new base impurity: {item}" for item in sorted(current - baseline)),
        *(f"stale base-purity baseline: {item}" for item in sorted(baseline - current)),
    ]


def _run_command(_argv: Sequence[str] | None = None) -> int:
    findings = violations(REPO_ROOT, BASELINE)
    if findings:
        print("[BASE-PURITY] FAILED", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("[BASE-PURITY] PASSED.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    status = _run_command(argv)
    findings = [] if status == 0 else [f"command returned status {status}"]
    return run_gate(
        "BASE-PURITY", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":
    raise SystemExit(main())
