from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicPosition
from src.ledger import Account, AccountType
from src.portfolio import AssetNotFoundError, PortfolioNotFoundError, PortfolioService
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.pricing import MarketDataOverride, PriceSource
from src.pricing.orm.market_data import FxRate
from tests.factories import UserFactory


def _pos(user_id, account_id, asset="AAPL", qty=Decimal("100"), cost=Decimal("10000.00"), currency="SGD", acq_days=60, acq_date=None, disposal_date=None, status=PositionStatus.ACTIVE, method=CostBasisMethod.FIFO) -> ManagedPosition:
    return ManagedPosition(
        user_id=user_id,
        account_id=account_id,
        asset_identifier=asset,
        quantity=qty,
        cost_basis=cost,
        currency=currency,
        acquisition_date=acq_date or date.today() - timedelta(days=acq_days),
        disposal_date=disposal_date,
        status=status,
        cost_basis_method=method,
    )


def _atom(user_id, asset="AAPL", broker="Test Broker", qty=Decimal("100"), mv=Decimal("12000.00"), currency="SGD", snap_date=None, sector=None, geography=None, asset_type=None, dedup_hash=None, source_documents=None) -> AtomicPosition:
    sd = snap_date or date.today()
    return AtomicPosition(
        user_id=user_id,
        snapshot_date=sd,
        asset_identifier=asset,
        broker=broker,
        quantity=qty,
        market_value=mv,
        currency=currency,
        sector=sector,
        geography=geography,
        asset_type=asset_type,
        dedup_hash=dedup_hash or f"{asset}_{sd}_{broker}",
        source_documents={} if source_documents is None else source_documents,
    )


async def _flush(db: AsyncSession, *objs) -> None:
    db.add_all(objs)
    await db.flush()


@pytest.fixture
def svc():
    return PortfolioService()


@pytest.fixture
async def account(db: AsyncSession, test_user):
    acct = Account(user_id=test_user.id, name="Test Investment", type=AccountType.ASSET, currency="SGD")
    await _flush(db, acct)
    return acct


@pytest.fixture
async def active_position(db: AsyncSession, test_user, account):
    pos = _pos(test_user.id, account.id)
    await _flush(db, pos)
    return pos


@pytest.fixture
async def atomic_snapshot(db: AsyncSession, test_user):
    atom = _atom(test_user.id, sector="Technology", geography="US", asset_type="stock", dedup_hash="aapl_svc_test")
    await _flush(db, atom)
    return atom


async def test_get_holdings_happy_and_provenance(db, test_user, svc, active_position, atomic_snapshot):
    h = (await svc.get_holdings(db, test_user.id, base_currency="SGD"))[0]
    assert (h.asset_identifier, h.market_value, h.cost_basis, h.unrealized_pnl, h.sector, h.geography, h.asset_type, h.account_name, h.provenance) == ("AAPL", Decimal("12000.00"), Decimal("10000.00"), Decimal("2000.00"), "Technology", "US", "stock", "Test Investment", None)


async def test_get_holdings_provenance_imported_with_source_document(db, test_user, svc, active_position):
    await _flush(db, _atom(test_user.id, asset_type="stock", dedup_hash="aapl_provenance_test", source_documents={"documents": [{"doc_id": "11111111-1111-4111-8111-111111111111", "doc_type": "brokerage_statement"}]}))
    holdings = await svc.get_holdings(db, test_user.id, base_currency="SGD")
    assert (len(holdings), holdings[0].provenance) == (1, "imported")


async def test_AC22_13_1_explicit_as_of_holdings_preserve_snapshot_provenance(db, test_user, svc, account):
    as_of = date(2025, 1, 31)
    await _flush(
        db,
        _pos(test_user.id, account.id, "VWRA", qty=Decimal("10"), cost=Decimal("1200.00"), acq_date=as_of),
        _atom(test_user.id, "VWRA", "Test Investment", qty=Decimal("10"), mv=Decimal("1200.00"), snap_date=as_of, asset_type="etf", dedup_hash="vwra_hist_prov", source_documents={"documents": [{"doc_id": "22222222-2222-4222-8222-222222222222", "doc_type": "brokerage_statement"}]}),
    )
    holdings = await svc.get_holdings(db, test_user.id, as_of_date=as_of, base_currency="SGD")
    assert (len(holdings), holdings[0].provenance) == (1, "imported")


