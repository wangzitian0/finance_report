from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionRef,
    TraceRecord,
    TraceRecordType,
    TraceResult,
    TraceScope,
    VersionedTraceRef,
)
from src.audit.orm.trace_record import TraceRecordRow
from src.pricing import (
    MarketValuationSelection,
    PriceableSubject,
    ResolutionPolicy,
    ResolvedValuationContribution,
    StockPrice,
    build_manual_valuation_lines,
    pricing_trace_policy_registry,
    record_manual_valuation,
    resolve_manual_valuation_contributions,
    resolve_selected_market_valuation_contribution,
    resolve_valuation_contribution,
)
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.reporting.extension.package_document import PackageAssembler
from src.schemas.portfolio import InvestmentPerformanceMarketValuationSelection

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "state_kwargs",
    [
        {"state": "authoritative", "reason_code": None, "decision": None},
        {
            "state": "authoritative",
            "reason_code": "unexpected",
            "decision": TraceDecisionRef(
                decision_id=uuid4(),
                target=VersionedTraceRef("pricing_subject", "property_value", "1"),
                assertion=VersionedTraceRef("pricing_authority", "selected_value", "1"),
            ),
        },
        {"state": "unproven", "reason_code": None, "decision": None},
        {
            "state": "unproven",
            "reason_code": "missing_observation",
            "decision": TraceDecisionRef(
                decision_id=uuid4(),
                target=VersionedTraceRef("pricing_subject", "property_value", "1"),
                assertion=VersionedTraceRef("pricing_authority", "selected_value", "1"),
            ),
        },
    ],
)
async def test_resolved_valuation_contribution_rejects_inconsistent_authority_state(state_kwargs):
    base = dict(
        subject=PriceableSubject.component("property_value"),
        requested_as_of=date(2026, 6, 1),
        resolution_policy="fixture-policy",
        lineage_id=None,
        observation_id=None,
        observation_version=None,
        observation_as_of=None,
        value=None,
        currency=None,
        source=None,
    )
    with pytest.raises(ValueError):
        ResolvedValuationContribution(**base, **state_kwargs)


async def _supersede_decision_parent(db, *, user_id, decision_id) -> None:
    repo = SqlTraceRecordRepository(db, pricing_trace_policy_registry())
    scope = TraceScope.tenant(user_id)
    decision = await repo.get(scope, decision_id)
    obs = await repo.get(scope, decision.parent_ids[0])
    await repo.append(
        TraceRecord.observation(
            scope=scope,
            target=VersionedTraceRef(obs.target.kind, obs.target.id, f"{obs.target.version}:corrected"),
            target_class=obs.target_class,
            assertion=VersionedTraceRef(obs.assertion.kind, obs.assertion.id, f"{obs.assertion.version}:corrected"),
            authority=obs.authority,
            result=TraceResult.PASS,
            execution_id=f"{obs.execution_id}:corrected",
            evidence_manifest_digest="d" * 64,
            occurred_at=obs.occurred_at + timedelta(microseconds=1),
            score=obs.score,
            reason_code="pricing_selection_corrected",
            supersedes_id=obs.record_id,
        )
    )


