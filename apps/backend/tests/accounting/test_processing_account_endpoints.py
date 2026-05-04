from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType
from src.services.processing_account import (
    create_transfer_in_entry,
    create_transfer_out_entry,
)


async def _seed_account(db: AsyncSession, user_id, name: str, code: str) -> Account:
    account = Account(
        user_id=user_id,
        name=name,
        code=code,
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    return account


@pytest.mark.asyncio
async def test_processing_summary_requires_auth(public_client: AsyncClient) -> None:
    resp = await public_client.get("/accounts/processing/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_processing_pending_requires_auth(public_client: AsyncClient) -> None:
    resp = await public_client.get("/accounts/processing/pending")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_processing_summary_empty(client: AsyncClient) -> None:
    resp = await client.get("/accounts/processing/summary")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pending_count"] == 0
    assert Decimal(data["pending_total"]) == Decimal("0")
    assert data["currency"] == "SGD"
    assert data["oldest_pending_date"] is None


@pytest.mark.asyncio
async def test_processing_pending_empty(client: AsyncClient) -> None:
    resp = await client.get("/accounts/processing/pending")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_processing_summary_aggregates_unpaired(client: AsyncClient, db: AsyncSession, test_user) -> None:
    user_id = test_user.id
    cash = await _seed_account(db, user_id, "Cash", "1001")
    savings = await _seed_account(db, user_id, "Savings", "1002")

    today = date.today()
    older = today - timedelta(days=10)
    newer = today - timedelta(days=2)

    await create_transfer_out_entry(
        db,
        user_id=user_id,
        source_account_id=cash.id,
        amount=Decimal("100.00"),
        txn_date=older,
        description="Older OUT",
    )
    await create_transfer_in_entry(
        db,
        user_id=user_id,
        dest_account_id=savings.id,
        amount=Decimal("40.00"),
        txn_date=newer,
        description="Newer IN",
    )
    await db.commit()

    resp = await client.get("/accounts/processing/summary")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pending_count"] == 2
    assert Decimal(data["pending_total"]) == Decimal("140.00")
    assert data["currency"] == "SGD"
    assert data["oldest_pending_date"] == older.isoformat()


@pytest.mark.asyncio
async def test_processing_pending_lists_pairs_with_days_outstanding(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    user_id = test_user.id
    cash = await _seed_account(db, user_id, "Cash", "1001")
    savings = await _seed_account(db, user_id, "Savings", "1002")

    today = date.today()
    out_date = today - timedelta(days=10)
    in_date = today - timedelta(days=3)

    await create_transfer_out_entry(
        db,
        user_id=user_id,
        source_account_id=cash.id,
        amount=Decimal("250.00"),
        txn_date=out_date,
        description="Wire out",
    )
    await create_transfer_in_entry(
        db,
        user_id=user_id,
        dest_account_id=savings.id,
        amount=Decimal("75.00"),
        txn_date=in_date,
        description="Wire in",
    )
    await db.commit()

    resp = await client.get("/accounts/processing/pending")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 2

    by_amount = {Decimal(item["amount"]): item for item in data["items"]}
    out_item = by_amount[Decimal("250.00")]
    in_item = by_amount[Decimal("75.00")]

    assert out_item["from_account"] == "Cash"
    assert "unmatched" in out_item["to_account"].lower()
    assert out_item["currency"] == "SGD"
    assert out_item["initiated_date"] == out_date.isoformat()
    assert out_item["days_outstanding"] == 10

    assert "unmatched" in in_item["from_account"].lower()
    assert in_item["to_account"] == "Savings"
    assert in_item["initiated_date"] == in_date.isoformat()
    assert in_item["days_outstanding"] == 3


@pytest.mark.asyncio
async def test_processing_pending_flags_over_seven_days(client: AsyncClient, db: AsyncSession, test_user) -> None:
    user_id = test_user.id
    cash = await _seed_account(db, user_id, "Cash", "1001")
    today = date.today()

    await create_transfer_out_entry(
        db,
        user_id=user_id,
        source_account_id=cash.id,
        amount=Decimal("500.00"),
        txn_date=today - timedelta(days=14),
        description="Stuck transfer",
    )
    await db.commit()

    resp = await client.get("/accounts/processing/pending")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["days_outstanding"] == 14
    assert items[0]["days_outstanding"] > 7
