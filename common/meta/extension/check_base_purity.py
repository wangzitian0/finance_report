"""Fail-closed shrink-only gate for production package-base impurity debt."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.base_purity import discover_impurities

REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def violations(repo_root: Path, baseline_path: Path) -> list[str]:
    try:
        baseline = set(json.loads(baseline_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read base-purity baseline: {exc}"]
    backend_src = repo_root / "apps/backend/src"
    if not backend_src.is_dir():
        return [f"cannot scan package base layers: missing directory {backend_src}"]
    current = set(discover_impurities(backend_src))
    return [
        *(f"new base impurity: {item}" for item in sorted(current - baseline)),
        *(f"stale base-purity baseline: {item}" for item in sorted(baseline - current)),
    ]


def _run_command(argv: Sequence[str] | None = None) -> int:
    repo_root = parse_args(list(argv or ())).repo_root.resolve()
    findings = violations(
        repo_root, repo_root / "common/meta/data/base-purity-baseline.json"
    )
    if findings:
        print("[BASE-PURITY] FAILED", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("[BASE-PURITY] PASSED.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        status = _run_command(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if status == 2:
        return 2
    findings = [] if status == 0 else [f"command returned status {status}"]
    return run_gate(
        "BASE-PURITY", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":
    raise SystemExit(main())