async def test_get_holdings_future_snapshot_default_and_explicit_as_of(db, test_user, svc, account):
    fut = date.today() + timedelta(days=12)
    await _flush(db, _pos(test_user.id, account.id, "FULLERTON_SGD_MMF", cost=Decimal("1000.00"), acq_date=fut), _atom(test_user.id, "FULLERTON_SGD_MMF", "Moomoo", mv=Decimal("1234.00"), snap_date=fut, dedup_hash="future_snap"))
    holdings = await svc.get_holdings(db, test_user.id, base_currency="SGD")
    assert (len(holdings), holdings[0].asset_identifier, holdings[0].market_value) == (1, "FULLERTON_SGD_MMF", Decimal("1234.00"))
    with pytest.raises(PortfolioNotFoundError):
        await svc.get_holdings(db, test_user.id, as_of_date=date.today(), base_currency="SGD")


async def test_get_holdings_explicit_as_of_historical_fx_fallback_and_filters(db, test_user, svc, account):
    hist, curr = date(2025, 1, 31), date(2025, 2, 28)
    await _flush(
        db,
        _pos(test_user.id, account.id, "VWRA", qty=Decimal("20"), cost=Decimal("3000.00"), acq_date=hist),
        _atom(test_user.id, "VWRA", "Test Investment", qty=Decimal("10"), mv=Decimal("1200.00"), snap_date=hist, sector="Global", geography="World", asset_type="etf", dedup_hash="vwra_hist"),
        _atom(test_user.id, "VWRA", "Test Investment", qty=Decimal("20"), mv=Decimal("3000.00"), snap_date=curr, sector="Global", geography="World", asset_type="etf", dedup_hash="vwra_curr"),
        _pos(test_user.id, account.id, "MSFT", qty=Decimal("5"), cost=Decimal("500.00"), currency="USD", acq_date=hist),
        _atom(test_user.id, "MSFT", "Test Investment", qty=Decimal("5"), mv=Decimal("100.00"), currency="USD", snap_date=hist, dedup_hash="msft_hist_usd"),
        FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=hist, source="test"),
        _pos(test_user.id, account.id, "FALLBACK", qty=Decimal("2"), cost=Decimal("20.00"), acq_date=hist),
        _atom(test_user.id, "FALLBACK", "External Broker", qty=Decimal("2"), mv=Decimal("30.00"), snap_date=hist, dedup_hash="fallback_hist"),
        _pos(test_user.id, account.id, "CLOSED", qty=Decimal("0"), cost=Decimal("0.00"), acq_date=hist, status=PositionStatus.DISPOSED),
        _atom(test_user.id, "CLOSED", "Test Investment", qty=Decimal("0"), mv=Decimal("0.00"), snap_date=hist, dedup_hash="closed_hist"),
        _atom(test_user.id, "UNRECONCILED", "External Broker", qty=Decimal("1"), mv=Decimal("10.00"), snap_date=hist, dedup_hash="unreconciled_hist"),
    )
    active = {h.asset_identifier: h for h in await svc.get_holdings(db, test_user.id, as_of_date=hist, base_currency="SGD")}
    with_disposed = {h.asset_identifier: h for h in await svc.get_holdings(db, test_user.id, as_of_date=hist, include_disposed=True, base_currency="SGD")}
    vwra, msft, fb, closed = active["VWRA"], active["MSFT"], active["FALLBACK"], with_disposed["CLOSED"]
    assert (
        set(active),
        (vwra.quantity, vwra.market_value, vwra.cost_basis, vwra.sector, vwra.asset_type),
        (msft.market_value, msft.cost_basis, msft.currency),
        fb.market_value,
        (closed.status, closed.disposal_date, closed.unrealized_pnl_percent),
    ) == (
        {"VWRA", "MSFT", "FALLBACK"},
        (Decimal("10"), Decimal("1200.00"), Decimal("1200.00"), "Global", "etf"),
        (Decimal("135.00000000"), Decimal("135.00000000"), "SGD"),
        Decimal("30.00"),
        (PositionStatus.DISPOSED, hist, Decimal("0.00")),
    )


