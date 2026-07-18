"""AC4.3.1 AC4.6.4 AC18.1.5 AC18.1.6: Review Queue Tests

These tests validate review queue operations including getting pending
items, accepting/rejecting matches, batch operations, and creating journal entries
from atomic transactions. Tests cover status transitions, amount validation,
batch processing scenarios, and error handling.

Fixtures are built natively on Layer 2: each "statement" is an
``UploadedDocument`` + ``StatementSummary`` and each transaction is an
``AtomicTransaction`` whose ``source_documents`` reference the document so the
review-queue services can resolve the owning statement. Matches are keyed on
``atomic_txn_id``; there is no per-transaction status column (match status is the
source of truth).
"""

import inspect
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, SqlTraceRecordRepository, TraceEmitter
from src.extraction import (
    DispositionContext,
    DispositionMode,
    DispositionPolicy,
    EconomicIntent,
    IntentProposal,
    IntentProposalOrigin,
    StatementTransaction,
    extraction_trace_policy_registry,
)
from src.extraction.extension.disposition_trace import emit_disposition_trace_records
from src.extraction.extension.review_queue import create_entry_from_txn, get_or_create_account
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.extraction.orm.layer3 import ClassificationRule, ClassificationStatus, RuleType, TransactionClassification
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import AccountType, JournalEntryStatus, ValidationError
from src.pricing import PricingError
from src.reconciliation import AmountMismatchError, EntryCreationError, MatchNotFoundError, ReconciliationStatus
from src.reconciliation.extension.review_queue import accept_match, batch_accept, get_pending_items, reject_match
from tests.factories import (
    AccountFactory,
    AtomicTransactionFactory,
    JournalEntryFactory,
    ReconciliationMatchFactory,
    StatementSummaryFactory,
    UploadedDocumentFactory,
    UserFactory,
)
from tests.ledger._ledger_helpers import create_valid_void_entry


async def _make_statement(
    db: AsyncSession,
    user_id,
    *,
    account_id=None,
    currency: str = "SGD",
    create_mapped_account: bool = False,
):
    """Create a linked UploadedDocument + StatementSummary conform.

    Returns the StatementSummary; its ``uploaded_document_id`` is what atomic
    transactions reference via ``source_documents``.
    """
    if create_mapped_account:
        if account_id is not None:
            raise ValueError("create_mapped_account and account_id are mutually exclusive")
        account = await AccountFactory.create_async(
            db,
            user_id=user_id,
            name="Test statement custody account",
            type=AccountType.ASSET,
            currency=currency,
        )
        account_id = account.id
    doc = await UploadedDocumentFactory.create_async(db, user_id=user_id)
    summary = await StatementSummaryFactory.create_async(
        db,
        user_id=user_id,
        account_id=account_id,
        uploaded_document_id=doc.id,
        file_hash=doc.file_hash,
        currency=currency,
    )
    return summary


async def _make_txn(
    db: AsyncSession,
    user_id,
    statement: StatementSummary,
    *,
    amount: Decimal = Decimal("50.00"),
    direction: TransactionDirection = TransactionDirection.OUT,
    txn_date: date | None = None,
    description: str = "Transaction",
    currency: str = "SGD",
) -> AtomicTransaction:
    """Create an AtomicTransaction owned by the given statement conform."""
    return await AtomicTransactionFactory.create_async(
        db,
        user_id=user_id,
        source_doc_id=statement.uploaded_document_id,
        amount=amount,
        direction=direction,
        txn_date=txn_date or date.today(),
        description=description,
        currency=currency,
    )


