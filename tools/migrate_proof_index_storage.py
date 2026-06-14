#!/usr/bin/env python3
"""One-shot migration to the conflict-free proof-index storage.

Two cross-cutting index artifacts are converted to their merge-safe form:

1. ``docs/ssot/ac-score-baseline.json`` (single central JSON object) ->
   ``docs/ssot/ac-score-baseline.jsonl`` (sorted, one AC per line). This is a
   PERSISTED ratchet: every score/metric/provenance is preserved EXACTLY so the
   ratchet floor never moves. Paired with ``merge=union`` in ``.gitattributes``,
   PRs adopting different ACs auto-merge.

2. ``docs/ssot/critical-proof-matrix.yaml`` is a DERIVED index: it is simply
   regenerated from the co-located ``@ac_proof(...)`` decorators via
   ``tools/generate_critical_proof_matrix.py``.

The script is idempotent. Re-run it at rebase time if sibling PRs (e.g. #1114 /
#1121) land first and reintroduce old-format entries: it picks up any remaining
``ac-score-baseline.json``, folds it into the JSONL ratchet (raise-only, so a
sibling's higher floor is kept), and regenerates the matrix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.ssot.ac_score_baseline_format import (  # noqa: E402
    load_jsonl,
    write_jsonl,
)
from common.ssot.generate_critical_proof_matrix import main as generate_matrix  # noqa: E402

REPO_ROOT = ROOT_DIR
LEGACY_BASELINE = REPO_ROOT / "docs" / "ssot" / "ac-score-baseline.json"
JSONL_BASELINE = REPO_ROOT / "docs" / "ssot" / "ac-score-baseline.jsonl"


def _raise_only_merge(
    existing: dict[str, dict], incoming: dict[str, dict]
) -> dict[str, dict]:
    """Keep the higher per-AC floor; never lower a baseline that already exists."""
    merged = dict(existing)
    for ac_id, record in incoming.items():
        prev = merged.get(ac_id)
        score = float(record.get("score", 0.0))
        if prev is None or score >= float(prev.get("score", 0.0)):
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
    status = migrate_baseline()
    if status != 0:
        return status
    # Regenerate the derived matrix from co-located @ac_proof declarations.
    return generate_matrix([])


if __name__ == "__main__":
    raise SystemExit(main())
