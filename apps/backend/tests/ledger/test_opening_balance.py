from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

import src.composition
from src.ledger import AccountType, JournalEntry, ValidationError, account_service
from src.ledger.extension import accounting
from src.ledger.extension.anchored_posting import submit_system_journal_entry
from tests.ledger._ledger_helpers import make_account


async def _api_account(client: AsyncClient, name: str, account_type: str, currency: str = "SGD") -> str:
    resp = await client.post("/accounts", json={"name": name, "type": account_type, "currency": currency})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_opening_balances_and_single_asset_equity_offset(client: AsyncClient) -> None:
    bank = await _api_account(client, "Bank", "ASSET")
    mortgage = await _api_account(client, "Mortgage", "LIABILITY")
    resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {bank: "10000.00", mortgage: "5000.00"}},
    )
    assert resp.status_code == 201
    lines = resp.json()["lines"]
    assert (
        sum(Decimal(ln["amount"]) for ln in lines if ln["direction"] == "DEBIT")
        == sum(Decimal(ln["amount"]) for ln in lines if ln["direction"] == "CREDIT")
        == Decimal("10000.00")
    )
    bs = (await client.get("/reports/balance-sheet", params={"as_of_date": "2026-12-31", "currency": "SGD"})).json()
    assert bs["is_balanced"] is True and (
        Decimal(bs["equation_delta"]),
        Decimal(bs["total_assets"]),
        Decimal(bs["total_equity"]),
    ) == (
        Decimal("0.00"),
        Decimal("10000.00"),
        Decimal("5000.00"),
    )

    savings = await _api_account(client, "Savings", "ASSET")
    assert (
        await client.post(
            "/accounts/opening-balances", json={"entry_date": "2026-01-01", "balances": {savings: "8000.00"}}
        )
    ).status_code == 201
    bs2 = (await client.get("/reports/balance-sheet", params={"as_of_date": "2026-12-31", "currency": "SGD"})).json()
    assert bs2["is_balanced"] is True and Decimal(bs2["total_assets"]) == Decimal("18000.00")


@pytest.mark.parametrize(
    "case", ["unknown", "prior_activity", "non_base", "acct_mismatch", "system", "equity_mismatch"]
)
async def test_opening_balance_rejections(client: AsyncClient, db, test_user, case: str) -> None:
    if case == "unknown":
        payload = {"entry_date": "2026-01-01", "balances": {str(uuid4()): "100.00"}}
    elif case == "prior_activity":
        bank = await _api_account(client, "Bank", "ASSET")
        assert (
            await client.post(
                "/accounts/opening-balances", json={"entry_date": "2026-01-01", "balances": {bank: "1000.00"}}
            )
        ).status_code == 201
        payload = {"entry_date": "2026-06-01", "balances": {bank: "2000.00"}}
    elif case == "non_base":
        payload = {
            "entry_date": "2026-01-01",
            "balances": {await _api_account(client, "Bank", "ASSET"): "1000.00"},
            "currency": "USD",
        }
    elif case == "acct_mismatch":
        payload = {
            "entry_date": "2026-01-01",
            "balances": {await _api_account(client, "USD Bank", "ASSET", "USD"): "1000.00"},
        }
    elif case == "system":
        sys_acc = await make_account(
            db, test_user.id, "Processing", AccountType.ASSET, code="1199", is_system=True, commit=True
        )
        payload = {"entry_date": "2026-01-01", "balances": {str(sys_acc.id): "100.00"}}
    else:
        await make_account(
            db, test_user.id, "Opening Balance Equity", AccountType.EQUITY, code="3199", is_system=True, commit=True
        )
        await client.put("/users/me/settings/base-currency", json={"base_currency": "USD"})
        payload = {
            "entry_date": "2026-01-01",
            "balances": {await _api_account(client, "USD Bank", "ASSET", "USD"): "1000.00"},
        }

    resp = await client.post("/accounts/opening-balances", json=payload)
    assert resp.status_code == 400
    if case == "equity_mismatch":
        assert "Opening Balance Equity account currency is SGD" in resp.text


async def test_guided_fx_and_tenant_scoping(client: AsyncClient, db, test_user, monkeypatch) -> None:
    acc = await make_account(db, test_user.id, "Opening USD", AccountType.ASSET, "USD")
    assert await account_service.opening_balance_currencies(db, test_user.id, [acc.id], "USD") == {"USD"}
    with pytest.raises(ValidationError, match="currency does not match"):
        await account_service.opening_balance_currencies(db, test_user.id, [acc.id], "SGD")
    with pytest.raises(ValidationError, match="Unknown or non-owned"):
        await account_service.opening_balance_currencies(db, uuid4(), [acc.id], "USD")
    await db.commit()

    provider = AsyncMock(return_value=Decimal("1.350000"))
    monkeypatch.setattr(src.composition, "get_exchange_rate", provider)
    foreign = await _api_account(client, "Foreign opening", "ASSET", "USD")
    assert (
        await client.post(
            "/accounts/opening-balances",
            json={"entry_date": "2026-01-01", "balances": {foreign: "100.00"}, "currency": "SGD"},
        )
    ).status_code == 400
    provider.assert_not_awaited()
    fx_resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {foreign: "100.00"}, "currency": "USD"},
    )
    assert fx_resp.status_code == 201
    lines = fx_resp.json()["lines"]
    asset_ln = next(ln for ln in lines if ln["account_id"] == foreign)
    equity_ln = next(ln for ln in lines if ln["account_id"] != foreign)
    assert (asset_ln["currency"], Decimal(asset_ln["amount"]), Decimal(asset_ln["fx_rate"])) == (
        "USD",
        Decimal("100.00"),
        Decimal("1.350000"),
    )
    assert (equity_ln["currency"], Decimal(equity_ln["amount"])) == ("SGD", Decimal("135.00"))
    assert provider.await_args.args[1:3] == ("USD", "SGD") and str(provider.await_args.args[3]) == "2026-01-01"


async def test_effective_usd_base_and_corrupted_balance_guard(client: AsyncClient, db, test_user, monkeypatch) -> None:
    assert (await client.put("/users/me/settings/base-currency", json={"base_currency": "USD"})).status_code == 200
    usd_bank = await _api_account(client, "USD Bank", "ASSET", "USD")
    usd_resp = await client.post(
        "/accounts/opening-balances", json={"entry_date": "2026-01-01", "balances": {usd_bank: "1000.00"}}
    )
    assert usd_resp.status_code == 201 and {ln["currency"] for ln in usd_resp.json()["lines"]} == {"USD"}

    account = await make_account(db, test_user.id, "Balance guard", AccountType.ASSET, "USD")
    called = False

    async def corrupted_command(*args, **kwargs):
        nonlocal called
        called = True
        lines = [dict(line) for line in kwargs["lines_data"]]
        lines[0]["amount"] += Decimal("1.00")
        return await submit_system_journal_entry(*args, **{**kwargs, "lines_data": lines})

    monkeypatch.setattr(accounting, "submit_system_journal_entry", corrupted_command)
    with pytest.raises(ValidationError, match="balanced"):
        async with db.begin_nested():
            await accounting.initialize_opening_positions(
                db,
                test_user.id,
                entry_date=date(2026, 1, 1),
                balances={account.id: Decimal("100")},
                base_currency="USD",
            )
    assert (
        called
        and await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id))
        == 1
    )
