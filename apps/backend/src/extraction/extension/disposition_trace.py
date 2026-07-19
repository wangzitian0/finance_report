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
    StatementDispositionPolicySnapshot,
    StatementTransaction,
)
from src.extraction.extension.disposition_policy import current_statement_disposition_policy_snapshot
from src.ledger import DecisionAnchor, journal_command_target


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


@dataclass(frozen=True, slots=True)
class JournalCommandPayloadTracePolicy:
    """Proves the canonical ledger command was materialized without mutation."""

    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(kind="invariant", id="journal-command-payload", version="1")

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
        valid = len(parents) == 1 and parents[0].result is TraceResult.PASS
        return TraceDecisionOutcome(
            TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            "journal_command_payload_bound" if valid else "journal_command_payload_invalid",
        )


@dataclass(frozen=True, slots=True)
class FinancialCommandAuthorizationTracePolicy:
    """Binds one accepted disposition to its exact balanced ledger command."""

    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(kind="financial_command", id="source-disposition", version="1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        return _authority(tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", producer_version="1")

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.MANIFEST

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        upstream = any(
            parent.record_type.value == "decision"
            and parent.target_class is TraceTargetClass.FINANCIAL
            and parent.result is TraceResult.AUTHORITATIVE
            for parent in parents
        )
        command_guard = any(
            parent.record_type.value == "decision"
            and parent.assertion == JournalCommandPayloadTracePolicy().assertion
            and parent.result is TraceResult.AUTHORITATIVE
            for parent in parents
        )
        return TraceDecisionOutcome(
            TraceResult.AUTHORITATIVE if upstream and command_guard else TraceResult.REJECTED,
            "financial_command_authorized" if upstream and command_guard else "financial_command_unauthorized",
        )


def build_disposition_trace_records(
    *,
    user_id: UUID,
    execution_id: str,
    occurred_at: datetime,
    transaction: StatementTransaction,
    proposal: IntentProposal | None,
    decision: DispositionDecision,
    policy_snapshot: StatementDispositionPolicySnapshot | None = None,
    invariant_supersedes_id: UUID | None = None,
    disposition_supersedes_id: UUID | None = None,
) -> tuple[TraceRecord, ...]:
    runtime_policy = policy_snapshot or current_statement_disposition_policy_snapshot(mode=decision.mode)
    if runtime_policy.mode is not decision.mode:
        raise ValueError("disposition policy snapshot mode must match the decision mode")
    if runtime_policy.policy_version != decision.policy_version:
        raise ValueError("disposition policy snapshot version must match the decision policy")
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
    evidence_digest = _digest(
        json.dumps(
            {
                "proposal_evidence": list(proposal.evidence) if proposal else ["no-intent-proposal"],
                "runtime_policy": runtime_policy.semantic_payload(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    package, tier, proof_kind, provenance, execution_stage, producer_version = _proposal_authority(proposal)
    candidate = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(
            kind="economic_intent",
            id=proposal.intent.value if proposal else EconomicIntent.UNKNOWN.value,
            version=runtime_policy.trace_version,
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
        evidence_manifest_digest=_digest(
            json.dumps(
                {
                    "decision": decision.semantic_digest,
                    "runtime_policy_digest": runtime_policy.semantic_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        ),
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
    policy_snapshot: StatementDispositionPolicySnapshot | None = None,
) -> tuple[TraceRecord, ...]:
    """Emit one causal set idempotently, superseding changed decision heads."""
    records = build_disposition_trace_records(
        user_id=user_id,
        execution_id=execution_id,
        occurred_at=occurred_at,
        transaction=transaction,
        proposal=proposal,
        decision=decision,
        policy_snapshot=policy_snapshot,
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
            policy_snapshot=policy_snapshot,
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
            policy_snapshot=policy_snapshot,
            invariant_supersedes_id=guard_supersedes_id,
            disposition_supersedes_id=disposition_supersedes_id,
        )
    return await emitter.emit_many(records)


async def authorize_financial_command(
    *,
    emitter: TraceEmitter,
    user_id: UUID,
    upstream_decision: TraceRecord,
    entry_date,
    memo: str,
    lines_data: list[dict],
    base_currency: str,
    source_id: UUID,
) -> DecisionAnchor:
    """Append the source-owned decision that binds authority to exact ledger bytes.

    The disposition decision remains the evidence for economic meaning. This
    manifest decision adds the independently computed command payload guard, so
    the ledger can verify an exact target without knowing how the source was
    classified or reviewed.
    """
    # ``source_type`` describes how the fact was obtained; it must not alter
    # the immutable identity of the source financial command. A re-review can
    # change provenance, but it cannot authorize a second posting for one
    # statement transaction.
    source_identity = f"statement-transaction:{source_id}"
    target = journal_command_target(
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        base_currency=base_currency,
        source_identity=source_identity,
    )
    scope = TraceScope.tenant(user_id)
    if (
        upstream_decision.scope != scope
        or upstream_decision.result is not TraceResult.AUTHORITATIVE
        or upstream_decision.target.kind != "statement_transaction"
        or upstream_decision.target.id != str(source_id)
    ):
        raise ValueError("financial command requires a current authoritative source decision")

    authorization_policy = FinancialCommandAuthorizationTracePolicy()
    current_authorization = await emitter.repository.current_decision(
        scope,
        TraceRecord.decision(
            scope=scope,
            target=target,
            policy=authorization_policy,
            execution_id=f"journal-command:{target.id}:{target.version}",
            occurred_at=upstream_decision.occurred_at,
            parents=(upstream_decision,),
        ).lineage,
    )
    if current_authorization is not None:
        if current_authorization.target != target:
            raise ValueError("a different command already owns this immutable source transaction")
        return DecisionAnchor.from_record(current_authorization)

    execution_id = f"journal-command:{target.id}:{target.version}"
    payload_digest = target.version
    observation = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(kind="ledger_command", id="canonical-payload", version="1"),
        authority=JournalCommandPayloadTracePolicy().authority,
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=payload_digest,
        occurred_at=upstream_decision.occurred_at,
        score=Ratio(Decimal("1")),
        reason_code="journal_command_payload_canonical",
    )
    payload_policy = JournalCommandPayloadTracePolicy()
    current_guard = await emitter.repository.current_decision(
        scope,
        TraceRecord.decision(
            scope=scope,
            target=target,
            policy=payload_policy,
            execution_id=execution_id,
            occurred_at=upstream_decision.occurred_at,
            parents=(observation,),
        ).lineage,
    )
    if current_guard is not None:
        if current_guard.target != target:
            raise ValueError("a different command payload guard already owns this source transaction")
        payload_guard = current_guard
    else:
        emitted = await emitter.emit_many(
            (
                observation,
                TraceRecord.decision(
                    scope=scope,
                    target=target,
                    policy=payload_policy,
                    execution_id=execution_id,
                    occurred_at=upstream_decision.occurred_at,
                    parents=(observation,),
                ),
            )
        )
        payload_guard = emitted[-1]

    authorization = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=authorization_policy,
        execution_id=execution_id,
        occurred_at=upstream_decision.occurred_at,
        parents=(upstream_decision, payload_guard),
    )
    return DecisionAnchor.from_record(await emitter.emit(authorization))
