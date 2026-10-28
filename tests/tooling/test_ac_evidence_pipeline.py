"""Contract for the AC behavioral-evidence emission and TraceRecord bridge."""

from __future__ import annotations

import json

import pytest

from common.testing.ac_evidence import (
    PROPERTY_KEY,
    ACEvidence,
    ACEvidenceError,
    record_ac_evidence,
)


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
    "ac_id",
    [
        "AC-ledger.2.1",
        "AC-reconciliation.fx-transfer.1",
        "AC-reconciliation.matching-core.4",
        "AC-audit.39.2",
    ],
)
def test_package_scoped_word_entity_group_ids_are_valid(ac_id):
    """A package-scoped id's group segment may be a word-entity slug, not
    just a number — regression for a group of tools that all shared this
    same over-strict numeric-only pattern (migration closeout wave 3,
    #1664)."""
    evidence = ACEvidence(**_valid_kwargs(ac_id=ac_id))
    assert evidence.ac_id == ac_id


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
        {"provenance": "golden_fixture"},  # bare form loses the honesty anchor
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


def test_record_ac_evidence_emits_serialised_record():
    captured: dict[str, str] = {}

    def fake_record_property(key, value):
        captured[key] = value

    evidence = record_ac_evidence(
        fake_record_property,
        ac_id="AC1.1.1",
        score=0.5,
        metric="m",
        comment="c",
        provenance="deterministic",
    )
    assert captured[PROPERTY_KEY] == evidence.to_json()
    assert ACEvidence.from_json(captured[PROPERTY_KEY]).ac_id == "AC1.1.1"


def test_record_ac_evidence_can_shadow_the_same_measurement_as_trace_record():
    from common.audit.extension import TraceJUnitAdapter, TraceRecordCodec

    captured: dict[str, str] = {}

    record_ac_evidence(
        lambda name, value: captured.__setitem__(name, value),
        ac_id="AC-testing.1.1",
        score=0.9,
        metric="accuracy",
        comment="fixture",
        provenance="deterministic",
    )

    assert ACEvidence.from_json(captured[PROPERTY_KEY]).score == 0.9
    trace = TraceRecordCodec.decode(captured[TraceJUnitAdapter.PROPERTY_KEY])
    assert trace.target.id == "AC-testing.1.1"
    assert trace.assertion.kind == "ac_proof"
    assert trace.assertion.id == "AC-testing.1.1"
    assert trace.assertion.id != "accuracy"
    assert trace.authority.package == "testing"
    assert trace.authority.tier == "CODE-ONLY"
    assert trace.scope.kind.value == "repository"
    # record_property runs before pytest knows the final testcase outcome.
    assert trace.result.value == "unproven"


def test_legacy_ac_evidence_is_not_guessed_into_a_trace_authority():
    from common.audit.extension import TraceJUnitAdapter

    captured: dict[str, str] = {}
    record_ac_evidence(
        lambda name, value: captured.__setitem__(name, value),
        ac_id="AC1.1.1",
        score=0.9,
        metric="accuracy",
        comment="legacy fixture",
        provenance="deterministic",
    )

    assert TraceJUnitAdapter.PROPERTY_KEY not in captured


def test_from_json_rejects_invalid_json():
    with pytest.raises(ACEvidenceError):
        ACEvidence.from_json("{not json")


def test_golden_fixture_at_ref_round_trips():
    evidence = ACEvidence(**_valid_kwargs(provenance="golden_fixture@deadbeef"))
    assert (
        ACEvidence.from_json(evidence.to_json()).provenance == "golden_fixture@deadbeef"
    )