async def test_AC_pricing_valuation_contribution_1_2_emit_supersede_and_pin(db, test_user):
    prop_sub, as_of = PriceableSubject.component("property_value"), date(2026, 6, 1)
    first = await record_manual_valuation(
        db,
        test_user.id,
        component_type="property_value",
        liquidity_class="illiquid",
        as_of=as_of,
        value=Decimal("500000"),
        currency="SGD",
        source="operator-appraisal",
    )
    c1 = await resolve_valuation_contribution(
        db, user_id=test_user.id, subject=prop_sub, as_of=as_of, policy=ResolutionPolicy()
    )
    await _supersede_decision_parent(db, user_id=test_user.id, decision_id=c1.decision_id)
    second = await record_manual_valuation(
        db,
        test_user.id,
        component_type="property_value",
        liquidity_class="illiquid",
        as_of=as_of,
        value=Decimal("510000"),
        currency="SGD",
        source="operator-appraisal",
    )
    c2 = await resolve_valuation_contribution(
        db, user_id=test_user.id, subject=prop_sub, as_of=as_of, policy=ResolutionPolicy()
    )
    c2_row = await db.get(TraceRecordRow, c2.decision_id)

    cpf = await record_manual_valuation(
        db,
        test_user.id,
        component_type="cpf_balance",
        liquidity_class="restricted",
        as_of=as_of,
        value=Decimal("100000"),
        currency="SGD",
        source="cpf-portal",
    )
    c_cpf = await resolve_valuation_contribution(
        db, user_id=test_user.id, subject=cpf.subject, as_of=date(2026, 6, 15), policy=ResolutionPolicy(max_age_days=30)
    )
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
    c_mkt = await resolve_valuation_contribution(
        db,
        user_id=test_user.id,
        subject=PriceableSubject.security("AAPL"),
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=1),
    )
    assert (
        (c1.is_authoritative, c1.observation_id, c1.decision_id is not None),
        (
            c2.is_authoritative,
            c2.observation_id,
            c2.decision_id != c1.decision_id,
            c2.observation_version != c1.observation_version,
            c2_row.supersedes_id,
        ),
        (
            c_cpf.is_authoritative,
            c_cpf.observation_id,
            bool(c_cpf.observation_version),
            bool(c_cpf.decision_id),
            c_cpf.decision.target.kind,
            c_cpf.decision.target.version,
            c_cpf.decision.assertion.kind,
            c_cpf.input_refs,
            c_cpf.resolution_policy,
        ),
        (c_mkt.is_authoritative, c_mkt.source is not None, c_mkt.decision_id is not None),
    ) == (
        (True, first.id, True),
        (True, second.id, True, True, c1.decision_id),
        (
            True,
            cpf.id,
            True,
            True,
            "pricing_valuation",
            c_cpf.observation_version,
            "pricing_valuation_attestation",
            (f"pricing_observation:{cpf.id}",),
            "max_age_days=30;min_authority=CRAWLER",
        ),
        (True, True, True),
    )


async def test_AC_pricing_valuation_contribution_3_missing_or_stale_decision_is_unproven(db, test_user):
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type="property_value",
                liquidity_class="illiquid",
                as_of_date=date(2026, 6, 1),
                value=Decimal("500000.00"),
                currency="SGD",
                source="legacy-import",
            ),
            StockPrice(
                symbol="STALEHEAD",
                price=Decimal("125.05"),
                currency="SGD",
                price_date=date(2026, 6, 15),
                source="recorded-provider",
            ),
        ]
    )
    await db.flush()
    missing = await resolve_valuation_contribution(
        db,
        user_id=test_user.id,
        subject=PriceableSubject.component("property_value"),
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=30),
    )
    cross_tenant = await resolve_valuation_contribution(
        db,
        user_id=uuid4(),
        subject=PriceableSubject.component("property_value"),
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=30),
    )
    market = await resolve_valuation_contribution(
        db,
        user_id=test_user.id,
        subject=PriceableSubject.security("STALEHEAD"),
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=0),
    )
    await _supersede_decision_parent(db, user_id=test_user.id, decision_id=market.decision_id)
    stale = await resolve_valuation_contribution(
        db,
        user_id=test_user.id,
        subject=PriceableSubject.security("STALEHEAD"),
        as_of=date(2026, 6, 15),
        policy=ResolutionPolicy(max_age_days=0),
    )
    decisions = tuple(
        (
            await db.execute(
                select(TraceRecordRow.id).where(
                    TraceRecordRow.scope_id == str(test_user.id), TraceRecordRow.record_type == TraceRecordType.DECISION
                )
            )
        ).scalars()
    )
    assert (
        (missing.is_authoritative, missing.decision_id, missing.reason_code),
        (cross_tenant.is_authoritative, cross_tenant.reason_code),
        (market.is_authoritative, market.decision_id is not None),
        (stale.is_authoritative, stale.observation_id, stale.decision_id, stale.reason_code, decisions),
    ) == (
        (False, None, "missing_observation_decision"),
        (False, "no_eligible_observation"),
        (True, True),
        (False, market.observation_id, None, "stale_observation_decision", (market.decision_id,)),
    )


