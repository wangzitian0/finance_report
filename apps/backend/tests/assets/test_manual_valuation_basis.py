"""Guided evidence intake — structured valuation basis (#706, EPIC-011 AC11.9.5).

A manual-trusted valuation should carry a structured ``valuation_basis`` (how the
value was determined), and a manual valuation that lacks any basis must surface a
``missing_valuation_basis`` readiness blocker so it cannot silently feed trusted
totals.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer3 import ManualValuationBasis, ManualValuationComponentType
from src.pricing import ValuationService


async def test_AC11_9_5_valuation_basis_captured_via_api(client):
    """AC11.9.5: a manual valuation captures and returns a structured valuation
    basis, and monetary values remain Decimal-safe."""
    payload = {
        "component_type": "esop",
        "as_of_date": "2026-03-31",
        "value": "12345.67",
        "currency": "SGD",
        "source": "employer equity portal",
        "valuation_basis": "employer_grant_document",
    }
    resp = await client.post("/assets/valuation-snapshots", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["valuation_basis"] == "employer_grant_document"
    assert body["value"] == "12345.67"  # Decimal-safe round-trip, no float drift
    assert body["provenance"] == "manual"


async def test_AC11_9_5_basis_is_optional_and_backward_compatible(client):
    """AC11.9.5: valuation_basis is optional at the API (no hard rejection); a
    record may omit it and still be created (the gap is a readiness blocker, not
    a 422)."""
    payload = {
        "component_type": "property_value",
        "as_of_date": "2026-03-31",
        "value": "500000.00",
        "currency": "SGD",
        "source": "private appraisal",
    }
    resp = await client.post("/assets/valuation-snapshots", json=payload)
    assert resp.status_code == 201
    assert resp.json()["valuation_basis"] is None


async def test_AC11_9_5_structured_basis_supersedes_the_unsubstantiated_head(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-pricing.manualvaluation.8: a structured basis is explicit on the current immutable head."""
    service = ValuationService()
    user_id = test_user.id
    as_of = date(2026, 3, 31)

    unsubstantiated = await service.create_valuation_snapshot(
        db,
        user_id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=as_of,
        value=Decimal("500000.00"),
        currency="SGD",
        source="private appraisal",
    )
    await db.commit()

    assert unsubstantiated.valuation_basis is None

    # Recording the structured basis supersedes the prior head (append-only),
    # so the head now carries a basis and the gap clears.
    substantiated = await service.create_valuation_snapshot(
        db,
        user_id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=as_of,
        value=Decimal("500000.00"),
        currency="SGD",
        source="private appraisal",
        valuation_basis=ManualValuationBasis.MARKET_APPRAISAL,
    )
    await db.commit()

    assert unsubstantiated.superseded_by_id == substantiated.id
    assert substantiated.superseded_by_id is None
    assert substantiated.valuation_basis is ManualValuationBasis.MARKET_APPRAISAL
