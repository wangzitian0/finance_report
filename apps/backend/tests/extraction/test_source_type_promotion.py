"""Stage-1 source provenance coverage."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import TransactionDirection
from src.extraction.orm.statement_enums import BankStatementStatus
from src.identity import User
from src.ledger import Account, AccountType, JournalEntry
from src.routers import statements as statements_router
from tests.factories import (
    AtomicTransactionFactory,
    StatementSummaryFactory,
    UploadedDocumentFactory,
)

pytestmark = pytest.mark.asyncio


async def test_stage1_approve_preserves_auto_parsed_provenance(db: AsyncSession, test_user: User) -> None:
    """AC-extraction.110.3: approval cannot manufacture reviewed ledger provenance."""
    bank_account = Account(
        user_id=test_user.id,
        name=f"DBS Confirmed {uuid4()}",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(bank_account)
    await db.flush()

    document = await UploadedDocumentFactory.create_async(db, test_user.id)
    statement = await StatementSummaryFactory.create_async(
        db,
        test_user.id,
        uploaded_document_id=document.id,
        account_id=bank_account.id,
        file_hash=f"stage1-source-type-{uuid4()}",
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
    txn = await AtomicTransactionFactory.create_async(
        db,
        test_user.id,
        source_doc_id=document.id,
        txn_date=date(2024, 2, 10),
        description="Lunch",
        amount=Decimal("20.00"),
        direction=TransactionDirection.OUT,
    )
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=test_user.id)

    assert result.journal_entries_created == 0
    entry_result = await db.execute(
        select(JournalEntry).where(JournalEntry.user_id == test_user.id).where(JournalEntry.source_id == txn.id)
    )
    assert entry_result.scalar_one_or_none() is None
