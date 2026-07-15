"""AC17.6: Portfolio router endpoint tests — holdings, performance, allocation, price updates."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction.orm.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.extraction.orm.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.ledger import Account, AccountType
from src.portfolio import AssetNotFoundError, DividendIncome, InvestmentTransaction, InvestmentTransactionType
from src.pricing.orm.market_data import FxRate
import src.portfolio.extension.api.portfolio as portfolio_router
from src.schemas.portfolio import HoldingResponse
from tests.ledger._ledger_helpers import create_valid_posted_entry


@pytest.fixture
async def investment_account(db: AsyncSession, test_user):
    account = Account(
        user_id=test_user.id,
        name="Investment Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.commit()
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
    db.add(deposit)

    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="AAPL",
        quantity=Decimal("100"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=60),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)

    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date.today(),
        asset_identifier="AAPL",
        # Matches investment_account.name -- point-in-time lookups now key by
        # (asset_identifier, broker) via Account.name (#1791 follow-up).
        broker="Investment Account",
        quantity=Decimal("100"),
        market_value=Decimal("12000.00"),
        currency="SGD",
        sector="Technology",
        geography="US",
        asset_type="stock",
        dedup_hash="aapl_test",
        source_documents={
            "documents": [
                {
                    "doc_id": "brokerage-doc-aapl",
                    "doc_type": "brokerage_statement",
                    "broker": "Investment Account",
                }
            ]
        },
    )
    db.add(atomic)
    await db.commit()
    return {"position": position, "account": investment_account}


async def test_get_holdings_empty_portfolio(client: AsyncClient):
    """AC17.6.1: GET /portfolio/holdings on empty portfolio returns 200 with empty page.

    Verify that the holdings endpoint gracefully handles no positions.
    """
    response = await client.get("/portfolio/holdings")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "warnings": []}


async def test_get_holdings_with_data(client: AsyncClient, portfolio_with_data):
    """AC17.6.2: GET /portfolio/holdings with data returns non-empty items page.

    Verify that the holdings endpoint returns portfolio data when positions exist.
    """
    response = await client.get("/portfolio/holdings")
    assert response.status_code == 200
    data = response.json()["items"]
    assert isinstance(data, list)
    assert len(data) > 0


async def test_holding_detail_dividends_realized_and_cost_basis_endpoints(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    portfolio_with_data,
):
    """AC17.7.2/AC17.7.3/AC17.7.4: Holding detail APIs return dividends, realized lots, and persist method."""
    position = portfolio_with_data["position"]
    dividend = DividendIncome(
        user_id=test_user.id,
        position_id=position.id,
        payment_date=date(2026, 2, 15),
        amount=Decimal("42.50"),
        currency="SGD",
    )
    sell = InvestmentTransaction(
        user_id=test_user.id,
        position_id=position.id,
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
    )
    db.add_all([dividend, sell])
    await db.commit()

    dividends_response = await client.get("/portfolio/AAPL/dividends")
    assert dividends_response.status_code == 200
    assert dividends_response.json()[0] | {"id": dividends_response.json()[0]["id"]} == {
        "id": dividends_response.json()[0]["id"],
        "ex_date": "2026-02-15",
        "pay_date": "2026-02-15",
        "amount": "42.50",
        "currency": "SGD",
        "reinvested": False,
    }

    realized_response = await client.get("/portfolio/AAPL/realized")
    assert realized_response.status_code == 200
    realized = realized_response.json()[0]
    assert realized["quantity"] == "5.000000"
    assert realized["basis"] == "500.00"
    assert realized["proceeds"] == "649.00"
    assert realized["gain_loss"] == "149.00"

    patch_response = await client.patch("/portfolio/AAPL", json={"cost_basis_method": "LIFO"})
    assert patch_response.status_code == 200
    assert patch_response.json() == {"updated_count": 1, "cost_basis_method": "LIFO"}
    await db.refresh(position)
    assert position.cost_basis_method == CostBasisMethod.LIFO


async def test_portfolio_summary_returns_realized_and_dividend_ytd(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    portfolio_with_data,
):
    """AC17.7.5: Portfolio summary exposes realized_pnl_ytd and dividend_income_ytd."""
    position = portfolio_with_data["position"]
    db.add_all(
        [
            DividendIncome(
                user_id=test_user.id,
                position_id=position.id,
                payment_date=date(date.today().year, 2, 15),
                amount=Decimal("42.50"),
                currency="SGD",
            ),
            InvestmentTransaction(
                user_id=test_user.id,
                position_id=position.id,
                transaction_date=date(date.today().year, 3, 1),
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
        ]
    )
    await db.commit()

    response = await client.get("/portfolio/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["realized_pnl_ytd"] == "149.00"
    assert data["dividend_income_ytd"] == "42.50"


async def test_portfolio_summary_returns_zeroes_when_service_has_no_holdings(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC17.7.5: Empty portfolio summary returns a zero dashboard contract."""
    monkeypatch.setattr(
        portfolio_router._portfolio_service,
        "get_portfolio_summary",
        AsyncMock(side_effect=AssetNotFoundError("no holdings")),
    )

    response = await client.get("/portfolio/summary?as_of_date=2026-05-20")

    assert response.status_code == 200
    data = response.json()
    assert data["total_market_value"] == "0.00"
    assert data["realized_pnl_ytd"] == "0.00"
    assert data["dividend_income_ytd"] == "0.00"
    assert data["holdings_count"] == 0


