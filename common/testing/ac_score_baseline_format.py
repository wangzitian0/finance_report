"""Conflict-free storage for the AC behavioural-score ratchet baseline.

``docs/ssot/ac-score-baseline.json`` was a single central JSON object: every
behavioural-anchoring PR adopting a new AC edited the same ``acs`` mapping, so
independent PRs collided textually (false sharing) on one file and were forced
through a linear merge train.

This module stores the SAME ratchet floor as **sorted line-oriented JSONL**:
one JSON object per AC, one per line, sorted by ``ac_id``. Paired with a
``merge=union`` ``.gitattributes`` rule, two PRs that adopt DIFFERENT ACs
auto-merge by union concatenation; only two PRs editing the SAME AC produce a
(legitimate, semantic) conflict.

This is a STORAGE change only. The baseline remains a PERSISTED ratchet — it is
never regenerated from current scores (that would erase the floor). The ratchet
semantics live in :mod:`common.testing.check_ac_score_baseline`; this module only
loads/normalises/writes the on-disk form, and keeps an in-memory shape
(``{"version": 1, "acs": {ac_id: {...}}}``) identical to the legacy JSON so the
ratchet logic is untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASELINE_VERSION = 1

# Fields persisted per AC line, in a stable key order for deterministic output.
# ``ac_id`` leads so a human can scan the sorted file; the rest mirror the legacy
# per-AC record.
_LINE_KEY_ORDER = ("ac_id", "score", "metric", "provenance")


def _normalize_record(ac_id: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "ac_id": ac_id,
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


def acs_to_lines(acs: dict[str, dict[str, Any]]) -> list[str]:
    """Render the per-AC mapping as sorted, deterministic JSONL lines."""
    lines: list[str] = []
    for ac_id in sorted(acs):
        record = _ordered_line(_normalize_record(ac_id, acs[ac_id]))
        lines.append(json.dumps(record, sort_keys=False, ensure_ascii=False))
    return lines


def render_jsonl(payload: dict[str, Any]) -> str:
    """Render a ``{"version", "acs"}`` payload as the canonical JSONL text."""
    acs = payload.get("acs", {})
    if not isinstance(acs, dict):
        acs = {}
    body = "\n".join(acs_to_lines(acs))
    return (body + "\n") if body else ""


def load_jsonl(path: Path) -> dict[str, Any]:
    """Load a JSONL baseline into the in-memory ``{"version", "acs"}`` shape.

    Blank lines are ignored (union merges can leave them). A duplicate ``ac_id``
    is a real same-AC conflict that git's union merge surfaces by keeping both
    lines; we fail loudly rather than silently picking one floor.
    """
    acs: dict[str, dict[str, Any]] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSONL line: {exc}") from exc
        if not isinstance(record, dict) or "ac_id" not in record:
            raise ValueError(
                f"{path}:{lineno}: each line must be a JSON object with an 'ac_id'"
            )
        ac_id = str(record["ac_id"])
        if ac_id in acs:
            raise ValueError(
                f"{path}:{lineno}: duplicate ac_id {ac_id!r} — resolve the "
                "same-AC ratchet conflict (keep the higher floor)"
            )
        acs[ac_id] = {
            "score": round(float(record.get("score", 0.0)), 6),
            "metric": record.get("metric", ""),
            "provenance": record.get("provenance", ""),
        }
    return {"version": BASELINE_VERSION, "acs": acs}


def write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Write the payload as canonical, sorted JSONL (deterministic order)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_jsonl(payload), encoding="utf-8")


def normalize_file(path: Path) -> dict[str, Any]:
    """Re-sort and re-normalise an on-disk JSONL baseline in place.

    Contributors append a new AC line anywhere; running this collapses the file
    back to sorted, canonical order so union merges never leave churn.
    """
    payload = load_jsonl(path)
    write_jsonl(path, payload)
    return payload
