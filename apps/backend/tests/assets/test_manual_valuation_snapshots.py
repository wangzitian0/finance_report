from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.audit import DataProvenance
from src.pricing import ManualValuationBasis, ManualValuationComponentType, ManualValuationLiquidityClass, ValuationComponentItem, ValuationService, record_manual_valuation
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.schemas.pricing import ManualValuationSnapshotCreate


async def test_create_manual_valuation_snapshot_crud_and_retired_endpoints(client):
    payload = {"component_type": "property_value", "as_of_date": "2026-05-18", "value": "1250000.99", "currency": "SGD", "source": "manual appraisal", "notes": "May checkpoint", "recurrence_days": 90, "reminder_date": "2026-08-16"}
    create_resp = await client.post("/pricing/manual-valuations", json=payload)
    created = create_resp.json()
    list_resp = await client.get("/pricing/manual-valuations")
    corrected_resp = await client.post("/pricing/manual-valuations", json={**payload, "value": "1260000.10", "notes": "Updated valuation"})
    updated = corrected_resp.json()
    retired = [(await getattr(client, m)(f"/assets/valuation-snapshots/{updated['id']}", **({"json": {"value": "1.00"}} if m == "patch" else {}))).status_code for m in ("patch", "delete", "get")]
    current_list = await client.get("/pricing/manual-valuations")
    assert (
        create_resp.status_code,
        (created["component_type"], created["liquidity_class"], created["value"], created["provenance"], bool(created["created_at"]), bool(created["updated_at"])),
        (list_resp.status_code, list_resp.json()["total"], list_resp.json()["items"][0]["id"], list_resp.json()["items"][0]["provenance"]),
        corrected_resp.status_code,
        (updated["value"], updated["notes"], updated["id"] != created["id"]),
        retired,
        (current_list.status_code, current_list.json()["total"], current_list.json()["items"][0]["id"]),
    ) == (201, ("property_value", "illiquid", "1250000.99", "manual", True, True), (200, 1, created["id"], "manual"), 201, ("1260000.10", "Updated valuation", True), [404, 404, 404], (200, 1, updated["id"]))


async def test_manual_valuation_snapshot_filter_errors_and_components_api(client):
    new_prop = {"component_type": "property_value", "as_of_date": "2026-05-18", "value": "1000000.02", "currency": "sgd", "source": "appraisal"}
    tax = {"component_type": "tax_refund", "as_of_date": "2026-05-19", "value": "1200.00", "currency": "SGD", "source": "IRAS"}
    for p in (new_prop, tax):
        assert (await client.post("/pricing/manual-valuations", json=p)).status_code == 201
    filtered = await client.get("/pricing/manual-valuations", params={"component_type": "property_value", "as_of_date": "2026-05-18"})
    bad = await client.get("/pricing/manual-valuations", params={"component_type": "unsupported"})
    for p in ({**new_prop, "as_of_date": "2026-01-31", "value": "1000000.01"}, {"component_type": "mortgage_balance", "as_of_date": "2026-05-18", "value": "300000.03", "currency": "SGD", "source": "bank portal"}):
        assert (await client.post("/pricing/manual-valuations", json=p)).status_code == 201
    comp = await client.get("/pricing/valuation-components", params={"as_of_date": "2026-05-18"})
    data = comp.json()
    assert (
        (filtered.status_code, filtered.json()["total"], filtered.json()["items"][0]["component_type"], filtered.json()["items"][0]["currency"]),
        bad.status_code,
        (comp.status_code, data["total_assets"], data["total_liabilities"], data["net_worth_delta"], {i["component_type"] for i in data["items"]}, {i["provenance"] for i in data["items"]}),
    ) == ((200, 1, "property_value", "SGD"), 400, (200, "1000000.02", "300000.03", "699999.99", {"property_value", "mortgage_balance"}, {"manual"}))


@pytest.mark.no_db
async def test_AC22_13_1_AC11_19_1_provenance_type_schema_and_row_lock() -> None:
    assert ValuationComponentItem.__dataclass_fields__["provenance"].type == DataProvenance
    assert ManualValuationSnapshotCreate(component_type=ManualValuationComponentType.PROPERTY_VALUE, as_of_date=date(2026, 5, 18), value=Decimal("1.23"), currency="sgd", source="manual").currency == "SGD"

    class _HeadQueryIssued(Exception):
        pass

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_HeadQueryIssued)
    with pytest.raises(_HeadQueryIssued):
        await record_manual_valuation(db, uuid4(), component_type=ManualValuationComponentType.PROPERTY_VALUE, liquidity_class=ManualValuationLiquidityClass.ILLIQUID, as_of=date(2026, 5, 18), value=Decimal("1000000.00"), currency="SGD", source="manual appraisal")
    assert "FOR UPDATE" in str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))


async def test_manual_valuation_snapshot_router_rolls_back_on_service_errors(client, monkeypatch):
    from src.routers import pricing as pricing_router

    async def fail(*_a, **_kw):
        raise RuntimeError("create failed")

    monkeypatch.setattr(pricing_router._valuations, "create_valuation_snapshot", fail)
    resp = await client.post("/pricing/manual-valuations", json={"component_type": "property_value", "as_of_date": "2026-05-18", "value": "1.00", "currency": "SGD", "source": "manual"})
    assert resp.status_code == 500


