from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.audit import DataProvenance
from src.pricing import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ValuationComponentItem,
    ValuationService,
    record_manual_valuation,
)
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.schemas.pricing import ManualValuationSnapshotCreate


async def test_create_manual_valuation_snapshot_crud_api(client):
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
    create_response = await client.post("/pricing/manual-valuations", json=payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["component_type"] == "property_value"
    assert created["liquidity_class"] == "illiquid"
    assert created["value"] == "1250000.99"
    assert created["provenance"] == "manual"
    assert created["created_at"]
    assert created["updated_at"]

    list_response = await client.get("/pricing/manual-valuations")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == created["id"]
    assert listed["items"][0]["provenance"] == "manual"

    # Append-only correction via POST on the same (component_type, source, as_of_date) identity
    corrected_response = await client.post(
        "/pricing/manual-valuations",
        json={**payload, "value": "1260000.10", "notes": "Updated valuation"},
    )
    assert corrected_response.status_code == 201
    updated = corrected_response.json()
    assert updated["value"] == "1260000.10"
    assert updated["notes"] == "Updated valuation"
    assert updated["id"] != created["id"]

    # Retired single-snapshot PATCH/DELETE/GET endpoints must not resolve
    assert (await client.patch(f"/assets/valuation-snapshots/{updated['id']}", json={"value": "1.00"})).status_code == 404
    assert (await client.delete(f"/assets/valuation-snapshots/{updated['id']}")).status_code == 404
    assert (await client.get(f"/assets/valuation-snapshots/{updated['id']}")).status_code == 404

    current_list = await client.get("/pricing/manual-valuations")
    assert current_list.status_code == 200
    assert current_list.json()["total"] == 1
    assert current_list.json()["items"][0]["id"] == updated["id"]


async def test_manual_valuation_snapshot_filter_and_default_liquidity(client):
    property_payload = {
        "component_type": "property_value",
        "as_of_date": "2026-05-18",
        "value": "1250000.00",
        "currency": "sgd",
        "source": "manual appraisal",
    }
    tax_payload = {
        "component_type": "tax_refund",
        "as_of_date": "2026-05-19",
        "value": "1200.00",
        "currency": "SGD",
        "source": "IRAS",
    }
    property_response = await client.post("/pricing/manual-valuations", json=property_payload)
    tax_response = await client.post("/pricing/manual-valuations", json=tax_payload)
    assert property_response.status_code == 201
    assert tax_response.status_code == 201
    assert property_response.json()["currency"] == "SGD"

    filtered_response = await client.get(
        "/pricing/manual-valuations", params={"component_type": "property_value", "as_of_date": "2026-05-18"}
    )
    assert filtered_response.status_code == 200
    filtered = filtered_response.json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["component_type"] == "property_value"


async def test_manual_valuation_snapshot_errors(client):
    invalid_filter_response = await client.get("/pricing/manual-valuations", params={"component_type": "unsupported"})
    assert invalid_filter_response.status_code == 400


async def test_manual_valuation_components_api_returns_latest_as_of_values(client):
    old_property = {
        "component_type": "property_value",
        "as_of_date": "2026-01-31",
        "value": "1000000.01",
        "currency": "SGD",
        "source": "appraisal",
    }
    new_property = {**old_property, "as_of_date": "2026-05-18", "value": "1000000.02"}
    mortgage = {
        "component_type": "mortgage_balance",
        "as_of_date": "2026-05-18",
        "value": "300000.03",
        "currency": "SGD",
        "source": "bank portal",
    }
    assert (await client.post("/pricing/manual-valuations", json=old_property)).status_code == 201
    assert (await client.post("/pricing/manual-valuations", json=new_property)).status_code == 201
    assert (await client.post("/pricing/manual-valuations", json=mortgage)).status_code == 201
    response = await client.get("/pricing/valuation-components", params={"as_of_date": "2026-05-18"})
    assert response.status_code == 200
    data = response.json()
    assert data["total_assets"] == "1000000.02"
    assert data["total_liabilities"] == "300000.03"
    assert data["net_worth_delta"] == "699999.99"
    assert {item["component_type"] for item in data["items"]} == {"property_value", "mortgage_balance"}
    assert {item["provenance"] for item in data["items"]} == {"manual"}


@pytest.mark.no_db
def test_AC22_13_1_valuation_component_item_uses_normalized_provenance_type() -> None:
    assert ValuationComponentItem.__dataclass_fields__["provenance"].type == DataProvenance


class _HeadQueryIssued(Exception):
    pass


@pytest.mark.no_db
async def test_AC11_19_1_current_valuation_head_query_takes_row_lock() -> None:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=_HeadQueryIssued)
    with pytest.raises(_HeadQueryIssued):
        await record_manual_valuation(
            db,
            uuid4(),
            component_type=ManualValuationComponentType.PROPERTY_VALUE,
            liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
            as_of=date(2026, 5, 18),
            value=Decimal("1000000.00"),
            currency="SGD",
            source="manual appraisal",
        )
    statement = db.execute.await_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled


