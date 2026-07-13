"""Tests for reconciliation engine and review queue."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.extraction import DocumentType, UploadedDocument
from src.extraction.extension.review_queue import create_entry_from_txn, get_or_create_account
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    validate_journal_balance,
)
from src.pricing.orm.market_data import FxRate
from src.reconciliation import (
    DEFAULT_CONFIG,
    MatchCandidate,
    ReconciliationMatch,
    ReconciliationStatus,
    auto_accept,
    build_many_to_one_groups,
    execute_matching,
    normalize_text,
)
from src.reconciliation.extension.anomaly import detect_anomalies
from src.reconciliation.extension.review_queue import accept_match, batch_accept, reject_match
from tests.ledger._ledger_helpers import create_valid_posted_entry


async def _seed_summary(
    db: AsyncSession,
    *,
    owner_id: UUID,
    base_date: date,
    account_id: UUID | None = None,
    currency: str = "SGD",
) -> StatementSummary:
    """Create an UploadedDocument + StatementSummary conform for a user.

    Returns the StatementSummary. Atomic transactions reference its
    ``uploaded_document_id`` via ``source_documents``.
    """
    doc = UploadedDocument(
        user_id=owner_id,
        file_path="statements/test.pdf",
        file_hash="test_hash_" + str(base_date) + uuid4().hex,
        original_filename="test.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()
    summary = StatementSummary(
        user_id=owner_id,
        account_id=account_id,
        uploaded_document_id=doc.id,
        file_hash=doc.file_hash,
        institution="Test Bank",
        account_last4="1234",
        currency=currency,
        period_start=base_date,
        period_end=base_date,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )
    db.add(summary)
    await db.flush()
    return summary


def _atomic(
    *,
    owner_id: UUID,
    txn_date: date,
    description: str,
    amount: Decimal,
    direction: str = "OUT",
    summary: StatementSummary | None = None,
    currency: str = "SGD",
) -> AtomicTransaction:
    """Build a Layer-2 atomic transaction, optionally linked to a statement conform."""
    doc_id = summary.uploaded_document_id if summary is not None else uuid4()
    return AtomicTransaction(
        user_id=owner_id,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=TransactionDirection(direction),
        currency=currency,
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(doc_id), "doc_type": DocumentType.BANK_STATEMENT.value}],
    )


def test_auto_accept_threshold(ac_evidence) -> None:
    """AC-reconciliation.score.2: [AC4.3.1] [AC4.3.2] Auto-accept helper respects the threshold."""
    at_threshold = auto_accept(DEFAULT_CONFIG.auto_accept, DEFAULT_CONFIG)
    below_review = auto_accept(DEFAULT_CONFIG.pending_review - 1, DEFAULT_CONFIG)
    assert at_threshold
    assert not below_review
    # Measured evidence: a score at the auto-accept threshold auto-accepts.
    ac_evidence(
        ac_id="AC-reconciliation.score.2",
        score=1.0 if at_threshold else 0.0,
        metric="auto_accept_at_threshold",
        comment=f"auto_accept({DEFAULT_CONFIG.auto_accept})={at_threshold} (threshold={DEFAULT_CONFIG.auto_accept})",
        provenance="deterministic",
    )
    # Measured evidence: a score below the review threshold does not auto-accept.
    ac_evidence(
        ac_id="AC-reconciliation.score.2",
        score=1.0 if not below_review else 0.0,
        metric="below_review_not_auto_accepted",
        comment=(
            f"auto_accept({DEFAULT_CONFIG.pending_review - 1})={below_review} "
            f"(review threshold={DEFAULT_CONFIG.pending_review})"
        ),
        provenance="deterministic",
    )


def test_normalize_text_and_grouping() -> None:
    """Normalize text and group batch-like transactions."""
    assert normalize_text("  ACME-CO.  ") == "acme co"

    txn_date = date(2024, 2, 10)
    uid = uuid4()
    txn_a = _atomic(
        owner_id=uid,
        txn_date=txn_date,
        description="Batch settlement ACME",
        amount=Decimal("12.00"),
        direction="OUT",
    )
    txn_b = _atomic(
        owner_id=uid,
        txn_date=txn_date,
        description="Batch settlement ACME",
        amount=Decimal("18.00"),
        direction="OUT",
    )

    groups = build_many_to_one_groups([txn_a, txn_b])
    assert len(groups) == 1
    assert len(groups[0]) == 2


async def test_execute_matching_auto_accepts_exact_match(db: AsyncSession, test_user) -> None:
    """Exact matches should be auto-accepted and reconciled."""
    user_id = test_user.id
    bank = Account(
        user_id=user_id,
        name="Bank - Main",
        type=AccountType.ASSET,
        currency="SGD",
    )
    income = Account(
        user_id=user_id,
        name="Income - Salary",
        type=AccountType.INCOME,
        currency="SGD",
    )
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 15),
        memo="Salary Payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([bank, income, entry])
    await db.flush()
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 1, 15))

    line_debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank.id,
        direction=Direction.DEBIT,
        amount=Decimal("1000.00"),
        currency="SGD",
    )
    line_credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=income.id,
        direction=Direction.CREDIT,
        amount=Decimal("1000.00"),
        currency="SGD",
    )
    txn = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 1, 15),
        description="Salary Payment",
        amount=Decimal("1000.00"),
        direction="IN",
    )
    db.add_all([line_debit, line_credit, txn])
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 1
    match = matches[0]
    assert match.status == ReconciliationStatus.AUTO_ACCEPTED
    assert match.match_score >= 95


async def test_execute_matching_no_candidates(db: AsyncSession, test_user):
    """Test matching when no candidates are found for a transaction."""
    user_id = test_user.id
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 1, 1))

    txn = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 1, 1),
        description="Ghost Payment",
        amount=Decimal("100.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 0
    await db.refresh(txn)


async def test_transfer_pair_not_double_counted(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.source-type-transfer.2: AC4.6.2: Matching transfer OUT/IN within 3 days uses Processing entries only."""
    user_id = test_user.id
    checking = Account(
        user_id=user_id,
        name="Bank - Checking",
        type=AccountType.ASSET,
        currency="SGD",
    )
    savings = Account(
        user_id=user_id,
        name="Bank - Savings",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add_all([checking, savings])
    await db.flush()

    out_summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 3, 10), account_id=checking.id)
    in_summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 3, 12), account_id=savings.id)

    out_txn = _atomic(
        owner_id=user_id,
        summary=out_summary,
        txn_date=date(2024, 3, 10),
        description="FAST transfer to savings",
        amount=Decimal("500.00"),
        direction="OUT",
    )
    in_txn = _atomic(
        owner_id=user_id,
        summary=in_summary,
        txn_date=date(2024, 3, 12),
        description="FAST transfer from checking",
        amount=Decimal("500.00"),
        direction="IN",
    )
    db.add_all([out_txn, in_txn])
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)

    assert len(matches) == 2
    assert {match.status for match in matches} == {ReconciliationStatus.AUTO_ACCEPTED}
    breakdowns = sorted((match.score_breakdown for match in matches), key=lambda item: sorted(item))
    assert breakdowns == [
        {"transfer_in": 100.0},
        {"transfer_out": 100.0},
    ]

    await db.refresh(out_txn)
    await db.refresh(in_txn)

    transfer_entries_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type == JournalEntrySourceType.SYSTEM)
        .options(selectinload(JournalEntry.lines))
    )
    transfer_entries = transfer_entries_result.scalars().unique().all()
    assert len(transfer_entries) == 2
    assert {entry.status for entry in transfer_entries} == {JournalEntryStatus.RECONCILED}