async def test_AC_pricing_valuation_contribution_4_rollback_is_atomic(db, test_user):
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
    assert (
        (await db.execute(select(ManualValuationSnapshot.id).where(ManualValuationSnapshot.user_id == user_id)))
        .scalars()
        .all(),
        (await db.execute(select(TraceRecordRow.id).where(TraceRecordRow.scope_id == str(user_id)))).scalars().all(),
    ) == ([], [])


async def test_AC_pricing_valuation_contribution_5_resolves_each_manual_lineage_without_shadow_trust(db, test_user):
    obs = [
        await record_manual_valuation(
            db,
            test_user.id,
            component_type="property_value",
            liquidity_class="illiquid",
            as_of=date(2026, 6, 1),
            value=Decimal(v),
            currency="SGD",
            source=s,
        )
        for s, v in (("home-a", "500000"), ("home-b", "750000"))
    ]
    contribs = await resolve_manual_valuation_contributions(
        db, user_id=test_user.id, as_of=date(2026, 6, 15), policy=ResolutionPolicy(max_age_days=30)
    )
    asset_lines, _ = await build_manual_valuation_lines(
        db, test_user.id, as_of_date=date(2026, 6, 15), target_currency="SGD"
    )
    pricing_src = Path(__file__).parents[2] / "src" / "pricing"
    assert (
        {i.observation_id for i in contribs},
        len({i.lineage_id for i in contribs}),
        all(i.is_authoritative and i.decision_id for i in contribs),
        {i.component_type for i in contribs},
        {i.liquidity_class for i in contribs},
        {i.valuation_basis for i in contribs},
        len(asset_lines),
        all("confidence_tier" not in line and "trusted" not in line for line in asset_lines),
        all("confidence_tier" not in p.read_text() for p in pricing_src.rglob("*.py")),
    ) == ({i.id for i in obs}, 2, True, {"property_value"}, {"illiquid"}, {None}, 2, True, True)


async def test_AC_pricing_valuation_contribution_6_selected_market_input_requires_exact_schedule_observation(
    db, test_user
):
    as_of = date(2026, 12, 31)
    selected = StockPrice(
        symbol="PKGSEC", price=Decimal("125.05"), currency="SGD", price_date=as_of, source="recorded-provider"
    )
    db.add(selected)
    await db.flush()
    ok = await resolve_selected_market_valuation_contribution(
        db,
        user_id=test_user.id,
        selection=MarketValuationSelection(
            subject=PriceableSubject.security("PKGSEC"), observation_id=selected.id, requested_as_of=as_of
        ),
        policy=ResolutionPolicy(max_age_days=0),
    )
    mismatch = await resolve_selected_market_valuation_contribution(
        db,
        user_id=test_user.id,
        selection=MarketValuationSelection(
            subject=PriceableSubject.security("PKGSEC"), observation_id=uuid4(), requested_as_of=as_of
        ),
        policy=ResolutionPolicy(max_age_days=0),
    )
    missing = await resolve_selected_market_valuation_contribution(
        db,
        user_id=test_user.id,
        selection=MarketValuationSelection(
            subject=PriceableSubject.security("MISSING"), observation_id=uuid4(), requested_as_of=as_of
        ),
        policy=ResolutionPolicy(max_age_days=0),
    )
    pkg_contribs = await PackageAssembler()._selected_market_contributions(
        db,
        user_id=test_user.id,
        selections=[
            InvestmentPerformanceMarketValuationSelection(
                asset_identifier="PKGSEC", observation_id=selected.id, requested_as_of=as_of
            )
        ],
    )
    manifest, unproven = await PackageAssembler()._input_manifest(db, user_id=test_user.id, contributions=pkg_contribs)
    assert (
        (ok.is_authoritative, ok.observation_id, ok.decision_id is not None),
        (mismatch.is_authoritative, mismatch.reason_code),
        (missing.is_authoritative, missing.reason_code),
        (
            len(pkg_contribs),
            pkg_contribs[0].is_authoritative,
            pkg_contribs[0].section_ids,
            unproven,
            manifest[0].decision_id,
            manifest[0].input_refs,
        ),
    ) == (
        (True, selected.id, True),
        (False, "selected_observation_mismatch"),
        (False, "no_eligible_observation"),
        (
            1,
            True,
            ("balance_sheet", "investment_performance", "traceability_appendix"),
            [],
            ok.decision_id,
            [f"pricing_observation:{selected.id}"],
        ),
    )
