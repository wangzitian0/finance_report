"""Decision-backed pricing inputs for a frozen personal-report package (#1915)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.audit.orm.trace_record import TraceRecordRow
from src.extraction.orm.layer3 import ManualValuationSnapshot
from src.pricing import (
    MarketValuationSelection,
    PriceableSubject,
    ResolutionPolicy,
    StockPrice,
    build_manual_valuation_lines,
    record_manual_valuation,
    resolve_manual_valuation_contributions,
    resolve_selected_market_valuation_contribution,
    resolve_valuation_contribution,
)
from src.reporting.extension.package_document import PackageAssembler
from src.schemas.portfolio import InvestmentPerformanceMarketValuationSelection

pytestmark = pytest.mark.asyncio


async def test_AC_pricing_valuation_contribution_1_manual_write_emits_and_supersedes_decision(db, test_user):
    """AC-pricing.valuation-contribution.1: a correction replaces the prior decision."""
    subject = PriceableSubject.component("property_value")
    first = await record_manual_valuation(
        db,
        test_user.id,
        component_type="property_value",
        liquidity_class="illiquid",
        as_of=date(2026, 6, 1),
        value=Decimal("500000"),
        currency="SGD",
        source="operator-appraisal",
    )
    first_contribution = await resolve_valuation_contribution(
        db,
        user_id=test_user.id,
        subject=subject,
        as_of=date(2026, 6, 1),
        policy=ResolutionPolicy(),
    )
    assert first_contribution.is_authoritative
    assert first_contribution.observation_id == first.id
    assert first_contribution.decision_id is not None

    second = await record_manual_valuation(
        db,
        test_user.id,
        component_type="property_value",
        liquidity_class="illiquid",
        as_of=date(2026, 6, 1),
        value=Decimal("510000"),
        currency="SGD",
        source="operator-appraisal",
    )
    second_contribution = await resolve_valuation_contribution(
        db,
        user_id=test_user.id,
        subject=subject,
        as_of=date(2026, 6, 1),
        policy=ResolutionPolicy(),
    )

    assert second_contribution.is_authoritative
    assert second_contribution.observation_id == second.id
    assert second_contribution.decision_id != first_contribution.decision_id
    assert second_contribution.observation_version != first_contribution.observation_version
    second_decision = await db.get(TraceRecordRow, second_contribution.decision_id)
    assert second_decision is not None
    assert second_decision.supersedes_id == first_contribution.decision_id


async def test_AC_pricing_valuation_contribution_2_resolve_pins_exact_observation_and_decision(db, test_user):
    """AC-pricing.valuation-contribution.2: the DTO is the complete package input."""
    observation = await record_manual_valuation(
        db,
        test_user.id,
        component_type="cpf_balance",
        liquidity_class="restricted",
        as_of=date(2026, 6, 1),
        value=Decimal("100000"),
        currency="SGD",
        source="cpf-portal",
    )

    contribution = await resolve_valuation_contribution(
        db,
        user_id=test_user.id,
        subject=observation.subject,
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=30),
    )

    assert contribution.is_authoritative
    assert contribution.observation_id == observation.id
    assert contribution.observation_version
    assert contribution.decision_id
    assert contribution.input_refs == (f"pricing_observation:{observation.id}",)
    assert contribution.resolution_policy == "max_age_days=30;min_authority=CRAWLER"

    # A provider row is not trusted because it says "crawler". Pricing emits
    # a deterministic decision that pins the selected row and this exact
    # resolution policy before it can become a package contribution.
    db.add(
        StockPrice(
            symbol="AAPL",
            price=Decimal("185.50"),
            currency="USD",
            price_date=date(2026, 6, 15),
            source="recorded-provider",
        )
    )
    await db.flush()
    market = await resolve_valuation_contribution(
        db,
        user_id=test_user.id,
        subject=PriceableSubject.security("AAPL"),
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=1),
    )
    assert market.is_authoritative
    assert market.source is not None
    assert market.decision_id is not None


async def test_AC_pricing_valuation_contribution_3_missing_or_stale_decision_is_unproven(db, test_user):
    """AC-pricing.valuation-contribution.3: missing authority stays explicitly unproven."""
    legacy = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type="property_value",
        liquidity_class="illiquid",
        as_of_date=date(2026, 6, 1),
        value=Decimal("500000.00"),
        currency="SGD",
        source="legacy-import",
    )
    db.add(legacy)
    await db.flush()

    missing = await resolve_valuation_contribution(
        db,
        user_id=test_user.id,
        subject=PriceableSubject.component("property_value"),
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=30),
    )
    assert not missing.is_authoritative
    assert missing.decision_id is None
    assert missing.reason_code == "missing_observation_decision"

    cross_tenant = await resolve_valuation_contribution(
        db,
        user_id=uuid4(),
        subject=PriceableSubject.component("property_value"),
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=30),
    )
    assert not cross_tenant.is_authoritative
    assert cross_tenant.reason_code == "no_eligible_observation"


async def test_AC_pricing_valuation_contribution_4_rollback_is_atomic(db, test_user):
    """AC-pricing.valuation-contribution.4: a failed write leaves no durable trace."""
    user_id = test_user.id
    await record_manual_valuation(
        db,
        user_id,
        component_type="property_value",
        liquidity_class="illiquid",
        as_of=date(2026, 6, 1),
        value=Decimal("500000"),
        currency="SGD",
        source="operator-appraisal",
    )
    await db.flush()
    await db.rollback()

    snapshots = (
        (await db.execute(select(ManualValuationSnapshot.id).where(ManualValuationSnapshot.user_id == user_id)))
        .scalars()
        .all()
    )
    traces = (
        (await db.execute(select(TraceRecordRow.id).where(TraceRecordRow.scope_id == str(user_id)))).scalars().all()
    )
    assert snapshots == []
    assert traces == []


async def test_AC_pricing_valuation_contribution_5_resolves_each_manual_lineage_without_shadow_trust(db, test_user):
    """AC-pricing.valuation-contribution.5: one component may have many exact lineages."""
    observations = []
    for source, value in (("home-a", "500000"), ("home-b", "750000")):
        observations.append(
            await record_manual_valuation(
                db,
                test_user.id,
                component_type="property_value",
                liquidity_class="illiquid",
                as_of=date(2026, 6, 1),
                value=Decimal(value),
                currency="SGD",
                source=source,
            )
        )

    contributions = await resolve_manual_valuation_contributions(
        db,
        user_id=test_user.id,
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=30),
    )

    assert {item.observation_id for item in contributions} == {item.id for item in observations}
    assert len({item.lineage_id for item in contributions}) == 2
    assert all(item.is_authoritative and item.decision_id for item in contributions)
    assert {item.component_type for item in contributions} == {"property_value"}
    assert {item.liquidity_class for item in contributions} == {"illiquid"}
    assert {item.valuation_basis for item in contributions} == {None}

    asset_lines, _ = await build_manual_valuation_lines(
        db,
        test_user.id,
        as_of_date=date(2026, 6, 15),
        target_currency="SGD",
    )
    assert len(asset_lines) == 2
    assert all("confidence_tier" not in line and "trusted" not in line for line in asset_lines)
    pricing_source = Path(__file__).parents[2] / "src" / "pricing"
    assert all("confidence_tier" not in path.read_text() for path in pricing_source.rglob("*.py"))


async def test_AC_pricing_valuation_contribution_6_selected_market_input_requires_exact_schedule_observation(
    db,
    test_user,
):
    """AC-pricing.valuation-contribution.6: a package can freeze only its schedule's exact market input."""
    as_of = date(2026, 12, 31)
    selected_price = StockPrice(
        symbol="PKGSEC",
        price=Decimal("125.05"),
        currency="SGD",
        price_date=as_of,
        source="recorded-provider",
    )
    db.add(selected_price)
    await db.flush()

    selection = MarketValuationSelection(
        subject=PriceableSubject.security("PKGSEC"),
        observation_id=selected_price.id,
        requested_as_of=as_of,
    )
    contribution = await resolve_selected_market_valuation_contribution(
        db,
        user_id=test_user.id,
        selection=selection,
        policy=ResolutionPolicy(max_age_days=0),
    )
    mismatch = await resolve_selected_market_valuation_contribution(
        db,
        user_id=test_user.id,
        selection=MarketValuationSelection(
            subject=PriceableSubject.security("PKGSEC"),
            observation_id=uuid4(),
            requested_as_of=as_of,
        ),
        policy=ResolutionPolicy(max_age_days=0),
    )

    assert contribution.is_authoritative
    assert contribution.observation_id == selected_price.id
    assert contribution.decision_id is not None
    assert not mismatch.is_authoritative
    assert mismatch.reason_code == "selected_observation_mismatch"

    package_contributions = await PackageAssembler()._selected_market_contributions(
        db,
        user_id=test_user.id,
        selections=[
            InvestmentPerformanceMarketValuationSelection(
                asset_identifier="PKGSEC",
                observation_id=selected_price.id,
                requested_as_of=as_of,
            )
        ],
    )
    manifest, unproven = await PackageAssembler()._input_manifest(
        db,
        user_id=test_user.id,
        contributions=package_contributions,
    )

    assert len(package_contributions) == 1
    assert package_contributions[0].is_authoritative
    assert package_contributions[0].section_ids == (
        "balance_sheet",
        "investment_performance",
        "traceability_appendix",
    )
    assert unproven == []
    assert manifest[0].decision_id == contribution.decision_id
    assert manifest[0].input_refs == [f"pricing_observation:{selected_price.id}"]