async def test_execute_matching_pending_review_and_unmatched(db: AsyncSession, test_user) -> None:
    """Pending review and unmatched cases are handled correctly."""
    user_id = test_user.id
    bank = Account(
        user_id=user_id,
        name="Bank - Alt",
        type=AccountType.ASSET,
        currency="SGD",
    )
    holding = Account(
        user_id=user_id,
        name="Holding - Asset",
        type=AccountType.ASSET,
        currency="SGD",
    )
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 2, 5),
        memo="Transfer",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([bank, holding, entry])
    await db.flush()
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 2, 10))

    line_debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank.id,
        direction=Direction.DEBIT,
        amount=Decimal("96.00"),
        currency="SGD",
    )
    line_credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=holding.id,
        direction=Direction.CREDIT,
        amount=Decimal("96.00"),
        currency="SGD",
    )
    txn_pending = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 2, 10),
        description="Transfer",
        amount=Decimal("100.00"),
        direction="IN",
    )
    txn_unmatched = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2023, 12, 15),
        description="Old Vendor",
        amount=Decimal("45.00"),
        direction="OUT",
    )
    db.add_all([line_debit, line_credit, txn_pending, txn_unmatched])
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 1
    assert matches[0].status == ReconciliationStatus.PENDING_REVIEW

    await db.refresh(txn_pending)
    await db.refresh(txn_unmatched)


