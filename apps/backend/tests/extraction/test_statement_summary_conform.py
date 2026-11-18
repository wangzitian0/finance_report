from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from src.extraction import BankStatementStatus, DocumentType, Stage1Status, TransactionDirection, UploadedDocument
from src.extraction.extension.statement_summary import resolve_custody_account_id
from src.extraction.orm.layer2 import AtomicTransaction
from tests.extraction._statement_run_helpers import make_account
from tests.factories import StatementSummaryFactory


async def _confirmed_doc(db, user_id, *, file_hash: str, account_id):
    doc = UploadedDocument(user_id=user_id, file_path=f"statements/{file_hash}.pdf", file_hash=file_hash, original_filename="dbs.pdf", document_type=DocumentType.BANK_STATEMENT)
    db.add(doc)
    await db.flush()
    await StatementSummaryFactory.create_async(
        db, user_id, account_id=account_id, uploaded_document_id=doc.id, file_hash=file_hash, institution="DBS",
        account_last4="1234", currency="SGD", period_start=date(2024, 1, 1), period_end=date(2024, 1, 31),
        opening_balance=Decimal("1000.00"), closing_balance=Decimal("1500.00"),
        status=BankStatementStatus.APPROVED if account_id is not None else BankStatementStatus.PARSED,
        stage1_status=Stage1Status.APPROVED if account_id is not None else Stage1Status.PENDING_REVIEW,
        balance_validated=account_id is not None,
    )
    return doc


def _atomic(db, user_id, *, source_documents, dedup_hash: str) -> AtomicTransaction:
    txn = AtomicTransaction(user_id=user_id, txn_date=date(2024, 1, 15), amount=Decimal("500.00"), direction=TransactionDirection.OUT, description="TRANSFER", currency="SGD", dedup_hash=dedup_hash, source_documents=source_documents)
    db.add(txn)
    return txn


async def test_AC1_currency_balances_jsonb_round_trips(db, test_user):
    summary = await StatementSummaryFactory.create_async(
        db, test_user.id, file_hash="hash-ccy-balances", institution="Wise", currency="SGD", period_start=date(2024, 1, 1), period_end=date(2024, 1, 31),
        opening_balance=Decimal("1000.00"), closing_balance=Decimal("1200.00"),
        currency_balances=[{"currency": "SGD", "opening": "1000.00", "closing": "1200.00"}, {"currency": "USD", "opening": "500.00", "closing": "300.00"}],
    )
    await db.commit()
    await db.refresh(summary)
    usd = next(b for b in summary.currency_balances if b["currency"] == "USD")
    assert (len(summary.currency_balances), usd["opening"], usd["closing"], summary.opening_balance, summary.closing_balance) == (2, "500.00", "300.00", Decimal("1000.00"), Decimal("1200.00"))


async def test_resolve_custody_account_cases(db, test_user):
    acct1 = await make_account(db, test_user.id, name="DBS Checking")
    acct2 = await make_account(db, test_user.id, name="OCBC")
    doc1 = await _confirmed_doc(db, test_user.id, file_hash="hash-sum-3", account_id=acct1.id)
    doc_wrap = await _confirmed_doc(db, test_user.id, file_hash="hash-wrap", account_id=acct1.id)
    doc_none = await _confirmed_doc(db, test_user.id, file_hash="hash-noacct", account_id=None)
    doc_ord2 = await _confirmed_doc(db, test_user.id, file_hash="hash-ord-2", account_id=acct2.id)

    t_direct = _atomic(db, test_user.id, source_documents=[{"doc_id": str(doc1.id), "doc_type": "bank_statement"}], dedup_hash="dedup-sum-3")
    t_wrap = _atomic(db, test_user.id, source_documents={"documents": [{"doc_id": str(doc_wrap.id), "doc_type": "bank_statement"}]}, dedup_hash="dedup-wrap")
    t_junk = _atomic(db, test_user.id, source_documents=["junk", {"doc_type": "bank_statement"}, {"doc_id": "not-a-uuid", "doc_type": "bank_statement"}, {"doc_id": str(uuid4()), "doc_type": "brokerage_statement"}], dedup_hash="dedup-junk")
    t_noacct = _atomic(db, test_user.id, source_documents=[{"doc_id": str(doc_none.id), "doc_type": "bank_statement"}], dedup_hash="dedup-noacct")
    t_weird = _atomic(db, test_user.id, source_documents="weird", dedup_hash="dedup-weird")
    t_order = _atomic(db, test_user.id, source_documents=[{"doc_id": str(doc_none.id), "doc_type": "bank_statement"}, {"doc_id": str(doc_ord2.id), "doc_type": "bank_statement"}], dedup_hash="dedup-order")
    t_empty = _atomic(db, test_user.id, source_documents=[], dedup_hash="dedup-no-source")
    t_unknown = _atomic(db, test_user.id, source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}], dedup_hash="dedup-none")
    await db.commit()

    assert [await resolve_custody_account_id(db, t) for t in (t_direct, t_wrap, t_junk, t_noacct, t_weird, t_order, t_empty, t_unknown)] == [
        acct1.id, acct1.id, None, None, None, acct2.id, None, None
    ]
