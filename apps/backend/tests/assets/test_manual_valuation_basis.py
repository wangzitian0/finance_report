"""Guided evidence intake — structured valuation basis (#706, EPIC-011 AC11.9.5).

A manual-trusted valuation should carry a structured ``valuation_basis`` (how the
value was determined), and a manual valuation that lacks any basis must surface a
``missing_valuation_basis`` readiness blocker so it cannot silently feed trusted
totals.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer3 import ManualValuationBasis, ManualValuationComponentType
from src.pricing import ValuationService
from src.reporting.extension.report_readiness import get_personal_report_package_readiness
from src.schemas.reporting import PersonalReportingFrameworkId


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


async def test_AC11_9_5_missing_basis_raises_then_clears_readiness_blocker(
    db: AsyncSession,
    test_user,
) -> None:
    """AC11.9.5 (#706 AC2): a manual valuation without a structured basis (and
    without legacy notes) surfaces a ``missing_valuation_basis`` readiness
    blocker; recording a structured basis clears it."""
    service = ValuationService()
    user_id = test_user.id
    as_of = date(2026, 3, 31)

    await service.create_valuation_snapshot(
        db,
        user_id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=as_of,
        value=Decimal("500000.00"),
        currency="SGD",
        source="private appraisal",
    )
    await db.commit()

    readiness = await get_personal_report_package_readiness(
        db, user_id, framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE, as_of_date=as_of
    )
    assert "missing_valuation_basis" in {blocker["code"] for blocker in readiness["blockers"]}

    # Recording the structured basis supersedes the prior head (append-only),
    # so the head now carries a basis and the gap clears.
    await service.create_valuation_snapshot(
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

    readiness_after = await get_personal_report_package_readiness(
        db, user_id, framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE, as_of_date=as_of
    )
    assert "missing_valuation_basis" not in {blocker["code"] for blocker in readiness_after["blockers"]}
