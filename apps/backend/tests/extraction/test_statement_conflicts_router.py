from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus, DocumentType, TransactionDirection, UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from tests.extraction._statement_run_helpers import make_account


async def test_review_conflicts_returns_candidates_and_404(client: AsyncClient, db: AsyncSession, test_user):
    account = await make_account(db, test_user.id, name=f"Conflict Account {uuid4()}")
    doc = UploadedDocument(id=uuid4(), user_id=test_user.id, file_path="/tmp/test.pdf", file_hash="conflict-hash", original_filename="test.pdf", document_type=DocumentType.BANK_STATEMENT)
    db.add(doc)
    await db.flush()
    stmt = StatementSummary(id=uuid4(), user_id=test_user.id, uploaded_document_id=doc.id, file_hash="conflict-hash", account_id=account.id, institution="DBS", currency="SGD", period_start=date(2026, 5, 1), period_end=date(2026, 5, 31), opening_balance=Decimal("0.00"), closing_balance=Decimal("0.00"), status=BankStatementStatus.APPROVED)
    db.add(stmt)
    await db.flush()
    db.add_all([
        AtomicTransaction(id=uuid4(), user_id=test_user.id, txn_date=d, description=desc, amount=amt, direction=dir_, currency="SGD", dedup_hash=uuid4().hex + uuid4().hex, source_documents=[{"doc_id": str(doc.id), "doc_type": DocumentType.BANK_STATEMENT.value}])
        for d, desc, amt, dir_ in [
            (date(2026, 5, 1), "Coffee", Decimal("4.20"), TransactionDirection.OUT),
            (date(2026, 5, 1), "Coffee", Decimal("4.20"), TransactionDirection.OUT),
            (date(2026, 5, 2), "Transfer out", Decimal("100.00"), TransactionDirection.OUT),
            (date(2026, 5, 2), "Transfer in", Decimal("100.00"), TransactionDirection.IN),
        ]
    ])
    await db.commit()
    resp = await client.get(f"/statements/{stmt.id}/conflicts")
    missing = await client.get("/statements/00000000-0000-0000-0000-000000000000/conflicts")
    data = resp.json()
    assert (resp.status_code, len(data["duplicates"]), len(data["transfer_pairs"]), data["duplicates"][0]["description"], missing.status_code) == (200, 2, 2, "Coffee", 404)
