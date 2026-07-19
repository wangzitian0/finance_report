"""Gate: the L4 ``backend`` super-package boundary only shrinks (#app-boundary).

Fails when a cross-boundary edge between the un-migrated ``apps/backend/src``
remainder and an already-carved package is **not** in the frozen baseline — i.e.
a NEW inbound encapsulation leak (remainder → a carved package's unpublished
internal) or a NEW outbound upward-layer edge (a carved package → the app
remainder). The baseline may only shrink: ``--update`` regenerates it from the
current tree (use it to record that edges were *removed*, never to bless new
ones — review makes that intent visible in the diff).

This is the fail-closed complement to ``check_package_contract``'s deep-import
gate, which cannot see these edges because the remainder is not yet a discovered
package. When each domain is finally carved out of the super-package, its edges
leave the baseline and the burndown shrinks toward zero.

stdlib + the pure ``app_boundary`` module only, so it runs in the lint env.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.app_boundary import (
    discover_and_compute_edges,
    discover_l4_deep_import_edges,
    dump_baseline,
    load_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_UPDATE_MODE = "shrink-only"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Regenerate the baseline from the current tree. Shrink-only: refuses to "
        "GROW an existing baseline (a new edge must be routed through the interface, "
        "not blessed). Bootstraps when the baseline file is missing.",
    )
    return parser.parse_args(argv)


def _run_command(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    baseline_path = repo_root / "common/meta/data/app-boundary-baseline.json"
    l4_baseline_path = repo_root / "common/meta/data/l4-root-import-baseline.json"
    current = sorted(set(discover_and_compute_edges(repo_root)))
    l4_current = sorted(set(discover_l4_deep_import_edges(repo_root)))

    if args.update:
        # Shrink-only: an existing baseline may be pruned (removed edges) but never
        # grown — that would silently bless a new leak. Only a missing baseline
        # bootstraps to whatever is in the tree.
        if baseline_path.exists():
            grew = sorted(set(current) - load_baseline(baseline_path))
            if grew:
                for edge in grew:
                    print(
                        f"::error title=App-boundary --update refused::{edge} — --update "
                        "will not GROW the baseline (that would bless a new edge). Route "
                        "it through the published interface, or move the code into the "
                        "owning package.",
                        file=sys.stderr,
                    )
                print(
                    f"[APP-BOUNDARY] --update REFUSED: would add {len(grew)} edge(s). "
                    "Delete the baseline to intentionally re-bootstrap.",
                    file=sys.stderr,
                )
                return 1
        dump_baseline(baseline_path, current)
        print(f"[APP-BOUNDARY] baseline updated: {len(current)} edge(s).")
        return 0

    baseline = load_baseline(baseline_path)
    l4_baseline = load_baseline(l4_baseline_path)
    new = sorted(set(current) - baseline) + sorted(set(l4_current) - l4_baseline)
    stale = sorted(baseline - set(current)) + sorted(l4_baseline - set(l4_current))

    if new:
        for edge in new:
            print(
                f"::error title=App-boundary edge added::{edge} — a new cross-boundary "
                "edge into/out of a carved package. Route it through the package's "
                "published interface, or move the code into the owning package. The "
                "baseline may only SHRINK.",
                file=sys.stderr,
            )
        print(
            f"[APP-BOUNDARY] FAILED: {len(new)} new cross-boundary edge(s).",
            file=sys.stderr,
        )
        return 1

    if stale:
        for edge in stale:
            print(
                f"::error title=App-boundary baseline stale::{edge} — this edge no "
                "longer exists; run 'check_app_boundary --update' to prune it (keeps "
                "the burndown honest).",
                file=sys.stderr,
            )
        print(
            f"[APP-BOUNDARY] FAILED: {len(stale)} stale baseline entries — run --update.",
            file=sys.stderr,
        )
        return 1

    print(f"[APP-BOUNDARY] PASSED: {len(current)} baselined edge(s), none added.")
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
        "APP-BOUNDARY", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
