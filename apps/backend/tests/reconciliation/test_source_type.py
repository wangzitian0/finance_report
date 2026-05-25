"""AC4.6.3 AC4.6.5 AC13.10 source_type trust hierarchy coverage."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
    User,
)
from src.services.reconciliation import execute_matching
from src.services.source_type_priority import SourceTypeDowngradeError, promote_entry_source_type

pytestmark = pytest.mark.asyncio


async def _add_accounts(db: AsyncSession, user_id) -> tuple[Account, Account, Account]:
    bank = Account(user_id=user_id, name=f"Bank {uuid4()}", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=user_id, name=f"Income {uuid4()}", type=AccountType.INCOME, currency="SGD")
    expense = Account(user_id=user_id, name=f"Expense {uuid4()}", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([bank, income, expense])
    await db.flush()
    return bank, income, expense


async def _add_entry(
    db: AsyncSession,
    *,
    user_id,
    debit_account: Account,
    credit_account: Account,
    amount: Decimal,
    memo: str,
    source_type: JournalEntrySourceType,
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 1, 15),
        memo=memo,
        source_type=source_type,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=debit_account.id,
                direction=Direction.DEBIT,
                amount=amount,
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit_account.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency="SGD",
            ),
        ]
    )
    await db.flush()
    return entry


async def _add_statement_txn(
    db: AsyncSession,
    *,
    user_id,
    description: str,
    amount: Decimal,
    direction: str,
) -> BankStatementTransaction:
    statement = BankStatement(
        user_id=user_id,
        file_path="statements/source-type.pdf",
        file_hash=f"source-type-{uuid4()}",
        original_filename="source-type.pdf",
        institution="DBS",
        account_last4="1234",
        currency="SGD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("100.00"),
        status=BankStatementStatus.PARSED,
    )
    db.add(statement)
    await db.flush()
    txn = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 1, 15),
        description=description,
        amount=amount,
        direction=direction,
        status=BankStatementTransactionStatus.PENDING,
    )
    db.add(txn)
    await db.flush()
    return txn


async def test_source_type_stamped_on_create(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC13.10.1: Manual API creation stamps source_type=manual by default."""
    bank, income, _ = await _add_accounts(db, test_user.id)
    await db.commit()

    response = await client.post(
        "/journal-entries",
        json={
            "entry_date": "2024-01-15",
            "memo": "Manual income",
            "lines": [
                {
                    "account_id": str(bank.id),
                    "direction": "DEBIT",
                    "amount": "100.00",
                    "currency": "SGD",
                },
                {
                    "account_id": str(income.id),
                    "direction": "CREDIT",
                    "amount": "100.00",
                    "currency": "SGD",
                },
            ],
        },
    )

    assert response.status_code == 201
    assert response.json()["source_type"] == JournalEntrySourceType.MANUAL.value


@pytest.mark.parametrize(
    "source_type",
    [
        JournalEntrySourceType.MANUAL.value,
        JournalEntrySourceType.USER_CONFIRMED.value,
        JournalEntrySourceType.AUTO_MATCHED.value,
        JournalEntrySourceType.AUTO_PARSED.value,
    ],
)
async def test_all_four_source_type_values_accepted_by_api(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    source_type: str,
) -> None:
    """AC13.10.6: API accepts the four source_type hierarchy values."""
    bank, income, _ = await _add_accounts(db, test_user.id)
    await db.commit()

    response = await client.post(
        "/journal-entries",
        json={
            "entry_date": "2024-01-16",
            "memo": f"Entry {source_type}",
            "source_type": source_type,
            "lines": [
                {
                    "account_id": str(bank.id),
                    "direction": "DEBIT",
                    "amount": "50.00",
                    "currency": "SGD",
                },
                {
                    "account_id": str(income.id),
                    "direction": "CREDIT",
                    "amount": "50.00",
                    "currency": "SGD",
                },
            ],
        },
    )

    assert response.status_code == 201
    assert response.json()["source_type"] == source_type


async def test_auto_match_sets_source_type(db: AsyncSession) -> None:
    """AC13.10.2: Auto-accepted reconciliation promotes source_type=auto_matched."""
    user = User(email=f"auto-match-{uuid4()}@example.com", hashed_password="hashed")
    db.add(user)
    await db.flush()
    bank, income, _ = await _add_accounts(db, user.id)
    entry = await _add_entry(
        db,
        user_id=user.id,
        debit_account=bank,
        credit_account=income,
        amount=Decimal("100.00"),
        memo="Salary Payment",
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    await _add_statement_txn(
        db,
        user_id=user.id,
        description="Salary Payment",
        amount=Decimal("100.00"),
        direction="IN",
    )

    matches = await execute_matching(db, user_id=user.id)

    assert len(matches) == 1
    assert entry.status == JournalEntryStatus.RECONCILED
    assert entry.source_type == JournalEntrySourceType.AUTO_MATCHED


async def test_manual_wins_conflict_resolution(db: AsyncSession) -> None:
    """AC13.10.4: Manual entries win equal-score conflicts over auto_parsed."""
    user = User(email=f"manual-wins-{uuid4()}@example.com", hashed_password="hashed")
    db.add(user)
    await db.flush()
    bank, _, expense = await _add_accounts(db, user.id)
    await _add_entry(
        db,
        user_id=user.id,
        debit_account=expense,
        credit_account=bank,
        amount=Decimal("12.00"),
        memo="Coffee Shop",
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    manual_entry = await _add_entry(
        db,
        user_id=user.id,
        debit_account=expense,
        credit_account=bank,
        amount=Decimal("12.00"),
        memo="Coffee Shop",
        source_type=JournalEntrySourceType.MANUAL,
    )
    await _add_statement_txn(
        db,
        user_id=user.id,
        description="Coffee Shop",
        amount=Decimal("12.00"),
        direction="OUT",
    )

    matches = await execute_matching(db, user_id=user.id)

    assert len(matches) == 1
    assert matches[0].journal_entry_ids == [str(manual_entry.id)]
    assert manual_entry.source_type == JournalEntrySourceType.MANUAL
    assert matches[0].score_breakdown["source_type_winner_rank"] == 4.0
    assert matches[0].score_breakdown["source_type_loser_rank"] == 1.0


async def test_source_type_no_downgrade(db: AsyncSession) -> None:
    """AC13.10.5: Explicit source_type downgrades are rejected."""
    user = User(email=f"no-downgrade-{uuid4()}@example.com", hashed_password="hashed")
    db.add(user)
    await db.flush()
    bank, income, _ = await _add_accounts(db, user.id)
    entry = await _add_entry(
        db,
        user_id=user.id,
        debit_account=bank,
        credit_account=income,
        amount=Decimal("10.00"),
        memo="Manual entry",
        source_type=JournalEntrySourceType.MANUAL,
    )

    with pytest.raises(SourceTypeDowngradeError):
        promote_entry_source_type(entry, JournalEntrySourceType.AUTO_PARSED, preserve_higher=False)

    assert entry.source_type == JournalEntrySourceType.MANUAL
