"""AC-audit.trace-projection.1: fixed machine cohort confidence."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.audit import (
    TraceConfidenceProjection,
    TraceLineage,
    TraceRecord,
    TraceRecordValidationError,
    TraceResult,
)

from .conftest import authority, decision_policy, observation


def test_AC_audit_trace_projection_1_uses_fixed_machine_cohort_heads():
    passed = observation(target_id="machine-a")
    failed = observation(
        scope=passed.scope,
        target_id="machine-b",
        result=TraceResult.FAIL,
        score="0",
    )
    manual = observation(
        scope=passed.scope,
        target_id="manual-extra",
        profile=authority(
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
        ),
    )
    correction = observation(
        scope=passed.scope,
        target_id="machine-b",
        target_version="v2",
        assertion_version="v2",
        supersedes_id=failed.record_id,
    )
    projection = TraceConfidenceProjection(
        cohort_id="machine-extraction",
        cohort_version="v1",
        members=(passed.lineage, failed.lineage),
    )

    confidence = projection.evaluate([passed, failed, manual, correction])

    assert confidence.value == Decimal("1")


def test_projection_distinguishes_assertions_over_the_same_target():
    first = observation(target_id="shared-target", assertion_id="parser-shape")
    second = observation(
        scope=first.scope,
        target_id="shared-target",
        assertion_id="balance-invariant",
        result=TraceResult.FAIL,
        score="0",
    )
    projection = TraceConfidenceProjection(
        cohort_id="two-independent-assertions",
        cohort_version="v1",
        members=(
            TraceLineage.from_refs(first.target, first.assertion),
            TraceLineage.from_refs(second.target, second.assertion),
        ),
    )

    assert projection.evaluate([first, second]).value == Decimal("0.5")


def test_projection_scores_terminal_decision_without_counting_its_ancestors():
    parent = observation()
    decision = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=decision_policy(assertion_id="terminal-confidence"),
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )
    projection = TraceConfidenceProjection(
        cohort_id="terminal-decisions",
        cohort_version="v1",
        members=(decision.lineage,),
    )

    assert projection.evaluate([parent, decision]).value == Decimal("1")

    correction = observation(
        scope=parent.scope,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=parent.record_id,
    )
    with pytest.raises(TraceRecordValidationError, match="missing"):
        projection.evaluate([parent, decision, correction])
