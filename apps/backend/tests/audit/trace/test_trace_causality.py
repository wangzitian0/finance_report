"""AC-audit.trace-record.3/.5: causal and financial authority boundaries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

import pytest

from src.audit import (
    TraceCausality,
    TraceDecisionOutcome,
    TraceRecord,
    TraceRecordValidationError,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)

from .conftest import authority, decision_policy, observation


def _decision(parents, *, policy=None, target=None, execution_id=None):
    first = parents[0]
    return TraceRecord.decision(
        scope=first.scope,
        target=target or first.target,
        policy=policy or decision_policy(),
        execution_id=execution_id or first.execution_id,
        occurred_at=first.occurred_at,
        parents=parents,
    )


def test_AC_audit_trace_record_3_decision_causality_fails_closed():
    parent = observation()
    assert _decision([parent]).parent_ids == (parent.record_id,)

    mutations = [
        observation(scope=TraceScope.tenant(uuid4())),
        observation(scope=parent.scope, target_id="other-target"),
        observation(scope=parent.scope, execution_id="other-execution"),
        observation(
            scope=parent.scope,
            result=TraceResult.SKIPPED,
        ),
    ]
    for incompatible in mutations:
        with pytest.raises(TraceRecordValidationError):
            _decision([parent, incompatible])

    failed_parent = observation(
        scope=parent.scope,
        result=TraceResult.FAIL,
    )
    rejected = _decision(
        [failed_parent],
        policy=decision_policy(result=TraceResult.REJECTED),
    )
    assert rejected.result is TraceResult.REJECTED


@dataclass(frozen=True, slots=True)
class RequiredManifestPolicy:
    required_assertion_ids: frozenset[str]
    assertion: VersionedTraceRef = VersionedTraceRef(
        kind="terminal",
        id="trusted-year",
        version="v1",
    )
    authority = authority()
    causality = TraceCausality.MANIFEST
    target_class = TraceTargetClass.GENERAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        actual = {parent.assertion.id for parent in parents}
        if actual != self.required_assertion_ids:
            raise TraceRecordValidationError("incomplete MANIFEST parent set")
        return TraceDecisionOutcome(
            result=TraceResult.AUTHORITATIVE,
            reason_code="manifest_complete",
        )


def test_manifest_fold_allows_declared_cross_target_execution_but_not_missing_or_cross_scope():
    first = observation(assertion_id="ledger-proof")
    second = observation(
        scope=first.scope,
        target_id="report-package",
        execution_id="deployed-execution",
        assertion_id="deployed-proof",
        target_class=TraceTargetClass.GENERAL,
    )
    policy = RequiredManifestPolicy(frozenset({"ledger-proof", "deployed-proof"}))

    decision = _decision(
        [first, second],
        policy=policy,
        target=VersionedTraceRef("goal", "trusted-year", "v1"),
        execution_id="terminal-fold",
    )
    assert decision.causality is TraceCausality.MANIFEST

    with pytest.raises(TraceRecordValidationError, match="incomplete MANIFEST"):
        _decision(
            [first],
            policy=policy,
            target=VersionedTraceRef("goal", "trusted-year", "v1"),
            execution_id="terminal-fold",
        )

    cross_scope = observation(
        target_id="report-package",
        execution_id="deployed-execution",
        assertion_id="deployed-proof",
        target_class=TraceTargetClass.GENERAL,
    )
    with pytest.raises(TraceRecordValidationError, match="cross-scope"):
        _decision(
            [first, cross_scope],
            policy=policy,
            target=VersionedTraceRef("goal", "trusted-year", "v1"),
            execution_id="terminal-fold",
        )


def test_AC_audit_trace_record_5_financial_authority_requires_code_parent():
    """AC-audit.trace-record.5: financial LLM authority requires a CODE guard."""

    llm_observation = observation(
        profile=authority(
            tier="LLM-LED",
            proof_kind="eval",
            provenance="live_llm",
        )
    )

    with pytest.raises(TraceRecordValidationError, match="CODE-ONLY"):
        _decision(
            [llm_observation],
            policy=decision_policy(
                profile=authority(
                    tier="LLM-ONLY",
                    proof_kind="eval",
                    provenance="live_llm",
                )
            ),
        )

    invariant_observation = observation(
        scope=llm_observation.scope,
        execution_id=llm_observation.execution_id,
        assertion_id="balance-invariant",
    )
    invariant_decision = _decision(
        [invariant_observation],
        policy=decision_policy(
            assertion_kind="invariant",
            assertion_id="balance-guard",
        ),
    )
    authoritative = _decision(
        [llm_observation, invariant_decision],
        policy=decision_policy(assertion_id="financial-authority"),
    )
    assert authoritative.result is TraceResult.AUTHORITATIVE