async def test_AC11_19_manual_valuation_service_history_dedup_and_scope(db, test_user):
    service = ValuationService()
    ident = dict(component_type=ManualValuationComponentType.PROPERTY_VALUE, as_of_date=date(2026, 5, 18), source="manual appraisal")
    first = await service.create_valuation_snapshot(db, user_id=test_user.id, value=Decimal("1000000.00"), currency="SGD", **ident)
    corrected = await service.create_valuation_snapshot(db, user_id=test_user.id, value=Decimal("1100000.00"), currency="USD", **ident)
    await db.commit()
    await db.refresh(first)
    history = (await db.execute(select(ManualValuationSnapshot).where(ManualValuationSnapshot.user_id == test_user.id, ManualValuationSnapshot.component_type == ident["component_type"], ManualValuationSnapshot.source == ident["source"], ManualValuationSnapshot.as_of_date == ident["as_of_date"]).order_by(ManualValuationSnapshot.version.desc()))).scalars().all()
    snapshots, total = await service.list_valuation_snapshots(db, test_user.id)
    assert (
        (first.value, first.version, first.superseded_by_id, corrected.value, corrected.currency, corrected.version, corrected.superseded_by_id),
        [(h.version, h.value) for h in history],
        (total, snapshots[0].value),
    ) == ((Decimal("1000000.00"), 1, corrected.id, Decimal("1100000.00"), "USD", 2, None), [(2, Decimal("1100000.00")), (1, Decimal("1000000.00"))], (1, Decimal("1100000.00")))


async def test_manual_valuation_snapshot_latest_components_and_restricted_toggle(db, test_user):
    service = ValuationService()
    for ctype, as_of, val, src in (
        (ManualValuationComponentType.PROPERTY_VALUE, date(2026, 1, 31), "1000000.01", "appraisal"),
        (ManualValuationComponentType.PROPERTY_VALUE, date(2026, 5, 18), "1000000.02", "appraisal"),
        (ManualValuationComponentType.MORTGAGE_BALANCE, date(2026, 5, 18), "300000.03", "bank portal"),
        (ManualValuationComponentType.CPF_BALANCE, date(2026, 5, 18), "50000.00", "CPF portal"),
        (ManualValuationComponentType.TAX_REFUND, date(2026, 5, 18), "1200.00", "IRAS"),
    ):
        await service.create_valuation_snapshot(db, user_id=test_user.id, component_type=ctype, as_of_date=as_of, value=Decimal(val), currency="SGD", source=src)
    await db.commit()
    full = await service.get_latest_valuation_components(db, test_user.id, as_of_date=date(2026, 5, 18), include_restricted=True)
    liquid = await service.get_latest_valuation_components(db, test_user.id, as_of_date=date(2026, 5, 18), include_restricted=False)
    assert (
        (full.total_assets, full.total_liabilities, full.net_worth_delta),
        {i.component_type for i in full.items},
        liquid.total_assets,
        next(i for i in full.items if i.component_type == "mortgage_balance").liquidity_class,
    ) == ((Decimal("1051200.02"), Decimal("300000.03"), Decimal("751199.99")), {"property_value", "mortgage_balance", "cpf_balance", "tax_refund"}, Decimal("1200.00"), "liability")


async def test_AC11_9_5_valuation_basis_api_and_superseding_head(client, db, test_user):
    with_basis = await client.post("/pricing/manual-valuations", json={"component_type": "esop", "as_of_date": "2026-03-31", "value": "12345.67", "currency": "SGD", "source": "employer equity portal", "valuation_basis": "employer_grant_document"})
    no_basis = await client.post("/pricing/manual-valuations", json={"component_type": "property_value", "as_of_date": "2026-03-31", "value": "500000.00", "currency": "SGD", "source": "private appraisal"})
    service = ValuationService()
    as_of = date(2026, 4, 30)
    unsub = await service.create_valuation_snapshot(db, test_user.id, component_type=ManualValuationComponentType.PROPERTY_VALUE, as_of_date=as_of, value=Decimal("500000.00"), currency="SGD", source="private appraisal")
    await db.commit()
    assert unsub.valuation_basis is None
    sub = await service.create_valuation_snapshot(db, test_user.id, component_type=ManualValuationComponentType.PROPERTY_VALUE, as_of_date=as_of, value=Decimal("500000.00"), currency="SGD", source="private appraisal", valuation_basis=ManualValuationBasis.MARKET_APPRAISAL)
    await db.commit()
    assert (
        (with_basis.status_code, with_basis.json()["valuation_basis"], with_basis.json()["value"], with_basis.json()["provenance"]),
        (no_basis.status_code, no_basis.json()["valuation_basis"]),
        (unsub.superseded_by_id, sub.superseded_by_id, sub.valuation_basis),
    ) == ((201, "employer_grant_document", "12345.67", "manual"), (201, None), (sub.id, None, ManualValuationBasis.MARKET_APPRAISAL))
