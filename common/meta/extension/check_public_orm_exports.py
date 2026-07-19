"""Fail-closed shrink-only gate for package-root public ORM exports."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.public_orm_exports import discover_public_orm_exports

REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def violations(repo_root: Path, baseline_path: Path) -> list[str]:
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(
            isinstance(item, str) for item in payload
        ):
            raise ValueError("baseline must be a JSON string list")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot read public-ORM baseline: {exc}"]
    try:
        current = set(discover_public_orm_exports(repo_root / "apps/backend/src"))
    except ValueError as exc:
        return [f"cannot discover public ORM exports: {exc}"]
    baseline = set(payload)
    return [
        *(f"new public ORM export: {item}" for item in sorted(current - baseline)),
        *(f"stale public-ORM baseline: {item}" for item in sorted(baseline - current)),
    ]


def _run_command(argv: Sequence[str] | None = None) -> int:
    repo_root = parse_args(list(argv or ())).repo_root.resolve()
    findings = violations(
        repo_root, repo_root / "common/meta/data/public-orm-export-baseline.json"
    )
    if findings:
        print("[PUBLIC-ORM] FAILED", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("[PUBLIC-ORM] PASSED.")
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
        "PUBLIC-ORM", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
