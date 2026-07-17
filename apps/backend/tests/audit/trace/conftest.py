"""Generated TraceRecord fixtures; no user financial data."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from src.audit import (
    Ratio,
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)


def authority(
    *,
    tier: str = "CODE-ONLY",
    proof_kind: str = "exact",
    provenance: str = "deterministic",
    stage: str = "github_ci.merge_authority",
) -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package="audit",
        tier=tier,
        proof_kind=proof_kind,
        provenance=provenance,
        execution_stage=stage,
        assertion_owner_digest="a" * 64,
        producer_version="test-producer@1",
    )


@dataclass(frozen=True, slots=True)
class FixtureDecisionPolicy:
    assertion: VersionedTraceRef
    authority: TraceAuthorityProfile
    causality: TraceCausality = TraceCausality.DIRECT
    target_class: TraceTargetClass = TraceTargetClass.FINANCIAL
    result: TraceResult = TraceResult.AUTHORITATIVE
    reason_code: str = "fixture_decision"

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        if not parents:
            raise ValueError("fixture policy requires parents")
        return TraceDecisionOutcome(
            result=self.result,
            reason_code=self.reason_code,
        )


def decision_policy(
    *,
    assertion_id: str = "promote",
    assertion_version: str = "v1",
    assertion_kind: str = "promotion",
    profile: TraceAuthorityProfile | None = None,
    causality: TraceCausality = TraceCausality.DIRECT,
    target_class: TraceTargetClass = TraceTargetClass.FINANCIAL,
    result: TraceResult = TraceResult.AUTHORITATIVE,
) -> FixtureDecisionPolicy:
    return FixtureDecisionPolicy(
        assertion=VersionedTraceRef(
            kind=assertion_kind,
            id=assertion_id,
            version=assertion_version,
        ),
        authority=profile or authority(),
        causality=causality,
        target_class=target_class,
        result=result,
    )


def observation(
    *,
    scope: TraceScope | None = None,
    target_id: str = "subject-1",
    target_version: str = "v1",
    target_class: TraceTargetClass = TraceTargetClass.FINANCIAL,
    assertion_kind: str = "invariant",
    assertion_id: str = "assertion-1",
    assertion_version: str = "v1",
    result: TraceResult = TraceResult.PASS,
    execution_id: str = "execution-1",
    profile: TraceAuthorityProfile | None = None,
    supersedes_id: UUID | None = None,
    score: str | None = "1",
    occurred_at: datetime | None = None,
) -> TraceRecord:
    return TraceRecord.observation(
        scope=scope or TraceScope.tenant(uuid4()),
        target=VersionedTraceRef(
            kind="financial_fact",
            id=target_id,
            version=target_version,
        ),
        target_class=target_class,
        assertion=VersionedTraceRef(
            kind=assertion_kind,
            id=assertion_id,
            version=assertion_version,
        ),
        authority=profile or authority(),
        result=result,
        execution_id=execution_id,
        evidence_manifest_digest="b" * 64,
        occurred_at=occurred_at or datetime(2026, 7, 17, tzinfo=UTC),
        score=Ratio(Decimal(score)) if score is not None else None,
        reason_code="fixture_result",
        supersedes_id=supersedes_id,
    )
