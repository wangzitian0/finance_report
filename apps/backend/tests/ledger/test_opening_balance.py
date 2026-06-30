"""Guided opening-balance flow (#949, EPIC-002 AC2.15).

A user with pre-existing assets/liabilities on day one can establish year-start
balances via one guided request; the system posts a balanced journal entry that
offsets the net into an Opening Balance Equity account, so a cross-year balance
sheet is complete and the accounting equation holds.
"""

from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient


async def _account(client: AsyncClient, name: str, account_type: str) -> str:
    resp = await client.post("/accounts", json={"name": name, "type": account_type, "currency": "SGD"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_AC2_15_1_opening_balances_post_balanced_and_reflect_in_balance_sheet(
    client: AsyncClient, ac_evidence
) -> None:
    """AC-ledger.15.1: a guided opening-balance request posts a balanced entry and the
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

    # Behavioral evidence: 10000 asset offset by 5000 liability nets 5000 into equity,
    # the entry balances at 10000.00, and the equation delta is exactly 0.00.
    ac_evidence(
        ac_id="AC-ledger.15.1",
        score=1.0,
        metric="opening_balance_golden_totals_match",
        comment="balanced 10000.00; total_assets 10000.00, total_equity 5000.00, equation_delta 0.00",
        provenance="deterministic",
    )


async def test_AC2_15_2_single_asset_opening_balance_offsets_into_equity(client: AsyncClient, ac_evidence) -> None:
    """AC-ledger.15.2: a single asset opening balance is offset entirely into Opening
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

    # Behavioral evidence: a single 8000 asset is offset entirely into equity, so
    # total_assets == total_equity == 8000.00 with the equation kept intact.
    ac_evidence(
        ac_id="AC-ledger.15.2",
        score=1.0,
        metric="single_asset_opening_offsets_into_equity",
        comment="total_assets 8000.00 == total_equity 8000.00 (single asset offset to equity)",
        provenance="deterministic",
    )


async def test_AC2_15_3_unknown_account_is_rejected(client: AsyncClient) -> None:
    """AC-ledger.15.3: an opening balance for a non-owned/unknown account is rejected."""
    resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {str(uuid4()): "100.00"}},
    )
    assert resp.status_code == 400


async def test_AC2_15_4_opening_balance_rejected_when_prior_activity_exists(client: AsyncClient) -> None:
    """AC-ledger.15.4: an opening balance establishes a starting position, not a delta,
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


async def test_AC2_15_5_non_base_currency_is_rejected(client: AsyncClient) -> None:
    """AC-ledger.15.5: opening balances are accepted only in the base currency (MVP),
    with a clear error rather than a confusing FX-rate failure."""
    bank = await _account(client, "Bank", "ASSET")
    resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {bank: "1000.00"}, "currency": "USD"},
    )
    assert resp.status_code == 400


async def test_AC2_15_6_account_currency_mismatch_is_rejected(client: AsyncClient) -> None:
    """AC-ledger.15.6: an opening balance into an account whose currency differs from the
    request (base) currency is rejected, so journal lines cannot be mis-stamped."""
    resp_acc = await client.post("/accounts", json={"name": "USD Bank", "type": "ASSET", "currency": "USD"})
    assert resp_acc.status_code == 201, resp_acc.text
    usd_bank = resp_acc.json()["id"]
    # Request currency defaults to base (SGD), which mismatches the USD account.
    resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {usd_bank: "1000.00"}},
    )
    assert resp.status_code == 400


async def test_AC2_15_7_system_account_target_is_rejected(client: AsyncClient, db, test_user) -> None:
    """AC-ledger.15.7: opening balances may only target user-managed accounts; a system
    account (e.g. Processing) cannot be set via this endpoint."""
    from src.models.account import Account, AccountType

    system_account = Account(
        user_id=test_user.id,
        name="Processing",
        code="1199",
        type=AccountType.ASSET,
        currency="SGD",
        is_system=True,
    )
    db.add(system_account)
    await db.commit()

    resp = await client.post(
        "/accounts/opening-balances",
        json={"entry_date": "2026-01-01", "balances": {str(system_account.id): "100.00"}},
    )
    assert resp.status_code == 400
