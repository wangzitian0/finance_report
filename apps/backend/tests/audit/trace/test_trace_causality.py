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
from tests.audit.trace.conftest import authority, decision as _decision, decision_policy, observation


@dataclass(frozen=True, slots=True)
class RequiredManifestPolicy:
    required_assertion_ids: frozenset[str]
    assertion: VersionedTraceRef = VersionedTraceRef(kind="terminal", id="trusted-year", version="v1")
    authority: object = authority()
    causality: TraceCausality = TraceCausality.MANIFEST
    target_class: TraceTargetClass = TraceTargetClass.GENERAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        if {p.assertion.id for p in parents} != self.required_assertion_ids:
            raise TraceRecordValidationError("incomplete MANIFEST parent set")
        return TraceDecisionOutcome(result=TraceResult.AUTHORITATIVE, reason_code="manifest_complete")


def test_AC_audit_trace_record_3_and_5_causality_and_code_parent() -> None:
    parent = observation()
    assert _decision([parent]).parent_ids == (parent.record_id,)
    for bad in (
        observation(scope=TraceScope.tenant(uuid4())),
        observation(scope=parent.scope, target_id="other-target"),
        observation(scope=parent.scope, execution_id="other-execution"),
        observation(scope=parent.scope, result=TraceResult.SKIPPED),
    ):
        with pytest.raises(TraceRecordValidationError):
            _decision([parent, bad])
    assert (
        _decision(
            [observation(scope=parent.scope, result=TraceResult.FAIL)],
            policy=decision_policy(result=TraceResult.REJECTED),
        ).result
        is TraceResult.REJECTED
    )

    p1 = observation(assertion_id="ledger-proof")
    p2 = observation(
        scope=p1.scope,
        target_id="report-package",
        execution_id="deployed-execution",
        assertion_id="deployed-proof",
        target_class=TraceTargetClass.GENERAL,
    )
    m_pol, goal = (
        RequiredManifestPolicy(frozenset({"ledger-proof", "deployed-proof"})),
        VersionedTraceRef("goal", "trusted-year", "v1"),
    )
    assert (
        _decision([p1, p2], policy=m_pol, target=goal, execution_id="terminal-fold").causality
        is TraceCausality.MANIFEST
    )

    cross_scope = observation(
        target_id="report-package",
        execution_id="deployed-execution",
        assertion_id="deployed-proof",
        target_class=TraceTargetClass.GENERAL,
    )
    for bad_parents, match in (([p1], "incomplete MANIFEST"), ([p1, cross_scope], "cross-scope")):
        with pytest.raises(TraceRecordValidationError, match=match):
            _decision(bad_parents, policy=m_pol, target=goal, execution_id="terminal-fold")

    llm_obs = observation(profile=authority(tier="LLM-LED", proof_kind="eval", provenance="live_llm"))
    with pytest.raises(TraceRecordValidationError, match="CODE-ONLY"):
        _decision(
            [llm_obs],
            policy=decision_policy(profile=authority(tier="LLM-ONLY", proof_kind="eval", provenance="live_llm")),
        )
    inv_dec = _decision(
        [observation(scope=llm_obs.scope, execution_id=llm_obs.execution_id, assertion_id="balance-invariant")],
        policy=decision_policy(assertion_kind="invariant", assertion_id="balance-guard"),
    )
    assert (
        _decision([llm_obs, inv_dec], policy=decision_policy(assertion_id="financial-authority")).result
        is TraceResult.AUTHORITATIVE
    )
