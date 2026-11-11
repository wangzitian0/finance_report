"""TraceRecord projection for the statement source-to-fact boundary."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from src.audit import (
    DeclarativeTracePolicy,
    Ratio,
    TraceAuthorityProfile,
    TraceDecisionOutcome,
    TraceDecisionPolicyRegistry,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    text_digest,
)
from src.extraction.base.result import ExtractionMethod, StatementExtractionResult
from src.extraction.base.validation import HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD
from src.extraction.extension.disposition_trace import (
    DispositionDecisionTracePolicy,
    DispositionInvariantTracePolicy,
    FinancialCommandAuthorizationTracePolicy,
    JournalCommandPayloadTracePolicy,
)
from src.extraction.extension.reviewed_statement_envelope import reviewed_envelope_trace_policies


def _authority(*, tier: str, proof_kind: str, provenance: str, producer_version: str) -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package="extraction",
        tier=tier,
        proof_kind=proof_kind,
        provenance=provenance,
        execution_stage="product.runtime",
        assertion_owner_digest=text_digest(f"extraction:{tier}:{proof_kind}:v1"),
        producer_version=producer_version,
    )


_CODE_AUTH = _authority(tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", producer_version="1")


@dataclass(frozen=True, slots=True)
class ExtractionInvariantTracePolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef(kind="invariant", id="extraction-result-integrity", version="1")
    )
    authority: TraceAuthorityProfile = field(default_factory=lambda: _CODE_AUTH)
    pass_reason: str = "result_integrity_satisfied"
    fail_reason: str = "result_integrity_failed"
    with_unit_score: bool = True


@dataclass(frozen=True, slots=True)
class ExtractionPromotionTracePolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef(kind="promotion", id="statement-extraction-promotion", version="1")
    )
    authority: TraceAuthorityProfile = field(default_factory=lambda: _CODE_AUTH)

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        observation = next((item for item in parents if item.reason_code.startswith("extraction_")), None)
        guard = next((item for item in parents if item.reason_code == "result_integrity_satisfied"), None)
        authoritative = bool(
            observation
            and guard
            and observation.reason_code == "extraction_balance_validated"
            and observation.score is not None
            and observation.score.value * 100 >= HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD
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
    result: StatementExtractionResult, *, user_id: UUID, execution_id: str, occurred_at: datetime
) -> tuple[TraceRecord, ...]:
    scope = TraceScope.tenant(user_id)
    target = VersionedTraceRef("statement_extraction_result", str(result.result_id), result.content_digest)
    tier, proof, prov = {
        ExtractionMethod.DETERMINISTIC: ("CODE-ONLY", "exact", "deterministic"),
        ExtractionMethod.LIVE_LLM: ("LLM-LED", "invariant", "live_llm"),
        ExtractionMethod.GOLDEN_FIXTURE: ("CODE-LED", "property", "golden_fixture@extraction"),
    }[result.provenance.method]
    result_obs = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("extraction", result.source_type.value, result.producer_version),
        authority=_authority(tier=tier, proof_kind=proof, provenance=prov, producer_version=result.producer_version),
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=result.source_content_digest,
        occurred_at=occurred_at,
        score=Ratio(result.confidence),
        reason_code=(
            "extraction_balance_validated"
            if result.balance_validated is True and not result.missing_required_facts
            else "extraction_review_required"
        ),
    )
    integrity_obs = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("invariant", "result-schema-and-digest", "1"),
        authority=_CODE_AUTH,
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=result.content_digest,
        occurred_at=occurred_at,
        score=Ratio(Decimal("1")),
        reason_code="result_schema_and_digest_valid",
    )
    integrity_dec = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=ExtractionInvariantTracePolicy(),
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(integrity_obs,),
    )
    promotion_dec = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=ExtractionPromotionTracePolicy(),
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(result_obs, integrity_dec),
    )
    return result_obs, integrity_obs, integrity_dec, promotion_dec
