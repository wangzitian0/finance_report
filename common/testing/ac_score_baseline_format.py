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

from pathlib import Path
from typing import Any

from common.testing import jsonl_baseline

BASELINE_VERSION = jsonl_baseline.BASELINE_VERSION


def acs_to_lines(acs: dict[str, dict[str, Any]]) -> list[str]:
    """Render the per-AC mapping as sorted, deterministic JSONL lines."""
    return jsonl_baseline.records_to_lines(acs, identifier_key="ac_id")


def render_jsonl(payload: dict[str, Any]) -> str:
    """Render a ``{"version", "acs"}`` payload as the canonical JSONL text."""
    return jsonl_baseline.render_jsonl(
        payload, identifier_key="ac_id", collection_key="acs"
    )


def load_jsonl(path: Path) -> dict[str, Any]:
    """Load a JSONL baseline into the in-memory ``{"version", "acs"}`` shape.

    Blank lines are ignored (union merges can leave them). A duplicate ``ac_id``
    is a real same-AC conflict that git's union merge surfaces by keeping both
    lines; we fail loudly rather than silently picking one floor.
    """
    return jsonl_baseline.load_jsonl(path, identifier_key="ac_id", collection_key="acs")


def write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Write the payload as canonical, sorted JSONL (deterministic order)."""
    jsonl_baseline.write_jsonl(
        path, payload, identifier_key="ac_id", collection_key="acs"
    )


def normalize_file(path: Path) -> dict[str, Any]:
    """Re-sort and re-normalise an on-disk JSONL baseline in place.

    Contributors append a new AC line anywhere; running this collapses the file
    back to sorted, canonical order so union merges never leave churn.
    """
    return jsonl_baseline.normalize_file(
        path, identifier_key="ac_id", collection_key="acs"
    )
