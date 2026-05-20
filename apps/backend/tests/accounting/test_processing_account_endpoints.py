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
    assert data["pending_total"] == "0.00"
    assert Decimal(data["pending_total"]) == Decimal("0")
    assert data["current_balance"] == "0.00"
    assert Decimal(data["current_balance"]) == Decimal("0")
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
    assert Decimal(data["pending_total"]) == Decimal("60.00")
    assert Decimal(data["current_balance"]) == Decimal("60.00")
    assert data["currency"] == "SGD"
    assert data["oldest_pending_date"] == older.isoformat()


@pytest.mark.asyncio
async def test_pending_total_uses_net_balance_not_sum_of_legs(client: AsyncClient, db: AsyncSession, test_user) -> None:
    user_id = test_user.id
    cash = await _seed_account(db, user_id, "Cash", "1001")
    savings = await _seed_account(db, user_id, "Savings", "1002")

    today = date.today()
    out_date = today - timedelta(days=30)
    in_date = today - timedelta(days=2)

    await create_transfer_out_entry(
        db,
        user_id=user_id,
        source_account_id=cash.id,
        amount=Decimal("100.00"),
        txn_date=out_date,
        description="Vendor payout alpha",
    )
    await create_transfer_in_entry(
        db,
        user_id=user_id,
        dest_account_id=savings.id,
        amount=Decimal("80.00"),
        txn_date=in_date,
        description="Refund receipt beta",
    )
    await db.commit()

    resp = await client.get("/accounts/processing/summary")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pending_count"] == 2
    assert Decimal(data["pending_total"]) == Decimal("20.00")
    assert Decimal(data["current_balance"]) == Decimal("20.00")


@pytest.mark.asyncio
async def test_pending_excludes_fully_paired_entries(client: AsyncClient, db: AsyncSession, test_user) -> None:
    user_id = test_user.id
    cash = await _seed_account(db, user_id, "Cash", "1001")
    savings = await _seed_account(db, user_id, "Savings", "1002")

    today = date.today()
    await create_transfer_out_entry(
        db,
        user_id=user_id,
        source_account_id=cash.id,
        amount=Decimal("100.00"),
        txn_date=today,
        description="Salary Transfer OUT: IN:",
    )
    await create_transfer_in_entry(
        db,
        user_id=user_id,
        dest_account_id=savings.id,
        amount=Decimal("100.00"),
        txn_date=today,
        description="Salary Transfer OUT: IN:",
    )
    await create_transfer_out_entry(
        db,
        user_id=user_id,
        source_account_id=cash.id,
        amount=Decimal("50.00"),
        txn_date=today - timedelta(days=30),
        description="Unmatched brokerage sweep",
    )
    await db.commit()

    summary_resp = await client.get("/accounts/processing/summary")
    assert summary_resp.status_code == 200, summary_resp.text
    summary = summary_resp.json()
    assert summary["pending_count"] == 1
    assert Decimal(summary["pending_total"]) == Decimal("50.00")

    pending_resp = await client.get("/accounts/processing/pending")
    assert pending_resp.status_code == 200, pending_resp.text
    data = pending_resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert Decimal(data["items"][0]["amount"]) == Decimal("50.00")


@pytest.mark.asyncio
async def test_pending_list_excludes_paired_legs(client: AsyncClient, db: AsyncSession, test_user) -> None:
    user_id = test_user.id
    cash = await _seed_account(db, user_id, "Cash", "1001")
    savings = await _seed_account(db, user_id, "Savings", "1002")

    today = date.today()
    await create_transfer_out_entry(
        db,
        user_id=user_id,
        source_account_id=cash.id,
        amount=Decimal("100.00"),
        txn_date=today,
        description="Salary Transfer OUT: IN:",
    )
    await create_transfer_in_entry(
        db,
        user_id=user_id,
        dest_account_id=savings.id,
        amount=Decimal("100.00"),
        txn_date=today,
        description="Salary Transfer OUT: IN:",
    )
    await create_transfer_out_entry(
        db,
        user_id=user_id,
        source_account_id=cash.id,
        amount=Decimal("50.00"),
        txn_date=today - timedelta(days=30),
        description="Unmatched brokerage sweep",
    )
    await db.commit()

    resp = await client.get("/accounts/processing/pending")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["items"]) == 1
    assert Decimal(data["items"][0]["amount"]) == Decimal("50.00")


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
