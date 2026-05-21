"""AC17.6: Portfolio router endpoint tests — holdings, performance, allocation, price updates."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.models.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.models.portfolio import DividendIncome, InvestmentTransaction, InvestmentTransactionType
from src.routers import portfolio as portfolio_router
from src.services.portfolio import AssetNotFoundError


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
        broker="Test Broker",
        quantity=Decimal("100"),
        market_value=Decimal("12000.00"),
        currency="SGD",
        sector="Technology",
        geography="US",
        asset_type="stock",
        dedup_hash="aapl_test",
        source_documents={},
    )
    db.add(atomic)
    await db.commit()
    return {"position": position, "account": investment_account}


@pytest.mark.asyncio
async def test_get_holdings_empty_portfolio(client: AsyncClient):
    """AC17.6.1: GET /portfolio/holdings on empty portfolio returns 200 with empty list.

    Verify that the holdings endpoint gracefully handles no positions.
    """
    response = await client.get("/portfolio/holdings")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_holdings_with_data(client: AsyncClient, portfolio_with_data):
    """AC17.6.2: GET /portfolio/holdings with data returns non-empty list.

    Verify that the holdings endpoint returns portfolio data when positions exist.
    """
    response = await client.get("/portfolio/holdings")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_update_holding_cost_basis_method_returns_404_for_missing_holding(client: AsyncClient):
    """AC17.7.3: Missing holding cost-basis updates return a stable 404."""
    response = await client.patch("/portfolio/MISSING", json={"cost_basis_method": "FIFO"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Holding not found"


@pytest.mark.asyncio
async def test_get_holdings_with_date_filter(client: AsyncClient, portfolio_with_data):
    """AC17.6.3: GET /portfolio/holdings with as_of_date filter returns 200.

    Verify that the holdings endpoint accepts and processes date filter.
    """
    past_date = (date.today() - timedelta(days=30)).isoformat()
    response = await client.get(f"/portfolio/holdings?as_of_date={past_date}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_holdings_defaults_to_future_imported_snapshot(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC8.13.10: Default holdings endpoint returns latest imported snapshot."""
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
    data = response.json()
    assert len(data) == 1
    assert data[0]["asset_identifier"] == "FULLERTON-SGD-MMF"
    assert Decimal(data[0]["market_value"]) == Decimal("1234.00")


