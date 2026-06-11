"""Aggregate AC behavioral-evidence from junit-xml into a per-AC summary.

CI already emits ``--junit-xml`` for every test stage. Each test may attach one
or more ``ac_evidence`` properties (see :mod:`common.testing.ac_evidence`). This
module reads those properties back and reduces them to one record per AC:

- ``code``  = the *worst* code seen across all rows, so a single failure surfaces
  and cannot be masked by a later passing row (the L2 gate stays honest);
- ``score`` = the best (max) score observed among *passing* rows;
- ``metric``/``comment``/``provenance`` taken from the row that owns the max score.

The output JSON is the input to :mod:`common.ssot.check_ac_score_baseline`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from common.testing.ac_evidence import PROPERTY_KEY, ACEvidence, ACEvidenceError

REPO_ROOT = Path(__file__).resolve().parents[2]

# Worst-first severity so the reduced ``code`` reflects the strongest failure.
_CODE_SEVERITY = {"error": 3, "fail": 2, "skip": 1, "pass": 0}


def iter_evidence(junit_paths: list[Path]) -> list[ACEvidence]:
    """Parse every ``ac_evidence`` property from the given junit-xml files."""
    records: list[ACEvidence] = []
    for path in junit_paths:
        if not path.exists():
            continue
        tree = ElementTree.parse(path)
        for prop in tree.iter("property"):
            if prop.get("name") != PROPERTY_KEY:
                continue
            value = prop.get("value")
            if value is None:
                continue
            records.append(ACEvidence.from_json(value))
    return records


def reduce_by_ac(records: list[ACEvidence]) -> dict[str, dict[str, Any]]:
    """Reduce raw evidence rows to one summary record per AC id."""
    summary: dict[str, dict[str, Any]] = {}
    for record in records:
        current = summary.get(record.ac_id)
        if current is None:
            summary[record.ac_id] = _as_summary(record)
            continue
        # Worst code wins; best *passing* score wins.
        if _CODE_SEVERITY[record.code] > _CODE_SEVERITY[current["code"]]:
            current["code"] = record.code
        passing = record.code == "pass"
        if passing and (not current["_has_pass"] or record.score > current["score"]):
            current.update(_as_summary(record))
    for record in summary.values():
        record.pop("_has_pass", None)
    return summary


def _as_summary(record: ACEvidence) -> dict[str, Any]:
    return {
        "code": record.code,
        "score": round(float(record.score), 6),
        "metric": record.metric,
        "comment": record.comment,
        "provenance": record.provenance,
        "_has_pass": record.code == "pass",
    }


def aggregate(junit_paths: list[Path]) -> dict[str, Any]:
    records = iter_evidence(junit_paths)
    return {"version": 1, "acs": reduce_by_ac(records)}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate AC evidence from junit-xml."
    )
    parser.add_argument(
        "junit",
        nargs="+",
        type=Path,
        help="junit-xml file(s) emitted by the test run(s).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the aggregate JSON here (default: stdout).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        result = aggregate(args.junit)
    except ACEvidenceError as exc:
        print(f"::error title=AC evidence::malformed evidence: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(
            f"Wrote AC evidence aggregate: {args.output} ({len(result['acs'])} AC(s))"
        )
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
