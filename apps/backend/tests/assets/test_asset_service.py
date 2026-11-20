from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.extraction.orm.layer2 import AtomicPosition
from src.ledger import Account
from src.portfolio import PositionService, PositionServiceError
from src.portfolio.orm.portfolio import ManagedPosition, PositionStatus


async def _fetch_positions(db, user_id, *, status_filter=None):
    query = select(ManagedPosition).where(ManagedPosition.user_id == user_id).order_by(ManagedPosition.asset_identifier)
    if status_filter is not None:
        query = query.where(ManagedPosition.status == status_filter)
    rows = list((await db.execute(query)).scalars().all())
    return rows, len(rows)


def _snap(user_id, asset="AAPL", qty="10.0", mv="1500.00", snap_date=date(2024, 1, 15), broker="Moomoo", currency="USD", dedup=None) -> AtomicPosition:
    return AtomicPosition(
        user_id=user_id,
        snapshot_date=snap_date,
        asset_identifier=asset,
        broker=broker,
        quantity=Decimal(qty),
        market_value=Decimal(mv),
        currency=currency,
        dedup_hash=dedup or f"{asset}_{snap_date}_{broker}_{qty}",
        source_documents={},
    )


async def _reconcile(db, user_id, *snaps, status_filter=None):
    db.add_all(snaps)
    await db.flush()
    result = await PositionService().reconcile_positions(db, user_id)
    positions, total = await _fetch_positions(db, user_id, status_filter=status_filter)
    return result, positions, total


class TestPositionService:
    async def test_reconcile_lifecycle_create_update_dispose_and_reactivate(self, db, test_user):
        r0, empty, total0 = await _reconcile(db, test_user.id)
        _, created, total1 = await _reconcile(db, test_user.id, _snap(test_user.id))
        created_state = (len(created), total1, created[0].asset_identifier, created[0].quantity, created[0].status, await db.scalar(select(Account.name).where(Account.id == created[0].account_id)))
        _, updated, _ = await _reconcile(db, test_user.id, _snap(test_user.id, qty="15.0", mv="2250.00", snap_date=date(2024, 1, 16)))
        updated_state = (len(updated), updated[0].quantity)
        disp_res, active_after_disp, active_count = await _reconcile(db, test_user.id, _snap(test_user.id, qty="0.0", mv="0.00", snap_date=date(2024, 1, 17)), status_filter=PositionStatus.ACTIVE)
        disposed_row = (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == test_user.id))).scalar_one()
        disposed_state = (disp_res.disposed, disp_res.updated, len(active_after_disp), active_count, disposed_row.status, disposed_row.disposal_date)
        _, reactivated, _ = await _reconcile(db, test_user.id, _snap(test_user.id, qty="5.0", mv="800.00", snap_date=date(2024, 1, 18)))
        assert ((empty, total0, r0.created), created_state, updated_state, disposed_state, (len(reactivated), reactivated[0].status, reactivated[0].quantity, reactivated[0].disposal_date)) == (([], 0, 0), (1, 1, "AAPL", Decimal("10.0"), PositionStatus.ACTIVE, "Moomoo"), (1, Decimal("15.0")), (1, 0, 0, 0, PositionStatus.DISPOSED, date(2024, 1, 17)), (1, PositionStatus.ACTIVE, Decimal("5.0"), None))

    async def test_reconcile_multi_asset_multi_broker_null_broker_and_short_stores_no_cost(self, db, test_user):
        _, positions, _ = await _reconcile(
            db,
            test_user.id,
            _snap(test_user.id, "TSLA", qty="5.0", mv="1250.00", broker="Interactive Brokers", dedup="h_tsla"),
            _snap(test_user.id, "AAPL", qty="10.0", mv="1500.00", broker="Moomoo", dedup="h_aapl_m"),
            _snap(test_user.id, "AAPL", qty="20.0", mv="3000.00", broker="Interactive Brokers", dedup="h_aapl_ib"),
            _snap(test_user.id, "GOOGL", qty="5.0", mv="700.00", broker="Moomoo", dedup="h_googl"),
            _snap(test_user.id, "BTC", qty="0.5", mv="25000.00", broker=None, dedup="h_btc"),
            _snap(test_user.id, "SHORT", qty="-10.0", mv="1500.00", broker="Moomoo", dedup="h_short"),
        )
        by_key = {(p.asset_identifier, await db.scalar(select(Account.name).where(Account.id == p.account_id))): p for p in positions}
        assert (
            len(positions),
            by_key[("TSLA", "Interactive Brokers")].cost_basis,
            {name for asset, name in by_key if asset == "AAPL"},
            by_key[("BTC", "Unknown Broker")].quantity,
            (by_key[("SHORT", "Moomoo")].quantity, by_key[("SHORT", "Moomoo")].status),
        ) == (6, None, {"Moomoo", "Interactive Brokers"}, Decimal("0.5"), (Decimal("-10.0"), PositionStatus.ACTIVE))

    async def test_reconcile_positions_skips_snapshot_with_null_fields(self, test_user):
        broken = SimpleNamespace(id=uuid4(), asset_identifier="BROKEN-ASSET", quantity=None, market_value=Decimal("100.00"), broker="Moomoo", currency="USD", snapshot_date=date(2024, 1, 1))
        query_result = MagicMock()
        query_result.scalars.return_value.all.return_value = [broken]
        db = AsyncMock()
        db.execute.return_value = query_result
        result = await PositionService().reconcile_positions(db, test_user.id)
        assert (result.skipped, result.skipped_assets) == (1, ["BROKEN-ASSET"])
        db.flush.assert_awaited_once()

    async def test_AC_portfolio_brokerage_import_13_reconcile_normalizes_cnh_and_rejects_invalid_currency(self, db, test_user):
        res, positions, _ = await _reconcile(db, test_user.id, _snap(test_user.id, "BABA", qty="10.0", mv="7200.00", snap_date=date(2026, 1, 15), broker="Futu", currency="CNH", dedup="hash_cnh"))
        acct = await db.get(Account, positions[0].account_id)
        assert (res.created, len(positions), positions[0].asset_identifier, positions[0].currency, acct.currency) == (1, 1, "BABA", "CNY", "CNY")
        db.add(_snap(test_user.id, "BADCCY", qty="5.0", mv="100.00", snap_date=date(2026, 1, 16), broker="Futu", currency="XYZ", dedup="hash_xyz"))
        await db.flush()
        with pytest.raises(PositionServiceError, match="XYZ"):
            await PositionService().reconcile_positions(db, test_user.id)
