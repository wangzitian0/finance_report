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
from pathlib import Path

from common.meta.extension.app_boundary import (
    discover_and_compute_edges,
    dump_baseline,
    load_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = REPO_ROOT / "docs/ssot/app-boundary-baseline.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Regenerate the baseline from the current tree (only to record REMOVED edges).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    repo_root = args.repo_root.resolve()
    baseline_path = repo_root / "docs/ssot/app-boundary-baseline.json"
    current = sorted(set(discover_and_compute_edges(repo_root)))

    if args.update:
        dump_baseline(baseline_path, current)
        print(f"[APP-BOUNDARY] baseline updated: {len(current)} edge(s).")
        return 0

    baseline = load_baseline(baseline_path)
    new = sorted(set(current) - baseline)
    stale = sorted(baseline - set(current))

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
            f"[APP-BOUNDARY] FAILED: {len(stale)} stale baseline entrie(s) — run --update.",
            file=sys.stderr,
        )
        return 1

    print(f"[APP-BOUNDARY] PASSED: {len(current)} baselined edge(s), none added.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
