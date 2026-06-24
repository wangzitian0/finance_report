#!/usr/bin/env python3
"""Gate 1e: keep ``draft`` packages from becoming a zero-enforcement dump.

A ``draft`` package may leave its authority tier undecided (the "HU" state), so
its ACs escape the tier->proof matrix. Two rules stop ``draft`` from being abused
as a place to park finished-but-unclassified work (vision Axiom B — drive
low-confidence DOWN, do not let it pool):

1. **No finished work hides in draft.** A ``draft`` package MUST NOT contain a
   ``status="done"`` roadmap AC. If the work is done, decide the tier and ship
   the package ``active``.
2. **Every draft is registered.** Each ``draft`` package must be listed in
   ``docs/ssot/draft-package-baseline.json``, so adding one is a deliberate,
   reviewed line in the diff rather than a silent accumulation. ``--update``
   rewrites the registry to the packages that are draft right now (pruning the
   ones that have since shipped).

Pure AST/text (no pydantic), so it runs in the CI lint env.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common.ssot.generate_ac_registry import package_contract_meta

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = REPO_ROOT / "docs" / "ssot" / "draft-package-baseline.json"


def _draft_packages(repo_root: Path) -> dict[str, list[str]]:
    """Map each draft package name -> its list of ``done`` roadmap AC ids."""
    drafts: dict[str, list[str]] = {}
    for path in sorted(repo_root.glob("common/*/contract.py")):
        meta = package_contract_meta(path)
        if meta is None or meta.get("status") != "draft":
            continue
        name = meta.get("name") or path.parent.name
        drafts[name] = [
            ac["id"] for ac in meta.get("roadmap", []) if ac.get("status") == "done"
        ]
    return drafts


def load_baseline(path: Path) -> set[str]:
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(n) for n in payload.get("draft_packages", [])}


def write_baseline(path: Path, drafts: set[str]) -> None:
    payload = {
        "_comment": (
            "Registered draft packages (tools/check_draft_packages.py). A draft "
            "package leaves its authority tier undecided; listing it here makes "
            "adding one a reviewed act. Resolve drafts to active over time."
        ),
        "draft_packages": sorted(drafts),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def violations(repo_root: Path, baseline_path: Path) -> list[str]:
    drafts = _draft_packages(repo_root)
    baseline = load_baseline(baseline_path)
    errors: list[str] = []
    for name in sorted(drafts):
        done = drafts[name]
        if done:
            errors.append(
                f"draft package {name!r} contains done AC(s) {done}: finished work "
                "must not hide in draft — decide the tier and ship it active."
            )
        if name not in baseline:
            errors.append(
                f"draft package {name!r} is not registered in "
                f"{baseline_path.name}: add it (deliberate, reviewed) or run "
                "--update."
            )
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enforce draft-package hygiene (no done ACs; registered)."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite the baseline to the packages that are draft right now.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    repo_root = args.repo_root.resolve()
    baseline_path = args.baseline or (
        repo_root / DEFAULT_BASELINE.relative_to(REPO_ROOT)
    )

    if args.update:
        drafts = set(_draft_packages(repo_root))
        write_baseline(baseline_path, drafts)
        print(f"Updated draft baseline: {baseline_path} ({len(drafts)} draft(s))")
        return 0

    errors = violations(repo_root, baseline_path)
    if errors:
        for message in errors:
            print(f"::error title=Draft package::{message}", file=sys.stderr)
        print(f"[DRAFT] FAILED: {len(errors)} draft-package violation(s).", file=sys.stderr)
        return 1
    print("[DRAFT] PASSED: draft packages carry no done ACs and are all registered.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
