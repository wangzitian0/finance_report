"""Fail-closed shrink-only gate for production package-base impurity debt."""

from __future__ import annotations

import argparse
import json
from collections.abc import Collection, Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.base_purity import discover_impurities

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_BASE_IMPURITIES: frozenset[str] = frozenset(
    {
        "llm/base/secrets.py::import src.config",
        "llm/base/usage.py::from src.observability import get_logger",
    }
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def violations(
    repo_root: Path,
    baseline_path: Collection[str] | Path = BASELINE_BASE_IMPURITIES,
) -> list[str]:
    if isinstance(baseline_path, Path):
        try:
            baseline = set(json.loads(baseline_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"cannot read base-purity baseline: {exc}"]
    else:
        baseline = set(baseline_path)
    backend_src = repo_root / "apps/backend/src"
    if not backend_src.is_dir():
        return [f"cannot scan package base layers: missing directory {backend_src}"]
    current = set(discover_impurities(backend_src))
    return [
        *(f"new base impurity: {item}" for item in sorted(current - baseline)),
        *(f"stale base-purity baseline: {item}" for item in sorted(baseline - current)),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    return run_gate(
        "BASE-PURITY",
        lambda repo_root: violations(repo_root, BASELINE_BASE_IMPURITIES),
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
