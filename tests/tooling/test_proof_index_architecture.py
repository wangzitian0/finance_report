"""AC8.13.138: conflict-free storage for the PERSISTED ratchet baseline.

The cross-cutting aggregate VIEWS (critical-proof matrix, vision-proof matrix,
EPIC status) are no longer committed-materialized — they are derived on demand
from the one AC-keyed graph and gated by ``tools/check_ac_index.py`` (covered by
AC8.13.139 in ``test_ac_index_consistency.py``). This module now owns only the
one PERSISTED artifact: ``docs/ssot/ac-score-baseline.jsonl`` is stored as
sorted, line-oriented JSONL with a ``merge=union`` gitattribute, loads into the
shape the ratchet uses, and the ratchet still fails on regression / missing
evidence / non-pass code.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.testing import (
    ac_score_baseline_format as baseline_format,
    check_ac_score_baseline as ratchet,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "docs" / "ssot" / "ac-score-baseline.jsonl"
GITATTRIBUTES = REPO_ROOT / ".gitattributes"


def test_AC8_13_138_baseline_is_sorted_jsonl_with_union_merge() -> None:
    """Baseline is sorted, one-AC-per-line JSONL guarded by merge=union."""
    lines = [line for line in BASELINE.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, "baseline must not be empty"
    ac_ids = []
    for line in lines:
        record = json.loads(line)  # each line is one standalone JSON object
        assert "ac_id" in record
        ac_ids.append(record["ac_id"])
    assert ac_ids == sorted(ac_ids), "lines must be sorted by ac_id"
    assert len(ac_ids) == len(set(ac_ids)), "no duplicate ac_id lines"

    gitattrs = GITATTRIBUTES.read_text(encoding="utf-8")
    assert "docs/ssot/ac-score-baseline.jsonl merge=union" in gitattrs


def test_AC8_13_138_baseline_loads_to_legacy_shape() -> None:
    """The JSONL form loads into the same {"version","acs"} shape the ratchet uses."""
    payload = baseline_format.load_jsonl(BASELINE)
    assert payload["version"] == 1
    assert isinstance(payload["acs"], dict) and payload["acs"]
    for record in payload["acs"].values():
        assert set(record) == {"score", "metric", "provenance"}


def _current(ac_id: str, score: float, code: str = "pass") -> dict:
    return {
        "version": 1,
        "acs": {
            ac_id: {
                "code": code,
                "score": score,
                "metric": "m",
                "provenance": "deterministic",
            }
        },
    }


def test_AC8_13_138_ratchet_still_fails_on_regression_and_missing_ac(tmp_path) -> None:
    """Ratchet semantics are UNCHANGED by the JSONL storage migration."""
    baseline = tmp_path / "b.jsonl"
    baseline_format.write_jsonl(
        baseline,
        {
            "version": 1,
            "acs": {"AC1.1.1": {"score": 0.8, "metric": "m", "provenance": "deterministic"}},
        },
    )

    # A score below the floor is a regression -> fail.
    regress = tmp_path / "regress.json"
    regress.write_text(json.dumps(_current("AC1.1.1", 0.5)), encoding="utf-8")
    assert ratchet.main([str(regress), "--baseline", str(baseline)]) == 1

    # Baselined AC with no evidence this run -> missing -> fail.
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps(_current("AC9.9.9", 0.99)), encoding="utf-8")
    assert ratchet.main([str(missing), "--baseline", str(baseline)]) == 1

    # Non-pass code cannot be bought back by a high score -> fail.
    non_pass = tmp_path / "nonpass.json"
    non_pass.write_text(json.dumps(_current("AC1.1.1", 0.99, code="fail")), encoding="utf-8")
    assert ratchet.main([str(non_pass), "--baseline", str(baseline)]) == 1

    # Meeting the floor with a passing code -> ok.
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_current("AC1.1.1", 0.85)), encoding="utf-8")
    assert ratchet.main([str(ok), "--baseline", str(baseline)]) == 0


def test_AC8_13_138_update_refuses_to_cement_a_regression(tmp_path) -> None:
    """--update must not lower the floor on a regressed/non-pass run."""
    baseline = tmp_path / "b.jsonl"
    baseline_format.write_jsonl(
        baseline,
        {
            "version": 1,
            "acs": {"AC1.1.1": {"score": 0.8, "metric": "m", "provenance": "deterministic"}},
        },
    )
    regress = tmp_path / "regress.json"
    regress.write_text(json.dumps(_current("AC1.1.1", 0.5)), encoding="utf-8")
    assert ratchet.main([str(regress), "--baseline", str(baseline), "--update"]) == 1
    # Floor unchanged after the refused update.
    assert baseline_format.load_jsonl(baseline)["acs"]["AC1.1.1"]["score"] == 0.8
