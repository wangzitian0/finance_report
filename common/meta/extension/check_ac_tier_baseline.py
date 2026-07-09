#!/usr/bin/env python3
"""Ratchet gate for AC authority-tier coverage.

Every acceptance criterion should eventually declare an authority *tier* (one of
:data:`common.meta.extension.generate_ac_registry.AC_TIERS`) — the property that says who
holds final decision authority over the behavior the AC describes, and therefore
what KIND of proof is valid for it (SSOT: ``common/meta/readme.md``).

The repo has ~1830 ACs that predate the tier attribute, so a hard "every AC must
declare a tier" check would fail CI on day one. This gate instead mirrors the
existing PROTECTION-FLOOR / AC-SCORE ratchet pattern: it maintains a persisted
baseline of the currently UNTAGGED ACs (the debt) and enforces two monotonic
rules:

- **No new untagged debt.** Every untagged AC in the current registry must be
  listed in the baseline. An AC that is NEW (or whose id is otherwise absent from
  the baseline) and lacks a tier fails the gate — newly added/modified ACs must
  declare their tier.
- **Debt may only shrink.** The baseline is never auto-grown. Tagging an AC (and
  removing it from the baseline via ``--update``) shrinks the debt; the
  ``--update`` action refuses to re-add any AC that is currently tagged, so the
  baseline can only move down.

Adopting a tier therefore costs nothing at the gate (a tagged AC is simply not in
the untagged set); the gate only bites when fresh untagged debt appears. This
lets the remaining ACs ratchet to a tier over time without a big-bang migration.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from common.meta.extension.generate_ac_registry import build_registry_entries

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASELINE = REPO_ROOT / "docs" / "ssot" / "ac-tier-baseline.json"


def current_untagged(repo_root: Path) -> set[str]:
    """Return the set of AC ids in the registry that declare no tier."""
    entries = build_registry_entries(epic_source=repo_root / "docs" / "project")
    return {ac_id for ac_id, entry in entries.items() if not entry.get("tier")}


def load_baseline(path: Path) -> set[str]:
    """Load the persisted untagged-debt baseline (set of AC ids)."""
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    untagged = payload.get("untagged", [])
    return {str(ac_id) for ac_id in untagged}


def write_baseline(path: Path, untagged: set[str]) -> None:
    """Persist the untagged-debt baseline as sorted JSON."""
    from common.meta.extension.ac_registry_format import sort_key

    payload: dict[str, Any] = {
        "_comment": (
            "Untagged-AC debt baseline for the authority-tier ratchet "
            "(tools/check_ac_tier_baseline.py). Lists ACs that predate the tier "
            "attribute and may stay untagged. Monotonic SHRINK-only: a NEW or "
            "MODIFIED AC missing from this list must declare a {tier:XX} marker. "
            "Bump down only via --update (which refuses to re-add a tagged AC)."
        ),
        "version": 1,
        "untagged": sorted(untagged, key=sort_key),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def evaluate(baseline: set[str], untagged: set[str]) -> dict[str, list[str]]:
    """Compare *untagged* (current) against *baseline*.

    - ``new_untagged``: untagged now but not in the baseline (the gate failure —
      new/modified ACs must declare a tier).
    - ``resolved``: in the baseline but tagged now (informational; shrink the
      baseline with ``--update``).
    """
    from common.meta.extension.ac_registry_format import sort_key

    new_untagged = sorted(untagged - baseline, key=sort_key)
    resolved = sorted(baseline - untagged, key=sort_key)
    return {"new_untagged": new_untagged, "resolved": resolved}


def ratcheted_baseline(baseline: set[str], untagged: set[str]) -> set[str]:
    """Shrink-only merge: drop tagged ACs, never add new untagged debt.

    The new baseline keeps only ids that are BOTH in the old baseline AND still
    untagged. A currently-untagged AC that was never in the baseline (new debt)
    is deliberately NOT adopted — ``--update`` cannot launder fresh debt.
    """
    return baseline & untagged


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ratchet authority-tier coverage on ACs (shrink-only debt baseline)."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Shrink the baseline to drop newly-tagged ACs (never adds new debt), then exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
    repo_root = args.repo_root.resolve()
    baseline_path = args.baseline or (
        repo_root / DEFAULT_BASELINE.relative_to(REPO_ROOT)
    )

    untagged = current_untagged(repo_root)
    baseline = load_baseline(baseline_path)

    if args.update:
        updated = ratcheted_baseline(baseline, untagged)
        write_baseline(baseline_path, updated)
        print(
            f"Updated tier baseline: {baseline_path} "
            f"({len(updated)} untagged AC(s), down from {len(baseline)})"
        )
        return 0

    findings = evaluate(baseline, untagged)
    print(
        "AC authority-tier ratchet: "
        f"{len(untagged)} untagged / baseline debt {len(baseline)}; "
        f"{len(findings['resolved'])} newly tagged."
    )
    if findings["new_untagged"]:
        for ac_id in findings["new_untagged"]:
            print(
                "::error title=AC tier ratchet::"
                f"{ac_id}: new/modified AC has no authority tier. Add a "
                "{tier:CODE-ONLY|CODE-LED|HU|LLM-LED|LLM-ONLY} marker at its definition site "
                "(see common/meta/readme.md).",
                file=sys.stderr,
            )
        print(
            f"[TIER] FAILED: {len(findings['new_untagged'])} AC(s) added/changed "
            "without an authority tier. The untagged-debt baseline may only "
            "shrink — declare a tier instead of growing it.",
            file=sys.stderr,
        )
        return 1

    print("[TIER] PASSED: no new untagged ACs; tier debt is non-increasing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
