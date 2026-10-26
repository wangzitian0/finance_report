"""TraceRecord projection for deterministic economic disposition."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from src.audit import (
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


def _require_authoritative_source_decision(
    upstream_decision: TraceRecord,
    *,
    scope: TraceScope,
    source_id: UUID,
) -> None:
    if (
        upstream_decision.scope != scope
        or upstream_decision.result is not TraceResult.AUTHORITATIVE
        or upstream_decision.target.kind != "statement_transaction"
        or upstream_decision.target.id != str(source_id)
    ):
        raise ValueError("financial command requires a current authoritative source decision")


def _payload_observation(
    *,
    scope: TraceScope,
    target: VersionedTraceRef,
    execution_id: str,
    upstream: TraceRecord,
) -> TraceRecord:
    """The observation that the canonical payload of a journal command was materialized."""
    return TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(kind="ledger_command", id="canonical-payload", version="1"),
        authority=JournalCommandPayloadTracePolicy().authority,
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=target.version,
        occurred_at=upstream.occurred_at,
        score=Ratio(Decimal("1")),
        reason_code="journal_command_payload_canonical",
    )


async def _lineages_with_decision_head(
    emitter: TraceEmitter,
    scope: TraceScope,
    lineages: Collection[TraceLineage],
) -> set[TraceLineage] | None:
    """The lineages that hold a decision head, read in one statement.

    A repository without the batch read gives ``None``. The caller then keeps the per-record path.
    """
    read = getattr(type(emitter.repository), "lineages_with_decision_head", None)
    if read is None:
        return None
    return await emitter.repository.lineages_with_decision_head(scope, lineages)  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True)
class DispositionTraceInput:
    """One transaction whose disposition needs its trace records."""

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
    """Emit the disposition records of many transactions with a fixed number of statements.

    Each result equals the one that ``emit_disposition_trace_records`` returns for the same input. A
    transaction whose guard or disposition lineage already holds a head keeps that per-record path,
    because it may supersede the head. So does a transaction that appears twice in the inputs: the
    second input must see the head of the first.
    """
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
    heads = await _lineages_with_decision_head(
        emitter, scope, [lineage for records in built for lineage in (records[2].lineage, records[3].lineage)]
    )
    uses = Counter(lineage for records in built for lineage in (records[2].lineage, records[3].lineage))
    fresh = [
        index
        for index, records in enumerate(built)
        if heads is not None
        and records[2].lineage not in heads
        and records[3].lineage not in heads
        and uses[records[2].lineage] == uses[records[3].lineage] == 1
    ]
    results: dict[int, tuple[TraceRecord, ...]] = {}
    if fresh:
        emitted = await emitter.emit_many([record for index in fresh for record in built[index]])
        for position, index in enumerate(fresh):
            results[index] = tuple(emitted[position * 4 : (position + 1) * 4])
    for index, item in enumerate(inputs):
        if index not in results:
            results[index] = await emit_disposition_trace_records(
                emitter=emitter,
                user_id=user_id,
                execution_id=execution_id,
                occurred_at=occurred_at,
                transaction=item.transaction,
                proposal=item.proposal,
                decision=item.decision,
                policy_snapshot=policy_snapshot,
            )
    return [results[index] for index in range(len(inputs))]


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
    _require_authoritative_source_decision(upstream_decision, scope=scope, source_id=source_id)

    authorization_policy = FinancialCommandAuthorizationTracePolicy()
    auth_head = await emitter.repository.decision_head(
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
    if auth_head is not None and auth_head.ancestry_current and auth_head.record.target == target:
        return DecisionAnchor.from_record(auth_head.record)
    authorization_supersedes_id = auth_head.record.record_id if auth_head is not None else None

    execution_id = f"journal-command:{target.id}:{target.version}"
    observation = _payload_observation(
        scope=scope, target=target, execution_id=execution_id, upstream=upstream_decision
    )
    payload_policy = JournalCommandPayloadTracePolicy()
    guard_head = await emitter.repository.decision_head(
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
    if guard_head is not None and guard_head.ancestry_current and guard_head.record.target == target:
        payload_guard = guard_head.record
    else:
        guard_supersedes_id = guard_head.record.record_id if guard_head is not None else None
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
                    supersedes_id=guard_supersedes_id,
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
        supersedes_id=authorization_supersedes_id,
    )
    return DecisionAnchor.from_record(await emitter.emit(authorization))


@dataclass(frozen=True, slots=True)
class FinancialCommandRequest:
    """The arguments of ``authorize_financial_command`` for one journal command."""

    upstream_decision: TraceRecord
    entry_date: date
    memo: str
    lines_data: list[dict]
    base_currency: str
    source_id: UUID


async def authorize_financial_commands_many(
    *,
    emitter: TraceEmitter,
    user_id: UUID,
    requests: Sequence[FinancialCommandRequest],
) -> list[DecisionAnchor]:
    """Authorize many journal commands with a fixed number of statements.

    Each anchor equals the one that ``authorize_financial_command`` returns for the same request. A
    command whose authorization or payload-guard lineage already holds a head keeps that per-command
    path, because it may reuse or supersede the head. So does a command whose target appears twice in
    the requests: the second request must see the head of the first.
    """
    scope = TraceScope.tenant(user_id)
    authorization_policy = FinancialCommandAuthorizationTracePolicy()
    payload_policy = JournalCommandPayloadTracePolicy()
    targets: list[VersionedTraceRef] = []
    for request in requests:
        _require_authoritative_source_decision(request.upstream_decision, scope=scope, source_id=request.source_id)
        targets.append(
            journal_command_target(
                entry_date=request.entry_date,
                memo=request.memo,
                lines_data=request.lines_data,
                base_currency=request.base_currency,
                source_identity=f"statement-transaction:{request.source_id}",
            )
        )
    lineages = [
        (
            TraceLineage.from_refs(target, authorization_policy.assertion),
            TraceLineage.from_refs(target, payload_policy.assertion),
        )
        for target in targets
    ]
    heads = await _lineages_with_decision_head(emitter, scope, [lineage for pair in lineages for lineage in pair])

    uses = Counter(lineage for pair in lineages for lineage in pair)
    fresh = [
        index
        for index, (authorization_lineage, guard_lineage) in enumerate(lineages)
        if heads is not None
        and authorization_lineage not in heads
        and guard_lineage not in heads
        and uses[authorization_lineage] == uses[guard_lineage] == 1
    ]
    anchors: dict[int, DecisionAnchor] = {}
    records: list[TraceRecord] = []
    for index in fresh:
        upstream, target = requests[index].upstream_decision, targets[index]
        execution_id = f"journal-command:{target.id}:{target.version}"
        observation = _payload_observation(scope=scope, target=target, execution_id=execution_id, upstream=upstream)
        payload_guard = TraceRecord.decision(
            scope=scope,
            target=target,
            policy=payload_policy,
            execution_id=execution_id,
            occurred_at=upstream.occurred_at,
            parents=(observation,),
        )
        authorization = TraceRecord.decision(
            scope=scope,
            target=target,
            policy=authorization_policy,
            execution_id=execution_id,
            occurred_at=upstream.occurred_at,
            parents=(upstream, payload_guard),
        )
        records.extend((observation, payload_guard, authorization))
    if records:
        emitted = await emitter.emit_many(records)
        for position, index in enumerate(fresh):
            anchors[index] = DecisionAnchor.from_record(emitted[position * 3 + 2])
    for index, request in enumerate(requests):
        if index not in anchors:
            anchors[index] = await authorize_financial_command(
                emitter=emitter,
                user_id=user_id,
                upstream_decision=request.upstream_decision,
                entry_date=request.entry_date,
                memo=request.memo,
                lines_data=request.lines_data,
                base_currency=request.base_currency,
                source_id=request.source_id,
            )
    return [anchors[index] for index in range(len(requests))]
