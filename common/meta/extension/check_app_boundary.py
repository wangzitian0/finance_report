"""Gate: enforce zero cross-boundary and L4 deep-import edges (#app-boundary).

Fails unconditionally when any cross-boundary edge exists between ``apps/backend/src``
and a carved package, or when any L4 delivery/composition module deep-imports a carved
package internal instead of its published root.

stdlib + the pure ``app_boundary`` module only, so it runs in the lint env.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_cli_command
from common.meta.extension.app_boundary import (
    discover_and_compute_edges,
    discover_l4_deep_import_edges,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def _main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    current = sorted(set(discover_and_compute_edges(repo_root)))
    l4_current = sorted(set(discover_l4_deep_import_edges(repo_root)))

    for edge in current:
        print(
            f"::error title=App-boundary edge detected::{edge} — route through the "
            "owning package interface or move the code into the package.",
            file=sys.stderr,
        )
    for edge in l4_current:
        print(
            f"::error title=L4 deep import detected::{edge} — import from the "
            "carved package root instead of internals.",
            file=sys.stderr,
        )
    if current or l4_current:
        print(
            f"[APP-BOUNDARY] FAILED: {len(current)} cross-boundary edge(s), "
            f"{len(l4_current)} L4 deep import(s).",
            file=sys.stderr,
        )
        return 1

    print("[APP-BOUNDARY] PASSED: 0 cross-boundary edges, 0 L4 deep imports.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli_command(_main, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
