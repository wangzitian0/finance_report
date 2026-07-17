"""Explicit, auditable posting command for an unmatched statement transaction."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType
from src.config_app import get_effective_base_currency
from src.extraction import (
    ClassificationRule,
    ClassificationStatus,
    DispositionContext,
    DispositionMode,
    DispositionPolicy,
    DispositionStatus,
    IntentProposal,
    IntentProposalOrigin,
    RuleType,
    StatementTransaction,
    TransactionClassification,
    create_entry_from_txn,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Account, JournalEntry, JournalEntryStatus
from src.reconciliation.base import ReviewedDispositionCommand, ReviewedDispositionError
from src.reconciliation.orm.reconciliation import ReconciliationMatch


def _reviewed_rule_name(transaction_id: UUID) -> str:
    return f"reviewed-disposition:{transaction_id}"


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
) -> JournalEntry:
    """Persist one reviewed semantic basis and post its single source entry.

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

    proposal = IntentProposal(
        schema_version="1",
        policy_version="reviewed-disposition-v1",
        origin=IntentProposalOrigin.REVIEWED_RULE,
        intent=command.intent,
        category=command.category.strip() if command.category else None,
        confidence=Decimal("1"),
        evidence=(f"review-rationale:{command.rationale.strip()}",),
    )
    decision = DispositionPolicy().decide(
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

    rule_name = _reviewed_rule_name(txn.id)
    recorded_result = await db.execute(
        select(TransactionClassification, ClassificationRule)
        .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
        .where(TransactionClassification.atomic_txn_id == txn.id)
        .where(ClassificationRule.user_id == user_id)
        .where(ClassificationRule.rule_name == rule_name)
        .with_for_update()
    )
    recorded = recorded_result.one_or_none()
    if recorded is not None:
        classification, _rule = recorded
        tags = classification.tags if isinstance(classification.tags, dict) else {}
        if tags.get("semantic_digest") != decision.semantic_digest:
            raise ReviewedDispositionError("Reviewed disposition is incompatible with the already-recorded decision")
        existing_entry = await _find_existing_entry(db, user_id=user_id, transaction_id=txn.id)
        if existing_entry is None:
            raise RuntimeError("Recorded reviewed disposition is missing its source journal entry")
        return existing_entry

    if await _find_existing_entry(db, user_id=user_id, transaction_id=txn.id):
        raise ReviewedDispositionError("A source journal entry already exists; reconcile that entry instead")

    rule = ClassificationRule(
        user_id=user_id,
        created_by=user_id,
        rule_name=rule_name,
        version_number=1,
        effective_date=txn.txn_date,
        # This is a record of one confirmed transaction, never a future matching rule.
        is_active=False,
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"kind": "reviewed_disposition", "transaction_id": str(txn.id)},
        tag_mappings={
            "intent": command.intent.value,
            "category": proposal.category,
            "rationale": command.rationale.strip(),
            "semantic_digest": decision.semantic_digest,
        },
        default_account_id=counter_account.id,
    )
    db.add(rule)
    await db.flush()
    db.add(
        TransactionClassification(
            atomic_txn_id=txn.id,
            rule_version_id=rule.id,
            account_id=counter_account.id,
            tags={
                "intent": command.intent.value,
                "category": proposal.category,
                "rationale": command.rationale.strip(),
                "semantic_digest": decision.semantic_digest,
            },
            confidence_score=100,
            status=ClassificationStatus.APPLIED,
        )
    )
    await db.flush()

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