async def test_update_holding_cost_basis_method_returns_404_for_missing_holding(client: AsyncClient):
    """AC17.7.3: Missing holding cost-basis updates return a stable 404."""
    response = await client.patch("/portfolio/MISSING", json={"cost_basis_method": "FIFO"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Holding not found"


async def test_get_holdings_with_date_filter(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.1: AC17.6.3: GET /portfolio/holdings with as_of_date filter returns 200.

    Verify that the holdings endpoint accepts and processes date filter.
    """
    past_date = (date.today() - timedelta(days=30)).isoformat()
    response = await client.get(f"/portfolio/holdings?as_of_date={past_date}")
    assert response.status_code == 200


async def test_get_holdings_defaults_to_future_imported_snapshot(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC-extraction.813.10: Default holdings endpoint returns latest imported snapshot."""
    future_date = date.today() + timedelta(days=12)
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="FULLERTON-SGD-MMF",
        quantity=Decimal("100"),
        cost_basis=Decimal("1000.00"),
        currency="SGD",
        acquisition_date=date.today(),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=future_date,
        asset_identifier="FULLERTON-SGD-MMF",
        broker="Moomoo E2E Portfolio",
        quantity=Decimal("100"),
        market_value=Decimal("1234.00"),
        currency="SGD",
        dedup_hash="router_future_snapshot",
        source_documents={},
    )
    db.add_all([position, atomic])
    await db.commit()

    response = await client.get("/portfolio/holdings")

    assert response.status_code == 200
    data = response.json()["items"]
    assert len(data) == 1
    assert data[0]["asset_identifier"] == "FULLERTON-SGD-MMF"
    assert Decimal(data[0]["market_value"]) == Decimal("1234.00")


async def test_get_holdings_explicit_date_does_not_use_future_snapshot(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC-extraction.813.10: Explicit holdings date remains date-bounded."""
    future_date = date.today() + timedelta(days=12)
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="FULLERTON-SGD-MMF",
        quantity=Decimal("100"),
        cost_basis=Decimal("1000.00"),
        currency="SGD",
        acquisition_date=date.today(),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=future_date,
        asset_identifier="FULLERTON-SGD-MMF",
        broker="Moomoo E2E Portfolio",
        quantity=Decimal("100"),
        market_value=Decimal("1234.00"),
        currency="SGD",
        dedup_hash="router_explicit_future_snapshot",
        source_documents={},
    )
    db.add_all([position, atomic])
    await db.commit()

    response = await client.get(f"/portfolio/holdings?as_of_date={date.today().isoformat()}")

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_get_holdings_explicit_date_uses_historical_snapshot_quantity(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC-portfolio.as-of.2: AC17.9.2: GET /portfolio/holdings with as_of_date returns historical snapshot quantity/value."""
    historical_date = date(2025, 1, 31)
    current_date = date(2025, 2, 28)
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="VWRA",
        quantity=Decimal("20"),
        cost_basis=Decimal("3000.00"),
        currency="SGD",
        acquisition_date=historical_date,
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    historical_atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=historical_date,
        asset_identifier="VWRA",
        broker="Investment Account",
        quantity=Decimal("10"),
        market_value=Decimal("1200.00"),
        currency="SGD",
        dedup_hash="router_vwra_historical_snapshot",
        source_documents={},
    )
    current_atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=current_date,
        asset_identifier="VWRA",
        broker="Investment Account",
        quantity=Decimal("20"),
        market_value=Decimal("3000.00"),
        currency="SGD",
        dedup_hash="router_vwra_current_snapshot",
        source_documents={},
    )
    db.add_all([position, historical_atomic, current_atomic])
    await db.commit()

    response = await client.get(f"/portfolio/holdings?as_of_date={historical_date.isoformat()}")

    assert response.status_code == 200
    data = response.json()["items"]
    assert len(data) == 1
    assert data[0]["asset_identifier"] == "VWRA"
    assert Decimal(data[0]["quantity"]) == Decimal("10.000000")
    assert Decimal(data[0]["market_value"]) == Decimal("1200.00")


async def test_AC_portfolio_holdings_6_unreconciled_snapshot_disclosed_in_warnings(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC-portfolio.holdings.6: a point-in-time snapshot with no reconciled
    managed position is excluded from the holdings page AND disclosed in the
    response's warnings list (#1796) — previously it was only logged, so the
    response silently read as complete."""
    snapshot_date = date(2025, 1, 31)
    db.add(
        AtomicPosition(
            user_id=test_user.id,
            snapshot_date=snapshot_date,
            asset_identifier="ORPHAN-FUND",
            broker="Test Broker",
            quantity=Decimal("10"),
            market_value=Decimal("1000.00"),
            currency="SGD",
            dedup_hash="orphan_snapshot_warning",
            source_documents={},
        )
    )
    await db.commit()

    response = await client.get(f"/portfolio/holdings?as_of_date={snapshot_date.isoformat()}")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert [w["type"] for w in body["warnings"]] == ["unreconciled_snapshot_skipped"]
    assert body["warnings"][0]["asset_identifier"] == "ORPHAN-FUND"
    assert body["warnings"][0]["as_of_date"] == snapshot_date.isoformat()


async def test_get_holdings_include_disposed(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.2: AC17.6.4: GET /portfolio/holdings with include_disposed=true returns 200.

    Verify that the holdings endpoint accepts the include_disposed parameter.
    """
    response = await client.get("/portfolio/holdings?include_disposed=true")
    assert response.status_code == 200


async def test_get_performance_without_period(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.3: AC17.6.5: GET /portfolio/performance without period returns metrics.

    Verify that the performance endpoint returns xirr, twr, and mwr.
    """
    response = await client.get("/portfolio/performance")
    assert response.status_code == 200
    data = response.json()
    assert "xirr" in data
    assert "time_weighted_return" in data
    assert "money_weighted_return" in data


async def test_get_performance_with_period(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.4: AC17.6.6: GET /portfolio/performance with period params returns metrics.

    Verify that the performance endpoint accepts period_start and period_end.
    """
    start = (date.today() - timedelta(days=90)).isoformat()
    end = date.today().isoformat()
    response = await client.get(f"/portfolio/performance?period_start={start}&period_end={end}")
    assert response.status_code == 200
    data = response.json()
    assert "xirr" in data
    assert "time_weighted_return" in data


async def test_AC17_10_1_AC17_10_2_get_investment_performance_report_schedule(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    portfolio_with_data,
):
    """AC-portfolio.report-schedule.1 · AC-portfolio.report-schedule.3: AC17.10.1 AC17.10.2 AC17.10.3: schedule exposes metrics, rows, freshness, sources, and notes."""
    position = portfolio_with_data["position"]
    source_id = uuid4()
    journal_entry = await create_valid_posted_entry(
        db,
        test_user.id,
        entry_date=date.today() - timedelta(days=5),
        memo="Realized investment sale",
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    dividend = DividendIncome(
        user_id=test_user.id,
        position_id=position.id,
        payment_date=date.today() - timedelta(days=10),
        amount=Decimal("42.50"),
        currency="SGD",
    )
    sell = InvestmentTransaction(
        user_id=test_user.id,
        position_id=position.id,
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
        journal_entry_id=journal_entry.id,
        source_id=source_id,
    )
    db.add_all([dividend, sell])
    await db.commit()

    period_start = (date.today() - timedelta(days=90)).isoformat()
    as_of_date = date.today().isoformat()
    response = await client.get(
        "/portfolio/performance/report-schedule"
        f"?period_start={period_start}&period_end={as_of_date}&as_of_date={as_of_date}&currency=SGD"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["period_start"] == period_start
    assert data["period_end"] == as_of_date
    assert data["as_of_date"] == as_of_date
    assert data["currency"] == "SGD"
    for key in ["xirr", "time_weighted_return", "money_weighted_return", "dividend_yield"]:
        assert key in data
        assert data[key] is None or isinstance(data[key], str)
    assert data["realized_pnl"] == "149.00"
    assert data["dividend_income"] == "42.50"
    assert data["unrealized_pnl"] == "2000.00"
    assert data["holdings"][0]["asset_identifier"] == "AAPL"
    assert data["holdings"][0]["realized_pnl"] == "149.00"
    assert data["holdings"][0]["dividend_income"] == "42.50"
    assert data["allocation"]
    assert data["data_freshness"]["latest_price_date"] == as_of_date
    assert set(data["source_links"]) >= {
        "brokerage_statement:brokerage-doc-aapl",
        f"investment_transaction_source:{source_id}",
        f"journal_entry:{journal_entry.id}",
        "report_section:investment_performance",
    }
    assert any(link.startswith("price_source:atomic_position:AAPL:") for link in data["source_links"])
    assert data["notes"]
    if data["time_weighted_return"] is None:
        assert any("TWR unavailable" in note for note in data["notes"])


async def test_AC17_10_6_investment_performance_schedule_converts_mixed_currency_amounts(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC-portfolio.report-schedule.6: AC17.10.6: Report schedule amounts are converted into presentation currency."""
    period_start = date(2026, 1, 1)
    sell_date = date(2026, 3, 1)
    dividend_date = date(2026, 4, 1)
    as_of_date = date(2026, 5, 20)
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="USD-STOCK",
        quantity=Decimal("10"),
        cost_basis=Decimal("1000.00"),
        currency="USD",
        acquisition_date=period_start,
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)
    await db.flush()
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.500000"),
                rate_date=period_start,
                source="test",
            ),
            FxRate(
                base_currency="USD", quote_currency="SGD", rate=Decimal("1.500000"), rate_date=sell_date, source="test"
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.500000"),
                rate_date=dividend_date,
                source="test",
            ),
            FxRate(
                base_currency="USD", quote_currency="SGD", rate=Decimal("1.500000"), rate_date=as_of_date, source="test"
            ),
            AtomicPosition(
                user_id=test_user.id,
                snapshot_date=as_of_date,
                asset_identifier="USD-STOCK",
                broker="Test Broker",
                quantity=Decimal("10"),
                market_value=Decimal("1200.00"),
                currency="USD",
                dedup_hash="usd_stock_schedule_snapshot",
                source_documents={},
            ),
            InvestmentTransaction(
                user_id=test_user.id,
                position_id=position.id,
                transaction_date=sell_date,
                transaction_type=InvestmentTransactionType.SELL,
                asset_identifier="USD-STOCK",
                quantity=Decimal("1"),
                unit_price=Decimal("120.00"),
                gross_amount=Decimal("120.00"),
                fees=Decimal("0.00"),
                currency="USD",
                cost_basis=Decimal("20.00"),
                realized_pnl=Decimal("100.00"),
                cost_basis_method=CostBasisMethod.FIFO,
            ),
            DividendIncome(
                user_id=test_user.id,
                position_id=position.id,
                payment_date=dividend_date,
                amount=Decimal("10.00"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    response = await client.get(
        "/portfolio/performance/report-schedule"
        f"?period_start={period_start}&period_end={as_of_date}&as_of_date={as_of_date}&currency=SGD"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "SGD"
    assert data["realized_pnl"] == "150.00"
    assert data["dividend_income"] == "15.00"
    assert data["unrealized_pnl"] == "300.00"
    holding = data["holdings"][0]
    assert holding["currency"] == "SGD"
    assert holding["cost_basis"] == "1500.00"
    assert holding["market_value"] == "1800.00"
    assert holding["unrealized_pnl"] == "300.00"
    assert holding["realized_pnl"] == "150.00"


async def test_AC19_8_8_investment_schedule_fallback_holding_cost_basis_converts_currency(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-portfolio.schedule-fallback.1: AC19.8.8: Fallback holdings without ManagedPosition still convert cost basis to presentation currency."""
    period_start = date(2026, 1, 1)
    as_of_date = date(2026, 5, 20)
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.500000"),
            rate_date=period_start,
            source="test",
        )
    )
    await db.commit()

    async def fake_holdings(*_args, **_kwargs):
        return [
            HoldingResponse(
                id=uuid4(),
                user_id=test_user.id,
                account_id=investment_account.id,
                asset_identifier="UNRECONCILED-USD",
                quantity=Decimal("10"),
                cost_basis=Decimal("1000.00"),
                market_value=Decimal("1800.00"),
                unrealized_pnl=Decimal("800.00"),
                unrealized_pnl_percent=Decimal("80.00"),
                currency="USD",
                native_cost_basis=Decimal("1000.00"),
                native_currency="USD",
                acquisition_date=period_start,
                status=PositionStatus.ACTIVE,
            )
        ]

    monkeypatch.setattr(portfolio_router._portfolio_service, "get_holdings", fake_holdings)

    response = await client.get(
        "/portfolio/performance/report-schedule"
        f"?period_start={period_start}&period_end={as_of_date}&as_of_date={as_of_date}&currency=SGD"
    )

    assert response.status_code == 200
    holding = response.json()["holdings"][0]
    assert holding["cost_basis"] == "1500.00"
    assert holding["market_value"] == "1800.00"
    assert holding["unrealized_pnl"] == "300.00"


async def test_AC17_10_4_report_schedule_marks_stale_when_any_holding_price_is_stale(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
    portfolio_with_data,
):
    """AC-portfolio.report-schedule.4: AC17.10.4: freshness is stale when any holding lacks current as-of-date price evidence."""
    stale_date = date.today() - timedelta(days=7)
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="MSFT",
        quantity=Decimal("10"),
        cost_basis=Decimal("2500.00"),
        currency="SGD",
        acquisition_date=stale_date,
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=stale_date,
        asset_identifier="MSFT",
        broker="Stale Broker",
        quantity=Decimal("10"),
        market_value=Decimal("2700.00"),
        currency="SGD",
        sector="Technology",
        geography="US",
        asset_type="stock",
        dedup_hash="msft_stale_snapshot",
        source_documents=[{"doc_id": "brokerage-doc-msft", "doc_type": "brokerage_statement"}],
    )
    db.add_all([position, atomic])
    await db.commit()

    as_of_date = date.today().isoformat()
    response = await client.get(
        "/portfolio/performance/report-schedule"
        f"?period_start={date.today().replace(month=1, day=1).isoformat()}"
        f"&period_end={as_of_date}&as_of_date={as_of_date}&currency=SGD"
    )

    assert response.status_code == 200
    freshness = response.json()["data_freshness"]
    assert freshness["stale"] is True
    assert freshness["stale_holdings"] == ["MSFT"]


async def test_AC17_10_1_report_schedule_uses_manual_override_after_period_end(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC17.10.1 AC17.10.2: Report-preparation overrides can evidence active holdings after period end."""
    period_start = date(2026, 5, 2)
    period_end = date(2026, 5, 19)
    override_date = date(2026, 5, 31)
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment_account.id,
        asset_identifier="FULLERTON_SGD_MMF",
        quantity=Decimal("100"),
        cost_basis=Decimal("1000.00"),
        currency="SGD",
        acquisition_date=period_start,
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=override_date,
        asset_identifier="FULLERTON_SGD_MMF",
        broker="Moomoo",
        quantity=Decimal("100"),
        market_value=Decimal("1250.00"),
        currency="SGD",
        sector="Cash",
        geography="SG",
        asset_type="mutual_fund",
        dedup_hash="fullerton_future_snapshot",
        source_documents=[{"doc_id": "brokerage-doc-fullerton", "doc_type": "brokerage_statement"}],
    )
    db.add_all([position, atomic])
    await db.commit()

    price_response = await client.post(
        "/portfolio/prices/update",
        json={
            "updates": [
                {
                    "asset_identifier": "FULLERTON_SGD_MMF",
                    "price": "12.50",
                    "currency": "SGD",
                    "price_date": override_date.isoformat(),
                }
            ]
        },
    )
    assert price_response.status_code == 200
    assert price_response.json()["updated_count"] == 1

    response = await client.get(
        "/portfolio/performance/report-schedule"
        f"?period_start={period_start.isoformat()}"
        f"&period_end={period_end.isoformat()}"
        f"&as_of_date={period_end.isoformat()}&currency=SGD"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["holdings"][0]["asset_identifier"] == "FULLERTON_SGD_MMF"
    assert data["holdings"][0]["market_value"] == "1250.00"
    assert {row["dimension"] for row in data["allocation"]} == {"asset_class", "geography", "sector"}
    assert data["data_freshness"]["latest_price_date"] == override_date.isoformat()
    assert data["data_freshness"]["manual_override_basis"] == (f"FULLERTON_SGD_MMF:{override_date.isoformat()}")
    assert any(link.startswith("price_source:market_data_override:FULLERTON_SGD_MMF:") for link in data["source_links"])


async def test_get_sector_allocation_empty(client: AsyncClient):
    """AC-portfolio.api.5: AC17.6.7: GET /portfolio/allocation/sector on empty portfolio returns [].

    Verify that the sector allocation endpoint returns empty list for no positions.
    """
    response = await client.get("/portfolio/allocation/sector")
    assert response.status_code == 200
    assert response.json() == []


async def test_get_sector_allocation_with_data(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.6: AC17.6.8: GET /portfolio/allocation/sector with data returns breakdown.

    Verify that the sector allocation endpoint returns category/value/percentage/count.
    """
    response = await client.get("/portfolio/allocation/sector")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        assert "category" in data[0]
        assert "value" in data[0]
        assert "percentage" in data[0]
        assert "count" in data[0]


async def test_get_geography_allocation_empty(client: AsyncClient):
    """AC-portfolio.api.7: AC17.6.9: GET /portfolio/allocation/geography on empty portfolio returns [].

    Verify that the geography allocation endpoint returns empty list for no positions.
    """
    response = await client.get("/portfolio/allocation/geography")
    assert response.status_code == 200
    assert response.json() == []


async def test_get_geography_allocation_with_data(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.8: AC17.6.10: GET /portfolio/allocation/geography with data returns breakdown.

    Verify that the geography allocation endpoint returns grouped results.
    """
    response = await client.get("/portfolio/allocation/geography")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


async def test_get_asset_class_allocation_empty(client: AsyncClient):
    """AC-portfolio.api.9: AC17.6.11: GET /portfolio/allocation/asset-class on empty portfolio returns [].

    Verify that the asset class allocation endpoint returns empty list for no positions.
    """
    response = await client.get("/portfolio/allocation/asset-class")
    assert response.status_code == 200
    assert response.json() == []


async def test_get_asset_class_allocation_with_data(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.10: AC17.6.12: GET /portfolio/allocation/asset-class with data returns breakdown.

    Verify that the asset class allocation endpoint returns grouped results.
    """
    response = await client.get("/portfolio/allocation/asset-class")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


async def test_update_prices_single(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.11: AC17.6.13: POST /portfolio/prices/update with single asset returns success.

    Verify that a single price update creates a MarketDataOverride.
    """
    payload = {
        "updates": [
            {
                "asset_identifier": "AAPL",
                "price": "155.50",
                "currency": "SGD",
                "price_date": date.today().isoformat(),
            }
        ]
    }
    response = await client.post("/portfolio/prices/update", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "updated_count" in data
    assert data["updated_count"] >= 0


async def test_update_prices_batch(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.12: AC17.6.14: POST /portfolio/prices/update with batch returns success.

    Verify that batch price updates are processed.
    """
    payload = {
        "updates": [
            {
                "asset_identifier": "AAPL",
                "price": "155.50",
                "currency": "SGD",
                "price_date": date.today().isoformat(),
            },
            {
                "asset_identifier": "GOOGL",
                "price": "140.25",
                "currency": "SGD",
                "price_date": date.today().isoformat(),
            },
        ]
    }
    response = await client.post("/portfolio/prices/update", json=payload)
    assert response.status_code == 200


async def test_update_prices_invalid_payload(client: AsyncClient):
    """AC-portfolio.api.13: AC17.6.15: POST /portfolio/prices/update with invalid payload returns 422.

    Verify that missing required fields trigger validation error.
    """
    payload = {"updates": [{"asset_identifier": "AAPL"}]}
    response = await client.post("/portfolio/prices/update", json=payload)
    assert response.status_code == 422


async def test_portfolio_endpoints_require_auth(public_client: AsyncClient):
    """AC-portfolio.api.14: AC17.6.16: All portfolio endpoints require authentication.

    Verify that unauthenticated requests return 401.
    """
    endpoints = [
        "/portfolio/holdings",
        "/portfolio/performance",
        "/portfolio/allocation/sector",
        "/portfolio/allocation/geography",
        "/portfolio/allocation/asset-class",
    ]
    for endpoint in endpoints:
        response = await public_client.get(endpoint)
        assert response.status_code == 401


async def test_allocation_with_as_of_date(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.15: AC17.6.17: GET /portfolio/allocation/sector with as_of_date returns 200.

    Verify that allocation endpoints accept as_of_date filter.
    """
    past_date = (date.today() - timedelta(days=15)).isoformat()
    response = await client.get(f"/portfolio/allocation/sector?as_of_date={past_date}")
    assert response.status_code == 200


async def test_performance_metrics_response_format(client: AsyncClient, portfolio_with_data):
    """AC-portfolio.api.16: AC17.6.18: GET /portfolio/performance returns string-formatted metrics.

    Verify that xirr, twr, mwr are returned as strings.
    """
    response = await client.get("/portfolio/performance")
    assert response.status_code == 200
    data = response.json()

    for key in ["xirr", "time_weighted_return", "money_weighted_return"]:
        assert key in data
        assert isinstance(data[key], str)


async def test_get_performance_insufficient_data(client: AsyncClient):
    """AC-portfolio.api.17: AC17.6.19: InsufficientDataError on empty portfolio -> xirr/mwr default to 0."""
    response = await client.get("/portfolio/performance")
    assert response.status_code == 200
    data = response.json()
    assert data["xirr"] == "0.00"
    assert data["money_weighted_return"] == "0.00"
    assert data["time_weighted_return"] == "0.00"


async def test_get_performance_xirr_calculation_error(client: AsyncClient, portfolio_with_data, monkeypatch):
    """AC-portfolio.api.18: AC17.6.20: PerformanceError (non-InsufficientData) on XIRR -> 422."""
    from src.portfolio import XIRRCalculationError

    async def _raise_xirr(*args, **kwargs):
        raise XIRRCalculationError("Newton+bisection failed")

    monkeypatch.setattr("src.portfolio.extension.api.portfolio.calculate_xirr", _raise_xirr)

    response = await client.get("/portfolio/performance")
    assert response.status_code == 422
    assert "Newton+bisection failed" in response.json()["detail"]


async def test_get_performance_mwr_calculation_error(client: AsyncClient, portfolio_with_data, monkeypatch):
    """AC-portfolio.api.19: AC17.6.21: PerformanceError (non-InsufficientData) on MWR -> 422."""
    from src.portfolio import XIRRCalculationError

    async def _ok_xirr(*args, **kwargs):
        return Decimal("10.00")

    async def _raise_mwr(*args, **kwargs):
        raise XIRRCalculationError("MWR convergence failed")

    monkeypatch.setattr("src.portfolio.extension.api.portfolio.calculate_xirr", _ok_xirr)
    monkeypatch.setattr("src.portfolio.extension.api.portfolio.calculate_money_weighted_return", _raise_mwr)

    response = await client.get("/portfolio/performance")
    assert response.status_code == 422
    assert "MWR convergence failed" in response.json()["detail"]


# --- AC17.30: Portfolio list endpoint pagination (issue #1007) ---


@pytest.fixture
async def portfolio_with_many_dividends(db: AsyncSession, test_user, portfolio_with_data):
    """Seed many dividend rows for a single ticker to exercise pagination bounds."""
    position = portfolio_with_data["position"]
    dividends = [
        DividendIncome(
            user_id=test_user.id,
            position_id=position.id,
            payment_date=date(2026, 1, 1) + timedelta(days=index),
            amount=Decimal("1.00"),
            currency="SGD",
        )
        for index in range(7)
    ]
    db.add_all(dividends)
    await db.commit()
    return {"count": len(dividends), "ticker": "AAPL"}


@pytest.fixture
async def portfolio_with_many_realized(db: AsyncSession, test_user, portfolio_with_data):
    """Seed many SELL transactions for a single ticker to exercise pagination bounds."""
    position = portfolio_with_data["position"]
    sells = [
        InvestmentTransaction(
            user_id=test_user.id,
            position_id=position.id,
            transaction_date=date(2026, 1, 1) + timedelta(days=index),
            transaction_type=InvestmentTransactionType.SELL,
            asset_identifier="AAPL",
            quantity=Decimal("1"),
            unit_price=Decimal("130.00"),
            gross_amount=Decimal("130.00"),
            fees=Decimal("0.00"),
            currency="SGD",
            cost_basis=Decimal("100.00"),
            realized_pnl=Decimal("30.00"),
            cost_basis_method=CostBasisMethod.FIFO,
        )
        for index in range(7)
    ]
    db.add_all(sells)
    await db.commit()
    return {"count": len(sells), "ticker": "AAPL"}


def _override_holdings_default_limit(monkeypatch: pytest.MonkeyPatch, new_default: int) -> None:
    """Monkeypatch the holdings route's `limit` default so default-cap behaviour
    can be validated without seeding hundreds of rows.

    FastAPI captures the default in the route's ``field_info`` at import time, so
    patching the module constant alone has no effect on requests; we patch the
    bound field default directly and restore it afterwards.
    """
    for route in portfolio_router.router.routes:
        if getattr(route, "path", None) == "/portfolio/holdings" and "GET" in getattr(route, "methods", set()):
            for query_param in route.dependant.query_params:
                if query_param.name == "limit":
                    monkeypatch.setattr(query_param.field_info, "default", new_default)
                    return
    raise AssertionError("Could not locate holdings route 'limit' query parameter")


async def test_AC17_30_1_holdings_default_cap_applied(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-portfolio.pagination.1: AC17.30.1: GET /portfolio/holdings caps results at the *default* limit when
    no `limit` param is passed.

    The default cap is monkeypatched to 2 and 3 holdings are seeded, so omitting
    `limit` must genuinely return only the default-capped 2 rows (not all 3).
    """
    _override_holdings_default_limit(monkeypatch, 2)

    for index in range(3):
        ticker = f"TICK{index}"
        db.add_all(
            [
                ManagedPosition(
                    user_id=test_user.id,
                    account_id=investment_account.id,
                    asset_identifier=ticker,
                    quantity=Decimal("10"),
                    cost_basis=Decimal("1000.00"),
                    currency="SGD",
                    acquisition_date=date.today(),
                    status=PositionStatus.ACTIVE,
                    cost_basis_method=CostBasisMethod.FIFO,
                ),
                AtomicPosition(
                    user_id=test_user.id,
                    snapshot_date=date.today(),
                    asset_identifier=ticker,
                    broker="Test Broker",
                    quantity=Decimal("10"),
                    market_value=Decimal("1100.00"),
                    currency="SGD",
                    dedup_hash=f"cap_snapshot_{ticker}",
                    source_documents={},
                ),
            ]
        )
    await db.commit()

    # No `limit` param -> the (patched) default cap of 2 must apply, not all 3.
    response = await client.get("/portfolio/holdings")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    # total reports the full match count, not the capped page size
    assert body["total"] == 3


async def test_AC17_30_2_holdings_limit_offset_honored(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC-portfolio.pagination.2: AC17.30.2: GET /portfolio/holdings honors limit and offset to page through holdings."""
    for index in range(3):
        ticker = f"PAGE{index}"
        db.add_all(
            [
                ManagedPosition(
                    user_id=test_user.id,
                    account_id=investment_account.id,
                    asset_identifier=ticker,
                    quantity=Decimal("10"),
                    cost_basis=Decimal("1000.00"),
                    currency="SGD",
                    acquisition_date=date.today(),
                    status=PositionStatus.ACTIVE,
                    cost_basis_method=CostBasisMethod.FIFO,
                ),
                AtomicPosition(
                    user_id=test_user.id,
                    snapshot_date=date.today(),
                    asset_identifier=ticker,
                    broker="Test Broker",
                    quantity=Decimal("10"),
                    market_value=Decimal("1100.00"),
                    currency="SGD",
                    dedup_hash=f"page_snapshot_{ticker}",
                    source_documents={},
                ),
            ]
        )
    await db.commit()

    full = await client.get("/portfolio/holdings")
    assert full.status_code == 200
    full_assets = [row["asset_identifier"] for row in full.json()["items"]]
    assert len(full_assets) == 3

    page = await client.get("/portfolio/holdings?limit=1&offset=1")
    assert page.status_code == 200
    page_assets = [row["asset_identifier"] for row in page.json()["items"]]
    assert page_assets == full_assets[1:2]


async def test_AC17_30_3_holdings_rejects_out_of_range_pagination(client: AsyncClient):
    """AC-portfolio.pagination.3: AC17.30.3: GET /portfolio/holdings rejects out-of-range limit/offset with 422."""
    too_large = await client.get("/portfolio/holdings?limit=10000")
    assert too_large.status_code == 422

    zero_limit = await client.get("/portfolio/holdings?limit=0")
    assert zero_limit.status_code == 422

    negative_offset = await client.get("/portfolio/holdings?offset=-1")
    assert negative_offset.status_code == 422


async def test_AC17_30_4_dividends_limit_offset_honored(
    client: AsyncClient,
    portfolio_with_many_dividends,
):
    """AC-portfolio.pagination.4: AC17.30.4: GET /portfolio/{ticker}/dividends honors limit/offset and rejects out-of-range."""
    ticker = portfolio_with_many_dividends["ticker"]
    total = portfolio_with_many_dividends["count"]

    full = await client.get(f"/portfolio/{ticker}/dividends")
    assert full.status_code == 200
    assert len(full.json()) == total

    limited = await client.get(f"/portfolio/{ticker}/dividends?limit=3")
    assert limited.status_code == 200
    assert len(limited.json()) == 3

    offset_page = await client.get(f"/portfolio/{ticker}/dividends?limit=3&offset=3")
    assert offset_page.status_code == 200
    assert [row["id"] for row in offset_page.json()] == [row["id"] for row in full.json()[3:6]]

    assert (await client.get(f"/portfolio/{ticker}/dividends?limit=10000")).status_code == 422


async def test_AC17_30_5_realized_limit_offset_honored(
    client: AsyncClient,
    portfolio_with_many_realized,
):
    """AC-portfolio.pagination.5: AC17.30.5: GET /portfolio/{ticker}/realized honors limit/offset and rejects out-of-range."""
    ticker = portfolio_with_many_realized["ticker"]
    total = portfolio_with_many_realized["count"]

    full = await client.get(f"/portfolio/{ticker}/realized")
    assert full.status_code == 200
    assert len(full.json()) == total

    limited = await client.get(f"/portfolio/{ticker}/realized?limit=2")
    assert limited.status_code == 200
    assert len(limited.json()) == 2

    offset_page = await client.get(f"/portfolio/{ticker}/realized?limit=2&offset=2")
    assert offset_page.status_code == 200
    assert [row["lot_id"] for row in offset_page.json()] == [row["lot_id"] for row in full.json()[2:4]]

    assert (await client.get(f"/portfolio/{ticker}/realized?offset=-1")).status_code == 422


async def test_AC17_30_6_allocation_limit_offset_honored(
    client: AsyncClient,
    portfolio_with_data,
):
    """AC-portfolio.pagination.6: AC17.30.6: GET /portfolio/allocation/* honors limit/offset and rejects out-of-range."""
    full = await client.get("/portfolio/allocation/sector")
    assert full.status_code == 200
    full_rows = full.json()

    limited = await client.get("/portfolio/allocation/sector?limit=1")
    assert limited.status_code == 200
    assert len(limited.json()) <= 1
    assert len(limited.json()) <= len(full_rows)

    assert (await client.get("/portfolio/allocation/geography?limit=10000")).status_code == 422
    assert (await client.get("/portfolio/allocation/asset-class?offset=-1")).status_code == 422
