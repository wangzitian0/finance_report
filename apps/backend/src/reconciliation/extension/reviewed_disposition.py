"""Explicit, auditable posting command for an unmatched statement transaction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType, TraceEmitter
from src.config_app import get_effective_base_currency
from src.extraction import (
    DispositionContext,
    DispositionMode,
    DispositionPolicy,
    DispositionStatus,
    IntentProposal,
    IntentProposalOrigin,
    StatementTransaction,
    build_disposition_trace_records,
    create_entry_from_txn,
    emit_disposition_trace_records,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Account, JournalEntry, JournalEntryStatus
from src.reconciliation.base import ReviewedDispositionCommand, ReviewedDispositionError
from src.reconciliation.orm.reconciliation import ReconciliationMatch


@dataclass(frozen=True, slots=True)
class ReviewedDispositionDependencies:
    """Explicit policy and assurance dependencies supplied by composition."""

    trace_emitter: TraceEmitter
    disposition_policy: DispositionPolicy


def _command_digest(command: ReviewedDispositionCommand) -> str:
    payload = {
        "schema_version": "1",
        "intent": command.intent.value,
        "counter_account_id": str(command.counter_account_id),
        "category": command.category.strip() if command.category else None,
        "rationale": command.rationale.strip(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _statement_transaction(txn: AtomicTransaction) -> StatementTransaction:
    return StatementTransaction(
        transaction_id=txn.id,
        transaction_date=txn.txn_date,
        amount=txn.amount,
        currency=txn.currency,
        direction=txn.direction,
        description=txn.description,
    )


async def _find_existing_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    transaction_id: UUID,
) -> JournalEntry | None:
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == transaction_id)
        .where(JournalEntry.status != JournalEntryStatus.VOID)
        .limit(1)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def submit_reviewed_disposition(
    db: AsyncSession,
    *,
    transaction_id: UUID,
    user_id: UUID,
    command: ReviewedDispositionCommand,
    dependencies: ReviewedDispositionDependencies,
) -> JournalEntry:
    """Append one reviewed causal decision and post its single source entry.

    The source transaction is locked first. Its semantic digest becomes the
    idempotency key: a retry of the same reviewed decision returns the existing
    source entry, while a different decision is rejected instead of rewriting
    accounting history.
    """
    transaction_result = await db.execute(
        select(AtomicTransaction)
        .where(AtomicTransaction.id == transaction_id)
        .where(AtomicTransaction.user_id == user_id)
        .with_for_update()
    )
    txn = transaction_result.scalar_one_or_none()
    if txn is None:
        raise LookupError("Transaction not found")

    # The route is deliberately scoped to transactions with no reconciliation
    # decision. A direct API call must not bypass an existing match review.
    matched_result = await db.execute(
        select(ReconciliationMatch.id).where(ReconciliationMatch.atomic_txn_id == txn.id).limit(1).with_for_update()
    )
    if matched_result.scalar_one_or_none() is not None:
        raise ReviewedDispositionError("Transaction already has a reconciliation match")

    counter_result = await db.execute(
        select(Account)
        .where(Account.id == command.counter_account_id)
        .where(Account.user_id == user_id)
        .with_for_update()
    )
    counter_account = counter_result.scalar_one_or_none()
    if counter_account is None:
        raise ReviewedDispositionError("Counter account not found")
    if not counter_account.is_active:
        raise ReviewedDispositionError("Counter account must be active")
    if counter_account.currency != txn.currency:
        raise ReviewedDispositionError("Counter account currency must match the transaction currency")

    command_digest = _command_digest(command)
    proposal = IntentProposal(
        schema_version="1",
        policy_version="reviewed-disposition-v1",
        origin=IntentProposalOrigin.MANUAL_ADJUDICATION,
        intent=command.intent,
        category=command.category.strip() if command.category else None,
        confidence=None,
        evidence=(f"reviewed-command:{command_digest}",),
    )
    decision = dependencies.disposition_policy.decide(
        _statement_transaction(txn),
        proposal=proposal,
        context=DispositionContext(
            counter_account_id=counter_account.id,
            counter_account_type=counter_account.type.value,
        ),
        mode=DispositionMode.ENFORCE,
    )
    if decision.status is not DispositionStatus.AUTHORITATIVE or not decision.should_apply:
        if decision.reason_code == "intent_counter_account_conflict":
            raise ReviewedDispositionError("Reviewed intent is incompatible with the counter-account type")
        raise ReviewedDispositionError(f"Reviewed disposition is not postable: {decision.reason_code}")

    occurred_at = datetime.now(UTC)
    execution_id = f"reviewed-disposition:{txn.id}:{command_digest}"
    candidate_record, _invariant_record, _guard_record, disposition_record = build_disposition_trace_records(
        user_id=user_id,
        execution_id=execution_id,
        occurred_at=occurred_at,
        transaction=_statement_transaction(txn),
        proposal=proposal,
        decision=decision,
    )
    current_decision = await dependencies.trace_emitter.repository.current_decision(
        disposition_record.scope,
        disposition_record.lineage,
    )
    if current_decision is not None:
        current_parents = []
        for parent_id in current_decision.parent_ids:
            current_parents.append(await dependencies.trace_emitter.repository.get(current_decision.scope, parent_id))
        manual_observation = next(
            (
                parent
                for parent in current_parents
                if parent is not None
                and parent.assertion.kind == "economic_intent"
                and parent.authority.provenance == "manual"
            ),
            None,
        )
        if manual_observation is not None:
            if manual_observation.evidence_manifest_digest != candidate_record.evidence_manifest_digest:
                raise ReviewedDispositionError(
                    "Reviewed disposition is incompatible with the already-recorded decision"
                )
            existing_entry = await _find_existing_entry(db, user_id=user_id, transaction_id=txn.id)
            if existing_entry is None:
                raise RuntimeError("Recorded reviewed disposition is missing its source journal entry")
            return existing_entry

    if await _find_existing_entry(db, user_id=user_id, transaction_id=txn.id):
        raise ReviewedDispositionError("A source journal entry already exists; reconcile that entry instead")

    await emit_disposition_trace_records(
        emitter=dependencies.trace_emitter,
        user_id=user_id,
        execution_id=execution_id,
        occurred_at=occurred_at,
        transaction=_statement_transaction(txn),
        proposal=proposal,
        decision=decision,
    )

    try:
        return await create_entry_from_txn(
            db,
            txn,
            user_id=user_id,
            base_currency=await get_effective_base_currency(db),
            auto_post=True,
            source_type=JournalEntrySourceType.USER_CONFIRMED,
            disposition=decision,
            counter_account=counter_account,
        )
    except ValueError as exc:
        raise ReviewedDispositionError(str(exc)) from exc
