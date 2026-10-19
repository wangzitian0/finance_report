"""Ratchet gate for AC behavioral-evidence scores.

Generalises the existing line-coverage baseline ratchet (``unified-coverage.json``)
to per-AC behavioral scores. Two orthogonal axes are enforced:

- L2 (hard, always): every AC in the baseline must show ``code == pass`` in the
  current run. A failing/skipped/errored test cannot be bought back by a score.
- L3 (ratchet): the current score for each baselined AC must not drop below its
  baseline (minus a tiny epsilon). The baseline only ever moves *up*, via
  ``--update``; it is never auto-lowered.

New ACs present in the current aggregate but absent from the baseline are
reported as informational — adopt them with ``--update`` when ready. This lets
each AC mature from informational to enforced on its own schedule, without a
big-bang migration.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from common.meta.base.gate_cli import run_gate
from common.testing.ac_score_baseline_format import load_jsonl, write_jsonl
from common.testing.jsonl_baseline import ratcheted_raise_only_merge

REPO_ROOT = Path(__file__).resolve().parents[2]
# The baseline is stored as conflict-free sorted JSONL (one AC per line) so two
# PRs adopting *different* ACs auto-merge via `merge=union` instead of colliding
# on one central JSON object. See common/testing/ac_score_baseline_format.py. This
# is a STORAGE change only — the baseline is still a persisted ratchet floor and
# is never regenerated from current scores.
DEFAULT_BASELINE = REPO_ROOT / "common" / "testing" / "data" / "ac-score-baseline.jsonl"
BASELINE_UPDATE_MODE = "raise-only"

# Floating-point slack so an identical re-measurement never trips the gate.
EPSILON = 1e-6


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _load_baseline(path: Path) -> dict[str, Any]:
    """Load the persisted ratchet baseline from sorted JSONL."""
    if not path.exists():
        return {"version": 1, "acs": {}}
    return load_jsonl(path)


def _acs(payload: dict[str, Any]) -> dict[str, Any]:
    acs = payload.get("acs", {})
    return acs if isinstance(acs, dict) else {}


def evaluate(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    """Return categorised findings comparing *current* evidence to *baseline*."""
    base_acs = _acs(baseline)
    cur_acs = _acs(current)

    regressions: list[str] = []
    missing: list[str] = []
    non_pass: list[str] = []
    new_acs: list[str] = []

    for ac_id, base in sorted(base_acs.items()):
        cur = cur_acs.get(ac_id)
        if cur is None:
            missing.append(f"{ac_id}: baselined AC has no evidence in this run")
            continue
        if cur.get("code") != "pass":
            non_pass.append(f"{ac_id}: code={cur.get('code')!r} (must be 'pass')")
        base_score = float(base.get("score", 0.0))
        cur_score = float(cur.get("score", 0.0))
        if cur_score < base_score - EPSILON:
            regressions.append(
                f"{ac_id}: score {cur_score:.4f} < baseline {base_score:.4f} "
                f"(delta {cur_score - base_score:+.4f})"
            )

    for ac_id in sorted(cur_acs):
        if ac_id not in base_acs:
            new_acs.append(f"{ac_id}: new AC evidence (adopt via --update)")

    return {
        "regressions": regressions,
        "missing": missing,
        "non_pass": non_pass,
        "new": new_acs,
    }


def ratcheted_baseline(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Raise-only merge: new baseline = max(old, current) per AC, plus new ACs."""
    return ratcheted_raise_only_merge(baseline, current, collection_key="acs")


def render(findings: dict[str, list[str]]) -> str:
    lines = ["AC score ratchet"]
    for title, key in (
        ("Regressions", "regressions"),
        ("Missing evidence", "missing"),
        ("Non-passing code", "non_pass"),
        ("New (informational)", "new"),
    ):
        items = findings[key]
        lines.append(f"  {title}: {len(items)}")
        lines.extend(f"    - {item}" for item in items)
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ratchet AC behavioral scores.")
    parser.add_argument("current", type=Path, help="Aggregated current evidence JSON.")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Raise the baseline to the current scores (never lowers).",
    )
    return parser.parse_args(argv)


def _run_command(argv: Sequence[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    current = _load_json(args.current)
    baseline = _load_baseline(args.baseline)

    findings = evaluate(baseline, current)

    if args.update:
        # Never cement a broken run: a regression / missing evidence / non-pass
        # code in the current aggregate must block the baseline raise.
        blocking = findings["regressions"] + findings["missing"] + findings["non_pass"]
        if blocking:
            for item in blocking:
                print(
                    f"::error title=AC score ratchet::refusing --update: {item}",
                    file=sys.stderr,
                )
            return 1
        updated = ratcheted_baseline(baseline, current)
        write_jsonl(args.baseline, updated)
        print(f"Updated baseline: {args.baseline} ({len(updated['acs'])} AC(s))")
        return 0

    print(render(findings))
    blocking = findings["regressions"] + findings["missing"] + findings["non_pass"]
    if blocking:
        for item in blocking:
            print(f"::error title=AC score ratchet::{item}", file=sys.stderr)
        return 1
    print("AC score ratchet passed.")
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
        "AC-SCORE-BASELINE", lambda _repo_root: findings, [], failure_status=status
    )


if __name__ == "__main__":
    raise SystemExit(main())
