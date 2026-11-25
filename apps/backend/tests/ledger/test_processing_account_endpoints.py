from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import (
    AccountType,
    ProcessingCurrencyConflictError,
    TransferAccountCurrencyMismatchError,
    create_transfer_in_entry,
    create_transfer_out_entry,
    get_or_create_processing_account,
)
from tests.ledger._ledger_helpers import make_account


@pytest.mark.parametrize("path", ["/reconciliation/transfers/summary", "/reconciliation/transfers/pending"])
async def test_processing_endpoints_require_auth(public_client: AsyncClient, path: str) -> None:
    assert (await public_client.get(path)).status_code == 401


async def test_processing_endpoints_empty(client: AsyncClient) -> None:
    summary = (await client.get("/reconciliation/transfers/summary")).json()
    assert (
        summary["pending_count"],
        Decimal(summary["pending_total"]),
        Decimal(summary["current_balance"]),
        summary["currency"],
        summary["oldest_pending_date"],
    ) == (
        0,
        Decimal("0"),
        Decimal("0"),
        "SGD",
        None,
    )
    assert (await client.get("/reconciliation/transfers/pending")).json() == {"total": 0, "items": []}


async def test_processing_summary_net_balance_and_paired_exclusion(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    uid = test_user.id
    cash = await make_account(db, uid, "Cash", AccountType.ASSET, code="1001")
    savings = await make_account(db, uid, "Savings", AccountType.ASSET, code="1002")
    today = date.today()
    older, newer = today - timedelta(days=10), today - timedelta(days=2)
    await create_transfer_out_entry(
        db,
        user_id=uid,
        source_account_id=cash.id,
        amount=Decimal("100.00"),
        txn_date=older,
        description="Older OUT",
        currency="SGD",
    )
    await create_transfer_in_entry(
        db,
        user_id=uid,
        dest_account_id=savings.id,
        amount=Decimal("40.00"),
        txn_date=newer,
        description="Newer IN",
        currency="SGD",
    )
    await db.commit()

    summary = (await client.get("/reconciliation/transfers/summary")).json()
    assert (
        summary["pending_count"],
        Decimal(summary["pending_total"]),
        Decimal(summary["current_balance"]),
        summary["currency"],
        summary["oldest_pending_date"],
    ) == (
        2,
        Decimal("60.00"),
        Decimal("60.00"),
        "SGD",
        older.isoformat(),
    )


async def test_pending_excludes_fully_paired_and_lists_days_outstanding(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    uid = test_user.id
    cash = await make_account(db, uid, "Cash", AccountType.ASSET, code="1001")
    savings = await make_account(db, uid, "Savings", AccountType.ASSET, code="1002")
    today = date.today()
    out_date, in_date = today - timedelta(days=14), today - timedelta(days=3)
    await create_transfer_out_entry(
        db,
        user_id=uid,
        source_account_id=cash.id,
        amount=Decimal("100.00"),
        txn_date=today,
        description="Salary Transfer OUT: IN:",
        currency="SGD",
    )
    await create_transfer_in_entry(
        db,
        user_id=uid,
        dest_account_id=savings.id,
        amount=Decimal("100.00"),
        txn_date=today,
        description="Salary Transfer OUT: IN:",
        currency="SGD",
    )
    await create_transfer_out_entry(
        db,
        user_id=uid,
        source_account_id=cash.id,
        amount=Decimal("250.00"),
        txn_date=out_date,
        description="Wire out",
        currency="SGD",
    )
    await create_transfer_in_entry(
        db,
        user_id=uid,
        dest_account_id=savings.id,
        amount=Decimal("75.00"),
        txn_date=in_date,
        description="Wire in",
        currency="SGD",
    )
    await db.commit()

    summary = (await client.get("/reconciliation/transfers/summary")).json()
    assert (summary["pending_count"], Decimal(summary["pending_total"])) == (2, Decimal("175.00"))
    data = (await client.get("/reconciliation/transfers/pending")).json()
    assert data["total"] == 2
    by_amt = {Decimal(item["amount"]): item for item in data["items"]}
    out_item, in_item = by_amt[Decimal("250.00")], by_amt[Decimal("75.00")]
    assert (
        out_item["from_account"] == "Cash"
        and "unmatched" in out_item["to_account"].lower()
        and out_item["days_outstanding"] == 14
    )
    assert (
        "unmatched" in in_item["from_account"].lower()
        and in_item["to_account"] == "Savings"
        and in_item["days_outstanding"] == 3
    )


async def test_processing_currency_invariants_and_config_isolation(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    uid = test_user.id
    processing = await get_or_create_processing_account(db, uid, currency="SGD")
    assert processing.currency == "SGD"
    await db.commit()
    assert (await client.put("/users/me/settings/base-currency", json={"base_currency": "USD"})).status_code == 200
    assert (await client.get("/reconciliation/transfers/summary")).json()["currency"] == "SGD"

    usd_cash = await make_account(db, uid, "USD Cash", AccountType.ASSET, "USD", code="1001")
    for transfer_ccy, exc, match in (
        ("USD", ProcessingCurrencyConflictError, "Processing account currency is SGD"),
        ("SGD", TransferAccountCurrencyMismatchError, "Transfer account currency is USD"),
    ):
        with pytest.raises(exc, match=match):
            await create_transfer_out_entry(
                db,
                user_id=uid,
                source_account_id=usd_cash.id,
                amount=Decimal("25.00"),
                txn_date=date.today(),
                description="sweep",
                currency=transfer_ccy,
            )


async def test_usd_transfer_uses_explicit_base(db: AsyncSession, test_user) -> None:
    cash = await make_account(db, test_user.id, "USD Cash", AccountType.ASSET, "USD", code="1001")
    entry = await create_transfer_out_entry(
        db,
        user_id=test_user.id,
        source_account_id=cash.id,
        amount=Decimal("25.00"),
        txn_date=date.today(),
        description="USD sweep",
        currency="USD",
    )
    await db.commit()
    assert entry.status.value == "posted" and {ln.currency for ln in entry.lines} == {"USD"}
