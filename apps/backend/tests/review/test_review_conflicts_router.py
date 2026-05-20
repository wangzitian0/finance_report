"""Review conflict contract tests."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import BankStatement, BankStatementTransaction, ConfidenceLevel


@pytest.mark.asyncio
async def test_review_conflicts_returns_duplicate_and_transfer_candidates(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC16.13.13: GET /review/conflicts/{statement_id} returns duplicates and transfer_pairs."""
    statement = BankStatement(
        user_id=test_user.id,
        file_path="/tmp/test.pdf",
        file_hash="conflict-hash",
        original_filename="test.pdf",
        institution="DBS",
        currency="SGD",
    )
    db.add(statement)
    await db.flush()
    db.add_all(
        [
            BankStatementTransaction(
                statement_id=statement.id,
                txn_date=date(2026, 5, 1),
                description="Coffee",
                amount=Decimal("4.20"),
                direction="OUT",
                confidence=ConfidenceLevel.HIGH,
            ),
            BankStatementTransaction(
                statement_id=statement.id,
                txn_date=date(2026, 5, 1),
                description="Coffee",
                amount=Decimal("4.20"),
                direction="OUT",
                confidence=ConfidenceLevel.HIGH,
            ),
            BankStatementTransaction(
                statement_id=statement.id,
                txn_date=date(2026, 5, 2),
                description="Transfer out",
                amount=Decimal("100.00"),
                direction="OUT",
                confidence=ConfidenceLevel.HIGH,
            ),
            BankStatementTransaction(
                statement_id=statement.id,
                txn_date=date(2026, 5, 2),
                description="Transfer in",
                amount=Decimal("100.00"),
                direction="IN",
                confidence=ConfidenceLevel.HIGH,
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


@pytest.mark.asyncio
async def test_review_conflicts_returns_404_for_missing_statement(client: AsyncClient):
    """AC16.13.14: Conflicts endpoint returns 404 when statement_id does not exist."""
    response = await client.get("/review/conflicts/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
