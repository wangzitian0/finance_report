"""EPIC-018 AC18.17.2 (#1546): the backfill/re-extract entry point is live."""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.models.layer3 import TransactionClassification
from src.services.transaction_classification import CategoryProposal, TransactionCategory
from tests.factories import AtomicTransactionFactory


@pytest.fixture
def enabled_flag(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", True)


@pytest.fixture
def stub_proposer(monkeypatch):
    async def proposer(transactions, policy):
        return [CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95) for _ in transactions]

    monkeypatch.setattr("src.services.transaction_classification.propose_categories", proposer)
    return proposer


@pytest.mark.asyncio
async def test_AC18_17_2_backfill_endpoint_classifies_then_is_idempotent(
    client: AsyncClient, db, test_user, enabled_flag, stub_proposer
):
    """AC18.17.2: POST /classifications/backfill classifies the caller's
    not-yet-classified transactions once; a second call is an idempotent no-op."""
    for i in range(2):
        await AtomicTransactionFactory.create_async(
            db, user_id=test_user.id, description=f"Salary {i}", txn_date=date(2026, 5, 10)
        )
    await db.commit()

    first = await client.post("/classifications/backfill")
    assert first.status_code == 200, first.text
    assert first.json()["classified"] == 2

    second = await client.post("/classifications/backfill")
    assert second.status_code == 200
    assert second.json()["classified"] == 0  # idempotent

    rows = (await db.execute(select(TransactionClassification))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_AC18_17_2_backfill_endpoint_is_flag_gated(
    client: AsyncClient, db, test_user, stub_proposer, monkeypatch
):
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", False)
    await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="Salary")
    await db.commit()

    resp = await client.post("/classifications/backfill")
    assert resp.status_code == 200
    assert resp.json()["classified"] == 0
