#!/usr/bin/env python3
"""One-shot migration to the conflict-free proof-index storage.

The persisted behavioural-score ratchet baseline is converted to its merge-safe
form: ``docs/ssot/ac-score-baseline.json`` (single central JSON object) ->
``docs/ssot/ac-score-baseline.jsonl`` (sorted, one AC per line). Each AC's
score/metric/provenance is carried over unchanged (scores are re-serialised
through ``float()`` and rounded to 6 decimal places, the same normalisation the
ratchet's own ``--update`` path already applies, so the floor never moves).
Paired with ``merge=union`` in ``.gitattributes``, PRs adopting different ACs
auto-merge.

The cross-cutting aggregate VIEWS (critical-proof matrix, vision-proof matrix,
EPIC status) are no longer committed at all: they are DERIVED on demand from the
one AC-keyed graph (``common/testing/ac_graph.py``) and gated by
``tools/check_ac_index.py``, so this migration no longer regenerates any matrix
file.

The script is idempotent. Re-run it at rebase time if sibling PRs land first and
reintroduce an old-format ``ac-score-baseline.json``: it folds the legacy file
into the JSONL ratchet (raise-only, so a sibling's higher floor is kept).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing.ac_score_baseline_format import (  # noqa: E402
    load_jsonl,
    write_jsonl,
)

REPO_ROOT = ROOT_DIR
LEGACY_BASELINE = REPO_ROOT / "docs" / "ssot" / "ac-score-baseline.json"
JSONL_BASELINE = REPO_ROOT / "docs" / "ssot" / "ac-score-baseline.jsonl"


def _raise_only_merge(existing: dict[str, dict], incoming: dict[str, dict]) -> dict[str, dict]:
    """Keep the higher per-AC floor; never lower a baseline that already exists.

    On a tie the EXISTING record wins: an equal incoming score must not churn
    the metric/provenance already on the head baseline. Only a strictly-higher
    incoming score raises (and replaces) the floor.
    """
    merged = dict(existing)
    for ac_id, record in incoming.items():
        prev = merged.get(ac_id)
        score = float(record.get("score", 0.0))
        if prev is not None and score <= float(prev.get("score", 0.0)):
            continue
        merged[ac_id] = {
            "score": round(score, 6),
            "metric": record.get("metric", ""),
            "provenance": record.get("provenance", ""),
        }
    return merged


def migrate_baseline() -> int:
    """Fold any legacy JSON baseline into the JSONL ratchet, preserving floors."""
    existing: dict[str, dict] = {}
    if JSONL_BASELINE.exists():
        existing = load_jsonl(JSONL_BASELINE)["acs"]

    incoming: dict[str, dict] = {}
    if LEGACY_BASELINE.exists():
        legacy = json.loads(LEGACY_BASELINE.read_text(encoding="utf-8"))
        incoming = legacy.get("acs", {}) if isinstance(legacy, dict) else {}

    merged = _raise_only_merge(existing, incoming)
    write_jsonl(JSONL_BASELINE, {"version": 1, "acs": merged})

    if LEGACY_BASELINE.exists():
        LEGACY_BASELINE.unlink()
        print(f"Removed legacy baseline: {LEGACY_BASELINE.name}")
    print(f"Wrote {JSONL_BASELINE.name} ({len(merged)} AC(s)).")
    return 0


def main() -> int:
    # The aggregate views are derived on demand from the AC graph and never
    # committed, so the only persisted artifact to migrate is the JSONL ratchet.
    return migrate_baseline()


if __name__ == "__main__":
    raise SystemExit(main())
