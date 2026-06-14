"""Tests for manual valuation snapshots."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from src.models.layer3 import ManualValuationComponentType, ManualValuationLiquidityClass
from src.schemas.assets import ManualValuationSnapshotCreate, ManualValuationSnapshotUpdate
from src.schemas.provenance import DataProvenance
from src.services.assets import AssetService, AssetServiceError, ValuationComponentItem


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
    assert created["provenance"] == "manual"
    assert created["created_at"]
    assert created["updated_at"]

    list_response = await client.get("/assets/valuation-snapshots")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == created["id"]
    assert listed["items"][0]["provenance"] == "manual"

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


async def test_manual_valuation_snapshot_filter_detail_and_default_liquidity_update(client):
    """AC11.9.1: Valuation APIs support filtering, detail reads, and default liquidity updates."""
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

    property_response = await client.post("/assets/valuation-snapshots", json=property_payload)
    tax_response = await client.post("/assets/valuation-snapshots", json=tax_payload)
    assert property_response.status_code == 201
    assert tax_response.status_code == 201

    created = property_response.json()
    detail_response = await client.get(f"/assets/valuation-snapshots/{created['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["currency"] == "SGD"

    filtered_response = await client.get(
        "/assets/valuation-snapshots",
        params={"component_type": "property_value", "as_of_date": "2026-05-18"},
    )
    assert filtered_response.status_code == 200
    filtered = filtered_response.json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["component_type"] == "property_value"

    update_response = await client.patch(
        f"/assets/valuation-snapshots/{created['id']}",
        json={"component_type": "tax_payable", "notes": None},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["component_type"] == "tax_payable"
    assert updated["liquidity_class"] == "liability"
    assert updated["notes"] is None


async def test_manual_valuation_snapshot_errors(client):
    """AC11.9.1: Valuation APIs return typed errors for bad filters and missing snapshots."""
    missing_id = uuid4()

    invalid_filter_response = await client.get(
        "/assets/valuation-snapshots",
        params={"component_type": "unsupported"},
    )
    assert invalid_filter_response.status_code == 400

    get_response = await client.get(f"/assets/valuation-snapshots/{missing_id}")
    assert get_response.status_code == 404

    patch_response = await client.patch(
        f"/assets/valuation-snapshots/{missing_id}",
        json={"value": "1.00"},
    )
    assert patch_response.status_code == 404

    delete_response = await client.delete(f"/assets/valuation-snapshots/{missing_id}")
    assert delete_response.status_code == 404


async def test_manual_valuation_components_api_returns_latest_as_of_values(client):
    """AC11.9.2 AC22.13.1: Latest valuation components expose manual provenance."""
    old_property = {
        "component_type": "property_value",
        "as_of_date": "2026-01-31",
        "value": "1000000.01",
        "currency": "SGD",
        "source": "appraisal",
    }
    new_property = {
        **old_property,
        "as_of_date": "2026-05-18",
        "value": "1000000.02",
    }
    mortgage = {
        "component_type": "mortgage_balance",
        "as_of_date": "2026-05-18",
        "value": "300000.03",
        "currency": "SGD",
        "source": "bank portal",
    }

    assert (await client.post("/assets/valuation-snapshots", json=old_property)).status_code == 201
    assert (await client.post("/assets/valuation-snapshots", json=new_property)).status_code == 201
    assert (await client.post("/assets/valuation-snapshots", json=mortgage)).status_code == 201

    response = await client.get("/assets/valuation-components", params={"as_of_date": "2026-05-18"})

    assert response.status_code == 200
    data = response.json()
    assert data["total_assets"] == "1000000.02"
    assert data["total_liabilities"] == "300000.03"
    assert data["net_worth_delta"] == "699999.99"
    assert {item["component_type"] for item in data["items"]} == {"property_value", "mortgage_balance"}
    assert {item["provenance"] for item in data["items"]} == {"manual"}


@pytest.mark.no_db
def test_AC22_13_1_valuation_component_item_uses_normalized_provenance_type() -> None:
    """AC22.13.1: Component provenance stays constrained to the shared vocabulary."""
    assert ValuationComponentItem.__dataclass_fields__["provenance"].type == DataProvenance


@pytest.mark.no_db
async def test_AC11_19_1_current_valuation_head_query_takes_row_lock() -> None:
    """AC11.19.1: Correction hand-off locks the current head before superseding it."""
    service = AssetService()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    await service._current_valuation_head(
        db,
        uuid4(),
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        source="manual appraisal",
        as_of_date=date(2026, 5, 18),
    )

    statement = db.execute.await_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled


async def test_manual_valuation_snapshot_router_rolls_back_on_service_errors(client, monkeypatch):
    """AC11.9.1: Valuation mutation endpoints return server errors when persistence fails."""
    from src.routers import assets as assets_router

    async def raise_on_create(*args, **kwargs):
        raise RuntimeError("create failed")

    async def raise_on_update(*args, **kwargs):
        raise RuntimeError("update failed")

    monkeypatch.setattr(assets_router._service, "create_valuation_snapshot", raise_on_create)
    create_response = await client.post(
        "/assets/valuation-snapshots",
        json={
            "component_type": "property_value",
            "as_of_date": "2026-05-18",
            "value": "1.00",
            "currency": "SGD",
            "source": "manual",
        },
    )
    assert create_response.status_code == 500

    monkeypatch.setattr(assets_router._service, "update_valuation_snapshot", raise_on_update)
    update_response = await client.patch(
        f"/assets/valuation-snapshots/{uuid4()}",
        json={"value": "2.00"},
    )
    assert update_response.status_code == 500


async def test_manual_valuation_snapshot_service_updates_optional_fields_and_missing_rows(db, test_user):
    """AC11.9.1: Service updates every optional field and handles missing snapshots."""
    service = AssetService()
    snapshot = await service.create_valuation_snapshot(
        db,
        user_id=test_user.id,
        component_type=ManualValuationComponentType.ESOP,
        liquidity_class=ManualValuationLiquidityClass.LIQUID,
        as_of_date=date(2026, 5, 18),
        value=Decimal("1234.567"),
        currency="usd",
        source="equity portal",
        notes="initial",
        recurrence_days=180,
        reminder_date=date(2026, 11, 14),
    )

    updated = await service.update_valuation_snapshot(
        db,
        test_user.id,
        snapshot.id,
        values={
            "component_type": ManualValuationComponentType.OTHER_ASSET,
            "liquidity_class": ManualValuationLiquidityClass.RESTRICTED,
            "as_of_date": date(2026, 6, 1),
            "value": Decimal("2345.678"),
            "currency": "hkd",
            "source": "updated portal",
            "notes": None,
            "recurrence_days": None,
            "reminder_date": None,
        },
    )
    await db.commit()

    assert updated is not None
    assert updated.component_type == ManualValuationComponentType.OTHER_ASSET
    assert updated.liquidity_class == ManualValuationLiquidityClass.RESTRICTED
    assert updated.as_of_date == date(2026, 6, 1)
    assert updated.value == Decimal("2345.68")
    assert updated.currency == "HKD"
    assert updated.source == "updated portal"
    assert updated.notes is None
    assert updated.recurrence_days is None
    assert updated.reminder_date is None

    missing_id = uuid4()
    assert (
        await service.update_valuation_snapshot(db, test_user.id, missing_id, values={"value": Decimal("1.00")}) is None
    )
    assert await service.delete_valuation_snapshot(db, test_user.id, missing_id) is False


@pytest.mark.asyncio
async def test_AC11_19_1_manual_valuation_correction_appends_version_and_preserves_history(db, test_user, ac_evidence):
    """AC11.19.1: Correcting a manual valuation appends a new version and never edits the prior fact in place.

    Vision Axiom A: a recorded fact is never changed in place; a later correction
    accumulates as a new version, and one version maps to exactly one value.
    """
    service = AssetService()
    # The version-chain identity matches the partial unique index exactly
    # (component_type, source, as_of_date) — currency is not part of it.
    identity = dict(
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=date(2026, 5, 18),
        source="manual appraisal",
    )

    first = await service.create_valuation_snapshot(
        db, user_id=test_user.id, value=Decimal("1000000.00"), currency="SGD", **identity
    )
    # A correction that also re-denominates the currency is still the same fact:
    # it must supersede, not collide on the (currency-less) unique index.
    corrected = await service.create_valuation_snapshot(
        db, user_id=test_user.id, value=Decimal("1100000.00"), currency="USD", **identity
    )
    await db.commit()

    # The prior fact is preserved unedited and points forward to its successor (append-only chain).
    await db.refresh(first)
    assert first.value == Decimal("1000000.00"), "prior fact must not be edited in place"
    assert first.version == 1
    assert first.superseded_by_id == corrected.id

    # The correction is the new current head: one version -> one value.
    assert corrected.value == Decimal("1100000.00")
    assert corrected.currency == "USD"
    assert corrected.version == 2
    assert corrected.superseded_by_id is None

    # Full history is retrievable, newest first, keyed by the currency-less identity.
    history = await service.list_valuation_versions(db, test_user.id, **identity)
    assert [(h.version, h.value) for h in history] == [
        (2, Decimal("1100000.00")),
        (1, Decimal("1000000.00")),
    ]

    # Measured evidence: the append-only correction chain matches its golden
    # shape exactly (prior fact frozen at v1, head at v2, forward link set).
    chain_correct = (
        first.value == Decimal("1000000.00")
        and first.version == 1
        and first.superseded_by_id == corrected.id
        and corrected.value == Decimal("1100000.00")
        and corrected.version == 2
        and corrected.superseded_by_id is None
    )
    ac_evidence(
        ac_id="AC11.19.1",
        score=1.0 if chain_correct else 0.0,
        metric="append_only_version_chain_matches_golden",
        comment=(
            "v1=1000000.00 frozen & superseded_by=head; "
            "head v2=1100000.00 with superseded_by=None"
        ),
        provenance="deterministic",
    )


@pytest.mark.asyncio
async def test_AC11_19_2_corrected_valuation_is_not_double_counted_in_net_worth(db, test_user, ac_evidence):
    """AC11.19.2: Heads-only reads use the current version, so a correction never double-counts."""
    service = AssetService()
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

    # Measured evidence: net-worth aggregate counts only the corrected head
    # (1,100,000) — the superseded 1,000,000 is neither added nor double-counted.
    expected_total = Decimal("1100000.00")
    counted_once = components.total_assets == expected_total and total == 1
    ac_evidence(
        ac_id="AC11.19.2",
        score=1.0 if counted_once else 0.0,
        metric="heads_only_total_assets_match",
        comment=(
            f"total_assets={components.total_assets} == golden {expected_total}; "
            f"heads listed={total} (superseded excluded)"
        ),
        provenance="deterministic",
    )


@pytest.mark.asyncio
async def test_editing_a_superseded_valuation_is_rejected(db, test_user):
    """Audit review: PATCH must not edit frozen history (Axiom A); superseded versions are read-only."""
    service = AssetService()
    identity = dict(
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=date(2026, 5, 18),
        source="manual appraisal",
    )
    first = await service.create_valuation_snapshot(
        db, user_id=test_user.id, value=Decimal("1000000.00"), currency="SGD", **identity
    )
    await service.create_valuation_snapshot(
        db, user_id=test_user.id, value=Decimal("1100000.00"), currency="SGD", **identity
    )  # supersedes `first`
    await db.commit()

    with pytest.raises(AssetServiceError, match="superseded"):
        await service.update_valuation_snapshot(db, test_user.id, first.id, values={"value": Decimal("999.00")})


@pytest.mark.asyncio
async def test_restricted_holdings_exclude_superseded_currency_correction(client):
    """Audit review: a currency-changing correction must not surface as a phantom restricted holding."""
    base = {
        "component_type": "rsu",
        "as_of_date": "2026-05-18",
        "source": "Acme RSU",
        "value": "1000.00",
    }
    assert (await client.post("/assets/valuation-snapshots", json={**base, "currency": "USD"})).status_code == 201
    # Correct it, changing currency — supersedes the prior version (same component/source/as_of_date).
    assert (
        await client.post("/assets/valuation-snapshots", json={**base, "currency": "SGD", "value": "1100.00"})
    ).status_code == 201

    response = await client.get("/assets/restricted")
    assert response.status_code == 200
    holdings = response.json()
    assert len(holdings) == 1, "superseded version must not appear as a second holding"
    assert holdings[0]["ticker"] == "Acme RSU"


def test_manual_valuation_snapshot_schema_normalizes_currency():
    """AC11.9.1: Manual valuation schemas normalize currency codes before service use."""
    create_payload = ManualValuationSnapshotCreate(
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=date(2026, 5, 18),
        value=Decimal("1.23"),
        currency="sgd",
        source="manual",
    )
    update_payload = ManualValuationSnapshotUpdate(currency="usd")
    empty_update = ManualValuationSnapshotUpdate(currency=None)

    assert create_payload.currency == "SGD"
    assert update_payload.currency == "USD"
    assert empty_update.currency is None


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
