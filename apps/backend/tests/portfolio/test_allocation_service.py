from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicPosition
from src.ledger import Account, AccountType
from src.portfolio import get_asset_class_allocation, get_geography_allocation, get_sector_allocation
from src.portfolio.extension.allocation import _build_allocation
from src.portfolio.extension.holdings import _account_names_by_id
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus


@pytest.mark.parametrize("getter", [get_sector_allocation, get_geography_allocation, get_asset_class_allocation])
async def test_allocation_empty_and_with_positions(db: AsyncSession, test_user, getter):
    assert await getter(db, test_user.id, base_currency="SGD") == []
    acct = Account(user_id=test_user.id, name="Test Broker", type=AccountType.ASSET, currency="SGD")
    db.add(acct)
    await db.flush()
    for asset, qty, cost, mv, sector, acq in (("AAPL", "100", "15000.00", "17000.00", "Technology", date(2023, 1, 1)), ("JPM", "50", "7500.00", "8500.00", "Financials", date(2023, 6, 1))):
        db.add_all([
            ManagedPosition(user_id=test_user.id, account_id=acct.id, asset_identifier=asset, quantity=Decimal(qty), cost_basis=Decimal(cost), currency="SGD", acquisition_date=acq, status=PositionStatus.ACTIVE, cost_basis_method=CostBasisMethod.FIFO),
            AtomicPosition(user_id=test_user.id, snapshot_date=date.today(), asset_identifier=asset, broker="Test Broker", quantity=Decimal(qty), market_value=Decimal(mv), currency="SGD", sector=sector, geography="US", asset_type="stock", dedup_hash=f"{asset}_alloc_hash", source_documents={}),
        ])
    await db.flush()
    result = await getter(db, test_user.id, base_currency="SGD")
    assert len(result) > 0 and all(hasattr(item, attr) for item in result for attr in ("category", "value", "percentage", "count"))


@pytest.mark.no_db
async def test_account_names_lookup_short_circuit_and_build_allocation():
    class _ExplodingSession:
        def __getattr__(self, name: str) -> None:
            raise AssertionError(f"empty-input guard must not touch the session (accessed .{name})")

    assert await _account_names_by_id(_ExplodingSession(), uuid4(), set()) == {}
    zero = _build_allocation([(object(), Decimal("0")), (object(), Decimal("0"))], key_fn=lambda _a: "cash")
    cats = iter(["a", "b", "b"])
    shares = {b.category: b.percentage for b in _build_allocation([(object(), Decimal("25")), (object(), Decimal("50")), (object(), Decimal("25"))], key_fn=lambda _a: next(cats))}
    assert (len(zero), zero[0].percentage, zero[0].count, shares) == (1, Decimal("0"), 2, {"a": Decimal("25"), "b": Decimal("75")})
