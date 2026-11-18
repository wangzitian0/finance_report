from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction import BankStatementStatus, DocumentSource, DocumentType, TransactionDirection, UploadedDocument
from src.extraction.extension.service import ExtractionService
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import AccountType, JournalEntry, JournalEntryStatus, JournalLine, get_or_create_processing_account, get_processing_balance
from src.reconciliation import ReconciliationMatch, ReconciliationStatus, execute_matching
from src.reconciliation.extension.repository import SqlReconciliationRepository
from tests.factories import AccountFactory
from tests.statement_ingestion import parse_and_load_statement_projection


async def _seed_statement(db: AsyncSession, user_id, *, account_id, file_hash: str) -> UploadedDocument:
    doc = UploadedDocument(user_id=user_id, file_path=f"/tmp/{file_hash}.pdf", file_hash=file_hash, original_filename="test.pdf", document_type=DocumentType.BANK_STATEMENT)
    db.add(doc)
    await db.flush()
    db.add(StatementSummary(user_id=user_id, account_id=account_id, uploaded_document_id=doc.id, file_hash=file_hash, institution="TestBank", account_last4="1234", currency="SGD", period_start=date(2025, 1, 1), period_end=date(2025, 1, 31), opening_balance=Decimal("0.00"), closing_balance=Decimal("0.00"), status=BankStatementStatus.PARSED))
    await db.flush()
    return doc


async def _seed_txn(db: AsyncSession, user_id, doc: UploadedDocument, *, description: str, amount: Decimal, direction: str, txn_date: date | None = None) -> AtomicTransaction:
    txn = AtomicTransaction(user_id=user_id, txn_date=txn_date or date.today(), description=description, amount=amount, direction=TransactionDirection(direction), currency="SGD", dedup_hash=uuid4().hex + uuid4().hex, source_documents=[{"doc_id": str(doc.id), "doc_type": DocumentType.BANK_STATEMENT.value}])
    db.add(txn)
    await db.flush()
    return txn


async def _lines_for(db: AsyncSession, account_id, entry_id=None) -> list[JournalLine]:
    q = select(JournalLine).where(JournalLine.account_id == account_id)
    return list((await db.execute(q if entry_id is None else q.where(JournalLine.journal_entry_id == entry_id))).scalars().all())


@pytest.mark.parametrize(("direction", "desc", "amt", "p_dir", "c_dir"), [("OUT", "TRANSFER TO SAVINGS ACCOUNT", "200.00", "DEBIT", "CREDIT"), ("IN", "PAYNOW TRANSFER FROM JANE", "300.00", "CREDIT", "DEBIT")])
async def test_transfer_leg_direction_and_idempotency(db: AsyncSession, test_user, direction: str, desc: str, amt: str, p_dir: str, c_dir: str):
    uid, dec_amt = test_user.id, Decimal(amt)
    acc = await AccountFactory.create_async(db, user_id=uid, name=f"Acc-{direction}")
    doc = await _seed_statement(db, uid, account_id=acc.id, file_hash=f"xfer_{direction}")
    txn = await _seed_txn(db, uid, doc, description=desc, amount=dec_amt, direction=direction)
    matches = await execute_matching(db, user_id=uid, currency="SGD")
    assert len(matches) == 1 and matches[0].match_score == 100 and len(matches[0].journal_entry_ids) == 1
    eid = UUID(matches[0].journal_entry_ids[0])
    entry = await db.get(JournalEntry, eid)
    assert entry.source_type == JournalEntrySourceType.SYSTEM and entry.status == JournalEntryStatus.RECONCILED
    proc = await get_or_create_processing_account(db, uid, currency="SGD")
    p_line, c_line = (await _lines_for(db, proc.id, eid))[0], (await _lines_for(db, acc.id, eid))[0]
    assert (p_line.direction.value, p_line.amount, c_line.direction.value, c_line.amount) == (p_dir, dec_amt, c_dir, dec_amt)
    assert await execute_matching(db, user_id=uid, currency="SGD") == []
    assert len((await db.execute(select(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == txn.id, ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED))).scalars().all()) == 1


