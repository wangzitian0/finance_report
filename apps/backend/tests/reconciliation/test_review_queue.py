from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.models import (
    AccountType,
    BankStatementTransactionStatus,
    JournalEntryStatus,
    ReconciliationStatus,
)
from src.services.review_queue import (
    accept_match,
    batch_accept,
    create_entry_from_txn,
    get_or_create_account,
    get_pending_items,
    reject_match,
)
from tests.factories import (
    AccountFactory,
    BankStatementFactory,
    BankStatementTransactionFactory,
    JournalEntryFactory,
    ReconciliationMatchFactory,
)


@pytest.mark.asyncio
async def test_get_pending_items_returns_pending_matches(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    results = await get_pending_items(db, user_id=test_user.id)
    assert len(results) == 1
    assert results[0].status == ReconciliationStatus.PENDING_REVIEW


@pytest.mark.asyncio
async def test_get_pending_items_excludes_accepted(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.ACCEPTED,
    )
    await db.commit()

    results = await get_pending_items(db, user_id=test_user.id)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_accept_match_updates_status(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id, amount=Decimal("100.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id, amount=Decimal("100.00"))
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    result = await accept_match(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED
    assert result.version == 2

    await db.refresh(txn)
    assert txn.status == BankStatementTransactionStatus.MATCHED


@pytest.mark.asyncio
async def test_accept_match_not_found_raises(db, test_user):
    with pytest.raises(ValueError, match="Match not found"):
        await accept_match(db, str(uuid4()), user_id=test_user.id)


@pytest.mark.asyncio
async def test_accept_match_already_accepted_returns_unchanged(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.ACCEPTED,
    )
    await db.commit()

    result = await accept_match(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED
    assert result.version == 1


@pytest.mark.asyncio
async def test_accept_match_amount_mismatch_raises(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id, amount=Decimal("500.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id, amount=Decimal("100.00"))
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    with pytest.raises(ValueError, match="Amount mismatch"):
        await accept_match(db, str(match.id), user_id=test_user.id)


@pytest.mark.asyncio
async def test_accept_match_skip_amount_validation(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id, amount=Decimal("500.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id, amount=Decimal("100.00"))
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    result = await accept_match(db, str(match.id), user_id=test_user.id, skip_amount_validation=True)
    assert result.status == ReconciliationStatus.ACCEPTED


@pytest.mark.asyncio
async def test_accept_match_reconciles_journal_entries(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id, amount=Decimal("100.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id, amount=Decimal("100.00"))
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    await accept_match(db, str(match.id), user_id=test_user.id)
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.RECONCILED


@pytest.mark.asyncio
async def test_accept_match_does_not_reconcile_void_entries(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id, amount=Decimal("100.00"))
    entry, _, _ = await JournalEntryFactory.create_balanced_async(
        db, user_id=test_user.id, amount=Decimal("100.00"), status=JournalEntryStatus.VOID
    )
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
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
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    result = await reject_match(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.REJECTED
    assert result.version == 2

    await db.refresh(txn)
    assert txn.status == BankStatementTransactionStatus.UNMATCHED


@pytest.mark.asyncio
async def test_reject_match_not_found_raises(db, test_user):
    with pytest.raises(ValueError, match="Match not found"):
        await reject_match(db, str(uuid4()), user_id=test_user.id)


@pytest.mark.asyncio
async def test_reject_match_already_rejected_returns_unchanged(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
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
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)

    txn1 = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
    entry1, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match1 = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn1.id,
        journal_entry_ids=[str(entry1.id)],
        match_score=90,
        status=ReconciliationStatus.PENDING_REVIEW,
    )

    txn2 = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
    entry2, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match2 = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn2.id,
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
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=50,
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await db.commit()

    accepted = await batch_accept(db, [str(match.id)], user_id=test_user.id, min_score=80)
    assert len(accepted) == 0


@pytest.mark.asyncio
async def test_batch_accept_reconciles_journal_entries(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
    entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
    match = await ReconciliationMatchFactory.create_async(
        db,
        bank_txn_id=txn.id,
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
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        direction="IN",
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
async def test_create_entry_from_txn_dr_direction(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        direction="DR",
        amount=Decimal("50.00"),
        txn_date=date(2025, 1, 20),
        description="Coffee shop",
    )
    await db.commit()

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)
    assert entry.status == JournalEntryStatus.DRAFT
    assert len(entry.lines) == 2


@pytest.mark.asyncio
async def test_create_entry_from_txn_wrong_user_raises(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(db, statement_id=stmt.id)
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
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id, account_id=linked_account.id)
    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        direction="IN",
        amount=Decimal("300.00"),
        txn_date=date(2025, 2, 1),
        description="Bonus",
    )
    await db.commit()

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id)
    account_ids = {line.account_id for line in entry.lines}
    assert linked_account.id in account_ids


@pytest.mark.asyncio
async def test_create_entry_sets_txn_pending(db, test_user):
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        direction="DR",
        amount=Decimal("25.00"),
    )
    await db.commit()

    await create_entry_from_txn(db, txn, user_id=test_user.id)
    await db.refresh(txn)
    assert txn.status == BankStatementTransactionStatus.PENDING