async def test_execute_matching_many_to_one_group(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.group-matching.1: [AC4.2.1] Batch-like transactions should reconcile via many-to-one grouping."""
    user_id = test_user.id
    bank = Account(
        user_id=user_id,
        name="Bank - Batch",
        type=AccountType.ASSET,
        currency="SGD",
    )
    expense = Account(
        user_id=user_id,
        name="Expense - Batch",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 4, 1),
        memo="Batch settlement ACME",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )

    db.add_all([bank, expense, entry])
    await db.flush()
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 4, 1))

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )

    txn_a = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 4, 1),
        description="Batch settlement ACME",
        amount=Decimal("40.00"),
        direction="OUT",
    )
    txn_b = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 4, 1),
        description="Batch settlement ACME",
        amount=Decimal("60.00"),
        direction="OUT",
    )
    db.add_all([txn_a, txn_b])
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 2
    assert all(m.status == ReconciliationStatus.AUTO_ACCEPTED for m in matches)


async def test_batch_accept_no_ids(db: AsyncSession):
    """Test batch_accept with empty list."""
    result = await batch_accept(db, [], user_id=uuid4())
    assert result == []


async def test_execute_matching_no_transactions(db: AsyncSession):
    """Test matching with no pending transactions."""
    result = await execute_matching(db, user_id=uuid4())
    assert result == []


async def test_find_candidates(db: AsyncSession, test_user):
    """Test find_candidates standalone helper."""
    from src.reconciliation import find_candidates, load_reconciliation_config

    user_id = test_user.id
    config = load_reconciliation_config()

    await create_valid_posted_entry(db, user_id, entry_date=date(2024, 1, 1), memo="Test Entry")

    # Within range
    results = await find_candidates(db, date(2024, 1, 1), config, user_id)
    assert len(results) == 1

    # Outside range
    results = await find_candidates(db, date(2024, 2, 1), config, user_id)
    assert len(results) == 0


async def test_execute_matching_multi_entry_combinations(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.group-matching.3: [AC4.2.3] Multi-entry combinations should produce the best match (One-to-Many)."""
    user_id = test_user.id
    bank = Account(
        user_id=user_id,
        name="Bank - Multi",
        type=AccountType.ASSET,
        currency="SGD",
    )
    expense = Account(
        user_id=user_id,
        name="Expense - Multi",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    entry_a = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 4, 5),
        memo="Split Payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry_b = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 4, 5),
        memo="Split Payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry_c = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 4, 5),
        memo="Split Payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )

    db.add_all([bank, expense, entry_a, entry_b, entry_c])
    await db.flush()
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 4, 5))

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_a.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("40.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_a.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("40.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_b.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("30.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_b.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("30.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_c.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("30.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_c.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("30.00"),
                currency="SGD",
            ),
        ]
    )

    txn = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 4, 5),
        description="Split Payment",
        amount=Decimal("100.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()

    matches = await execute_matching(db, user_id=user_id)
    assert len(matches) == 1
    match = matches[0]
    assert match.status == ReconciliationStatus.AUTO_ACCEPTED
    assert match.score_breakdown.get("multi_entry") == 2

    await db.refresh(txn)


async def test_review_queue_error_paths(db: AsyncSession) -> None:
    """Review queue helpers raise on missing matches and handle empty batch."""
    with pytest.raises(ValueError, match="Match not found"):
        await accept_match(db, str(uuid4()), user_id=uuid4())
    with pytest.raises(ValueError, match="Match not found"):
        await reject_match(db, str(uuid4()), user_id=uuid4())
    assert await batch_accept(db, [], user_id=uuid4()) == []


async def test_get_or_create_account_reuses_existing(db: AsyncSession, test_user) -> None:
    """get_or_create_account returns existing records."""
    user_id = test_user.id
    account = await get_or_create_account(
        db,
        name="Bank - Main",
        account_type=AccountType.ASSET,
        currency="SGD",
        user_id=user_id,
    )
    account_again = await get_or_create_account(
        db,
        name="Bank - Main",
        account_type=AccountType.ASSET,
        currency="SGD",
        user_id=user_id,
    )
    assert account_again.id == account.id


async def test_create_entry_from_txn_inflow_uses_statement_currency(
    db: AsyncSession,
    test_user,
) -> None:
    """Inflow transactions use statement currency and income account."""
    user_id = test_user.id
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.350000"),
            rate_date=date(2024, 4, 10),
            source="test",
        )
    )
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 4, 10), currency="USD")

    txn = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 4, 10),
        description="Client deposit",
        amount=Decimal("250.00"),
        direction="IN",
        currency="USD",
    )
    db.add(txn)
    await db.commit()

    entry = await create_entry_from_txn(db, txn, user_id=user_id)
    assert entry.source_type == JournalEntrySourceType.AUTO_PARSED
    assert all(line.currency == "USD" for line in entry.lines)
    assert all(line.fx_rate == Decimal("1.350000") for line in entry.lines)

    result = await db.execute(
        select(Account).where(Account.name == "Income - Uncategorized").where(Account.user_id == user_id)
    )
    assert result.scalar_one_or_none() is not None