async def test_get_holdings_empty_unreconciled_and_disposed(db, test_user, svc, account, atomic_snapshot):
    with pytest.raises(PortfolioNotFoundError):
        await svc.get_holdings(db, test_user.id, base_currency="SGD")
    await _flush(db, _atom(test_user.id, "UNREC", "External", qty=Decimal("1"), mv=Decimal("10.00"), snap_date=date(2025, 1, 31), dedup_hash="unrec_only"))
    with pytest.raises(PortfolioNotFoundError):
        await svc.get_holdings(db, test_user.id, as_of_date=date(2025, 1, 31), base_currency="SGD")
    await _flush(db, _pos(test_user.id, account.id, "AAPL", qty=Decimal("50"), cost=Decimal("5000.00"), acq_days=90, disposal_date=date.today() - timedelta(days=10), status=PositionStatus.DISPOSED))
    with pytest.raises(PortfolioNotFoundError):
        await svc.get_holdings(db, test_user.id, include_disposed=False, base_currency="SGD")
    disposed = await svc.get_holdings(db, test_user.id, include_disposed=True, base_currency="SGD")
    assert (len(disposed), disposed[0].status) == (1, PositionStatus.DISPOSED)


async def test_get_holdings_fx_zero_cost_and_user_isolation(db, test_user, svc, account):
    other_id = (await UserFactory.create_async(db)).id
    await _flush(
        db,
        _pos(test_user.id, account.id, "MSFT", qty=Decimal("50"), cost=Decimal("5000.00"), currency="USD", acq_days=30),
        _atom(test_user.id, "MSFT", "Broker", qty=Decimal("50"), mv=Decimal("6000.00"), currency="USD", dedup_hash="msft_fx_test"),
        FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=date.today(), source="test"),
        FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.30"), rate_date=date.today() - timedelta(days=30), source="test"),
        _pos(test_user.id, account.id, "FREE", qty=Decimal("10"), cost=Decimal("0.00"), acq_days=10, method=CostBasisMethod.AVGCOST),
        _atom(test_user.id, "FREE", "Broker", qty=Decimal("10"), mv=Decimal("500.00"), dedup_hash="free_zero_cost"),
        _pos(test_user.id, account.id, "NOCLASS", qty=Decimal("10"), cost=Decimal("1000.00"), acq_days=10),
        _atom(other_id, "NOCLASS", "B", qty=Decimal("10"), mv=Decimal("1200.00"), dedup_hash="noclass_other_user", sector="Other"),
        MarketDataOverride(user_id=test_user.id, asset_identifier="NOCLASS", price_date=date.today(), price=Decimal("120.00"), currency="SGD", source=PriceSource.MANUAL),
    )
    by_asset = {h.asset_identifier: h for h in await svc.get_holdings(db, test_user.id, base_currency="SGD")}
    msft, free, noclass = by_asset["MSFT"], by_asset["FREE"], by_asset["NOCLASS"]
    assert ((msft.market_value, msft.cost_basis, msft.currency), free.unrealized_pnl_percent, (noclass.asset_type, noclass.sector, noclass.geography)) == ((Decimal("8100.00"), Decimal("6500.00"), "SGD"), Decimal("0.00"), (None, None, None))


