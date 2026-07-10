"""Conflict-free storage for the cassette graded-eval ratchet baseline.

EPIC-023 AC23.8 / issue #1307. This mirrors
:mod:`common.testing.ac_score_baseline_format`: the per-case score FLOOR is stored
as **sorted, line-oriented JSONL** (one JSON object per case, one per line,
sorted by ``case_id``). Paired with a ``merge=union`` ``.gitattributes`` rule,
two PRs that ratchet DIFFERENT cases auto-merge by union concatenation; only two
PRs editing the SAME case produce a (legitimate, semantic) conflict.

This is a STORAGE module only. The baseline is a PERSISTED ratchet floor — it is
never regenerated from current scores (that would erase the floor). The ratchet
semantics live in :mod:`common.testing.cassette_graded_eval`; this module only
loads/normalises/writes the on-disk form into the in-memory shape
``{"version": 1, "cases": {case_id: {...}}}``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = (
    REPO_ROOT / "common" / "testing" / "fixtures" / "cassette-eval-baseline.jsonl"
)
CORPUS_COUNT_BASELINE = (
    REPO_ROOT
    / "common"
    / "testing"
    / "fixtures"
    / "cassette-corpus-count-baseline.json"
)

BASELINE_VERSION = 1

# Fields persisted per case line, in a stable key order for deterministic output.
_LINE_KEY_ORDER = ("case_id", "score", "metric", "provenance")


def _normalize_record(case_id: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "score": round(float(record.get("score", 0.0)), 6),
        "metric": record.get("metric", ""),
        "provenance": record.get("provenance", ""),
    }


def _ordered_line(record: dict[str, Any]) -> dict[str, Any]:
    ordered = {key: record[key] for key in _LINE_KEY_ORDER if key in record}
    for key, value in record.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def cases_to_lines(cases: dict[str, dict[str, Any]]) -> list[str]:
    """Render the per-case mapping as sorted, deterministic JSONL lines."""
    lines: list[str] = []
    for case_id in sorted(cases):
        record = _ordered_line(_normalize_record(case_id, cases[case_id]))
        lines.append(json.dumps(record, sort_keys=False, ensure_ascii=False))
    return lines


def render_jsonl(payload: dict[str, Any]) -> str:
    """Render a ``{"version", "cases"}`` payload as the canonical JSONL text."""
    cases = payload.get("cases", {})
    if not isinstance(cases, dict):
        cases = {}
    body = "\n".join(cases_to_lines(cases))
    return (body + "\n") if body else ""


def load_jsonl(path: Path) -> dict[str, Any]:
    """Load a JSONL baseline into the in-memory ``{"version", "cases"}`` shape.

    Blank lines are ignored (union merges can leave them). A duplicate ``case_id``
    is a real same-case conflict that git's union merge surfaces by keeping both
    lines; we fail loudly rather than silently picking one floor.
    """
    if not path.exists():
        return {"version": BASELINE_VERSION, "cases": {}}
    cases: dict[str, dict[str, Any]] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSONL line: {exc}") from exc
        if not isinstance(record, dict) or "case_id" not in record:
            raise ValueError(
                f"{path}:{lineno}: each line must be a JSON object with a 'case_id'"
            )
        case_id = str(record["case_id"])
        if case_id in cases:
            raise ValueError(
                f"{path}:{lineno}: duplicate case_id {case_id!r} — resolve the "
                "same-case ratchet conflict (keep the higher floor)"
            )
        cases[case_id] = {
            "score": round(float(record.get("score", 0.0)), 6),
            "metric": record.get("metric", ""),
            "provenance": record.get("provenance", ""),
        }
    return {"version": BASELINE_VERSION, "cases": cases}


def write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Write the payload as canonical, sorted JSONL (deterministic order)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_jsonl(payload), encoding="utf-8")


def normalize_file(path: Path) -> dict[str, Any]:
    """Re-sort and re-normalise an on-disk JSONL baseline in place."""
    payload = load_jsonl(path)
    write_jsonl(path, payload)
    return payload


# --------------------------------------------------------------------------- #
# Corpus-count floor: a SEPARATE raise-only ratchet from the per-case JSONL
# above. The per-case ratchet's "missing" finding only fires when a case's
# baseline LINE outlives its ground-truth file; a commit that removes a
# ground-truth file AND its baseline line together leaves no per-case floor to
# detect the loss — the corpus silently shrinks with every existing check
# green. This floor is independently persisted so only an explicit
# `--update` (never a same-commit deletion) can raise it.
# --------------------------------------------------------------------------- #
def load_corpus_count_floor(path: Path = CORPUS_COUNT_BASELINE) -> int:
    """Load the persisted corpus-count floor; a missing file is a zero floor.

    A missing file defaults to 0, but a PRESENT ``min_cases`` that is not a
    non-negative integer is a hard error rather than a silent coercion:
    ``int(-5)`` or ``int(1.5)`` would silently weaken or disable the ratchet.
    """
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    min_cases = payload.get("min_cases", 0)
    if isinstance(min_cases, bool) or not isinstance(min_cases, int) or min_cases < 0:
        raise ValueError(
            f"{path}: 'min_cases' must be a non-negative integer, got {min_cases!r}"
        )
    return min_cases


def write_corpus_count_floor(path: Path, min_cases: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": (
            "Raise-only floor for the number of graded-eval cases "
            "(llm_cassettes/ground_truth/*.truth.json). Independent of "
            "cassette-eval-baseline.jsonl's per-case floors so a commit that "
            "removes a case's ground-truth file AND its baseline line together "
            "cannot silently shrink the corpus. Raise only via "
            "`python tools/check_cassette_graded_eval.py --update`."
        ),
        "min_cases": min_cases,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
