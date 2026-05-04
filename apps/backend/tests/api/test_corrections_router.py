from httpx import AsyncClient

from tests.factories import BankStatementFactory, BankStatementTransactionFactory


async def test_post_create_correction_and_stats(client: AsyncClient, db, test_user):
    """AC4.7.1: POST /corrections persists a correction and /corrections/stats reflects it."""
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        description="Test purchase",
        suggested_category="Misc",
    )
    await db.commit()

    response = await client.post(
        "/corrections",
        json={
            "transaction_id": str(txn.id),
            "corrected_category": "Office Supplies",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["transaction_id"] == str(txn.id)
    assert body["corrected_category"] == "Office Supplies"

    stats = await client.get("/corrections/stats")
    assert stats.status_code == 200
    sbody = stats.json()
    assert sbody["total_corrections"] >= 1
    assert isinstance(sbody["top_corrections"], list)