async def _reviewed_posting_command(db: AsyncSession, user_id, txn: AtomicTransaction, *, counter_account=None):
    """Build explicit reviewed semantic input for entry-creation tests."""
    if counter_account is None:
        intent = EconomicIntent.INCOME if txn.direction is TransactionDirection.IN else EconomicIntent.EXPENSE
        counter_account = await get_or_create_account(
            db,
            name="Income - Test" if intent is EconomicIntent.INCOME else "Expense - Test",
            account_type=AccountType.INCOME if intent is EconomicIntent.INCOME else AccountType.EXPENSE,
            currency=txn.currency,
            user_id=user_id,
        )
    else:
        intent = EconomicIntent.INCOME if counter_account.type is AccountType.INCOME else EconomicIntent.EXPENSE
    proposal = IntentProposal(
        schema_version="1",
        policy_version="reviewed-test-v1",
        origin=IntentProposalOrigin.REVIEWED_RULE,
        intent=intent,
        category="TEST",
        confidence=Decimal("1"),
        evidence=("reviewed-test",),
    )
    decision = DispositionPolicy().decide(
        StatementTransaction(
            transaction_id=txn.id,
            transaction_date=txn.txn_date,
            amount=txn.amount,
            currency=txn.currency,
            direction=txn.direction,
            description=txn.description,
        ),
        proposal=proposal,
        context=DispositionContext(counter_account_id=counter_account.id),
        mode=DispositionMode.ENFORCE,
    )
    return decision, counter_account, proposal


async def _create_reviewed_entry(db: AsyncSession, txn: AtomicTransaction, *, user_id, **kwargs):
    counter_account = kwargs.pop("counter_account", None)
    decision, counter_account, proposal = await _reviewed_posting_command(
        db,
        user_id,
        txn,
        counter_account=counter_account,
    )
    source_transaction = StatementTransaction(
        transaction_id=txn.id,
        transaction_date=txn.txn_date,
        amount=txn.amount,
        currency=txn.currency,
        direction=txn.direction,
        description=txn.description,
    )
    emitter = TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry()))
    source_decision = (
        await emit_disposition_trace_records(
            emitter=emitter,
            user_id=user_id,
            execution_id=f"review-queue-test:{txn.id}",
            occurred_at=datetime.now(UTC),
            transaction=source_transaction,
            proposal=proposal,
            decision=decision,
        )
    )[-1]
    return await create_entry_from_txn(
        db,
        txn,
        user_id=user_id,
        disposition=decision,
        counter_account=counter_account,
        source_decision=source_decision,
        trace_emitter=emitter,
        **kwargs,
    )


