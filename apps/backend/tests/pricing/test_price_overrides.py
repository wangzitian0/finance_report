from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.ledger import Account, AccountType
from src.pricing import record_override


@pytest.fixture
async def position_for_override(db: AsyncSession, test_user):
    account = Account(user_id=test_user.id, name="Test Investment", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    pos = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="AAPL",
        quantity=Decimal("100"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=30),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(pos)
    await db.commit()
    return pos


async def test_update_prices_happy(db: AsyncSession, test_user, position_for_override):
    obs = await record_override(
        db,
        test_user.id,
        asset_identifier="AAPL",
        as_of=date.today(),
        price=Decimal("155.00"),
        currency="SGD",
    )
    await db.commit()
    assert obs.value == Decimal("155.00")
    assert obs.observed_at is not None


async def test_create_price_overrides_endpoint(client: AsyncClient, position_for_override):
    payload = {
        "updates": [
            {
                "asset_identifier": "AAPL",
                "price": "155.50",
                "currency": "SGD",
                "price_date": date.today().isoformat(),
            },
            {
                "asset_identifier": "NOPE",
                "price": "99.00",
                "currency": "SGD",
                "price_date": date.today().isoformat(),
            },
        ]
    }
    response = await client.post("/pricing/price-overrides", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["updated_count"] == 2
    assert data["results"][0]["success"] is True
    assert data["results"][0]["price"] == "155.50"
    assert data["results"][1]["success"] is False
    assert "not found" in data["results"][1]["message"]


async def test_create_price_overrides_batch_and_validation(client: AsyncClient, db: AsyncSession, test_user, position_for_override):
    db.add(
        ManagedPosition(
            user_id=test_user.id,
            account_id=position_for_override.account_id,
            asset_identifier="GOOGL",
            quantity=Decimal("10"),
            cost_basis=Decimal("1400.00"),
            currency="SGD",
            acquisition_date=date.today() - timedelta(days=30),
            status=PositionStatus.ACTIVE,
            cost_basis_method=CostBasisMethod.FIFO,
        )
    )
    await db.commit()
    payload = {
        "updates": [
            {"asset_identifier": "AAPL", "price": "155.50", "currency": "SGD", "price_date": date.today().isoformat()},
            {"asset_identifier": "GOOGL", "price": "140.25", "currency": "SGD", "price_date": date.today().isoformat()},
        ]
    }
    response = await client.post("/pricing/price-overrides", json=payload)
    assert response.status_code == 200
    assert response.json()["updated_count"] == 2

    invalid_response = await client.post("/pricing/price-overrides", json={"updates": [{"asset_identifier": "AAPL"}]})
    assert invalid_response.status_code == 422