async def test_transfer_unlinked_auto_pair_and_mixed_transactions(db: AsyncSession, test_user):
    uid = test_user.id
    unlinked_doc = await _seed_statement(db, uid, account_id=None, file_hash="test_hash_no_account")
    await _seed_txn(db, uid, unlinked_doc, description="TRANSFER TO CHECKING", amount=Decimal("150.00"), direction="OUT")
    assert await execute_matching(db, user_id=uid, currency="SGD") == []
    proc = await get_or_create_processing_account(db, uid, currency="SGD")
    assert await _lines_for(db, proc.id) == []

    cash = await AccountFactory.create_async(db, user_id=uid, name="Cash")
    checking = await AccountFactory.create_async(db, user_id=uid, name="Checking")
    expense = await AccountFactory.create_async(db, user_id=uid, name="Expenses", type=AccountType.EXPENSE)
    cash_doc = await _seed_statement(db, uid, account_id=cash.id, file_hash="cash_stmt")
    chk_doc = await _seed_statement(db, uid, account_id=checking.id, file_hash="checking_stmt")
    out_txn = await _seed_txn(db, uid, cash_doc, description="FAST PAYMENT TO BANK B", amount=Decimal("500.00"), direction="OUT", txn_date=date(2025, 1, 10))
    in_txn = await _seed_txn(db, uid, chk_doc, description="FAST PAYMENT FROM BANK A", amount=Decimal("500.00"), direction="IN", txn_date=date(2025, 1, 11))
    assert {t.id for t in await SqlReconciliationRepository(db).list_pending_transactions(uid)} >= {out_txn.id, in_txn.id}
    paired = await execute_matching(db, user_id=uid, currency="SGD")
    assert len(paired) == 2 and {m.status for m in paired} == {ReconciliationStatus.AUTO_ACCEPTED} and await get_processing_balance(db, uid, currency="SGD") == Decimal("0.00")
    assert list((await db.execute(select(StatementSummary.status).where(StatementSummary.uploaded_document_id.in_([cash_doc.id, chk_doc.id])))).scalars().all()) == [BankStatementStatus.PARSED, BankStatementStatus.PARSED]

    await _seed_txn(db, uid, cash_doc, description="TRANSFER OUT - UNPAIRED", amount=Decimal("250.00"), direction="OUT")
    assert len(await execute_matching(db, user_id=uid, currency="SGD")) == 1 and await get_processing_balance(db, uid, currency="SGD") == Decimal("250.00")

    e1 = JournalEntry(user_id=uid, entry_date=date.today(), memo="Office supplies purchase", status=JournalEntryStatus.POSTED, source_type=JournalEntrySourceType.MANUAL, lines=[JournalLine(account_id=expense.id, direction="DEBIT", amount=Decimal("35.50")), JournalLine(account_id=cash.id, direction="CREDIT", amount=Decimal("35.50"))])
    e2 = JournalEntry(user_id=uid, entry_date=date.today(), memo="Supermarket purchase", status=JournalEntryStatus.POSTED, source_type=JournalEntrySourceType.MANUAL, lines=[JournalLine(account_id=expense.id, direction="DEBIT", amount=Decimal("85.30")), JournalLine(account_id=cash.id, direction="CREDIT", amount=Decimal("85.30"))])
    db.add_all([e1, e2])
    await db.flush()
    await _seed_txn(db, uid, cash_doc, description="OFFICE DEPOT STORE #123", amount=Decimal("35.50"), direction="OUT")
    m_norm = await execute_matching(db, user_id=uid, currency="SGD")
    assert len(m_norm) == 1 and UUID(m_norm[0].journal_entry_ids[0]) == e1.id

    await _seed_txn(db, uid, cash_doc, description="PAYNOW TRANSFER TO SAVINGS", amount=Decimal("400.00"), direction="OUT")
    await _seed_txn(db, uid, cash_doc, description="NTUC FAIRPRICE #512", amount=Decimal("85.30"), direction="OUT")
    m_mix = await execute_matching(db, user_id=uid, currency="SGD")
    xfer = next(m for m in m_mix if m.score_breakdown.get("transfer_out"))
    groc = next(m for m in m_mix if str(e2.id) in (m.journal_entry_ids or []))
    assert len(m_mix) == 2 and xfer.match_score == 100 and UUID(groc.journal_entry_ids[0]) == e2.id
    p_lines = await _lines_for(db, proc.id)
    assert len(p_lines) == 4 and any(line.amount == Decimal("400.00") for line in p_lines)


async def test_reconciliation_reads_layer2_and_is_idempotent(db: AsyncSession, test_user):
    uid = test_user.id
    bank = await AccountFactory.create_async(db, user_id=uid, name="L4 Bank")
    db.add(JournalEntry(user_id=uid, entry_date=date(2024, 1, 15), memo="Salary Deposit", status=JournalEntryStatus.POSTED, source_type="manual", lines=[JournalLine(account_id=bank.id, direction="DEBIT", amount=Decimal("500.00"), currency="SGD"), JournalLine(account_id=bank.id, direction="CREDIT", amount=Decimal("500.00"), currency="SGD")]))
    await db.commit()
    payload = {"account_last4": "1234", "currency": "SGD", "period_start": "2024-01-01", "period_end": "2024-01-31", "opening_balance": "1000.00", "closing_balance": "1500.00", "transactions": [{"date": "2024-01-15", "description": "Salary Deposit", "amount": "500.00", "direction": "IN", "reference": "SAL001"}]}
    service = ExtractionService()
    with patch.object(service, "extract_financial_data", return_value=payload):
        _, statement, _ = await parse_and_load_statement_projection(service, db=db, source=DocumentSource.resolve(path=Path("test_l4.pdf"), content=b"PDF-CONTENT-L4"), institution="DBS", user_id=uid, account_id=bank.id)
    statement.status = BankStatementStatus.APPROVED
    await db.commit()
    matches = await execute_matching(db, user_id=uid, currency="SGD")
    assert len(matches) == 1 and matches[0].status in (ReconciliationStatus.AUTO_ACCEPTED, ReconciliationStatus.PENDING_REVIEW)
    txn = await db.get(AtomicTransaction, matches[0].atomic_txn_id)
    assert (txn.amount, txn.description) == (Decimal("500.00"), "Salary Deposit") and await execute_matching(db, user_id=uid, currency="SGD") == []
