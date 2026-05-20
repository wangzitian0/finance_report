"""Stage-1 source_type promotion coverage."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    JournalEntry,
    JournalEntrySourceType,
    User,
)
from src.routers import statements as statements_router

pytestmark = pytest.mark.asyncio


async def test_stage1_approve_promotes_source_type(db: AsyncSession, test_user: User) -> None:
    """AC13.10.3: Stage-1 approval creates user_confirmed journal entries."""
    bank_account = Account(
        user_id=test_user.id,
        name=f"DBS Confirmed {uuid4()}",
        type=AccountType.ASSET,
        currency="SGD",
    )
    statement = BankStatement(
        user_id=test_user.id,
        account_id=None,
        file_path="tmp/source-type-promotion.pdf",
        file_hash=f"stage1-source-type-{uuid4()}",
        original_filename="source-type-promotion.pdf",
        institution="DBS",
        account_last4="1234",
        currency="SGD",
        period_start=date(2024, 2, 1),
        period_end=date(2024, 2, 29),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("80.00"),
        status=BankStatementStatus.PARSED,
        balance_validated=True,
    )
    db.add_all([bank_account, statement])
    await db.flush()
    statement.account_id = bank_account.id
    txn = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2024, 2, 10),
        description="Lunch",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=test_user.id)

    assert result.journal_entries_created == 1
    entry_result = await db.execute(
        select(JournalEntry).where(JournalEntry.user_id == test_user.id).where(JournalEntry.source_id == txn.id)
    )
    entry = entry_result.scalar_one()
    assert entry.source_type == JournalEntrySourceType.USER_CONFIRMED
