from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicPosition, AtomicTransaction
from src.ledger import Account, AccountType
from src.ledger.orm.journal import Direction, JournalEntry, JournalEntryStatus
from src.portfolio import AssetNotFoundError, DividendIncome, InvestmentTransaction, InvestmentTransactionType
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.pricing.orm.market_data import FxRate, StockPrice
from src.routers import portfolio as portfolio_router
from src.schemas.portfolio import HoldingResponse
from tests.ledger._ledger_helpers import create_valid_posted_entry


def _make_managed_position(
    user_id,
    account_id,
    asset_identifier: str = "AAPL",
    quantity: Decimal = Decimal("100"),
    cost_basis: Decimal = Decimal("10000.00"),
    currency: str = "SGD",
    acquisition_date: date | None = None,
    status: PositionStatus = PositionStatus.ACTIVE,
    cost_basis_method: CostBasisMethod = CostBasisMethod.FIFO,
) -> ManagedPosition:
    return ManagedPosition(
        user_id=user_id,
        account_id=account_id,
        asset_identifier=asset_identifier,
        quantity=quantity,
        cost_basis=cost_basis,
        currency=currency,
        acquisition_date=acquisition_date or date.today() - timedelta(days=60),
        status=status,
        cost_basis_method=cost_basis_method,
    )


def _make_buy(position: ManagedPosition, *, quantity: Decimal, cost: Decimal) -> InvestmentTransaction:
    """Return the BUY row that supports the cost of ``position`` at a past date (#2920)."""
    return InvestmentTransaction(
        user_id=position.user_id,
        position_id=position.id,
        transaction_date=position.acquisition_date,
        transaction_type=InvestmentTransactionType.BUY,
        asset_identifier=position.asset_identifier,
        quantity=quantity,
        unit_price=cost / quantity,
        gross_amount=cost,
        fees=Decimal("0.00"),
        currency=position.currency,
        cost_basis=cost,
        realized_pnl=Decimal("0.00"),
        cost_basis_method=CostBasisMethod.FIFO,
    )


def _make_atomic_position(
    user_id,
    asset_identifier: str = "AAPL",
    broker: str = "Investment Account",
    quantity: Decimal = Decimal("100"),
    market_value: Decimal = Decimal("12000.00"),
    currency: str = "SGD",
    snapshot_date: date | None = None,
    sector: str | None = None,
    geography: str | None = None,
    asset_type: str | None = None,
    dedup_hash: str | None = None,
    source_documents: dict | list | None = None,
) -> AtomicPosition:
    snap_date = snapshot_date or date.today()
    return AtomicPosition(
        user_id=user_id,
        snapshot_date=snap_date,
        asset_identifier=asset_identifier,
        broker=broker,
        quantity=quantity,
        market_value=market_value,
        currency=currency,
        sector=sector,
        geography=geography,
        asset_type=asset_type,
        dedup_hash=dedup_hash or f"{asset_identifier}_{snap_date}_{broker}",
        source_documents={} if source_documents is None else source_documents,
    )


async def _commit(db: AsyncSession, *objs) -> None:
    db.add_all(objs)
    await db.commit()


@pytest.fixture
async def investment_account(db: AsyncSession, test_user):
    account = Account(user_id=test_user.id, name="Investment Account", type=AccountType.ASSET, currency="SGD")
    await _commit(db, account)
    return account


@pytest.fixture
async def portfolio_with_data(db: AsyncSession, test_user, investment_account):
    deposit = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date.today() - timedelta(days=60),
        amount=Decimal("10000.00"),
        currency="SGD",
        direction=TransactionDirection.IN,
        description="Test deposit for portfolio",
        source_documents={},
        dedup_hash="test_deposit",
    )
    position = _make_managed_position(test_user.id, investment_account.id, "AAPL")
    atomic = _make_atomic_position(
        test_user.id,
        "AAPL",
        sector="Technology",
        geography="US",
        asset_type="stock",
        dedup_hash="aapl_test",
        source_documents={"documents": [{"doc_id": "brokerage-doc-aapl", "doc_type": "brokerage_statement", "broker": "Investment Account"}]},
    )
    await _commit(db, deposit, position, atomic)
    return {"position": position, "atomic": atomic, "account": investment_account}