async def test_manual_valuation_snapshot_router_rolls_back_on_service_errors(client, monkeypatch):
    from src.routers import pricing as pricing_router

    async def raise_on_create(*args, **kwargs):
        raise RuntimeError("create failed")

    monkeypatch.setattr(pricing_router._valuations, "create_valuation_snapshot", raise_on_create)
    create_response = await client.post(
        "/pricing/manual-valuations",
        json={
            "component_type": "property_value",
            "as_of_date": "2026-05-18",
            "value": "1.00",
            "currency": "SGD",
            "source": "manual",
        },
    )
    assert create_response.status_code == 500


async def test_AC11_19_1_manual_valuation_correction_appends_version_and_preserves_history(db, test_user):
    service = ValuationService()
    identity = dict(
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=date(2026, 5, 18),
        source="manual appraisal",
    )
    first = await service.create_valuation_snapshot(
        db, user_id=test_user.id, value=Decimal("1000000.00"), currency="SGD", **identity
    )
    corrected = await service.create_valuation_snapshot(
        db, user_id=test_user.id, value=Decimal("1100000.00"), currency="USD", **identity
    )
    await db.commit()
    await db.refresh(first)
    assert first.value == Decimal("1000000.00"), "prior fact must not be edited in place"
    assert first.version == 1
    assert first.superseded_by_id == corrected.id
    assert corrected.value == Decimal("1100000.00")
    assert corrected.currency == "USD"
    assert corrected.version == 2
    assert corrected.superseded_by_id is None
    history = (
        (
            await db.execute(
                select(ManualValuationSnapshot)
                .where(ManualValuationSnapshot.user_id == test_user.id)
                .where(ManualValuationSnapshot.component_type == identity["component_type"])
                .where(ManualValuationSnapshot.source == identity["source"])
                .where(ManualValuationSnapshot.as_of_date == identity["as_of_date"])
                .order_by(ManualValuationSnapshot.version.desc())
            )
        )
        .scalars()
        .all()
    )
    assert [(h.version, h.value) for h in history] == [(2, Decimal("1100000.00")), (1, Decimal("1000000.00"))]


async def test_AC11_19_2_corrected_valuation_is_not_double_counted_in_net_worth(db, test_user):
    service = ValuationService()
    key = dict(
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=date(2026, 5, 18),
        currency="SGD",
        source="manual appraisal",
    )
    await service.create_valuation_snapshot(db, user_id=test_user.id, value=Decimal("1000000.00"), **key)
    await service.create_valuation_snapshot(db, user_id=test_user.id, value=Decimal("1100000.00"), **key)
    await db.commit()
    components = await service.get_latest_valuation_components(db, test_user.id, as_of_date=date(2026, 5, 18))
    assert components.total_assets == Decimal("1100000.00"), "superseded version must be excluded"
    snapshots, total = await service.list_valuation_snapshots(db, test_user.id)
    assert total == 1, "list returns only current heads"
    assert snapshots[0].value == Decimal("1100000.00")


def test_manual_valuation_snapshot_schema_normalizes_currency():
    create_payload = ManualValuationSnapshotCreate(
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=date(2026, 5, 18),
        value=Decimal("1.23"),
        currency="sgd",
        source="manual",
    )
    assert create_payload.currency == "SGD"


async def test_manual_valuation_snapshot_latest_net_worth_components(db, test_user):
    service = ValuationService()
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


async def test_manual_valuation_snapshot_restricted_toggle(db, test_user):
    service = ValuationService()
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
        db, test_user.id, as_of_date=date(2026, 5, 18), include_restricted=True
    )
    liquid_only = await service.get_latest_valuation_components(
        db, test_user.id, as_of_date=date(2026, 5, 18), include_restricted=False
    )
    assert all_components.total_assets == Decimal("51200.00")
    assert liquid_only.total_assets == Decimal("1200.00")
    assert {item.component_type for item in all_components.items} == {"cpf_balance", "tax_refund"}
