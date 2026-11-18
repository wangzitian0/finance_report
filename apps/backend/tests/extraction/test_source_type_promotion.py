from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    JournalEntrySourceType,
    SourceTypeDowngradeError,
    is_user_data_source_type,
    normalize_source_type,
    promote_entries_source_type,
    promote_entry_source_type,
    source_type_rank,
    source_type_tiebreak_key,
    statement_source_values,
)
from src.extraction import BankStatementStatus, Stage1Status, TransactionDirection
from src.identity import User
from src.ledger import AccountType, JournalEntry
from src.platform import DomainError
from src.request_context import RequestContext
from src.routers import statements as statements_router
from tests.extraction._statement_run_helpers import make_account
from tests.factories import AtomicTransactionFactory, StatementSummaryFactory, UploadedDocumentFactory

pytestmark = pytest.mark.asyncio


async def test_stage1_approve_preserves_auto_parsed_provenance(db: AsyncSession, test_user: User) -> None:
    bank_account = await make_account(db, test_user.id, name=f"DBS Confirmed {uuid4()}")
    document = await UploadedDocumentFactory.create_async(db, test_user.id)
    statement = await StatementSummaryFactory.create_async(
        db, test_user.id, uploaded_document_id=document.id, account_id=bank_account.id, file_hash=document.file_hash,
        institution="DBS", account_last4="1234", currency="SGD", period_start=date(2024, 2, 1), period_end=date(2024, 2, 29),
        opening_balance=Decimal("100.00"), closing_balance=Decimal("80.00"), status=BankStatementStatus.PARSED, balance_validated=True,
    )
    txn = await AtomicTransactionFactory.create_async(db, test_user.id, source_doc_id=document.id, txn_date=date(2024, 2, 10), description="Lunch", amount=Decimal("20.00"), direction=TransactionDirection.OUT)
    await db.commit()
    with pytest.raises(DomainError) as error:
        await statements_router.approve_statement_stage1(statement_id=statement.id, ctx=RequestContext(db, test_user.id))
    await db.refresh(statement)
    entry = (await db.execute(select(JournalEntry).where(JournalEntry.user_id == test_user.id, JournalEntry.source_id == txn.id))).scalar_one_or_none()
    assert (error.value.status_code, error.value.detail, statement.status, statement.stage1_status, entry) == (
        409, "Economic review required: intent_missing", BankStatementStatus.PARSED, Stage1Status.PENDING_REVIEW, None
    )


async def test_normalize_source_type_priority_and_tiebreak() -> None:
    manual, legacy, parsed = JournalEntry(source_type=JournalEntrySourceType.MANUAL), JournalEntry(source_type="bank_statement"), JournalEntry(source_type=JournalEntrySourceType.AUTO_PARSED)
    confirmed = JournalEntry(source_type=JournalEntrySourceType.USER_CONFIRMED)
    with pytest.raises(SourceTypeDowngradeError):
        promote_entry_source_type(confirmed, JournalEntrySourceType.AUTO_MATCHED, preserve_higher=False)
    promote_entries_source_type([parsed, manual], JournalEntrySourceType.AUTO_MATCHED)
    entry_id = uuid4()
    ranked = JournalEntry(id=entry_id, source_type=JournalEntrySourceType.USER_CONFIRMED)
    assert (
        normalize_source_type(None), normalize_source_type("bank_statement"), source_type_rank("unknown"),
        is_user_data_source_type("unknown"), is_user_data_source_type(JournalEntrySourceType.SYSTEM), statement_source_values(),
        promote_entry_source_type(manual, JournalEntrySourceType.AUTO_PARSED), manual.source_type,
        promote_entry_source_type(legacy, JournalEntrySourceType.AUTO_PARSED), legacy.source_type,
        confirmed.source_type, parsed.source_type, source_type_tiebreak_key(ranked),
    ) == (
        JournalEntrySourceType.MANUAL, JournalEntrySourceType.AUTO_PARSED, 0, False, False, ["auto_parsed", "auto_matched", "user_confirmed"],
        False, JournalEntrySourceType.MANUAL, True, JournalEntrySourceType.AUTO_PARSED, JournalEntrySourceType.USER_CONFIRMED,
        JournalEntrySourceType.AUTO_MATCHED, (3, entry_id),
    )
