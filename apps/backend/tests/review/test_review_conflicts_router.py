"""Review conflict contract tests."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import DocumentType, UploadedDocument
from src.models.account import Account, AccountType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_enums import BankStatementStatus
from src.models.statement_summary import StatementSummary


async def test_review_conflicts_returns_duplicate_and_transfer_candidates(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC16.13.13: GET /review/conflicts/{statement_id} returns duplicates and transfer_pairs."""
    account = Account(
        user_id=test_user.id,
        name=f"Conflict Account {uuid4()}",
        type=AccountType.ASSET,
        currency="SGD",
    )
    doc = UploadedDocument(
        id=uuid4(),
        user_id=test_user.id,
        file_path="/tmp/test.pdf",
        file_hash="conflict-hash",
        original_filename="test.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add_all([account, doc])
    await db.flush()

    statement = StatementSummary(
        id=uuid4(),
        user_id=test_user.id,
        uploaded_document_id=doc.id,
        file_hash="conflict-hash",
        account_id=account.id,
        institution="DBS",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.APPROVED,
    )
    db.add(statement)
    await db.flush()

    def _txn(*, txn_date, description, amount, direction):
        return AtomicTransaction(
            id=uuid4(),
            user_id=test_user.id,
            txn_date=txn_date,
            description=description,
            amount=amount,
            direction=direction,
            currency="SGD",
            dedup_hash=uuid4().hex + uuid4().hex,
            source_documents=[{"doc_id": str(doc.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
        )

    db.add_all(
        [
            _txn(
                txn_date=date(2026, 5, 1),
                description="Coffee",
                amount=Decimal("4.20"),
                direction=TransactionDirection.OUT,
            ),
            _txn(
                txn_date=date(2026, 5, 1),
                description="Coffee",
                amount=Decimal("4.20"),
                direction=TransactionDirection.OUT,
            ),
            _txn(
                txn_date=date(2026, 5, 2),
                description="Transfer out",
                amount=Decimal("100.00"),
                direction=TransactionDirection.OUT,
            ),
            _txn(
                txn_date=date(2026, 5, 2),
                description="Transfer in",
                amount=Decimal("100.00"),
                direction=TransactionDirection.IN,
            ),
        ]
    )
    await db.commit()

    response = await client.get(f"/review/conflicts/{statement.id}")

    assert response.status_code == 200
    data = response.json()
    assert len(data["duplicates"]) == 2
    assert len(data["transfer_pairs"]) == 2
    assert data["duplicates"][0]["description"] == "Coffee"


async def test_review_conflicts_returns_404_for_missing_statement(client: AsyncClient):
    """AC16.13.14: Conflicts endpoint returns 404 when statement_id does not exist."""
    response = await client.get("/review/conflicts/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
