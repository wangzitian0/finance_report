from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.pricing import record_override


@pytest.fixture
async def position_for_override(db: AsyncSession, test_user):
    account = Account(user_id=test_user.id, name="Test Investment", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    pos = ManagedPosition(user_id=test_user.id, account_id=account.id, asset_identifier="AAPL", quantity=Decimal("100"), cost_basis=Decimal("10000.00"), currency="SGD", acquisition_date=date.today() - timedelta(days=30), status=PositionStatus.ACTIVE, cost_basis_method=CostBasisMethod.FIFO)
    db.add(pos)
    await db.commit()
    return pos


async def test_price_overrides_record_and_endpoint_batch_validation(client: AsyncClient, db: AsyncSession, test_user, position_for_override):
    obs = await record_override(db, test_user.id, asset_identifier="AAPL", as_of=date.today(), price=Decimal("155.00"), currency="SGD")
    db.add(ManagedPosition(user_id=test_user.id, account_id=position_for_override.account_id, asset_identifier="GOOGL", quantity=Decimal("10"), cost_basis=Decimal("1400.00"), currency="SGD", acquisition_date=date.today() - timedelta(days=30), status=PositionStatus.ACTIVE, cost_basis_method=CostBasisMethod.FIFO))
    await db.commit()
    today_iso = date.today().isoformat()
    mixed = await client.post("/pricing/price-overrides", json={"updates": [{"asset_identifier": "AAPL", "price": "155.50", "currency": "SGD", "price_date": today_iso}, {"asset_identifier": "NOPE", "price": "99.00", "currency": "SGD", "price_date": today_iso}]})
    batch = await client.post("/pricing/price-overrides", json={"updates": [{"asset_identifier": "AAPL", "price": "155.50", "currency": "SGD", "price_date": today_iso}, {"asset_identifier": "GOOGL", "price": "140.25", "currency": "SGD", "price_date": today_iso}]})
    invalid = await client.post("/pricing/price-overrides", json={"updates": [{"asset_identifier": "AAPL"}]})
    m_data = mixed.json()
    assert (
        (obs.value, obs.observed_at is not None),
        (mixed.status_code, m_data["updated_count"], m_data["results"][0]["success"], m_data["results"][0]["price"], m_data["results"][1]["success"], "not found" in m_data["results"][1]["message"]),
        (batch.status_code, batch.json()["updated_count"], invalid.status_code),
    ) == ((Decimal("155.00"), True), (200, 2, True, "155.50", False, True), (200, 2, 422))
