from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, SourceTypeDowngradeError, promote_entry_source_type
from src.extraction import BankStatementStatus, TransactionDirection
from src.ledger import AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reconciliation import ReconciliationMatchJournalEntry, execute_matching
from tests.factories import AccountFactory, AtomicTransactionFactory, StatementSummaryFactory, UploadedDocumentFactory, UserFactory

pytestmark = pytest.mark.asyncio


async def _add_accounts(db: AsyncSession, uid):
    return await AccountFactory.create_async(db, user_id=uid, name=f"B {uuid4()}"), await AccountFactory.create_async(db, user_id=uid, name=f"I {uuid4()}", type=AccountType.INCOME), await AccountFactory.create_async(db, user_id=uid, name=f"E {uuid4()}", type=AccountType.EXPENSE)


async def _add_entry(db: AsyncSession, uid, debit_acc, credit_acc, amount: Decimal, memo: str, source_type: JournalEntrySourceType) -> JournalEntry:
    e = JournalEntry(user_id=uid, entry_date=date(2024, 1, 15), memo=memo, source_type=source_type, status=JournalEntryStatus.POSTED, lines=[JournalLine(account_id=debit_acc.id, direction=Direction.DEBIT, amount=amount, currency="SGD"), JournalLine(account_id=credit_acc.id, direction=Direction.CREDIT, amount=amount, currency="SGD")])
    db.add(e)
    await db.flush()
    return e


async def _add_stmt_txn(db: AsyncSession, uid, desc: str, amt: Decimal, direction: str):
    custody, doc = await AccountFactory.create_async(db, user_id=uid, name=f"C {uuid4()}"), await UploadedDocumentFactory.create_async(db, user_id=uid)
    await StatementSummaryFactory.create_async(
        db,
        user_id=uid,
        account_id=custody.id,
        uploaded_document_id=doc.id,
        file_hash=doc.file_hash,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.APPROVED,
    )
    return await AtomicTransactionFactory.create_async(db, user_id=uid, source_doc_id=doc.id, txn_date=date(2024, 1, 15), description=desc, amount=amt, direction=TransactionDirection(direction))


async def test_source_type_stamped_on_create_and_auto_match(client: AsyncClient, db: AsyncSession, test_user) -> None:
    bank, income, _ = await _add_accounts(db, test_user.id)
    await db.commit()
    resp = await client.post("/journal-entries", json={"entry_date": "2024-01-15", "memo": "Manual income", "lines": [{"account_id": str(bank.id), "direction": "DEBIT", "amount": "100.00", "currency": "SGD"}, {"account_id": str(income.id), "direction": "CREDIT", "amount": "100.00", "currency": "SGD"}]})
    assert resp.status_code == 201 and resp.json()["source_type"] == JournalEntrySourceType.MANUAL.value

    uid = (await UserFactory.create_async(db)).id
    b2, i2, e2 = await _add_accounts(db, uid)
    entry = await _add_entry(db, uid, b2, i2, Decimal("100.00"), "Salary Payment", JournalEntrySourceType.AUTO_PARSED)
    await _add_stmt_txn(db, uid, "Salary Payment", Decimal("100.00"), "IN")
    matches = await execute_matching(db, user_id=uid, currency="SGD")
    assert len(matches) == 1 and (entry.status, entry.source_type) == (JournalEntryStatus.RECONCILED, JournalEntrySourceType.AUTO_PARSED) and await db.get(ReconciliationMatchJournalEntry, (matches[0].id, entry.id)) is not None

    await _add_entry(db, uid, e2, b2, Decimal("12.00"), "Coffee Shop", JournalEntrySourceType.AUTO_PARSED)
    manual = await _add_entry(db, uid, e2, b2, Decimal("12.00"), "Coffee Shop", JournalEntrySourceType.MANUAL)
    await _add_stmt_txn(db, uid, "Coffee Shop", Decimal("12.00"), "OUT")
    m2 = await execute_matching(db, user_id=uid, currency="SGD")
    assert len(m2) == 1 and m2[0].journal_entry_ids == [str(manual.id)] and (m2[0].score_breakdown["source_type_winner_rank"], m2[0].score_breakdown["source_type_loser_rank"]) == (4.0, 1.0)
    with pytest.raises(SourceTypeDowngradeError):
        promote_entry_source_type(manual, JournalEntrySourceType.AUTO_PARSED, preserve_higher=False)
    assert manual.source_type == JournalEntrySourceType.MANUAL


@pytest.mark.parametrize("source_type", [JournalEntrySourceType.MANUAL.value, JournalEntrySourceType.USER_CONFIRMED.value, JournalEntrySourceType.AUTO_MATCHED.value, JournalEntrySourceType.AUTO_PARSED.value])
async def test_public_journal_api_rejects_caller_selected_source_type(client: AsyncClient, db: AsyncSession, test_user, source_type: str) -> None:
    bank, income, _ = await _add_accounts(db, test_user.id)
    await db.commit()
    resp = await client.post("/journal-entries", json={"entry_date": "2024-01-16", "memo": f"Entry {source_type}", "source_type": source_type, "lines": [{"account_id": str(bank.id), "direction": "DEBIT", "amount": "50.00", "currency": "SGD"}, {"account_id": str(income.id), "direction": "CREDIT", "amount": "50.00", "currency": "SGD"}]})
    assert resp.status_code == 422
