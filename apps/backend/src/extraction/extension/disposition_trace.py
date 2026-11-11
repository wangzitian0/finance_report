"""TraceRecord projection for deterministic economic disposition."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from src.audit import (
    DeclarativeTracePolicy,
    Ratio,
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceLineage,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    canonical_json_digest,
    text_digest,
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
        assertion_owner_digest=text_digest(f"disposition:{tier}:{proof_kind}:v1"),
        producer_version=producer_version,
    )


_CODE_AUTH = _authority(tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", producer_version="1")


def _proposal_authority(proposal: IntentProposal | None) -> tuple[str, str, str, str, str, str]:
    if proposal is None:
        return "extraction", "CODE-ONLY", "exact", "deterministic", "product.runtime", "no-proposal"
    pkg, tier, proof, prov, stage = {
        IntentProposalOrigin.REVIEWED_RULE: ("extraction", "CODE-ONLY", "exact", "deterministic", "product.runtime"),
        IntentProposalOrigin.LIVE_LLM: ("extraction", "LLM-LED", "invariant", "live_llm", "product.runtime"),
        IntentProposalOrigin.RECONCILIATION_FACT: (
            "extraction",
            "CODE-LED",
            "property",
            "deterministic",
            "product.runtime",
        ),
        IntentProposalOrigin.MANUAL_ADJUDICATION: (
            "reconciliation",
            "CODE-ONLY",
            "exact",
            "manual",
            "manual.adjudication",
        ),
    }[proposal.origin]
    return pkg, tier, proof, prov, stage, proposal.policy_version


@dataclass(frozen=True, slots=True)
class DispositionInvariantTracePolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("invariant", "disposition-command-integrity", "1")
    )
    authority: TraceAuthorityProfile = field(default_factory=lambda: _CODE_AUTH)
    pass_reason: str = "disposition_invariant_satisfied"
    fail_reason: str = "disposition_invariant_failed"
    with_unit_score: bool = True


@dataclass(frozen=True, slots=True)
class DispositionDecisionTracePolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("disposition", "economic-disposition", "1")
    )
    authority: TraceAuthorityProfile = field(default_factory=lambda: _CODE_AUTH)

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
class JournalCommandPayloadTracePolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("invariant", "journal-command-payload", "1")
    )
    authority: TraceAuthorityProfile = field(default_factory=lambda: _CODE_AUTH)
    pass_reason: str = "journal_command_payload_bound"
    fail_reason: str = "journal_command_payload_invalid"


@dataclass(frozen=True, slots=True)
class FinancialCommandAuthorizationTracePolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("financial_command", "source-disposition", "1")
    )
    authority: TraceAuthorityProfile = field(default_factory=lambda: _CODE_AUTH)
    causality: TraceCausality = TraceCausality.MANIFEST

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        upstream = any(
            p.record_type.value == "decision"
            and p.target_class is TraceTargetClass.FINANCIAL
            and p.result is TraceResult.AUTHORITATIVE
            for p in parents
        )
        command_guard = any(
            p.record_type.value == "decision"
            and p.assertion == JournalCommandPayloadTracePolicy().assertion
            and p.result is TraceResult.AUTHORITATIVE
            for p in parents
        )
        ok = upstream and command_guard
        return TraceDecisionOutcome(
            TraceResult.AUTHORITATIVE if ok else TraceResult.REJECTED,
            "financial_command_authorized" if ok else "financial_command_unauthorized",
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
    target = VersionedTraceRef(
        kind="statement_transaction",
        id=str(transaction.transaction_id),
        version=canonical_json_digest(
            {
                "id": str(transaction.transaction_id),
                "date": transaction.transaction_date.isoformat(),
                "amount": str(transaction.amount),
                "currency": transaction.currency,
                "direction": transaction.direction.value,
                "description": transaction.description,
            }
        ),
    )
    scope = TraceScope.tenant(user_id)
    pkg, tier, proof, prov, stage, prod_ver = _proposal_authority(proposal)
    candidate = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(
            "economic_intent",
            proposal.intent.value if proposal else EconomicIntent.UNKNOWN.value,
            runtime_policy.trace_version,
        ),
        authority=_authority(
            package=pkg, tier=tier, proof_kind=proof, provenance=prov, execution_stage=stage, producer_version=prod_ver
        ),
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=canonical_json_digest(
            {
                "proposal_evidence": list(proposal.evidence) if proposal else ["no-intent-proposal"],
                "runtime_policy": runtime_policy.semantic_payload(),
            }
        ),
        occurred_at=occurred_at,
        score=Ratio(proposal.confidence) if proposal and proposal.confidence is not None else None,
        reason_code=f"disposition_candidate_{decision.status.value}",
    )
    invariant = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("invariant", "balanced-command-or-explicit-review", "1"),
        authority=_CODE_AUTH,
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=canonical_json_digest(
            {"decision": decision.semantic_digest, "runtime_policy_digest": runtime_policy.semantic_digest}
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
    def _build(inv_sup: UUID | None = None, disp_sup: UUID | None = None) -> tuple[TraceRecord, ...]:
        return build_disposition_trace_records(
            user_id=user_id,
            execution_id=execution_id,
            occurred_at=occurred_at,
            transaction=transaction,
            proposal=proposal,
            decision=decision,
            policy_snapshot=policy_snapshot,
            invariant_supersedes_id=inv_sup,
            disposition_supersedes_id=disp_sup,
        )

    records = _build()
    cur_guard = await emitter.repository.current_decision(records[2].scope, records[2].lineage)
    guard_sup = cur_guard.record_id if cur_guard is not None and cur_guard.record_id != records[2].record_id else None
    if guard_sup is not None:
        records = _build(guard_sup)
    cur_disp = await emitter.repository.current_decision(records[3].scope, records[3].lineage)
    disp_sup = cur_disp.record_id if cur_disp is not None and cur_disp.record_id != records[3].record_id else None
    if disp_sup is not None:
        records = _build(guard_sup, disp_sup)
    return await emitter.emit_many(records)


def _require_authoritative_source_decision(
    upstream_decision: TraceRecord, *, scope: TraceScope, source_id: UUID
) -> None:
    if (
        upstream_decision.scope != scope
        or upstream_decision.result is not TraceResult.AUTHORITATIVE
        or upstream_decision.target.kind != "statement_transaction"
        or upstream_decision.target.id != str(source_id)
    ):
        raise ValueError("financial command requires a current authoritative source decision")


def _payload_observation(
    *, scope: TraceScope, target: VersionedTraceRef, execution_id: str, upstream: TraceRecord
) -> TraceRecord:
    return TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("ledger_command", "canonical-payload", "1"),
        authority=JournalCommandPayloadTracePolicy().authority,
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=target.version,
        occurred_at=upstream.occurred_at,
        score=Ratio(Decimal("1")),
        reason_code="journal_command_payload_canonical",
    )


async def _lineages_with_decision_head(
    emitter: TraceEmitter, scope: TraceScope, lineages: Collection[TraceLineage]
) -> set[TraceLineage] | None:
    if getattr(type(emitter.repository), "lineages_with_decision_head", None) is None:
        return None
    return await emitter.repository.lineages_with_decision_head(scope, lineages)  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True)
class DispositionTraceInput:
    transaction: StatementTransaction
    proposal: IntentProposal | None
    decision: DispositionDecision


async def emit_disposition_trace_records_many(
    *,
    emitter: TraceEmitter,
    user_id: UUID,
    execution_id: str,
    occurred_at: datetime,
    inputs: Sequence[DispositionTraceInput],
    policy_snapshot: StatementDispositionPolicySnapshot | None = None,
) -> list[tuple[TraceRecord, ...]]:
    built = [
        build_disposition_trace_records(
            user_id=user_id,
            execution_id=execution_id,
            occurred_at=occurred_at,
            transaction=item.transaction,
            proposal=item.proposal,
            decision=item.decision,
            policy_snapshot=policy_snapshot,
        )
        for item in inputs
    ]
    scope = TraceScope.tenant(user_id)
    all_lineages = [lin for rec in built for lin in (rec[2].lineage, rec[3].lineage)]
    heads = await _lineages_with_decision_head(emitter, scope, all_lineages)
    uses = Counter(all_lineages)
    fresh = [
        idx
        for idx, rec in enumerate(built)
        if heads is not None
        and rec[2].lineage not in heads
        and rec[3].lineage not in heads
        and uses[rec[2].lineage] == uses[rec[3].lineage] == 1
    ]
    results: dict[int, tuple[TraceRecord, ...]] = {}
    if fresh:
        emitted = await emitter.emit_many([r for idx in fresh for r in built[idx]])
        for pos, idx in enumerate(fresh):
            results[idx] = tuple(emitted[pos * 4 : (pos + 1) * 4])
    for idx, item in enumerate(inputs):
        if idx not in results:
            results[idx] = await emit_disposition_trace_records(
                emitter=emitter,
                user_id=user_id,
                execution_id=execution_id,
                occurred_at=occurred_at,
                transaction=item.transaction,
                proposal=item.proposal,
                decision=item.decision,
                policy_snapshot=policy_snapshot,
            )
    return [results[i] for i in range(len(inputs))]


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
    target = journal_command_target(
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        base_currency=base_currency,
        source_identity=f"statement-transaction:{source_id}",
    )
    scope = TraceScope.tenant(user_id)
    _require_authoritative_source_decision(upstream_decision, scope=scope, source_id=source_id)
    auth_policy = FinancialCommandAuthorizationTracePolicy()
    execution_id = f"journal-command:{target.id}:{target.version}"
    auth_head = await emitter.repository.decision_head(
        scope, TraceLineage.from_refs(target, auth_policy.assertion)
    )
    if auth_head is not None and auth_head.ancestry_current and auth_head.record.target == target:
        return DecisionAnchor.from_record(auth_head.record)

    observation = _payload_observation(scope=scope, target=target, execution_id=execution_id, upstream=upstream_decision)
    payload_policy = JournalCommandPayloadTracePolicy()
    guard_head = await emitter.repository.decision_head(
        scope, TraceLineage.from_refs(target, payload_policy.assertion)
    )
    if guard_head is not None and guard_head.ancestry_current and guard_head.record.target == target:
        payload_guard = guard_head.record
    else:
        payload_guard = (
            await emitter.emit_many(
                (
                    observation,
                    TraceRecord.decision(
                        scope=scope,
                        target=target,
                        policy=payload_policy,
                        execution_id=execution_id,
                        occurred_at=upstream_decision.occurred_at,
                        parents=(observation,),
                        supersedes_id=guard_head.record.record_id if guard_head is not None else None,
                    ),
                )
            )
        )[-1]

    authorization = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=auth_policy,
        execution_id=execution_id,
        occurred_at=upstream_decision.occurred_at,
        parents=(upstream_decision, payload_guard),
        supersedes_id=auth_head.record.record_id if auth_head is not None else None,
    )
    return DecisionAnchor.from_record(await emitter.emit(authorization))


@dataclass(frozen=True, slots=True)
class FinancialCommandRequest:
    upstream_decision: TraceRecord
    entry_date: date
    memo: str
    lines_data: list[dict]
    base_currency: str
    source_id: UUID


async def authorize_financial_commands_many(
    *, emitter: TraceEmitter, user_id: UUID, requests: Sequence[FinancialCommandRequest]
) -> list[DecisionAnchor]:
    scope = TraceScope.tenant(user_id)
    auth_policy = FinancialCommandAuthorizationTracePolicy()
    payload_policy = JournalCommandPayloadTracePolicy()
    targets: list[VersionedTraceRef] = []
    for req in requests:
        _require_authoritative_source_decision(req.upstream_decision, scope=scope, source_id=req.source_id)
        targets.append(
            journal_command_target(
                entry_date=req.entry_date,
                memo=req.memo,
                lines_data=req.lines_data,
                base_currency=req.base_currency,
                source_identity=f"statement-transaction:{req.source_id}",
            )
        )
    lineages = [
        (TraceLineage.from_refs(t, auth_policy.assertion), TraceLineage.from_refs(t, payload_policy.assertion))
        for t in targets
    ]
    all_lin = [lin for pair in lineages for lin in pair]
    heads = await _lineages_with_decision_head(emitter, scope, all_lin)
    uses = Counter(all_lin)
    fresh = [
        idx
        for idx, (auth_lin, guard_lin) in enumerate(lineages)
        if heads is not None and auth_lin not in heads and guard_lin not in heads and uses[auth_lin] == uses[guard_lin] == 1
    ]
    anchors: dict[int, DecisionAnchor] = {}
    records: list[TraceRecord] = []
    for idx in fresh:
        upstream, target = requests[idx].upstream_decision, targets[idx]
        execution_id = f"journal-command:{target.id}:{target.version}"
        obs = _payload_observation(scope=scope, target=target, execution_id=execution_id, upstream=upstream)
        guard = TraceRecord.decision(
            scope=scope, target=target, policy=payload_policy, execution_id=execution_id, occurred_at=upstream.occurred_at, parents=(obs,)
        )
        auth = TraceRecord.decision(
            scope=scope, target=target, policy=auth_policy, execution_id=execution_id, occurred_at=upstream.occurred_at, parents=(upstream, guard)
        )
        records.extend((obs, guard, auth))
    if records:
        emitted = await emitter.emit_many(records)
        for pos, idx in enumerate(fresh):
            anchors[idx] = DecisionAnchor.from_record(emitted[pos * 3 + 2])
    for idx, req in enumerate(requests):
        if idx not in anchors:
            anchors[idx] = await authorize_financial_command(
                emitter=emitter,
                user_id=user_id,
                upstream_decision=req.upstream_decision,
                entry_date=req.entry_date,
                memo=req.memo,
                lines_data=req.lines_data,
                base_currency=req.base_currency,
                source_id=req.source_id,
            )
    return [anchors[i] for i in range(len(requests))]