async def test_get_holdings_empty_and_populated(client: AsyncClient, portfolio_with_data):
    resp = await client.get("/portfolio/holdings")
    assert (resp.status_code, len(resp.json()["items"]) > 0) == (200, True)
    past = (date.today() - timedelta(days=30)).isoformat()
    assert (await client.get(f"/portfolio/holdings?as_of_date={past}")).status_code == 200
    assert (await client.get("/portfolio/holdings?include_disposed=true")).status_code == 200


async def test_get_holdings_empty_portfolio(client: AsyncClient):
    resp = await client.get("/portfolio/holdings")
    assert (resp.status_code, resp.json()) == (200, {"items": [], "total": 0, "warnings": []})


async def test_holding_detail_dividends_realized_and_cost_basis_endpoints(client: AsyncClient, db: AsyncSession, test_user, portfolio_with_data):
    pos = portfolio_with_data["position"]
    await _commit(
        db,
        DividendIncome(user_id=test_user.id, position_id=pos.id, payment_date=date(2026, 2, 15), amount=Decimal("42.50"), currency="SGD"),
        InvestmentTransaction(
            user_id=test_user.id,
            position_id=pos.id,
            transaction_date=date(2026, 3, 1),
            transaction_type=InvestmentTransactionType.SELL,
            asset_identifier="AAPL",
            quantity=Decimal("5"),
            unit_price=Decimal("130.00"),
            gross_amount=Decimal("650.00"),
            fees=Decimal("1.00"),
            currency="SGD",
            cost_basis=Decimal("500.00"),
            realized_pnl=Decimal("149.00"),
            cost_basis_method=CostBasisMethod.FIFO,
        ),
    )
    div_resp = await client.get("/portfolio/AAPL/dividends")
    real_resp = await client.get("/portfolio/AAPL/realized")
    patch_resp = await client.patch("/portfolio/AAPL", json={"cost_basis_method": "LIFO"})
    await db.refresh(pos)
    div_item = div_resp.json()[0]
    real_item = real_resp.json()[0]
    assert (
        div_resp.status_code,
        {k: div_item[k] for k in ("ex_date", "pay_date", "amount", "currency", "reinvested", "journal_entry_id")},
        real_resp.status_code,
        (real_item["quantity"], real_item["basis"], real_item["proceeds"], real_item["gain_loss"]),
        patch_resp.status_code,
        patch_resp.json(),
        pos.cost_basis_method,
    ) == (
        200,
        {"ex_date": "2026-02-15", "pay_date": "2026-02-15", "amount": "42.50", "currency": "SGD", "reinvested": False, "journal_entry_id": None},
        200,
        ("5.000000", "500.00", "649.00", "149.00"),
        200,
        {"updated_count": 1, "cost_basis_method": "LIFO"},
        CostBasisMethod.LIFO,
    )


async def test_portfolio_summary_returns_realized_and_dividend_ytd(client: AsyncClient, db: AsyncSession, test_user, portfolio_with_data):
    pos = portfolio_with_data["position"]
    yr = date.today().year
    await _commit(
        db,
        DividendIncome(user_id=test_user.id, position_id=pos.id, payment_date=date(yr, 2, 15), amount=Decimal("42.50"), currency="SGD"),
        InvestmentTransaction(
            user_id=test_user.id,
            position_id=pos.id,
            transaction_date=date(yr, 3, 1),
            transaction_type=InvestmentTransactionType.SELL,
            asset_identifier="AAPL",
            quantity=Decimal("5"),
            unit_price=Decimal("130.00"),
            gross_amount=Decimal("650.00"),
            fees=Decimal("1.00"),
            currency="SGD",
            cost_basis=Decimal("500.00"),
            realized_pnl=Decimal("149.00"),
            cost_basis_method=CostBasisMethod.FIFO,
        ),
    )
    resp = await client.get("/portfolio/summary")
    data = resp.json()
    assert (resp.status_code, data["realized_pnl_ytd"], data["dividend_income_ytd"]) == (200, "149.00", "42.50")


