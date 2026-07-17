"""TraceRecord projection for deterministic economic disposition."""

from __future__ import annotations

import hashlib
import json
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
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.audit.extension.trace_emitter import TraceEmitter
from src.extraction.base.disposition import (
    DispositionDecision,
    DispositionStatus,
    EconomicIntent,
    IntentProposal,
    IntentProposalOrigin,
    StatementTransaction,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _authority(
    *,
    tier: str,
    proof_kind: str,
    provenance: str,
    producer_version: str,
    package: str = "extraction",
    execution_stage: str = "product.runtime",
) -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package=package,
        tier=tier,
        proof_kind=proof_kind,
        provenance=provenance,
        execution_stage=execution_stage,
        assertion_owner_digest=_digest(f"disposition:{tier}:{proof_kind}:v1"),
        producer_version=producer_version,
    )


def _proposal_authority(proposal: IntentProposal | None) -> tuple[str, str, str, str, str, str]:
    """Map the proposal's closed origin to the existing audit vocabulary."""
    if proposal is None:
        return "extraction", "CODE-ONLY", "exact", "deterministic", "product.runtime", "no-proposal"
    return {
        IntentProposalOrigin.REVIEWED_RULE: (
            "extraction",
            "CODE-ONLY",
            "exact",
            "deterministic",
            "product.runtime",
            proposal.policy_version,
        ),
        IntentProposalOrigin.LIVE_LLM: (
            "extraction",
            "LLM-LED",
            "invariant",
            "live_llm",
            "product.runtime",
            proposal.policy_version,
        ),
        IntentProposalOrigin.RECONCILIATION_FACT: (
            "extraction",
            "CODE-LED",
            "property",
            "deterministic",
            "product.runtime",
            proposal.policy_version,
        ),
        IntentProposalOrigin.MANUAL_ADJUDICATION: (
            "reconciliation",
            "CODE-ONLY",
            "exact",
            "manual",
            "manual.adjudication",
            proposal.policy_version,
        ),
    }[proposal.origin]


@dataclass(frozen=True, slots=True)
class DispositionInvariantTracePolicy:
    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(kind="invariant", id="disposition-command-integrity", version="1")

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
            reason_code="disposition_invariant_satisfied" if passed else "disposition_invariant_failed",
            score=Ratio(Decimal("1" if passed else "0")),
        )


@dataclass(frozen=True, slots=True)
class DispositionDecisionTracePolicy:
    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(kind="disposition", id="economic-disposition", version="1")

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
        marker = next((item for item in parents if item.reason_code.startswith("disposition_candidate_")), None)
        guard = next((item for item in parents if item.reason_code == "disposition_invariant_satisfied"), None)
        if guard is None or marker is None:
            return TraceDecisionOutcome(TraceResult.REJECTED, "disposition_parents_invalid")
        status = marker.reason_code.removeprefix("disposition_candidate_")
        return TraceDecisionOutcome(
            result=(
                TraceResult.AUTHORITATIVE
                if status in {DispositionStatus.AUTHORITATIVE.value, DispositionStatus.ALREADY_COVERED.value}
                else TraceResult.REVIEW
            ),
            reason_code=f"disposition_{status}",
            score=marker.score,
        )


def build_disposition_trace_records(
    *,
    user_id: UUID,
    execution_id: str,
    occurred_at: datetime,
    transaction: StatementTransaction,
    proposal: IntentProposal | None,
    decision: DispositionDecision,
    invariant_supersedes_id: UUID | None = None,
    disposition_supersedes_id: UUID | None = None,
) -> tuple[TraceRecord, ...]:
    transaction_payload = {
        "id": str(transaction.transaction_id),
        "date": transaction.transaction_date.isoformat(),
        "amount": str(transaction.amount),
        "currency": transaction.currency,
        "direction": transaction.direction.value,
        "description": transaction.description,
    }
    target = VersionedTraceRef(
        kind="statement_transaction",
        id=str(transaction.transaction_id),
        version=_digest(json.dumps(transaction_payload, sort_keys=True, separators=(",", ":"))),
    )
    scope = TraceScope.tenant(user_id)
    evidence_digest = _digest("|".join(proposal.evidence) if proposal else "no-intent-proposal")
    package, tier, proof_kind, provenance, execution_stage, producer_version = _proposal_authority(proposal)
    candidate = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(
            kind="economic_intent",
            id=proposal.intent.value if proposal else EconomicIntent.UNKNOWN.value,
            version=proposal.policy_version if proposal else "none",
        ),
        authority=_authority(
            package=package,
            tier=tier,
            proof_kind=proof_kind,
            provenance=provenance,
            execution_stage=execution_stage,
            producer_version=producer_version,
        ),
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=evidence_digest,
        occurred_at=occurred_at,
        score=Ratio(proposal.confidence) if proposal and proposal.confidence is not None else None,
        reason_code=f"disposition_candidate_{decision.status.value}",
    )
    invariant = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(kind="invariant", id="balanced-command-or-explicit-review", version="1"),
        authority=_authority(tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", producer_version="1"),
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=decision.semantic_digest,
        occurred_at=occurred_at,
        score=Ratio(Decimal("1")),
        reason_code="disposition_command_or_review_valid",
    )
    guard = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=DispositionInvariantTracePolicy(),
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(invariant,),
        supersedes_id=invariant_supersedes_id,
    )
    disposition = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=DispositionDecisionTracePolicy(),
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(candidate, guard),
        supersedes_id=disposition_supersedes_id,
    )
    return candidate, invariant, guard, disposition


async def emit_disposition_trace_records(
    *,
    emitter: TraceEmitter,
    user_id: UUID,
    execution_id: str,
    occurred_at: datetime,
    transaction: StatementTransaction,
    proposal: IntentProposal | None,
    decision: DispositionDecision,
) -> tuple[TraceRecord, ...]:
    """Emit one causal set idempotently, superseding changed decision heads."""
    records = build_disposition_trace_records(
        user_id=user_id,
        execution_id=execution_id,
        occurred_at=occurred_at,
        transaction=transaction,
        proposal=proposal,
        decision=decision,
    )
    current_guard = await emitter.repository.current_decision(records[2].scope, records[2].lineage)
    guard_supersedes_id = (
        current_guard.record_id
        if current_guard is not None and current_guard.record_id != records[2].record_id
        else None
    )
    if guard_supersedes_id is not None:
        records = build_disposition_trace_records(
            user_id=user_id,
            execution_id=execution_id,
            occurred_at=occurred_at,
            transaction=transaction,
            proposal=proposal,
            decision=decision,
            invariant_supersedes_id=guard_supersedes_id,
        )

    current_disposition = await emitter.repository.current_decision(records[3].scope, records[3].lineage)
    disposition_supersedes_id = (
        current_disposition.record_id
        if current_disposition is not None and current_disposition.record_id != records[3].record_id
        else None
    )
    if disposition_supersedes_id is not None:
        records = build_disposition_trace_records(
            user_id=user_id,
            execution_id=execution_id,
            occurred_at=occurred_at,
            transaction=transaction,
            proposal=proposal,
            decision=decision,
            invariant_supersedes_id=guard_supersedes_id,
            disposition_supersedes_id=disposition_supersedes_id,
        )
    return await emitter.emit_many(records)
