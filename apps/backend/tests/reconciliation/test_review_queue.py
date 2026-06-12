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

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    ClassificationRule,
    ClassificationStatus,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    ReconciliationStatus,
    RuleType,
    TransactionClassification,
)
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_summary import StatementSummary
from src.services.accounting import ValidationError
from src.services.review_queue import (
    accept_match,
    batch_accept,
    create_entry_from_txn,
    get_or_create_account,
    get_pending_items,
    reject_match,
)
from tests.accounting._ledger_helpers import create_valid_void_entry
from tests.factories import (
    AccountFactory,
    AtomicTransactionFactory,
    JournalEntryFactory,
    ReconciliationMatchFactory,
    StatementSummaryFactory,
    UploadedDocumentFactory,
)


async def _make_statement(db: AsyncSession, user_id, *, account_id=None, currency: str = "SGD"):
    """Create a linked UploadedDocument + StatementSummary conform.

    Returns the StatementSummary; its ``uploaded_document_id`` is what atomic
    transactions reference via ``source_documents``.
    """
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_accept_match_updates_status(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id, amount=Decimal("100.00"))
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    result = await accept_match(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED
    assert result.version == 2


@pytest.mark.asyncio
async def test_accept_match_not_found_raises(db, test_user):
    with pytest.raises(ValueError, match="Match not found"):
        await accept_match(db, str(uuid4()), user_id=test_user.id)


@pytest.mark.asyncio
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

    result = await accept_match(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED
    assert result.version == 1


@pytest.mark.asyncio
async def test_accept_match_amount_mismatch_raises(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("500.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id, amount=Decimal("100.00"))
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    with pytest.raises(ValueError, match="Amount mismatch"):
        await accept_match(db, str(match.id), user_id=test_user.id)


@pytest.mark.asyncio
async def test_accept_match_skip_amount_validation(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("500.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id, amount=Decimal("100.00"))
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    result = await accept_match(db, str(match.id), user_id=test_user.id, skip_amount_validation=True)
    assert result.status == ReconciliationStatus.ACCEPTED


@pytest.mark.asyncio
async def test_accept_match_reconciles_journal_entries(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id, amount=Decimal("100.00"))
    match = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    await accept_match(db, str(match.id), user_id=test_user.id)
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.RECONCILED


@pytest.mark.asyncio
async def test_accept_match_creates_missing_journal_entry(db, test_user):
    """AC16.24.4: Accepting a Stage 2 match without entries creates and reconciles one journal entry."""
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

    result = await accept_match(db, str(match.id), user_id=test_user.id)

    assert result.status == ReconciliationStatus.ACCEPTED
    assert len(result.journal_entry_ids) == 1
    entry = await db.get(JournalEntry, UUID(result.journal_entry_ids[0]))
    assert entry is not None
    assert entry.source_type == JournalEntrySourceType.USER_CONFIRMED
    assert entry.source_id == txn.id
    assert entry.status == JournalEntryStatus.RECONCILED


@pytest.mark.asyncio
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

    await accept_match(db, str(match.id), user_id=test_user.id, skip_amount_validation=True)
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.VOID


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_reject_match_not_found_raises(db, test_user):
    with pytest.raises(ValueError, match="Match not found"):
        await reject_match(db, str(uuid4()), user_id=test_user.id)


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_batch_accept_empty_list(db, test_user):
    result = await batch_accept(db, [], user_id=test_user.id)
    assert result == []


@pytest.mark.asyncio
async def test_batch_accept_accepts_high_score_matches(db, test_user):
    stmt = await _make_statement(db, test_user.id)

    txn1 = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry1, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match1 = await ReconciliationMatchFactory.create_async(
        db,
        atomic_txn_id=txn1.id,
        journal_entry_ids=[str(entry1.id)],
        match_score=90,
        status=ReconciliationStatus.PENDING_REVIEW,
    )

    txn2 = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry2, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_batch_accept_reconciles_journal_entries(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt, amount=Decimal("100.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_create_entry_from_txn_in_direction(db, test_user):
    stmt = await _make_statement(db, test_user.id)
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

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)
    assert entry.status == JournalEntryStatus.DRAFT
    assert len(entry.lines) == 2

    debit_line = next(line for line in entry.lines if line.direction.value == "DEBIT")
    credit_line = next(line for line in entry.lines if line.direction.value == "CREDIT")
    assert debit_line.amount == Decimal("200.00")
    assert credit_line.amount == Decimal("200.00")


@pytest.mark.asyncio
async def test_create_entry_from_txn_out_direction(db, test_user):
    stmt = await _make_statement(db, test_user.id)
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

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)
    assert entry.status == JournalEntryStatus.DRAFT
    assert len(entry.lines) == 2


@pytest.mark.asyncio
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

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id, auto_post=True)
    assert entry.status == JournalEntryStatus.POSTED


@pytest.mark.asyncio
async def test_create_entry_from_txn_auto_post_requires_account_mapping(db, test_user):
    """AC3.6.2: Posted entries cannot silently use the Bank - Main fallback."""
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.IN,
        amount=Decimal("75.00"),
    )
    await db.commit()

    with pytest.raises(ValueError, match="Account mapping required before posting"):
        await create_entry_from_txn(db, txn, user_id=test_user.id, auto_post=True)


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_create_entry_from_txn_rejects_unowned_preloaded_bank_account(db, test_user):
    user_id = test_user.id
    stmt = await _make_statement(db, user_id)
    txn = await _make_txn(db, user_id, stmt)
    other_account = await AccountFactory.create_async(
        db,
        user_id=uuid4(),
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_create_entry_from_txn_wrong_user_raises(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(db, test_user.id, stmt)
    await db.commit()

    with pytest.raises(ValueError, match="Transaction does not belong to user"):
        await create_entry_from_txn(db, txn, user_id=uuid4())


@pytest.mark.asyncio
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

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)
    account_ids = {line.account_id for line in entry.lines}
    assert linked_account.id in account_ids


@pytest.mark.asyncio
async def test_statement_summary_rejects_linked_account_not_owned(db, test_user):
    other_user_id = uuid4()
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


@pytest.mark.asyncio
async def test_create_entry_from_txn_raises_when_generated_entry_unbalanced(db, test_user):
    stmt = await _make_statement(db, test_user.id)
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.IN,
        amount=Decimal("10.00"),
    )
    await db.commit()

    with patch("src.services.review_queue.validate_journal_balance", side_effect=ValidationError("not balanced")):
        with pytest.raises(ValueError, match="Generated entry does not balance"):
            await create_entry_from_txn(db, txn, user_id=test_user.id)


@pytest.mark.asyncio
async def test_create_entry_from_txn_uses_layer3_classification_account(db, test_user):
    classified_account = await AccountFactory.create_async(
        db,
        user_id=test_user.id,
        name="Expense - Food & Dining",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    stmt = await _make_statement(db, test_user.id, currency="SGD")
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

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)

    debit_line = next(line for line in entry.lines if line.direction.value == "DEBIT")
    assert debit_line.account_id == classified_account.id


@pytest.mark.asyncio
async def test_create_entry_from_txn_outflow_defaults_to_uncategorized_expense(db, test_user):
    """Without a Layer-3 classification, an outflow debits Expense - Uncategorized."""
    stmt = await _make_statement(db, test_user.id, currency="SGD")
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.OUT,
        amount=Decimal("15.00"),
        description="MRT",
    )
    await db.commit()

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)
    debit_line = next(line for line in entry.lines if line.direction.value == "DEBIT")

    account_result = await db.execute(select(Account).where(Account.id == debit_line.account_id))
    account = account_result.scalar_one()

    assert account.name == "Expense - Uncategorized"
    assert account.type == AccountType.EXPENSE
    assert account.user_id == test_user.id


@pytest.mark.asyncio
async def test_create_entry_from_txn_inflow_defaults_to_uncategorized_income(db, test_user):
    """Without a Layer-3 classification, an inflow credits Income - Uncategorized."""
    stmt = await _make_statement(db, test_user.id, currency="SGD")
    txn = await _make_txn(
        db,
        test_user.id,
        stmt,
        direction=TransactionDirection.IN,
        amount=Decimal("1200.00"),
        description="Monthly salary",
    )
    await db.commit()

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)
    credit_line = next(line for line in entry.lines if line.direction.value == "CREDIT")

    account_result = await db.execute(select(Account).where(Account.id == credit_line.account_id))
    account = account_result.scalar_one()

    assert account.name == "Income - Uncategorized"
    assert account.type == AccountType.INCOME
    assert account.user_id == test_user.id