async def test_portfolio_summary_zeroes_and_404_missing_holding(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(portfolio_router.portfolio_service, "get_portfolio_summary", AsyncMock(side_effect=AssetNotFoundError("no holdings")))
    resp = await client.get("/portfolio/summary?as_of_date=2026-05-20")
    data = resp.json()
    missing = await client.patch("/portfolio/MISSING", json={"cost_basis_method": "FIFO"})
    assert (
        resp.status_code,
        data["total_market_value"],
        data["realized_pnl_ytd"],
        data["dividend_income_ytd"],
        data["holdings_count"],
        missing.status_code,
        missing.json()["detail"],
    ) == (200, "0.00", "0.00", "0.00", 0, 404, "Holding not found")


@pytest.mark.parametrize(("with_as_of", "expected_count"), [(False, 1), (True, 0)])
async def test_get_holdings_future_snapshot_visibility(client: AsyncClient, db: AsyncSession, test_user, investment_account, with_as_of, expected_count):
    future_date = date.today() + timedelta(days=12)
    await _commit(
        db,
        _make_managed_position(test_user.id, investment_account.id, "FULLERTON-SGD-MMF", cost_basis=Decimal("1000.00"), acquisition_date=date.today()),
        _make_atomic_position(test_user.id, "FULLERTON-SGD-MMF", broker="Moomoo E2E Portfolio", market_value=Decimal("1234.00"), snapshot_date=future_date, dedup_hash=f"router_future_{with_as_of}"),
    )
    url = f"/portfolio/holdings?as_of_date={date.today().isoformat()}" if with_as_of else "/portfolio/holdings"
    resp = await client.get(url)
    items = resp.json()["items"]
    assert (resp.status_code, len(items)) == (200, expected_count)
    if expected_count:
        assert (items[0]["asset_identifier"], Decimal(items[0]["market_value"])) == ("FULLERTON-SGD-MMF", Decimal("1234.00"))


async def test_get_holdings_explicit_date_uses_historical_snapshot_quantity(client: AsyncClient, db: AsyncSession, test_user, investment_account):
    hist, curr = date(2025, 1, 31), date(2025, 2, 28)
    await _commit(
        db,
        _make_managed_position(test_user.id, investment_account.id, "VWRA", quantity=Decimal("20"), cost_basis=Decimal("3000.00"), acquisition_date=hist),
        _make_atomic_position(test_user.id, "VWRA", quantity=Decimal("10"), market_value=Decimal("1200.00"), snapshot_date=hist, dedup_hash="router_vwra_hist"),
        _make_atomic_position(test_user.id, "VWRA", quantity=Decimal("20"), market_value=Decimal("3000.00"), snapshot_date=curr, dedup_hash="router_vwra_curr"),
    )
    resp = await client.get(f"/portfolio/holdings?as_of_date={hist.isoformat()}")
    items = resp.json()["items"]
    assert (resp.status_code, len(items), items[0]["asset_identifier"], Decimal(items[0]["quantity"]), Decimal(items[0]["market_value"])) == (200, 1, "VWRA", Decimal("10.000000"), Decimal("1200.00"))


async def test_AC_portfolio_holdings_6_unreconciled_snapshot_disclosed_in_warnings(client: AsyncClient, db: AsyncSession, test_user):
    snap_date = date(2025, 1, 31)
    await _commit(db, _make_atomic_position(test_user.id, "ORPHAN-FUND", broker="Test Broker", quantity=Decimal("10"), market_value=Decimal("1000.00"), snapshot_date=snap_date, dedup_hash="orphan_snapshot_warning"))
    resp = await client.get(f"/portfolio/holdings?as_of_date={snap_date.isoformat()}")
    body = resp.json()
    assert (resp.status_code, body["items"], [w["type"] for w in body["warnings"]], body["warnings"][0]["asset_identifier"], body["warnings"][0]["as_of_date"]) == (
        200,
        [],
        ["unreconciled_snapshot_skipped"],
        "ORPHAN-FUND",
        snap_date.isoformat(),
    )


async def test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule(client: AsyncClient, db: AsyncSession, test_user, portfolio_with_data):
    pos = portfolio_with_data["position"]
    source_id = uuid4()
    je = await create_valid_posted_entry(db, test_user.id, entry_date=date.today() - timedelta(days=5), memo="Realized investment sale", source_type=JournalEntrySourceType.AUTO_PARSED)
    await _commit(
        db,
        DividendIncome(user_id=test_user.id, position_id=pos.id, payment_date=date.today() - timedelta(days=10), amount=Decimal("42.50"), currency="SGD"),
        _make_buy(pos, quantity=Decimal("105"), cost=Decimal("10500.00")),
        InvestmentTransaction(
            user_id=test_user.id,
            position_id=pos.id,
            transaction_date=date.today() - timedelta(days=5),
            transaction_type=InvestmentTransactionType.SELL,
            asset_identifier="AAPL",
            quantity=Decimal("5"),
            unit_price=Decimal("130.00"),
            gross_amount=Decimal("650.00"),
            fees=Decimal("1.00"),
            currency="SGD",
            cost_basis=Decimal("500.00"),
            realized_pnl=Decimal("149.00"),
            cost_basis_method=CostBasisMethod.FIFO,
            journal_entry_id=je.id,
            source_id=source_id,
        ),
    )
    period_start, as_of = (date.today() - timedelta(days=90)).isoformat(), date.today().isoformat()
    resp = await client.get(f"/portfolio/performance/report-schedule?period_start={period_start}&period_end={as_of}&as_of_date={as_of}&currency=SGD")
    data = resp.json()
    assert (
        resp.status_code,
        data["period_start"],
        data["period_end"],
        data["as_of_date"],
        data["currency"],
        data["realized_pnl"],
        data["dividend_income"],
        data["unrealized_pnl"],
        (data["holdings"][0]["asset_identifier"], data["holdings"][0]["realized_pnl"], data["holdings"][0]["dividend_income"]),
        bool(data["allocation"]),
        data["data_freshness"]["latest_price_date"],
        bool(data["notes"]),
    ) == (200, period_start, as_of, as_of, "SGD", "149.00", "42.50", "2000.00", ("AAPL", "149.00", "42.50"), True, as_of, True)
    assert all(k in data and (data[k] is None or isinstance(data[k], str)) for k in ("xirr", "time_weighted_return", "money_weighted_return", "dividend_yield"))
    assert set(data["source_links"]) >= {"brokerage_statement:brokerage-doc-aapl", f"investment_transaction_source:{source_id}", f"journal_entry:{je.id}", "report_section:investment_performance"}
    assert any(link.startswith("price_source:atomic_position:AAPL:") for link in data["source_links"])
    assert any("TWR unavailable" in n for n in data["notes"]) if data["time_weighted_return"] is None else Decimal(data["time_weighted_return"]).is_finite()


async def test_AC17_10_1_investment_schedule_publishes_the_exact_market_observation_it_uses(client: AsyncClient, db: AsyncSession, portfolio_with_data):
    as_of = date.today()
    pos, atom = portfolio_with_data["position"], portfolio_with_data["atomic"]
    pos.asset_identifier = atom.asset_identifier = " aapl "
    stock_price = StockPrice(symbol="AAPL", price=Decimal("125.05"), currency="SGD", price_date=as_of, source="recorded-provider")
    await _commit(
        db,
        _make_managed_position(pos.user_id, pos.account_id, "ZERO", quantity=Decimal("0"), cost_basis=Decimal("0.00"), acquisition_date=as_of),
        stock_price,
        StockPrice(symbol="ZERO", price=Decimal("5.00"), currency="SGD", price_date=as_of, source="recorded-provider"),
        _make_atomic_position(pos.user_id, "ZERO", quantity=Decimal("0"), market_value=Decimal("0.00"), snapshot_date=as_of, dedup_hash="zero_schedule_market_selection"),
    )
    resp = await client.get("/portfolio/performance/report-schedule", params={"period_start": (as_of - timedelta(days=90)).isoformat(), "period_end": as_of.isoformat(), "as_of_date": as_of.isoformat(), "currency": "SGD"})
    payload = resp.json()
    assert (resp.status_code, next(h for h in payload["holdings"] if h["asset_identifier"] == " aapl ")["market_value"], payload["market_valuation_selections"]) == (
        200,
        "12505.00",
        [{"asset_identifier": " aapl ", "observation_id": str(stock_price.id), "requested_as_of": as_of.isoformat()}],
    )


async def test_AC17_10_6_investment_performance_schedule_converts_mixed_currency_amounts(client: AsyncClient, db: AsyncSession, test_user, investment_account):
    p_start, sell_d, div_d, as_of = date(2026, 1, 1), date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 20)
    pos = _make_managed_position(test_user.id, investment_account.id, "USD-STOCK", quantity=Decimal("10"), cost_basis=Decimal("1000.00"), currency="USD", acquisition_date=p_start)
    db.add(pos)
    await db.flush()
    await _commit(
        db,
        *[FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.500000"), rate_date=d, source="test") for d in (p_start, sell_d, div_d, as_of)],
        _make_atomic_position(test_user.id, "USD-STOCK", broker="Test Broker", quantity=Decimal("10"), market_value=Decimal("1200.00"), currency="USD", snapshot_date=as_of, dedup_hash="usd_stock_schedule_snapshot"),
        _make_buy(pos, quantity=Decimal("11"), cost=Decimal("1020.00")),
        InvestmentTransaction(user_id=test_user.id, position_id=pos.id, transaction_date=sell_d, transaction_type=InvestmentTransactionType.SELL, asset_identifier="USD-STOCK", quantity=Decimal("1"), unit_price=Decimal("120.00"), gross_amount=Decimal("120.00"), fees=Decimal("0.00"), currency="USD", cost_basis=Decimal("20.00"), realized_pnl=Decimal("100.00"), cost_basis_method=CostBasisMethod.FIFO),
        DividendIncome(user_id=test_user.id, position_id=pos.id, payment_date=div_d, amount=Decimal("10.00"), currency="USD"),
    )
    resp = await client.get(f"/portfolio/performance/report-schedule?period_start={p_start}&period_end={as_of}&as_of_date={as_of}&currency=SGD")
    data = resp.json()
    h = data["holdings"][0]
    assert (resp.status_code, data["currency"], data["realized_pnl"], data["dividend_income"], data["unrealized_pnl"], (h["currency"], h["cost_basis"], h["market_value"], h["unrealized_pnl"], h["realized_pnl"])) == (
        200,
        "SGD",
        "150.00",
        "15.00",
        "300.00",
        ("SGD", "1500.00", "1800.00", "300.00", "150.00"),
    )


async def test_AC17_10_4_report_schedule_marks_stale_when_any_holding_price_is_stale(client: AsyncClient, db: AsyncSession, test_user, investment_account, portfolio_with_data):
    stale_date = date.today() - timedelta(days=7)
    await _commit(
        db,
        _make_managed_position(test_user.id, investment_account.id, "MSFT", quantity=Decimal("10"), cost_basis=Decimal("2500.00"), acquisition_date=stale_date),
        _make_atomic_position(test_user.id, "MSFT", broker="Stale Broker", quantity=Decimal("10"), market_value=Decimal("2700.00"), snapshot_date=stale_date, sector="Technology", geography="US", asset_type="stock", dedup_hash="msft_stale_snapshot", source_documents=[{"doc_id": "brokerage-doc-msft", "doc_type": "brokerage_statement"}]),
    )
    as_of = date.today().isoformat()
    resp = await client.get(f"/portfolio/performance/report-schedule?period_start={date.today().replace(month=1, day=1).isoformat()}&period_end={as_of}&as_of_date={as_of}&currency=SGD")
    freshness = resp.json()["data_freshness"]
    assert (resp.status_code, freshness["stale"], freshness["stale_holdings"]) == (200, True, ["MSFT"])


async def test_AC17_10_1_report_schedule_uses_manual_override_after_period_end(client: AsyncClient, db: AsyncSession, test_user, investment_account):
    p_start, p_end, ov_date = date(2026, 5, 2), date(2026, 5, 19), date(2026, 5, 31)
    await _commit(
        db,
        _make_managed_position(test_user.id, investment_account.id, "FULLERTON_SGD_MMF", cost_basis=Decimal("1000.00"), acquisition_date=p_start),
        _make_atomic_position(test_user.id, "FULLERTON_SGD_MMF", broker="Moomoo", market_value=Decimal("1250.00"), snapshot_date=ov_date, sector="Cash", geography="SG", asset_type="mutual_fund", dedup_hash="fullerton_future_snapshot", source_documents=[{"doc_id": "brokerage-doc-fullerton", "doc_type": "brokerage_statement"}]),
    )
    price_resp = await client.post("/pricing/price-overrides", json={"updates": [{"asset_identifier": "FULLERTON_SGD_MMF", "price": "12.50", "currency": "SGD", "price_date": ov_date.isoformat()}]})
    resp = await client.get(f"/portfolio/performance/report-schedule?period_start={p_start.isoformat()}&period_end={p_end.isoformat()}&as_of_date={p_end.isoformat()}&currency=SGD")
    data = resp.json()
    assert (
        price_resp.status_code,
        price_resp.json()["updated_count"],
        resp.status_code,
        data["holdings"][0]["asset_identifier"],
        data["holdings"][0]["market_value"],
        {row["dimension"] for row in data["allocation"]},
        data["data_freshness"]["latest_price_date"],
        data["data_freshness"]["manual_override_basis"],
    ) == (200, 1, 200, "FULLERTON_SGD_MMF", "1250.00", {"asset_class", "geography", "sector"}, ov_date.isoformat(), f"FULLERTON_SGD_MMF:{ov_date.isoformat()}")
    assert any(link.startswith("price_source:market_data_override:FULLERTON_SGD_MMF:") for link in data["source_links"])


@pytest.mark.parametrize("dimension", ["sector", "geography", "asset-class"])
async def test_allocation_endpoints_empty_and_with_data(client: AsyncClient, db: AsyncSession, test_user, investment_account, dimension):
    empty = await client.get(f"/portfolio/allocation/{dimension}")
    assert (empty.status_code, empty.json()) == (200, [])
    await _commit(db, _make_managed_position(test_user.id, investment_account.id, "AAPL"), _make_atomic_position(test_user.id, "AAPL", sector="Technology", geography="US", asset_type="stock", dedup_hash=f"alloc_{dimension}"))
    pop = await client.get(f"/portfolio/allocation/{dimension}")
    rows = pop.json()
    assert (pop.status_code, isinstance(rows, list), len(rows) >= 1, rows[0]["count"] >= 1, Decimal(rows[0]["value"]) > Decimal("0")) == (200, True, True, True, True)
    assert {"category", "value", "percentage", "count"} <= set(rows[0])
    assert (await client.get(f"/portfolio/allocation/{dimension}?as_of_date={(date.today() - timedelta(days=15)).isoformat()}")).status_code == 200


async def test_portfolio_endpoints_require_auth(public_client: AsyncClient):
    for ep in ("/portfolio/holdings", "/portfolio/allocation/sector", "/portfolio/allocation/geography", "/portfolio/allocation/asset-class"):
        assert (await public_client.get(ep)).status_code == 401


async def test_AC_portfolio_2673_1_create_holding_dividend_posts_balanced_journal_entry(client: AsyncClient, db: AsyncSession, test_user, portfolio_with_data):
    pay_date = date(date.today().year, 3, 15)
    resp = await client.post("/portfolio/AAPL/dividends", json={"payment_date": pay_date.isoformat(), "amount": "85.50", "currency": "SGD", "dividend_type": "ordinary", "notes": "Quarterly cash dividend"})
    payload = resp.json()
    list_resp = await client.get("/portfolio/AAPL/dividends")
    matching = next(item for item in list_resp.json() if item["id"] == payload["id"])
    dividend = await db.scalar(select(DividendIncome).where(DividendIncome.id == payload["id"]))
    inv_txn = await db.scalar(select(InvestmentTransaction).where(InvestmentTransaction.user_id == test_user.id, InvestmentTransaction.position_id == dividend.position_id, InvestmentTransaction.transaction_type == InvestmentTransactionType.DIVIDEND, InvestmentTransaction.transaction_date == pay_date))
    entry = await db.scalar(select(JournalEntry).where(JournalEntry.id == inv_txn.journal_entry_id).options(selectinload(JournalEntry.lines)))
    income_acct = await db.scalar(select(Account).where(Account.user_id == test_user.id, Account.type == AccountType.INCOME, Account.code == "4210"))
    debits = sum(line.amount for line in entry.lines if line.direction == Direction.DEBIT)
    credits = sum(line.amount for line in entry.lines if line.direction == Direction.CREDIT)
    assert (
        resp.status_code,
        payload["amount"],
        payload["currency"],
        payload["pay_date"],
        payload.get("journal_entry_id") is not None,
        list_resp.status_code,
        matching["journal_entry_id"],
        dividend.amount,
        inv_txn.gross_amount,
        entry.status,
        debits,
        credits,
        any(line.account_id == income_acct.id and line.direction == Direction.CREDIT for line in entry.lines),
    ) == (201, "85.50", "SGD", pay_date.isoformat(), True, 200, payload["journal_entry_id"], Decimal("85.50"), Decimal("85.50"), JournalEntryStatus.POSTED, Decimal("85.50"), Decimal("85.50"), True)


def _override_holdings_default_limit(monkeypatch: pytest.MonkeyPatch, new_default: int) -> None:
    for route in portfolio_router.router.routes:
        if getattr(route, "path", None) == "/portfolio/holdings" and "GET" in getattr(route, "methods", set()):
            for qp in route.dependant.query_params:
                if qp.name == "limit":
                    monkeypatch.setattr(qp.field_info, "default", new_default)
                    return
    raise AssertionError("Could not locate holdings route 'limit' query parameter")


async def test_AC17_30_holdings_pagination_and_cap(client: AsyncClient, db: AsyncSession, test_user, investment_account, monkeypatch: pytest.MonkeyPatch):
    objs = [
        obj
        for i in range(3)
        for obj in (
            _make_managed_position(test_user.id, investment_account.id, f"PAGE{i}", quantity=Decimal("10"), cost_basis=Decimal("1000.00"), acquisition_date=date.today()),
            _make_atomic_position(test_user.id, f"PAGE{i}", broker="Test Broker", quantity=Decimal("10"), market_value=Decimal("1100.00"), dedup_hash=f"page_snapshot_PAGE{i}"),
        )
    ]
    await _commit(db, *objs)
    full = await client.get("/portfolio/holdings")
    page = await client.get("/portfolio/holdings?limit=1&offset=1")
    _override_holdings_default_limit(monkeypatch, 2)
    capped = await client.get("/portfolio/holdings")
    full_assets = [row["asset_identifier"] for row in full.json()["items"]]
    assert (
        full.status_code,
        len(full_assets),
        page.status_code,
        [row["asset_identifier"] for row in page.json()["items"]],
        capped.status_code,
        len(capped.json()["items"]),
        capped.json()["total"],
    ) == (200, 3, 200, full_assets[1:2], 200, 2, 3)
    for bad in ("limit=10000", "limit=0", "offset=-1"):
        assert (await client.get(f"/portfolio/holdings?{bad}")).status_code == 422


async def test_AC17_30_4_5_6_dividends_realized_allocation_pagination(client: AsyncClient, db: AsyncSession, test_user, portfolio_with_data):
    pos = portfolio_with_data["position"]
    await _commit(
        db,
        *[DividendIncome(user_id=test_user.id, position_id=pos.id, payment_date=date(2026, 1, 1) + timedelta(days=i), amount=Decimal("1.00"), currency="SGD") for i in range(7)],
        *[InvestmentTransaction(user_id=test_user.id, position_id=pos.id, transaction_date=date(2026, 1, 1) + timedelta(days=i), transaction_type=InvestmentTransactionType.SELL, asset_identifier="AAPL", quantity=Decimal("1"), unit_price=Decimal("130.00"), gross_amount=Decimal("130.00"), fees=Decimal("0.00"), currency="SGD", cost_basis=Decimal("100.00"), realized_pnl=Decimal("30.00"), cost_basis_method=CostBasisMethod.FIFO) for i in range(7)],
    )
    div_full, div_lim, div_off = await client.get("/portfolio/AAPL/dividends"), await client.get("/portfolio/AAPL/dividends?limit=3"), await client.get("/portfolio/AAPL/dividends?limit=3&offset=3")
    real_full, real_lim, real_off = await client.get("/portfolio/AAPL/realized"), await client.get("/portfolio/AAPL/realized?limit=2"), await client.get("/portfolio/AAPL/realized?limit=2&offset=2")
    alloc_full, alloc_lim = await client.get("/portfolio/allocation/sector"), await client.get("/portfolio/allocation/sector?limit=1")
    assert (
        len(div_full.json()),
        len(div_lim.json()),
        [r["id"] for r in div_off.json()],
        (await client.get("/portfolio/AAPL/dividends?limit=10000")).status_code,
        len(real_full.json()),
        len(real_lim.json()),
        [r["lot_id"] for r in real_off.json()],
        (await client.get("/portfolio/AAPL/realized?offset=-1")).status_code,
        len(alloc_lim.json()) <= 1 and len(alloc_lim.json()) <= len(alloc_full.json()),
        (await client.get("/portfolio/allocation/geography?limit=10000")).status_code,
        (await client.get("/portfolio/allocation/asset-class?offset=-1")).status_code,
    ) == (7, 3, [r["id"] for r in div_full.json()[3:6]], 422, 7, 2, [r["lot_id"] for r in real_full.json()[2:4]], 422, True, 422, 422)


async def test_portfolio_summary_falls_back_to_ledger_dividend_income_ytd(client: AsyncClient, db: AsyncSession, test_user, portfolio_with_data):
    await create_valid_posted_entry(db, test_user.id, entry_date=date(date.today().year, 2, 10), memo="Dividend", amount=Decimal("200.00"), source_type=JournalEntrySourceType.AUTO_PARSED, debit_account_type=AccountType.ASSET, credit_account_type=AccountType.INCOME)
    await db.commit()
    resp = await client.get("/portfolio/summary")
    assert (resp.status_code, resp.json()["dividend_income_ytd"]) == (200, "200.00")
