"""Tests for manual valuation snapshots."""

from datetime import date
from decimal import Decimal

import pytest

from src.models.layer3 import ManualValuationComponentType
from src.services.assets import AssetService


@pytest.mark.asyncio
async def test_create_manual_valuation_snapshot_crud_api(client):
    """AC11.9.1: Manual valuation snapshots support audited CRUD endpoints."""
    payload = {
        "component_type": "property_value",
        "as_of_date": "2026-05-18",
        "value": "1250000.99",
        "currency": "SGD",
        "source": "manual appraisal",
        "notes": "May checkpoint",
        "recurrence_days": 90,
        "reminder_date": "2026-08-16",
    }

    create_response = await client.post("/assets/valuation-snapshots", json=payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["component_type"] == "property_value"
    assert created["liquidity_class"] == "illiquid"
    assert created["value"] == "1250000.99"
    assert created["created_at"]
    assert created["updated_at"]

    list_response = await client.get("/assets/valuation-snapshots")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == created["id"]

    update_response = await client.patch(
        f"/assets/valuation-snapshots/{created['id']}",
        json={"value": "1260000.10", "notes": "Updated valuation"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["value"] == "1260000.10"
    assert updated["notes"] == "Updated valuation"

    delete_response = await client.delete(f"/assets/valuation-snapshots/{created['id']}")
    assert delete_response.status_code == 204

    empty_response = await client.get("/assets/valuation-snapshots")
    assert empty_response.status_code == 200
    assert empty_response.json()["total"] == 0


@pytest.mark.asyncio
async def test_manual_valuation_snapshot_latest_net_worth_components(db, test_user):
    """AC11.9.2: Latest manual snapshots feed net worth components without float arithmetic."""
    service = AssetService()

    await service.create_valuation_snapshot(
        db,
        user_id=test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=date(2026, 1, 31),
        value=Decimal("1000000.01"),
        currency="SGD",
        source="appraisal",
    )
    await service.create_valuation_snapshot(
        db,
        user_id=test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=date(2026, 5, 18),
        value=Decimal("1000000.02"),
        currency="SGD",
        source="appraisal",
    )
    await service.create_valuation_snapshot(
        db,
        user_id=test_user.id,
        component_type=ManualValuationComponentType.MORTGAGE_BALANCE,
        as_of_date=date(2026, 5, 18),
        value=Decimal("300000.03"),
        currency="SGD",
        source="bank portal",
    )
    await db.commit()

    components = await service.get_latest_valuation_components(db, test_user.id, as_of_date=date(2026, 5, 18))

    assert components.total_assets == Decimal("1000000.02")
    assert components.total_liabilities == Decimal("300000.03")
    assert components.net_worth_delta == Decimal("699999.99")
    assert components.items[0].value == Decimal("1000000.02")
    assert components.items[1].liquidity_class == "liability"


@pytest.mark.asyncio
async def test_manual_valuation_snapshot_restricted_toggle(db, test_user):
    """AC11.9.3: Restricted/illiquid values can be excluded from liquid net worth views."""
    service = AssetService()

    await service.create_valuation_snapshot(
        db,
        user_id=test_user.id,
        component_type=ManualValuationComponentType.CPF_BALANCE,
        as_of_date=date(2026, 5, 18),
        value=Decimal("50000.00"),
        currency="SGD",
        source="CPF portal",
    )
    await service.create_valuation_snapshot(
        db,
        user_id=test_user.id,
        component_type=ManualValuationComponentType.TAX_REFUND,
        as_of_date=date(2026, 5, 18),
        value=Decimal("1200.00"),
        currency="SGD",
        source="IRAS",
    )
    await db.commit()

    all_components = await service.get_latest_valuation_components(
        db,
        test_user.id,
        as_of_date=date(2026, 5, 18),
        include_restricted=True,
    )
    liquid_only = await service.get_latest_valuation_components(
        db,
        test_user.id,
        as_of_date=date(2026, 5, 18),
        include_restricted=False,
    )

    assert all_components.total_assets == Decimal("51200.00")
    assert liquid_only.total_assets == Decimal("1200.00")
    assert {item.component_type for item in all_components.items} == {"cpf_balance", "tax_refund"}