async def test_get_pending_items_returns_pending_matches(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    results = await get_pending_items(db, user_id=test_user.id)
    assert len(results) == 1
    assert results[0].status == ReconciliationStatus.PENDING_REVIEW


async def test_get_pending_items_excludes_accepted(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.ACCEPTED,
    )
    await db.commit()

    results = await get_pending_items(db, user_id=test_user.id)
    assert len(results) == 0


async def test_accept_match_updates_status(db, test_user):
    stmt = await _make_statement(db, test_user.id, create_mapped_account=True)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry = await _create_reviewed_entry(db, txn, user_id=test_user.id, auto_post=True)
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    result = await accept_match(db, match.id, user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED
    assert result.version == 2


async def test_accept_match_not_found_raises(db, test_user):
    with pytest.raises(MatchNotFoundError, match="Match not found"):
        await accept_match(db, uuid4(), user_id=test_user.id)


async def test_accept_match_already_accepted_returns_unchanged(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.ACCEPTED,
    )
    await db.commit()

    result = await accept_match(db, match.id, user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED
    assert result.version == 1


async def test_accept_match_amount_mismatch_raises(db, test_user):
    stmt = await _make_statement(db, test_user.id, create_mapped_account=True)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry = await _create_reviewed_entry(db, txn, user_id=test_user.id, auto_post=True)
    txn.amount = Decimal("500.00")
    await db.flush()
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    with pytest.raises(AmountMismatchError, match="Amount mismatch"):
        await accept_match(db, match.id, user_id=test_user.id)


async def test_AC_review_hardening_2_accept_match_validation_unconditional(db, test_user):
    """AC-reconciliation.review-hardening.2: amount validation cannot be bypassed (#1864)."""
    # The public signature carries no bypass flag — entry balance validation
    # is never skippable (red line).
    assert "skip_amount_validation" not in inspect.signature(accept_match).parameters

    stmt = await _make_statement(db, test_user.id, create_mapped_account=True)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry = await _create_reviewed_entry(db, txn, user_id=test_user.id, auto_post=True)
    txn.amount = Decimal("500.00")
    await db.flush()
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    with pytest.raises(AmountMismatchError, match="Amount mismatch"):
        await accept_match(db, match.id, user_id=test_user.id)


async def test_accept_match_reconciles_journal_entries(db, test_user):
    stmt = await _make_statement(db, test_user.id, create_mapped_account=True)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry = await _create_reviewed_entry(db, txn, user_id=test_user.id, auto_post=True)
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    await accept_match(db, match.id, user_id=test_user.id)
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.RECONCILED
    assert entry.source_type is JournalEntrySourceType.AUTO_PARSED


async def test_accept_match_without_reviewed_disposition_requires_entry_context(db, test_user):
    """AC-reconciliation.review-queue.14: accepting a match cannot invent a source entry."""
    account = await AccountFactory.create_async(
        db,
        user_id=test_user.id,
        name="Mapped Review Queue Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    stmt = await _make_statement(db, test_user.id, account_id=account.id)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("42.00"), direction=TransactionDirection.OUT)
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    with pytest.raises(EntryCreationError, match="pre-existing journal entry"):
        await accept_match(db, match.id, user_id=test_user.id)
    await db.refresh(match)
    assert match.status == ReconciliationStatus.PENDING_REVIEW
    assert match.journal_entry_ids == []


async def test_accept_match_does_not_reconcile_void_entries(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry = await create_valid_void_entry(db, test_user.id, memo="Void match candidate")
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
        match_score=95,
    )
    await db.commit()

    with pytest.raises(EntryCreationError, match="current decision authority"):
        await accept_match(db, match.id, user_id=test_user.id)
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.VOID


async def test_reject_match_updates_status(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    result = await reject_match(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.REJECTED
    assert result.version == 2


async def test_reject_match_not_found_raises(db, test_user):
    with pytest.raises(MatchNotFoundError, match="Match not found"):
        await reject_match(db, str(uuid4()), user_id=test_user.id)


async def test_reject_match_already_rejected_returns_unchanged(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.REJECTED,
    )
    await db.commit()

    result = await reject_match(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.REJECTED
    assert result.version == 1


async def test_batch_accept_empty_list(db, test_user):
    result = await batch_accept(db, [], user_id=test_user.id)
    assert result == []


async def test_batch_accept_accepts_high_score_matches(db, test_user):
    stmt = await _make_statement(db, test_user.id, create_mapped_account=True)

    txn1 = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry1 = await _create_reviewed_entry(db, txn1, user_id=test_user.id, auto_post=True)
    match1 = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn1.id,
        journal_entry_ids=[str(entry1.id)],
        match_score=90,
        status=ReconciliationStatus.PENDING_REVIEW,
    )

    txn2 = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry2 = await _create_reviewed_entry(db, txn2, user_id=test_user.id, auto_post=True)
    match2 = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn2.id,
        journal_entry_ids=[str(entry2.id)],
        match_score=90,
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    accepted = await batch_accept(db, [str(match1.id), str(match2.id)], user_id=test_user.id, min_score=80)
    assert len(accepted) == 2
    for m in accepted:
        assert m.status == ReconciliationStatus.ACCEPTED


async def test_batch_accept_skips_low_score(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=50,
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    accepted = await batch_accept(db, [str(match.id)], user_id=test_user.id, min_score=80)
    assert len(accepted) == 0


async def test_batch_accept_reconciles_journal_entries(db, test_user):
    stmt = await _make_statement(db, test_user.id, create_mapped_account=True)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry = await _create_reviewed_entry(db, txn, user_id=test_user.id, auto_post=True)
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=90,
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    await batch_accept(db, [str(match.id)], user_id=test_user.id, min_score=80)
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.RECONCILED


async def test_get_or_create_account_creates_new(db, test_user):
    account = await get_or_create_account(
        db,
        name="Test Account",
        account_type=AccountType.ASSET,
        currency="SGD",
        user_id=test_user.id,
    )
    assert account.name == "Test Account"
    assert account.type == AccountType.ASSET
    assert account.currency == "SGD"


async def test_get_or_create_account_returns_existing(db, test_user):
    a1 = await get_or_create_account(
        db,
        name="Same Account",
        account_type=AccountType.ASSET,
        currency="SGD",
        user_id=test_user.id,
    )
    a2 = await get_or_create_account(
        db,
        name="Same Account",
        account_type=AccountType.ASSET,
        currency="SGD",
        user_id=test_user.id,
    )
    assert a1.id == a2.id


async def test_create_entry_from_txn_in_direction(db, test_user):
    stmt = await _make_statement(db, test_user.id, create_mapped_account=True)
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.IN,
        amount=Decimal("200.00"),
        txn_date=date(2025, 1, 15),
        description="Salary deposit",
    )
    await db.commit()

    entry = await _create_reviewed_entry(db, txn, user_id=test_user.id)
    assert entry.status == JournalEntryStatus.DRAFT
    assert len(entry.lines) == 2

    debit_line = next(line for line in entry.lines if line.direction.value == "DEBIT")
    credit_line = next(line for line in entry.lines if line.direction.value == "CREDIT")
    assert debit_line.amount == Decimal("200.00")
    assert credit_line.amount == Decimal("200.00")


async def test_create_entry_from_txn_out_direction(db, test_user):
    stmt = await _make_statement(db, test_user.id, create_mapped_account=True)
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.OUT,
        amount=Decimal("50.00"),
        txn_date=date(2025, 1, 20),
        description="Coffee shop",
    )
    await db.commit()

    entry = await _create_reviewed_entry(db, txn, user_id=test_user.id)
    assert entry.status == JournalEntryStatus.DRAFT
    assert len(entry.lines) == 2


async def test_create_entry_from_txn_auto_post_creates_posted_entry(db, test_user):
    linked_account = await AccountFactory.create_async(
        db,
        user_id=test_user.id,
        name="Mapped Bank Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    stmt = await _make_statement(db, test_user.id, account_id=linked_account.id)
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.IN,
        amount=Decimal("75.00"),
    )
    await db.commit()

    entry = await _create_reviewed_entry(db, txn, user_id=test_user.id, auto_post=True)
    assert entry.status == JournalEntryStatus.POSTED


async def test_create_entry_from_txn_auto_post_requires_account_mapping(db, test_user):
    """AC-extraction.6.2: Posted entries cannot silently use the Bank - Main fallback."""
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.IN,
        amount=Decimal("75.00"),
    )
    await db.commit()

    with pytest.raises(ValueError, match="Account mapping required before statement posting"):
        await create_entry_from_txn(db, txn, user_id=test_user.id, auto_post=True)


async def test_create_entry_from_txn_rejects_mismatched_preloaded_statement(db, test_user):
    user_id = test_user.id
    stmt = await _make_statement(db, user_id)
    other_stmt = await _make_statement(db, user_id)
    txn = await _make_txn(db, user_id, stmt)
    await db.flush()

    # Mismatch is detected when the preloaded statement belongs to a different user.
    other_stmt.user_id = uuid4()
    with pytest.raises(ValueError, match="Preloaded statement does not match"):
        await create_entry_from_txn(db, txn, user_id=user_id, preloaded_statement=other_stmt)


async def test_create_entry_from_txn_rejects_unowned_preloaded_bank_account(db, test_user):
    user_id = test_user.id
    stmt = await _make_statement(db, user_id)
    txn = await _make_txn(db, user_id, stmt)
    other_account = await AccountFactory.create_async(
        db,
        user_id=(await UserFactory.create_async(db)).id,
        name="Other User Preloaded Bank",
        type=AccountType.ASSET,
        currency="SGD",
    )
    await db.flush()

    with pytest.raises(ValueError, match="Bank account does not belong to user"):
        await create_entry_from_txn(
            db,
            txn,
            user_id=user_id,
            preloaded_statement=stmt,
            preloaded_bank_account=other_account,
        )


async def test_create_entry_from_txn_rejects_mismatched_preloaded_bank_account(db, test_user):
    user_id = test_user.id
    statement_account = await AccountFactory.create_async(
        db,
        user_id=user_id,
        name="Statement Bank",
        type=AccountType.ASSET,
        currency="SGD",
    )
    other_account = await AccountFactory.create_async(
        db,
        user_id=user_id,
        name="Other Preloaded Bank",
        type=AccountType.ASSET,
        currency="SGD",
    )
    stmt = await _make_statement(db, user_id, account_id=statement_account.id)
    txn = await _make_txn(db, user_id, stmt)
    await db.flush()

    with pytest.raises(ValueError, match="Preloaded bank account does not match statement"):
        await create_entry_from_txn(
            db,
            txn,
            user_id=user_id,
            preloaded_statement=stmt,
            preloaded_bank_account=other_account,
        )


async def test_create_entry_from_txn_wrong_user_raises(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt)
    await db.commit()

    with pytest.raises(ValueError, match="Transaction does not belong to user"):
        await create_entry_from_txn(db, txn, user_id=uuid4())


async def test_create_entry_from_txn_uses_statement_linked_account(db, test_user):
    linked_account = await AccountFactory.create_async(
        db,
        user_id=test_user.id,
        name="DBS Savings",
        type=AccountType.ASSET,
        currency="SGD",
    )
    stmt = await _make_statement(db, test_user.id, account_id=linked_account.id)
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.IN,
        amount=Decimal("300.00"),
        txn_date=date(2025, 2, 1),
        description="Bonus",
    )
    await db.commit()

    entry = await _create_reviewed_entry(db, txn, user_id=test_user.id)
    account_ids = {line.account_id for line in entry.lines}
    assert linked_account.id in account_ids


async def test_statement_summary_rejects_linked_account_not_owned(db, test_user):
    other_user_id = (await UserFactory.create_async(db)).id
    other_users_account = await AccountFactory.create_async(
        db,
        user_id=other_user_id,
        name="Other User Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    with pytest.raises(IntegrityError):
        await _make_statement(db, test_user.id, account_id=other_users_account.id)
    await db.rollback()


async def test_create_entry_from_txn_raises_when_generated_entry_unbalanced(db, test_user):
    stmt = await _make_statement(db, test_user.id, create_mapped_account=True)
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.IN,
        amount=Decimal("10.00"),
    )
    await db.commit()

    with patch(
        "src.extraction.extension.review_queue.submit_anchored_journal_entry",
        side_effect=ValidationError("not balanced"),
    ):
        with pytest.raises(ValueError, match="Generated entry does not balance"):
            await _create_reviewed_entry(db, txn, user_id=test_user.id)


async def test_create_entry_from_txn_uses_layer3_classification_account(db, test_user):
    """AC-extraction.1801.3: create_entry_from_txn reads the Layer-3 classification before defaulting to Uncategorized."""
    classified_account = await AccountFactory.create_async(
        db,
        user_id=test_user.id,
        name="Expense - Food & Dining",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    stmt = await _make_statement(
        db,
        test_user.id,
        currency="SGD",
        create_mapped_account=True,
    )
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.OUT,
        amount=Decimal("80.00"),
        description="Dinner",
    )

    rule = ClassificationRule(
        user_id=test_user.id,
        version_number=1,
        effective_date=txn.txn_date,
        rule_name="Food rule",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["dinner"]},
        default_account_id=classified_account.id,
        created_by=test_user.id,
    )
    db.add(rule)
    await db.flush()

    classification = TransactionClassification(
        atomic_txn_id=txn.id,
        rule_version_id=rule.id,
        account_id=classified_account.id,
        confidence_score=100,
        status=ClassificationStatus.APPLIED,
    )
    db.add(classification)

    await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    entry = await _create_reviewed_entry(
        db,
        txn,
        user_id=test_user.id,
        counter_account=classified_account,
    )

    debit_line = next(line for line in entry.lines if line.direction.value == "DEBIT")
    assert debit_line.account_id == classified_account.id


async def test_create_entry_from_txn_outflow_without_disposition_requires_review(db, test_user):
    """AC-extraction.1801.4: an outflow cannot manufacture an expense category."""
    stmt = await _make_statement(
        db,
        test_user.id,
        currency="SGD",
        create_mapped_account=True,
    )
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.OUT,
        amount=Decimal("15.00"),
        description="MRT",
    )
    await db.commit()

    with pytest.raises(ValueError, match="Authoritative economic disposition"):
        await create_entry_from_txn(db, txn, user_id=test_user.id)


async def test_create_entry_from_txn_inflow_without_disposition_requires_review(db, test_user):
    """AC-extraction.1801.5: an inflow cannot manufacture an income category."""
    stmt = await _make_statement(
        db,
        test_user.id,
        currency="SGD",
        create_mapped_account=True,
    )
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.IN,
        amount=Decimal("1200.00"),
        description="Monthly salary",
    )
    await db.commit()

    with pytest.raises(ValueError, match="Authoritative economic disposition"):
        await create_entry_from_txn(db, txn, user_id=test_user.id)


