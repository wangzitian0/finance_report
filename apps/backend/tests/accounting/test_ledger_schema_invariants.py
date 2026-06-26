"""Database-level ledger invariant tests for direct write bypass attempts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine


async def _account(db: AsyncSession, user_id, name: str, account_type: AccountType) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, is_active=True)
    db.add(account)
    await db.flush()
    return account


async def _valid_posted_entry(
    db: AsyncSession, user_id, *, memo: str = "posted"
) -> tuple[JournalEntry, JournalLine, JournalLine]:
    debit_account = await _account(db, user_id, f"{memo} cash", AccountType.ASSET)
    credit_account = await _account(db, user_id, f"{memo} income", AccountType.INCOME)
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date.today(),
        memo=memo,
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=debit_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=credit_account.id,
        direction=Direction.CREDIT,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    db.add_all([debit, credit])
    await db.commit()
    await db.refresh(entry)
    await db.refresh(debit)
    await db.refresh(credit)
    return entry, debit, credit


async def test_AC2_14_1_posted_entry_requires_two_lines_at_database_boundary(db: AsyncSession, test_user):
    """AC2.14.1: Posted/reconciled entries need at least two lines at the database boundary."""
    cash = await _account(db, test_user.id, "cash", AccountType.ASSET)
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="single line posted bypass",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=cash.id,
            direction=Direction.DEBIT,
            amount=Decimal("10.00"),
            currency="SGD",
        )
    )

    with pytest.raises(IntegrityError):
        await db.commit()


async def test_AC2_14_2_posted_entry_must_balance_in_base_currency(db: AsyncSession, test_user):
    """AC2.14.2: Posted/reconciled entries balance debit and credit totals in base currency."""
    cash = await _account(db, test_user.id, "cash", AccountType.ASSET)
    income = await _account(db, test_user.id, "income", AccountType.INCOME)
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="unbalanced posted bypass",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("99.98"),
                currency="SGD",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db.commit()


async def test_AC2_14_3_non_base_posted_lines_require_positive_fx_rate(db: AsyncSession, test_user):
    """AC2.14.3: Non-base posted/reconciled lines require positive FX rates."""
    cash = await _account(db, test_user.id, "hkd cash", AccountType.ASSET)
    income = await _account(db, test_user.id, "sgd income", AccountType.INCOME)
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="missing fx bypass",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="HKD",
                fx_rate=Decimal("0.000000"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await db.commit()


async def test_AC2_14_4_posted_entries_and_lines_are_immutable_but_drafts_are_editable(db: AsyncSession, test_user):
    """AC2.14.4: Posted/reconciled ledger facts block direct mutation; drafts remain editable."""
    user_id = test_user.id
    entry, debit, _credit = await _valid_posted_entry(db, user_id)
    entry_id = entry.id

    entry.memo = "mutated posted memo"
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    await db.refresh(entry)
    await db.refresh(debit)

    debit.amount = Decimal("101.00")
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    await db.refresh(debit)

    await db.delete(debit)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()

    extra_cash = await _account(db, user_id, "extra cash", AccountType.ASSET)
    extra_income = await _account(db, user_id, "extra income", AccountType.INCOME)
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_id,
                account_id=extra_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_id,
                account_id=extra_income.id,
                direction=Direction.CREDIT,
                amount=Decimal("1.00"),
                currency="SGD",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()

    reconcile_entry, _reconcile_debit, _reconcile_credit = await _valid_posted_entry(
        db, user_id, memo="reconcile source guard"
    )
    reconcile_entry.status = JournalEntryStatus.RECONCILED
    reconcile_entry.source_type = JournalEntrySourceType.AUTO_PARSED
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()

    draft_account = await _account(db, user_id, "draft cash", AccountType.ASSET)
    draft = JournalEntry(
        user_id=user_id,
        entry_date=date.today(),
        memo="editable draft",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(draft)
    await db.flush()
    draft_line = JournalLine(
        journal_entry_id=draft.id,
        account_id=draft_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("1.00"),
        currency="SGD",
    )
    db.add(draft_line)
    await db.commit()

    draft.memo = "edited draft"
    draft_line.amount = Decimal("2.00")
    await db.commit()
    await db.delete(draft_line)
    await db.delete(draft)
    await db.commit()


async def test_AC2_14_5_void_transition_requires_reversal_relationship(db: AsyncSession, test_user):
    """AC2.14.5: Voiding preserves a non-null immutable reversal relationship."""
    user_id = test_user.id
    entry, _debit, _credit = await _valid_posted_entry(db, user_id, memo="original")
    entry_id = entry.id

    entry.status = JournalEntryStatus.VOID
    entry.void_reason = "missing reversal"
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    entry = await db.get(JournalEntry, entry_id)
    assert entry is not None

    reversal, _reversal_debit, _reversal_credit = await _valid_posted_entry(db, user_id, memo="reversal")
    entry.status = JournalEntryStatus.VOID
    entry.void_reason = "valid reversal"
    entry.void_reversal_entry_id = reversal.id
    await db.commit()

    entry.void_reversal_entry_id = None
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    entry = await db.get(JournalEntry, entry_id)
    assert entry is not None

    await db.delete(entry)
    with pytest.raises(IntegrityError):
        await db.commit()