async def test_create_entry_from_txn_requires_fx_rate_for_foreign_statement_currency(
    db: AsyncSession,
    test_user,
) -> None:
    """Foreign-currency statement auto-entry creation must not invent FX rates."""
    user_id = test_user.id
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 4, 11), currency="USD")

    txn = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 4, 11),
        description="Client deposit without FX",
        amount=Decimal("250.00"),
        direction="IN",
        currency="USD",
    )
    db.add(txn)
    await db.commit()

    with pytest.raises(ValueError, match="FX rate required to create USD journal entry"):
        await create_entry_from_txn(db, txn, user_id=user_id)


async def test_review_queue_actions_and_entry_creation(db: AsyncSession) -> None:
    """AC-reconciliation.review-queue.1: Review queue operations update match and transaction status."""
    user_id = uuid4()
    user = User(
        id=user_id,
        email=f"default-{uuid4()}@example.com",
        hashed_password="hashed",
    )
    db.add(user)
    await db.flush()
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 3, 1))

    txn_accept = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 3, 1),
        description="Coffee",
        amount=Decimal("12.34"),
        direction="OUT",
    )
    txn_reject = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 3, 1),
        description="Snacks",
        amount=Decimal("5.00"),
        direction="OUT",
    )
    txn_batch = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 3, 1),
        description="Lunch",
        amount=Decimal("15.00"),
        direction="OUT",
    )
    db.add_all([txn_accept, txn_reject, txn_batch])
    await db.commit()

    entry_accept = await create_entry_from_txn(db, txn_accept, user_id=user_id)
    entry_result = await db.execute(
        select(JournalEntry).where(JournalEntry.id == entry_accept.id).options(selectinload(JournalEntry.lines))
    )
    entry_accept = entry_result.scalar_one()
    validate_journal_balance(entry_accept.lines)

    accounts_result = await db.execute(select(Account).where(Account.user_id == user_id))
    accounts = {account.name: account for account in accounts_result.scalars().all()}
    bank = accounts["Bank - Main"]
    expense = accounts["Expense - Uncategorized"]

    entry_reject = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 3, 1),
        memo="Reject entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry_batch = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 3, 1),
        memo="Batch entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([entry_reject, entry_batch])
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_reject.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("5.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_reject.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("5.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_batch.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("15.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_batch.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("15.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    match_accept = ReconciliationMatch(
        atomic_txn_id=txn_accept.id,
        journal_entry_ids=[str(entry_accept.id)],
        match_score=92,
        score_breakdown={"amount": 100.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_reject = ReconciliationMatch(
        atomic_txn_id=txn_reject.id,
        journal_entry_ids=[str(entry_reject.id)],
        match_score=55,
        score_breakdown={"amount": 70.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_batch = ReconciliationMatch(
        atomic_txn_id=txn_batch.id,
        journal_entry_ids=[str(entry_batch.id)],
        match_score=85,
        score_breakdown={"amount": 90.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add_all([match_accept, match_reject, match_batch])
    await db.commit()

    accepted = await accept_match(db, str(match_accept.id), user_id=user_id)
    rejected = await reject_match(db, str(match_reject.id), user_id=user_id)
    batch = await batch_accept(db, [str(match_batch.id)], user_id=user_id)

    assert accepted.status == ReconciliationStatus.ACCEPTED
    assert rejected.status == ReconciliationStatus.REJECTED
    assert len(batch) == 1
    assert batch[0].status == ReconciliationStatus.ACCEPTED

    await db.refresh(entry_accept)
    assert entry_accept.status == JournalEntryStatus.RECONCILED


async def test_detect_anomalies_flags_expected_patterns(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.anomaly-detection.1: [AC4.5.1] Anomaly detection flags large, frequent, and new merchants."""
    user_id = test_user.id
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 3, 4))

    history_events = [
        _atomic(
            owner_id=user_id,
            summary=summary,
            txn_date=date(2024, 3, 4),
            description="Coffee Shop",
            amount=Decimal("10.00"),
            direction="OUT",
        )
        for _ in range(6)
    ]
    db.add_all(history_events)
    await db.commit()

    txn_large = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 3, 4),
        description="Coffee Shop",
        amount=Decimal("200.00"),
        direction="OUT",
    )
    anomalies_large = await detect_anomalies(db, txn_large, user_id=user_id)
    anomaly_types = {item.anomaly_type for item in anomalies_large}
    assert "LARGE_AMOUNT" in anomaly_types
    assert "FREQUENCY_SPIKE" in anomaly_types

    # 2024-03-09 is Saturday. Fixed date chosen to ensure stable weekend detection
    # across all timezones (no date arithmetic that could shift days).
    weekend_date = date(2024, 3, 9)
    txn_weekend = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=weekend_date,
        description="Gift Shop",
        amount=Decimal("60.00"),
        direction="OUT",
    )
    anomalies_weekend = await detect_anomalies(db, txn_weekend, user_id=user_id)
    weekend_types = {item.anomaly_type for item in anomalies_weekend}
    assert "NEW_MERCHANT" in weekend_types
    assert "WEEKEND_LARGE" in weekend_types


async def test_execute_matching_reuses_pattern_score_cache(db: AsyncSession, test_user) -> None:
    """AC4.6.6: Pattern score cache reuses merchant token score across transactions."""
    user_id = test_user.id
    bank = Account(user_id=user_id, name="Bank - Cache", type=AccountType.ASSET, currency="SGD")
    expense = Account(user_id=user_id, name="Expense - Cache", type=AccountType.EXPENSE, currency="SGD")
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 6, 10),
        memo="seed",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([bank, expense, entry])
    await db.flush()
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 6, 10))
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("1.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("1.00"),
                currency="SGD",
            ),
            _atomic(
                owner_id=user_id,
                summary=summary,
                txn_date=date(2024, 6, 10),
                description="ACME lunch",
                amount=Decimal("10.00"),
                direction="OUT",
            ),
            _atomic(
                owner_id=user_id,
                summary=summary,
                txn_date=date(2024, 6, 11),
                description="ACME dinner",
                amount=Decimal("11.00"),
                direction="OUT",
            ),
        ]
    )
    await db.commit()

    with (
        patch("src.reconciliation.extension.matching.detect_transfer_pattern", return_value=False),
        patch("src.reconciliation.extension.matching.find_transfer_pairs", new_callable=AsyncMock, return_value=[]),
        patch(
            "src.reconciliation.extension.matching.score_pattern", new_callable=AsyncMock, return_value=0.0
        ) as mock_score,
    ):
        await execute_matching(db, user_id=user_id)

    assert mock_score.await_count == 1


async def test_execute_matching_many_to_one_skips_unbalanced_entry(db: AsyncSession, test_user) -> None:
    """AC4.6.7: Many-to-one skips unbalanced candidates and leaves transactions unmatched."""
    user_id = test_user.id
    await create_valid_posted_entry(
        db,
        user_id,
        entry_date=date(2024, 7, 1),
        memo="Batch settlement",
        amount=Decimal("100.00"),
    )
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 7, 1))
    db.add_all(
        [
            _atomic(
                owner_id=user_id,
                summary=summary,
                txn_date=date(2024, 7, 1),
                description="Batch payroll",
                amount=Decimal("40.00"),
                direction="OUT",
            ),
            _atomic(
                owner_id=user_id,
                summary=summary,
                txn_date=date(2024, 7, 1),
                description="Batch payroll",
                amount=Decimal("60.00"),
                direction="OUT",
            ),
        ]
    )
    await db.commit()

    with (
        patch("src.reconciliation.extension.matching.find_transfer_pairs", new_callable=AsyncMock, return_value=[]),
        patch("src.reconciliation.extension.matching.is_entry_balanced", return_value=False),
    ):
        matches = await execute_matching(db, user_id=user_id)

    assert matches == []


async def test_execute_matching_many_to_one_keeps_same_existing_match(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.match.1: AC-extraction.406.8: Many-to-one keeps existing match when journal entry IDs are unchanged."""
    user_id = test_user.id
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 8, 1))
    txn = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 8, 1),
        description="Batch settlement",
        amount=Decimal("100.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.flush()
    existing_match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=["11111111-1111-1111-1111-111111111111"],
        match_score=95,
        score_breakdown={"amount": 100.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(existing_match)
    await db.commit()

    candidate = MatchCandidate(
        journal_entry_ids=["11111111-1111-1111-1111-111111111111"],
        score=95,
        breakdown={"amount": 100.0},
    )

    with (
        patch("src.reconciliation.extension.matching.build_many_to_one_groups", return_value=[[txn, txn]]),
        patch("src.reconciliation.extension.matching.prune_candidates", return_value=[object()]),
        patch("src.reconciliation.extension.matching.is_entry_balanced", return_value=True),
        patch(
            "src.reconciliation.extension.matching.calculate_match_score",
            new_callable=AsyncMock,
            return_value=candidate,
        ),
        patch("src.reconciliation.extension.matching.detect_transfer_pattern", return_value=False),
        patch("src.reconciliation.extension.matching.find_transfer_pairs", new_callable=AsyncMock, return_value=[]),
        patch("src.reconciliation.extension.matching.entry_total_amount", return_value=Decimal("100.00")),
    ):
        matches = await execute_matching(db, user_id=user_id)

    assert matches == []


async def test_execute_matching_many_to_one_layer2_sets_atomic_txn_id(db: AsyncSession, monkeypatch, test_user) -> None:
    """AC-reconciliation.source-type-transfer.7: AC4.6.9: Layer-2 reconciliation writes atomic_txn_id and supports transfer-pair logging."""
    user_id = test_user.id

    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2024, 8, 10),
        description="Batch card settlement",
        amount=Decimal("30.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash="m2o-layer2-atomic",
        source_documents=[{"doc_id": str(uuid4())}],
    )
    db.add(txn)
    await db.flush()

    entry = await create_valid_posted_entry(
        db,
        user_id,
        entry_date=date(2024, 8, 10),
        memo="candidate",
        amount=Decimal("30.00"),
    )

    candidate = MatchCandidate(journal_entry_ids=[str(entry.id)], score=95, breakdown={"amount": 100.0})

    with (
        patch("src.reconciliation.extension.matching.detect_transfer_pattern", return_value=False),
        patch("src.reconciliation.extension.matching.find_transfer_pairs", new_callable=AsyncMock, return_value=[]),
        patch("src.reconciliation.extension.matching.build_many_to_one_groups", return_value=[[txn]]),
        patch("src.reconciliation.extension.matching.prune_candidates", return_value=[entry]),
        patch("src.reconciliation.extension.matching.is_entry_balanced", return_value=True),
        patch(
            "src.reconciliation.extension.matching.calculate_match_score",
            new_callable=AsyncMock,
            return_value=candidate,
        ),
        patch("src.reconciliation.extension.matching.score_pattern", new_callable=AsyncMock, return_value=0.0),
    ):
        matches = await execute_matching(db, user_id=user_id)

    assert len(matches) == 1
    assert matches[0].atomic_txn_id == txn.id


async def test_execute_matching_three_entry_combination_skips_unbalanced_member(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.recovered-coverage.2: AC4.7.3: Reconciliation phase-2 – 3-entry combo exceeding tolerance is skipped."""
    user_id = test_user.id
    summary = await _seed_summary(db, owner_id=user_id, base_date=date(2024, 9, 12))

    txn = _atomic(
        owner_id=user_id,
        summary=summary,
        txn_date=date(2024, 9, 12),
        description="three-part settlement",
        amount=Decimal("3.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.flush()

    entry_a = await create_valid_posted_entry(
        db,
        user_id,
        entry_date=date(2024, 9, 12),
        memo="a",
        amount=Decimal("1.00"),
    )
    entry_b = await create_valid_posted_entry(
        db,
        user_id,
        entry_date=date(2024, 9, 12),
        memo="b",
        amount=Decimal("1.00"),
    )
    entry_c = await create_valid_posted_entry(
        db,
        user_id,
        entry_date=date(2024, 9, 12),
        memo="c",
        amount=Decimal("1.00"),
    )

    low_score = MatchCandidate(journal_entry_ids=[str(entry_a.id)], score=0, breakdown={"amount": 0.0})

    with (
        patch("src.reconciliation.extension.matching.detect_transfer_pattern", return_value=False),
        patch("src.reconciliation.extension.matching.find_transfer_pairs", new_callable=AsyncMock, return_value=[]),
        patch("src.reconciliation.extension.matching.build_many_to_one_groups", return_value=[]),
        patch("src.reconciliation.extension.matching.prune_candidates", return_value=[entry_a, entry_b, entry_c]),
        patch(
            "src.reconciliation.extension.matching.is_entry_balanced",
            side_effect=lambda e: e.id != entry_c.id,
        ),
        patch(
            "src.reconciliation.extension.matching.calculate_match_score",
            new_callable=AsyncMock,
            return_value=low_score,
        ),
        patch("src.reconciliation.extension.matching.entry_total_amount", return_value=Decimal("1.00")),
        patch("src.reconciliation.extension.matching.score_pattern", new_callable=AsyncMock, return_value=0.0),
    ):
        matches = await execute_matching(db, user_id=user_id)

    assert matches == []


async def test_execute_matching_layer2_atomic_match_and_transfer_pair_logging(
    db: AsyncSession, monkeypatch, test_user
) -> None:
    """AC-reconciliation.recovered-coverage.3: AC4.7.4: Reconciliation phase-2 – atomic match and transfer pair logging in layer-2."""
    user_id = test_user.id

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 9, 1),
        memo="Layer2 candidate",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    bank = Account(user_id=user_id, name="Bank L2", type=AccountType.ASSET, currency="SGD")
    expense = Account(user_id=user_id, name="Expense L2", type=AccountType.EXPENSE, currency="SGD")
    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2024, 9, 1),
        description="Office supplies",
        amount=Decimal("50.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash="layer2-atomic-1",
        source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}],
    )
    db.add_all([entry, bank, expense, txn])
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=expense.id,
                direction=Direction.DEBIT,
                amount=Decimal("50.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.CREDIT,
                amount=Decimal("50.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    candidate = MatchCandidate(journal_entry_ids=[str(entry.id)], score=99, breakdown={"amount": 100.0})
    with (
        patch("src.reconciliation.extension.matching.detect_transfer_pattern", return_value=False),
        patch("src.reconciliation.extension.matching.build_many_to_one_groups", return_value=[]),
        patch(
            "src.reconciliation.extension.matching.calculate_match_score",
            new_callable=AsyncMock,
            return_value=candidate,
        ),
        patch(
            "src.reconciliation.extension.matching.find_transfer_pairs",
            new_callable=AsyncMock,
            return_value=[("a", "b")],
        ),
        patch("src.reconciliation.extension.matching.score_pattern", new_callable=AsyncMock, return_value=0.0),
    ):
        matches = await execute_matching(db, user_id=user_id)

    assert len(matches) == 1
    assert matches[0].atomic_txn_id == txn.id
