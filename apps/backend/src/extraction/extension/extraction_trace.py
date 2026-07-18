"""TraceRecord projection for the statement source-to-fact boundary."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from src.audit import (
    Ratio,
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceDecisionPolicyRegistry,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.extraction.base.result import ExtractionMethod, StatementExtractionResult
from src.extraction.extension.disposition_trace import (
    DispositionDecisionTracePolicy,
    DispositionInvariantTracePolicy,
    FinancialCommandAuthorizationTracePolicy,
    JournalCommandPayloadTracePolicy,
)
from src.extraction.extension.reviewed_statement_envelope import reviewed_envelope_trace_policies


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _authority(*, tier: str, proof_kind: str, provenance: str, producer_version: str) -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package="extraction",
        tier=tier,
        proof_kind=proof_kind,
        provenance=provenance,
        execution_stage="product.runtime",
        assertion_owner_digest=_digest(f"extraction:{tier}:{proof_kind}:v1"),
        producer_version=producer_version,
    )


@dataclass(frozen=True, slots=True)
class ExtractionInvariantTracePolicy:
    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(kind="invariant", id="extraction-result-integrity", version="1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        return _authority(tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", producer_version="1")

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.DIRECT

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        passed = len(parents) == 1 and parents[0].result is TraceResult.PASS
        return TraceDecisionOutcome(
            result=TraceResult.AUTHORITATIVE if passed else TraceResult.REJECTED,
            reason_code="result_integrity_satisfied" if passed else "result_integrity_failed",
            score=Ratio(Decimal("1" if passed else "0")),
        )


@dataclass(frozen=True, slots=True)
class ExtractionPromotionTracePolicy:
    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(kind="promotion", id="statement-extraction-promotion", version="1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        return _authority(tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", producer_version="1")

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.DIRECT

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        observation = next((item for item in parents if item.reason_code.startswith("extraction_")), None)
        guard = next((item for item in parents if item.reason_code == "result_integrity_satisfied"), None)
        authoritative = bool(
            observation
            and guard
            and observation.reason_code == "extraction_balance_validated"
            and observation.score is not None
            and observation.score.value >= Decimal("0.85")
            and guard.result is TraceResult.AUTHORITATIVE
        )
        return TraceDecisionOutcome(
            result=TraceResult.AUTHORITATIVE if authoritative else TraceResult.REVIEW,
            reason_code="extraction_promoted" if authoritative else "extraction_requires_review",
            score=observation.score if observation else None,
        )


def extraction_trace_policy_registry() -> TraceDecisionPolicyRegistry:
    return TraceDecisionPolicyRegistry(
        policies=(
            ExtractionInvariantTracePolicy(),
            ExtractionPromotionTracePolicy(),
            DispositionInvariantTracePolicy(),
            DispositionDecisionTracePolicy(),
            *reviewed_envelope_trace_policies(),
            JournalCommandPayloadTracePolicy(),
            FinancialCommandAuthorizationTracePolicy(),
        )
    )


def build_extraction_trace_records(
    result: StatementExtractionResult,
    *,
    user_id: UUID,
    execution_id: str,
    occurred_at: datetime,
) -> tuple[TraceRecord, ...]:
    """Build the exact observation -> code guard -> promotion causal graph."""
    scope = TraceScope.tenant(user_id)
    target = VersionedTraceRef(
        kind="statement_extraction_result",
        id=str(result.result_id),
        version=result.content_digest,
    )
    authority = {
        ExtractionMethod.DETERMINISTIC: ("CODE-ONLY", "exact", "deterministic"),
        ExtractionMethod.LIVE_LLM: ("LLM-LED", "invariant", "live_llm"),
        ExtractionMethod.GOLDEN_FIXTURE: ("CODE-LED", "property", "golden_fixture@extraction"),
    }[result.provenance.method]
    complete = not result.missing_required_facts
    result_observation = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(
            kind="extraction",
            id=result.source_type.value,
            version=result.producer_version,
        ),
        authority=_authority(
            tier=authority[0],
            proof_kind=authority[1],
            provenance=authority[2],
            producer_version=result.producer_version,
        ),
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=result.source_content_digest,
        occurred_at=occurred_at,
        score=Ratio(result.confidence),
        reason_code=(
            "extraction_balance_validated"
            if result.balance_validated is True and complete
            else "extraction_review_required"
        ),
    )
    integrity_observation = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(kind="invariant", id="result-schema-and-digest", version="1"),
        authority=_authority(
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            producer_version="1",
        ),
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=result.content_digest,
        occurred_at=occurred_at,
        score=Ratio(Decimal("1")),
        reason_code="result_schema_and_digest_valid",
    )
    invariant_policy = ExtractionInvariantTracePolicy()
    integrity_decision = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=invariant_policy,
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(integrity_observation,),
    )
    promotion_decision = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=ExtractionPromotionTracePolicy(),
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(result_observation, integrity_decision),
    )
    return result_observation, integrity_observation, integrity_decision, promotion_decision
