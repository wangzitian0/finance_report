"""Guided opening-balance flow (#949, EPIC-002 AC2.15).

A user with pre-existing assets/liabilities on day one can establish year-start
balances via one guided request; the system posts a balanced journal entry that
offsets the net into an Opening Balance Equity account, so a cross-year balance
sheet is complete and the accounting equation holds.
"""

from decimal import Decimal
from uuid import uuid4


async def _account(client, name: str, account_type: str) -> str:
    resp = await client.post("/accounts", json={"name": name, "type": account_type, "currency": "SGD"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_AC2_15_1_opening_balances_post_balanced_and_reflect_in_balance_sheet(client):
    """AC2.15.1: a guided opening-balance request posts a balanced entry and the
    as-of balance sheet reflects the starting position with the equation intact."""
    bank = await _account(client, "Bank", "ASSET")
    mortgage = await _account(client, "Mortgage", "LIABILITY")

    resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {bank: "10000.00", mortgage: "5000.00"}},
    )
    assert resp.status_code == 201, resp.text
    entry = resp.json()

    # The posted entry is balanced (debits == credits), Decimal-safe.
    debit = sum(Decimal(line["amount"]) for line in entry["lines"] if line["direction"] == "DEBIT")
    credit = sum(Decimal(line["amount"]) for line in entry["lines"] if line["direction"] == "CREDIT")
    assert debit == credit == Decimal("10000.00")

    bs = (await client.get("/reports/balance-sheet", params={"as_of_date": "2026-12-31", "currency": "SGD"})).json()
    assert bs["is_balanced"] is True
    assert Decimal(bs["equation_delta"]) == Decimal("0.00")
    assert Decimal(bs["total_assets"]) == Decimal("10000.00")
    # Net worth (assets - liabilities) is captured as Opening Balance Equity.
    assert Decimal(bs["total_equity"]) == Decimal("5000.00")


async def test_AC2_15_2_single_asset_opening_balance_offsets_into_equity(client):
    """AC2.15.2: a single asset opening balance is offset entirely into Opening
    Balance Equity, keeping the entry balanced."""
    savings = await _account(client, "Savings", "ASSET")
    resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {savings: "8000.00"}},
    )
    assert resp.status_code == 201, resp.text

    bs = (await client.get("/reports/balance-sheet", params={"as_of_date": "2026-12-31", "currency": "SGD"})).json()
    assert bs["is_balanced"] is True
    assert Decimal(bs["total_assets"]) == Decimal("8000.00")
    assert Decimal(bs["total_equity"]) == Decimal("8000.00")


async def test_AC2_15_3_unknown_account_is_rejected(client):
    """AC2.15.3: an opening balance for a non-owned/unknown account is rejected."""
    resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {str(uuid4()): "100.00"}},
    )
    assert resp.status_code == 400


async def test_AC2_15_4_opening_balance_rejected_when_prior_activity_exists(client):
    """AC2.15.4: an opening balance establishes a starting position, not a delta,
    so it is rejected when an affected account already has posted activity before
    the opening date."""
    bank = await _account(client, "Bank", "ASSET")
    first = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {bank: "1000.00"}},
    )
    assert first.status_code == 201, first.text
    # A later opening on the same account now has prior activity before it.
    second = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-06-01", "balances": {bank: "2000.00"}},
    )
    assert second.status_code == 400


async def test_AC2_15_5_non_base_currency_is_rejected(client):
    """AC2.15.5: opening balances are accepted only in the base currency (MVP),
    with a clear error rather than a confusing FX-rate failure."""
    bank = await _account(client, "Bank", "ASSET")
    resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {bank: "1000.00"}, "currency": "USD"},
    )
    assert resp.status_code == 400