async def test_create_entry_from_txn_lazy_loads_missing_fx_rate(db, test_user):
    """AC-extraction.1779.1: a foreign-currency line with no stored FX rate is
    resolved through the on-demand chain (lazy_load=True) instead of failing
    closed immediately -- a date->rate fact is immutable once resolved, so
    consulting the same lazy chain reporting/internal-transfer/revaluation
    already use is safe here too (#1779)."""
    stmt = await _make_statement(
        db,
        test_user.id,
        currency="CNY",
        create_mapped_account=True,
    )
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.OUT,
        amount=Decimal("100.00"),
        currency="CNY",
        txn_date=date(2025, 1, 15),
    )
    await db.commit()

    with patch(
        # Patches the injected port, not src.pricing.get_exchange_rate: #1675
        # D5c inverted review_queue.py's fx lookup into
        # register_fx_rate_provider() (a real ledger/extraction <-> pricing
        # cycle otherwise, since pricing now depends on extraction's
        # published ORM entities), so conftest.py's module-top registration
        # captures the real get_exchange_rate once at import time. Patching
        # src.pricing.get_exchange_rate after that has no effect on the
        # already-bound reference; patch the module-level slot instead.
        "src.extraction.extension.review_queue._get_exchange_rate",
    ) as mock_get_rate:
        mock_get_rate.return_value = Decimal("0.19")
        entry = await _create_reviewed_entry(db, txn, user_id=test_user.id)

    mock_get_rate.assert_awaited_once_with(db, "CNY", "SGD", date(2025, 1, 15), lazy_load=True)
    assert entry.status == JournalEntryStatus.DRAFT


