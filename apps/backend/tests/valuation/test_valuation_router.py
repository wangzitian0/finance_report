"""AC11.8 / P0 #388: valuation snapshot API tests."""

from decimal import Decimal

import pytest


@pytest.mark.asyncio
async def test_create_manual_property_valuation_snapshot(client):
    """P0 #388: manual valuation snapshots capture value, source, freshness."""
    payload = {
        "component_type": "property",
        "component_name": "Singapore Condo",
        "side": "asset",
        "value": "1200000.00",
        "currency": "SGD",
        "as_of_date": "2026-05-18",
        "source": "manual",
        "confidence": "trusted",
        "stale_after_days": 90,
        "include_in_total_net_worth": True,
        "include_in_liquid_net_worth": False,
        "notes": "Quarterly estimate",
    }

    response = await client.post("/valuations/snapshots", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["component_type"] == "property"
    assert data["component_name"] == "Singapore Condo"
    assert data["side"] == "asset"
    assert data["value"] == "1200000.00"
    assert data["currency"] == "SGD"
    assert data["source"] == "manual"
    assert data["confidence"] == "trusted"
    assert data["freshness"] == "fresh"


@pytest.mark.asyncio
async def test_latest_components_return_only_latest_as_of_snapshot(client):
    """P0 #388: latest component view is as-of-date aware."""
    old_payload = {
        "component_type": "insurance_cash_value",
        "component_name": "Whole Life Policy",
        "side": "asset",
        "value": "10000.00",
        "currency": "SGD",
        "as_of_date": "2026-01-01",
        "stale_after_days": 30,
    }
    new_payload = {
        **old_payload,
        "value": "10500.00",
        "as_of_date": "2026-05-01",
    }
    mortgage_payload = {
        "component_type": "mortgage",
        "component_name": "Home Loan",
        "side": "liability",
        "value": "600000.00",
        "currency": "SGD",
        "as_of_date": "2026-04-30",
        "stale_after_days": 31,
    }

    assert (await client.post("/valuations/snapshots", json=old_payload)).status_code == 201
    assert (await client.post("/valuations/snapshots", json=new_payload)).status_code == 201
    assert (await client.post("/valuations/snapshots", json=mortgage_payload)).status_code == 201

    response = await client.get("/valuations/components?as_of_date=2026-05-18")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    by_name = {item["component_name"]: item for item in data["items"]}
    assert by_name["Whole Life Policy"]["value"] == "10500.00"
    assert by_name["Whole Life Policy"]["freshness"] == "fresh"
    assert by_name["Home Loan"]["side"] == "liability"


@pytest.mark.asyncio
async def test_stale_component_marks_freshness_against_reference_date(client):
    """P0 #388: stale_after_days makes stale valuation explicit."""
    payload = {
        "component_type": "cpf_or_long_term_savings",
        "component_name": "CPF OA",
        "side": "asset",
        "value": "50000.00",
        "currency": "SGD",
        "as_of_date": "2026-01-01",
        "stale_after_days": 30,
        "include_in_liquid_net_worth": False,
    }
    await client.post("/valuations/snapshots", json=payload)

    response = await client.get("/valuations/components?as_of_date=2026-05-18")

    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["freshness"] == "stale"


@pytest.mark.asyncio
async def test_valuation_snapshot_values_are_decimal_backed(client, db, test_user):
    """P0 #388: valuation monetary fields preserve Decimal precision."""
    payload = {
        "component_type": "tax_payable_or_refund",
        "component_name": "IRAS payable",
        "side": "liability",
        "value": "1234.56",
        "currency": "SGD",
        "as_of_date": "2026-05-18",
    }
    response = await client.post("/valuations/snapshots", json=payload)
    assert response.status_code == 201

    from sqlalchemy import select

    from src.models import ValuationSnapshot

    result = await db.execute(select(ValuationSnapshot).where(ValuationSnapshot.user_id == test_user.id))
    snapshot = result.scalar_one()
    assert isinstance(snapshot.value, Decimal)
    assert snapshot.value == Decimal("1234.56")


@pytest.mark.asyncio
async def test_valuation_snapshots_require_auth(public_client):
    """P0 #388: valuation endpoints are user-owned."""
    response = await public_client.get("/valuations/components")
    assert response.status_code == 401
