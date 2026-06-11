"""End-to-end contract for the AC behavioral-evidence pipeline.

Proves the whole chain hermetically (no DB, no app deps):

    test emits (code, score, metric, comment, provenance)
        -> junit-xml <property>
        -> common.ssot.ac_evidence_aggregate  (reduce per AC)
        -> common.ssot.check_ac_score_baseline (L2 + L3 ratchet gate)

Covers AC8.13.* hygiene siblings only indirectly; this file is the executable
specification for the mechanism itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from xml.etree import ElementTree

import pytest

from common.ssot import ac_evidence_aggregate as agg
from common.ssot import check_ac_score_baseline as ratchet
from common.testing.ac_evidence import (
    PROPERTY_KEY,
    ACEvidence,
    ACEvidenceError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# Schema / validation                                                         #
# --------------------------------------------------------------------------- #
def _valid_kwargs(**overrides):
    base = dict(
        ac_id="AC4.1.4",
        code="pass",
        score=0.9,
        metric="description_similarity_pct",
        comment="measured",
        provenance="deterministic",
    )
    base.update(overrides)
    return base


def test_valid_record_round_trips():
    evidence = ACEvidence(**_valid_kwargs())
    restored = ACEvidence.from_json(evidence.to_json())
    assert restored == evidence


@pytest.mark.parametrize(
    "overrides",
    [
        {"ac_id": "AC4.1"},  # not ACx.y.z
        {"ac_id": "4.1.4"},  # missing prefix
        {"code": "passed"},  # not in VALID_CODES
        {"score": 1.5},  # > 1.0
        {"score": -0.1},  # < 0.0
        {"score": True},  # bool is not a score
        {"metric": "  "},  # honesty anchor: must name the yardstick
        {"comment": ""},  # must explain
        {"provenance": "vibes"},  # not a known provenance
        {"provenance": "golden_fixture@"},  # empty ref
    ],
)
def test_invalid_records_are_rejected(overrides):
    with pytest.raises(ACEvidenceError):
        ACEvidence(**_valid_kwargs(**overrides))


def test_golden_fixture_provenance_with_ref_is_accepted():
    evidence = ACEvidence(**_valid_kwargs(provenance="golden_fixture@abc123"))
    assert evidence.provenance == "golden_fixture@abc123"


def test_from_json_rejects_non_object_and_missing_fields():
    with pytest.raises(ACEvidenceError):
        ACEvidence.from_json("[1, 2, 3]")
    with pytest.raises(ACEvidenceError):
        ACEvidence.from_json(json.dumps({"ac_id": "AC1.1.1"}))


# --------------------------------------------------------------------------- #
# Aggregation                                                                 #
# --------------------------------------------------------------------------- #
def _junit_with(records: list[dict], path: Path) -> Path:
    """Write a minimal junit-xml carrying the given ac_evidence properties."""
    suite = ElementTree.Element("testsuites")
    testsuite = ElementTree.SubElement(
        suite, "testsuite", name="s", tests=str(len(records))
    )
    for index, record in enumerate(records):
        case = ElementTree.SubElement(testsuite, "testcase", name=f"t{index}")
        props = ElementTree.SubElement(case, "properties")
        ElementTree.SubElement(
            props,
            "property",
            name=PROPERTY_KEY,
            value=ACEvidence(**record).to_json(),
        )
    ElementTree.ElementTree(suite).write(path, encoding="unicode")
    return path


def test_aggregate_keeps_best_passing_score(tmp_path):
    junit = _junit_with(
        [
            _valid_kwargs(score=0.7),
            _valid_kwargs(score=0.95),  # best passing wins
        ],
        tmp_path / "j.xml",
    )
    result = agg.aggregate([junit])
    assert result["acs"]["AC4.1.4"]["score"] == 0.95
    assert result["acs"]["AC4.1.4"]["code"] == "pass"


def test_aggregate_reports_worst_code(tmp_path):
    junit = _junit_with(
        [
            _valid_kwargs(score=0.9, code="pass"),
            _valid_kwargs(score=0.0, code="fail"),  # worst code surfaces
        ],
        tmp_path / "j.xml",
    )
    result = agg.aggregate([junit])
    assert result["acs"]["AC4.1.4"]["code"] == "fail"


# --------------------------------------------------------------------------- #
# Ratchet gate                                                                #
# --------------------------------------------------------------------------- #
def _payload(ac_id: str, score: float, code: str = "pass") -> dict:
    return {
        "version": 1,
        "acs": {
            ac_id: {
                "code": code,
                "score": score,
                "metric": "m",
                "comment": "c",
                "provenance": "deterministic",
            }
        },
    }


def test_ratchet_passes_on_equal_and_improvement():
    baseline = {"version": 1, "acs": {"AC4.1.4": {"score": 0.9}}}
    assert ratchet.evaluate(baseline, _payload("AC4.1.4", 0.9))["regressions"] == []
    assert ratchet.evaluate(baseline, _payload("AC4.1.4", 0.95))["regressions"] == []


def test_ratchet_fails_on_regression():
    baseline = {"version": 1, "acs": {"AC4.1.4": {"score": 0.9}}}
    findings = ratchet.evaluate(baseline, _payload("AC4.1.4", 0.8))
    assert len(findings["regressions"]) == 1


def test_ratchet_fails_on_missing_evidence():
    baseline = {"version": 1, "acs": {"AC4.1.4": {"score": 0.9}}}
    findings = ratchet.evaluate(baseline, {"version": 1, "acs": {}})
    assert len(findings["missing"]) == 1


def test_ratchet_fails_on_non_pass_code():
    baseline = {"version": 1, "acs": {"AC4.1.4": {"score": 0.9}}}
    findings = ratchet.evaluate(baseline, _payload("AC4.1.4", 0.95, code="fail"))
    assert len(findings["non_pass"]) == 1


def test_ratchet_reports_new_ac_as_informational():
    findings = ratchet.evaluate({"version": 1, "acs": {}}, _payload("AC9.9.9", 0.5))
    assert findings["regressions"] == []
    assert len(findings["new"]) == 1


def test_update_is_raise_only():
    baseline = {"version": 1, "acs": {"AC4.1.4": {"score": 0.9}}}
    # A lower current score must NOT lower the baseline.
    lowered = ratchet.ratcheted_baseline(baseline, _payload("AC4.1.4", 0.5))
    assert lowered["acs"]["AC4.1.4"]["score"] == 0.9
    # A higher one raises it.
    raised = ratchet.ratcheted_baseline(baseline, _payload("AC4.1.4", 0.95))
    assert raised["acs"]["AC4.1.4"]["score"] == 0.95


# --------------------------------------------------------------------------- #
# Live emission: record_property -> junit -> aggregate (no app deps)          #
# --------------------------------------------------------------------------- #
def test_record_property_emission_flows_to_aggregate(tmp_path):
    test_file = tmp_path / "test_emit.py"
    test_file.write_text(
        textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from common.testing.ac_evidence import record_ac_evidence

            def test_emits(record_property):
                record_ac_evidence(
                    record_property,
                    ac_id="AC1.1.1",
                    score=0.5,
                    metric="demo",
                    comment="live emission",
                    provenance="deterministic",
                )
            """
        ),
        encoding="utf-8",
    )
    junit = tmp_path / "out.xml"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "-p",
            "no:xdist",
            "-o",
            "addopts=",
            "-q",
            f"--junit-xml={junit}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = agg.aggregate([junit])
    assert result["acs"]["AC1.1.1"]["score"] == 0.5
    assert result["acs"]["AC1.1.1"]["code"] == "pass"


def test_committed_baseline_matches_schema():
    """The seeded baseline must be loadable and well-formed."""
    baseline = json.loads(
        (REPO_ROOT / "docs" / "ssot" / "ac-score-baseline.json").read_text()
    )
    assert baseline["version"] == 1
    assert "AC4.1.4" in baseline["acs"]
    assert 0.0 <= baseline["acs"]["AC4.1.4"]["score"] <= 1.0