async def test_get_portfolio_summary_cases(db, test_user, svc, account):
    await _flush(
        db,
        _pos(test_user.id, account.id, "GIFT", qty=Decimal("5"), cost=Decimal("0.00"), acq_days=30, method=CostBasisMethod.AVGCOST),
        _atom(test_user.id, "GIFT", "B", qty=Decimal("5"), mv=Decimal("250.00"), dedup_hash="gift_unrealized"),
    )
    zero_summary = await svc.get_portfolio_summary(db, test_user.id, base_currency="SGD")
    assert (
        zero_summary.total_market_value,
        zero_summary.total_cost_basis,
        zero_summary.total_unrealized_pnl,
        zero_summary.net_pnl,
        zero_summary.net_pnl_percent,
    ) == (Decimal("250.00"), Decimal("0.00"), Decimal("250.00"), Decimal("250.00"), Decimal("0.00"))
    await _flush(
        db,
        _pos(test_user.id, account.id, "NVDA", qty=Decimal("10"), cost=Decimal("2000.00"), currency="USD", acq_days=45),
        _atom(test_user.id, "NVDA", "B", qty=Decimal("10"), mv=Decimal("2500.00"), currency="USD", dedup_hash="nvda_unrealized_fx"),
        FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=date.today(), source="test"),
        FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.30"), rate_date=date.today() - timedelta(days=45), source="test"),
        _pos(test_user.id, account.id, "MSFT", qty=Decimal("50"), cost=Decimal("5000.00"), acq_days=120, disposal_date=date.today() - timedelta(days=10), status=PositionStatus.DISPOSED),
        _atom(test_user.id, "MSFT", "Test Broker", qty=Decimal("50"), mv=Decimal("5500.00"), sector="Technology", geography="US", asset_type="stock", dedup_hash="msft_disposed_summary"),
    )
    summary = await svc.get_portfolio_summary(db, test_user.id, base_currency="SGD")
    assert (
        summary.active_positions_count,
        summary.disposed_positions_count,
        summary.holdings_count,
        summary.currency,
        summary.total_market_value,
        summary.total_cost_basis,
        summary.total_unrealized_pnl,
        summary.total_realized_pnl,
        summary.net_pnl,
        summary.net_pnl_percent,
    ) == (2, 1, 3, "SGD", Decimal("3625.00"), Decimal("2600.00"), Decimal("1025.00"), Decimal("0"), Decimal("1025.00"), Decimal("39.42"))


async def test_get_latest_price_and_atomic_helpers(db, test_user, svc, active_position, account):
    with pytest.raises(AssetNotFoundError):
        await svc._get_latest_price(db, active_position, date.today(), test_user.id)
    zero_pos = _pos(test_user.id, account.id, "ZERO_Q")
    await _flush(
        db,
        zero_pos,
        _atom(test_user.id, "ZERO_Q", "B", qty=Decimal("0"), mv=Decimal("999.00"), dedup_hash="zero_q_snap"),
        _atom(test_user.id, "AAPL", "B", qty=Decimal("100"), mv=Decimal("12000.00"), dedup_hash="aapl_normal"),
    )
    zero_price = await svc._get_latest_price(db, zero_pos, date.today(), test_user.id)
    atomic_price = await svc._get_latest_price(db, active_position, date.today(), test_user.id)
    await _flush(db, MarketDataOverride(user_id=test_user.id, asset_identifier="AAPL", price_date=date.today(), price=Decimal("200.00"), currency="SGD", source=PriceSource.MANUAL))
    override_price = await svc._get_latest_price(db, active_position, date.today(), test_user.id)
    await _flush(
        db,
        _atom(test_user.id, "TEST", "B", qty=Decimal("10"), mv=Decimal("100.00"), snap_date=date.today() - timedelta(days=30), sector="Old", dedup_hash="test_old"),
        _atom(test_user.id, "TEST", "B", qty=Decimal("10"), mv=Decimal("200.00"), sector="New", dedup_hash="test_new"),
    )
    latest = await svc._get_latest_atomic(db, "TEST", test_user.id)
    missing = await svc._get_latest_atomic(db, "NOPE", test_user.id)
    assert (zero_price, atomic_price, override_price, latest.sector, missing) == (Decimal("999.00"), Decimal("120"), Decimal("200.00"), "New", None)