@pytest.mark.asyncio
async def test_get_holdings_explicit_date_does_not_use_future_snapshot(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC8.13.10: Explicit holdings date remains date-bounded."""
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
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_holdings_explicit_date_uses_historical_snapshot_quantity(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    investment_account,
):
    """AC17.9.2: GET /portfolio/holdings with as_of_date returns historical snapshot quantity/value."""
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
    data = response.json()
    assert len(data) == 1
    assert data[0]["asset_identifier"] == "VWRA"
    assert Decimal(data[0]["quantity"]) == Decimal("10.000000")
    assert Decimal(data[0]["market_value"]) == Decimal("1200.00")


@pytest.mark.asyncio
async def test_get_holdings_include_disposed(client: AsyncClient, portfolio_with_data):
    """AC17.6.4: GET /portfolio/holdings with include_disposed=true returns 200.

    Verify that the holdings endpoint accepts the include_disposed parameter.
    """
    response = await client.get("/portfolio/holdings?include_disposed=true")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_performance_without_period(client: AsyncClient, portfolio_with_data):
    """AC17.6.5: GET /portfolio/performance without period returns metrics.

    Verify that the performance endpoint returns xirr, twr, and mwr.
    """
    response = await client.get("/portfolio/performance")
    assert response.status_code == 200
    data = response.json()
    assert "xirr" in data
    assert "time_weighted_return" in data
    assert "money_weighted_return" in data


@pytest.mark.asyncio
async def test_get_performance_with_period(client: AsyncClient, portfolio_with_data):
    """AC17.6.6: GET /portfolio/performance with period params returns metrics.

    Verify that the performance endpoint accepts period_start and period_end.
    """
    start = (date.today() - timedelta(days=90)).isoformat()
    end = date.today().isoformat()
    response = await client.get(f"/portfolio/performance?period_start={start}&period_end={end}")
    assert response.status_code == 200
    data = response.json()
    assert "xirr" in data
    assert "time_weighted_return" in data


@pytest.mark.asyncio
async def test_get_sector_allocation_empty(client: AsyncClient):
    """AC17.6.7: GET /portfolio/allocation/sector on empty portfolio returns [].

    Verify that the sector allocation endpoint returns empty list for no positions.
    """
    response = await client.get("/portfolio/allocation/sector")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_sector_allocation_with_data(client: AsyncClient, portfolio_with_data):
    """AC17.6.8: GET /portfolio/allocation/sector with data returns breakdown.

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


@pytest.mark.asyncio
async def test_get_geography_allocation_empty(client: AsyncClient):
    """AC17.6.9: GET /portfolio/allocation/geography on empty portfolio returns [].

    Verify that the geography allocation endpoint returns empty list for no positions.
    """
    response = await client.get("/portfolio/allocation/geography")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_geography_allocation_with_data(client: AsyncClient, portfolio_with_data):
    """AC17.6.10: GET /portfolio/allocation/geography with data returns breakdown.

    Verify that the geography allocation endpoint returns grouped results.
    """
    response = await client.get("/portfolio/allocation/geography")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_asset_class_allocation_empty(client: AsyncClient):
    """AC17.6.11: GET /portfolio/allocation/asset-class on empty portfolio returns [].

    Verify that the asset class allocation endpoint returns empty list for no positions.
    """
    response = await client.get("/portfolio/allocation/asset-class")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_asset_class_allocation_with_data(client: AsyncClient, portfolio_with_data):
    """AC17.6.12: GET /portfolio/allocation/asset-class with data returns breakdown.

    Verify that the asset class allocation endpoint returns grouped results.
    """
    response = await client.get("/portfolio/allocation/asset-class")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_update_prices_single(client: AsyncClient, portfolio_with_data):
    """AC17.6.13: POST /portfolio/prices/update with single asset returns success.

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


@pytest.mark.asyncio
async def test_update_prices_batch(client: AsyncClient, portfolio_with_data):
    """AC17.6.14: POST /portfolio/prices/update with batch returns success.

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


@pytest.mark.asyncio
async def test_update_prices_invalid_payload(client: AsyncClient):
    """AC17.6.15: POST /portfolio/prices/update with invalid payload returns 422.

    Verify that missing required fields trigger validation error.
    """
    payload = {"updates": [{"asset_identifier": "AAPL"}]}
    response = await client.post("/portfolio/prices/update", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_portfolio_endpoints_require_auth(public_client: AsyncClient):
    """AC17.6.16: All portfolio endpoints require authentication.

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


@pytest.mark.asyncio
async def test_allocation_with_as_of_date(client: AsyncClient, portfolio_with_data):
    """AC17.6.17: GET /portfolio/allocation/sector with as_of_date returns 200.

    Verify that allocation endpoints accept as_of_date filter.
    """
    past_date = (date.today() - timedelta(days=15)).isoformat()
    response = await client.get(f"/portfolio/allocation/sector?as_of_date={past_date}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_performance_metrics_response_format(client: AsyncClient, portfolio_with_data):
    """AC17.6.18: GET /portfolio/performance returns string-formatted metrics.

    Verify that xirr, twr, mwr are returned as strings.
    """
    response = await client.get("/portfolio/performance")
    assert response.status_code == 200
    data = response.json()

    for key in ["xirr", "time_weighted_return", "money_weighted_return"]:
        assert key in data
        assert isinstance(data[key], str)


@pytest.mark.asyncio
async def test_get_performance_insufficient_data(client: AsyncClient):
    """AC17.6.19: InsufficientDataError on empty portfolio -> xirr/mwr default to 0."""
    response = await client.get("/portfolio/performance")
    assert response.status_code == 200
    data = response.json()
    assert data["xirr"] == "0.00"
    assert data["money_weighted_return"] == "0.00"
    assert data["time_weighted_return"] == "0.00"


@pytest.mark.asyncio
async def test_get_performance_xirr_calculation_error(client: AsyncClient, portfolio_with_data, monkeypatch):
    """AC17.6.20: PerformanceError (non-InsufficientData) on XIRR -> 422."""
    from src.services.performance import XIRRCalculationError

    async def _raise_xirr(*args, **kwargs):
        raise XIRRCalculationError("Newton+bisection failed")

    monkeypatch.setattr("src.routers.portfolio.performance.calculate_xirr", _raise_xirr)

    response = await client.get("/portfolio/performance")
    assert response.status_code == 422
    assert "Newton+bisection failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_performance_mwr_calculation_error(client: AsyncClient, portfolio_with_data, monkeypatch):
    """AC17.6.21: PerformanceError (non-InsufficientData) on MWR -> 422."""
    from src.services.performance import XIRRCalculationError

    async def _ok_xirr(*args, **kwargs):
        return Decimal("10.00")

    async def _raise_mwr(*args, **kwargs):
        raise XIRRCalculationError("MWR convergence failed")

    monkeypatch.setattr("src.routers.portfolio.performance.calculate_xirr", _ok_xirr)
    monkeypatch.setattr("src.routers.portfolio.performance.calculate_money_weighted_return", _raise_mwr)

    response = await client.get("/portfolio/performance")
    assert response.status_code == 422
    assert "MWR convergence failed" in response.json()["detail"]
