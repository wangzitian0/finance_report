"""Cassette graded field-accuracy eval gate (EPIC-023 AC23.8 / issue #1307).

Scores each committed statement cassette per-field against its SYNTHETIC ground
truth and ratchets a persisted per-case floor that may only go UP. The gate FAILS
when a refreshed cassette regresses below its floor — catching the "balance chain
still reconciles but a field is now wrong" drift the AC23.7 balance gate cannot
see.

Pure Python (no key/network/DB): runs in the lint job alongside
``check_llm_cassettes`` so it never perturbs the AC behavioral-score aggregator.
``--update`` raises the floor to the current scores (never lowers, refuses to
cement a regressed run) and is the local ``make llm-record`` companion.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common.ssot.cassette_eval_baseline import DEFAULT_BASELINE, load_jsonl, write_jsonl
from common.ssot.cassette_graded_eval import (
    GROUND_TRUTH_DIR,
    evaluate,
    load_cases,
    ratcheted_baseline,
)


def render(findings: dict[str, list[str]]) -> str:
    lines = ["Cassette graded eval ratchet"]
    for title, key in (
        ("Regressions", "regressions"),
        ("Missing ground truth", "missing"),
        ("Unbaselined cases (need a floor)", "new"),
    ):
        items = findings.get(key, [])
        lines.append(f"  {title}: {len(items)}")
        lines.extend(f"    - {item}" for item in items)
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cassette graded field-accuracy ratchet.")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Raise the per-case floor to the current scores (never lowers).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not GROUND_TRUTH_DIR.exists() or not any(GROUND_TRUTH_DIR.glob("*.truth.json")):
        print("[CASSETTE-EVAL] no ground-truth artifacts; nothing to grade.")
        return 0

    findings = evaluate(baseline_path=args.baseline)
    # A regressed score or a vanished baseline line blocks BOTH paths. An
    # unbaselined ("new") case blocks the GATE path too — otherwise adding a case
    # (or accidentally deleting its floor) would leave the ratchet silently
    # disabled for that case while CI stays green. `--update` is the sanctioned way
    # to adopt new cases, so it does NOT treat "new" as blocking.
    blocking_update = findings["regressions"] + findings["missing"]
    blocking_gate = blocking_update + findings["new"]

    if args.update:
        if blocking_update:
            for item in blocking_update:
                print(
                    f"::error title=Cassette graded eval::refusing --update: {item}",
                    file=sys.stderr,
                )
            return 1
        baseline = load_jsonl(args.baseline)
        current = findings["_current"]  # type: ignore[assignment]
        updated = ratcheted_baseline(baseline, current)  # type: ignore[arg-type]
        # Carry provenance from the cases for new floors.
        provenance = {
            c.case_id: f"{c.modality}/{c.institution_class}/{c.edge_condition}"
            for c in load_cases()
        }
        for case_id, record in updated["cases"].items():
            if not record.get("provenance"):
                record["provenance"] = provenance.get(case_id, "")
            record.setdefault("metric", "field-accuracy")
        write_jsonl(args.baseline, updated)
        print(f"Updated cassette-eval baseline: {args.baseline} ({len(updated['cases'])} case(s))")
        return 0

    print(render(findings))
    if blocking_gate:
        for item in blocking_gate:
            print(f"::error title=Cassette graded eval::{item}", file=sys.stderr)
        print(
            "[CASSETTE-EVAL] FAILED: a committed cassette regressed below its "
            "field-accuracy floor, lost its baselined floor, or has no floor yet. "
            "Re-record correctly via `make llm-record`, fix the ground truth if the "
            "statement legitimately changed, or adopt a new case's floor with "
            "`python tools/check_cassette_graded_eval.py --update`.",
            file=sys.stderr,
        )
        return 1
    print(
        "[CASSETTE-EVAL] PASSED: every committed cassette is baselined and meets "
        "its field-accuracy floor."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