async def test_create_entry_from_txn_still_fails_closed_when_fx_rate_unresolvable(db, test_user):
    """AC-extraction.1779.1: when even the lazy on-demand chain cannot resolve a
    rate, entry creation still fails closed -- a journal entry cannot post
    without a real rate, unlike a report line, which can just omit the value
    (#1779)."""
    stmt = await _make_statement(db, test_user.id, currency="CNY")
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.OUT,
        amount=Decimal("100.00"),
        currency="CNY",
        txn_date=date(2025, 1, 15),
    )
    await db.commit()

    with patch(
        # Patches the injected port, not src.pricing.get_exchange_rate: see
        # test_create_entry_from_txn_lazy_loads_missing_fx_rate above.
        "src.extraction.extension.review_queue._get_exchange_rate",
        side_effect=PricingError("No FX rate available for CNY/SGD on 2025-01-15"),
    ) as mock_get_rate:
        with pytest.raises(ValueError, match="FX rate required to create CNY journal entry"):
            await create_entry_from_txn(db, txn, user_id=test_user.id)

    # The failure path must still have attempted the lazy chain -- if
    # lazy_load ever regresses back to False while this except/raise stays
    # in place, this call-args assertion is what would actually catch it
    # (the exception-message assertion above would still pass either way).
    mock_get_rate.assert_awaited_once_with(db, "CNY", "SGD", date(2025, 1, 15), lazy_load=True)
