from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import AccountType, Direction
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass
from src.reporting import PersonalReportingFrameworkId, ReportError, personal_report_package_decision_ref
from src.reporting.base.diagnostics import EquationDiagnosticCategory, EquationDiagnosticResult
from src.reporting.base.package_decision import personal_report_package_target
from src.reporting.extension.package_document import PackageAssembler, _restricted_asset_treatment_disclosure
from src.schemas.reporting import ExcludedHoldingRow, PersonalReportPackageContext, PersonalReportPackageDocument
from tests.reporting._report_fixtures import post_lines, post_pair, seed_accounts, seed_valuations

AS_OF = date(2026, 10, 23)
PERIOD_START = date(2025, 11, 1)
VALUATION_DATE = date(2026, 9, 30)
BANK_BALANCE = Decimal("20360.65")
PROPERTY = Decimal("1200000.00")
MORTGAGE = Decimal("650000.00")
ESOP = Decimal("42000.00")
FULL_NET_WORTH = BANK_BALANCE + PROPERTY + ESOP - MORTGAGE
LIQUID_NET_WORTH = BANK_BALANCE
MAIN_SHAPE_DOCUMENT = Path(__file__).resolve().parents[1] / "fixtures" / "package_document_main_shape.json"
MAIN_SHAPE_DECISION_VERSION = "aacc713256b0f0411ce8c416598a2b75ddbb8a0634fe0e4036f773f2094da538"

_money = lambda v: Decimal(str(v))
_scope_q = lambda inc: "" if inc is None else f"&include_restricted={'true' if inc else 'false'}"


async def _seed_issue_2645_account(db: AsyncSession, user_id: UUID) -> None:
    bank, opening, salary, groceries = await seed_accounts(
        db,
        user_id,
        ("DBS Savings", AccountType.ASSET),
        ("Opening Balance", AccountType.EQUITY),
        ("Salary", AccountType.INCOME),
        ("Groceries", AccountType.EXPENSE),
    )
    for dt, memo, d_acc, c_acc, amt in (
        (date(2025, 12, 1), "Opening", bank, opening, "15000.00"),
        (date(2026, 8, 25), "Salary", bank, salary, "8000.00"),
        (date(2026, 9, 15), "Groceries", groceries, bank, "2639.35"),
    ):
        await post_pair(db, user_id, dt, memo, d_acc, c_acc, amt, source_type=JournalEntrySourceType.AUTO_PARSED)
    await seed_valuations(
        db,
        user_id,
        (
            ManualValuationComponentType.PROPERTY_VALUE,
            ManualValuationLiquidityClass.ILLIQUID,
            PROPERTY,
            "SGD",
            VALUATION_DATE,
            "Condo",
        ),
        (
            ManualValuationComponentType.MORTGAGE_BALANCE,
            ManualValuationLiquidityClass.LIABILITY,
            MORTGAGE,
            "SGD",
            VALUATION_DATE,
            "Condo loan",
        ),
        (
            ManualValuationComponentType.ESOP,
            ManualValuationLiquidityClass.RESTRICTED,
            ESOP,
            "SGD",
            VALUATION_DATE,
            "Employer ESOP",
        ),
        commit=True,
    )


async def _surface_net_worths(client: AsyncClient, include_restricted: bool | None) -> dict[str, Decimal]:
    q = f"as_of_date={AS_OF.isoformat()}&currency=SGD{_scope_q(include_restricted)}"
    sheet = (await client.get(f"/reports/balance-sheet?{q}")).json()
    series = (
        await client.get(
            f"/reports/net-worth/timeseries?from={PERIOD_START.isoformat()}&to={AS_OF.isoformat()}&granularity=monthly&currency=SGD{_scope_q(include_restricted)}"
        )
    ).json()
    alloc = (await client.get(f"/reports/net-worth/allocation?{q}")).json()
    assert series["points"][-1]["date"] == AS_OF.isoformat()
    eq_total = sum(
        (
            _money(sheet[k])
            for k in (
                "total_equity",
                "net_income",
                "unrealized_fx_gain_loss",
                "cta_adjustment",
                "net_worth_adjustment_gain_loss",
            )
        ),
        Decimal("0"),
    )
    return {
        "home": _money(sheet["total_assets"]) - _money(sheet["total_liabilities"]),
        "bs_eq": eq_total,
        "chart": _money(series["points"][-1]["net_worth"]),
        "portfolio": _money(alloc["net_worth"]),
    }


async def _assemble(db: AsyncSession, user_id: UUID, *, include_restricted: bool):
    return await PackageAssembler().assemble(
        db,
        user_id=user_id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=PERIOD_START,
        end_date=AS_OF,
        as_of_date=AS_OF,
        currency="SGD",
        include_restricted=include_restricted,
    )


@pytest.mark.parametrize(
    ("include_restricted", "expected"),
    [(None, FULL_NET_WORTH), (True, FULL_NET_WORTH), (False, LIQUID_NET_WORTH)],
    ids=["route-default", "include-restricted", "exclude-restricted"],
)
async def test_AC_reporting_net_worth_scope_1_every_surface_reads_one_net_worth(
    client: AsyncClient, db: AsyncSession, test_user, include_restricted: bool | None, expected: Decimal
) -> None:
    await _seed_issue_2645_account(db, test_user.id)
    worths = await _surface_net_worths(client, include_restricted)
    assert worths == dict.fromkeys(worths, expected)


@pytest.mark.parametrize(
    ("include_restricted", "expected_val_net"), [(True, PROPERTY + ESOP - MORTGAGE), (False, Decimal("0.00"))]
)
async def test_AC_reporting_net_worth_scope_2_manual_valuations_stay_out_of_fx_and_cta(
    client: AsyncClient, db: AsyncSession, test_user, include_restricted: bool, expected_val_net: Decimal
) -> None:
    await _seed_issue_2645_account(db, test_user.id)
    sheet = (
        await client.get(
            f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD{_scope_q(include_restricted)}"
        )
    ).json()
    assert (
        _money(sheet["unrealized_fx_gain_loss"]),
        _money(sheet["cta_adjustment"]),
        _money(sheet["net_worth_adjustment_gain_loss"]),
        sheet["is_balanced"],
    ) == (Decimal("0.00"), Decimal("0.00"), expected_val_net, True)


async def test_AC_reporting_net_worth_scope_3_and_8_excluded_classes_and_allocation_sources(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    await _seed_issue_2645_account(db, test_user.id)
    liquid = (
        await client.get(f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false")
    ).json()
    full = (
        await client.get(f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=true")
    ).json()
    excluded = {
        r["asset_class"]: (_money(r["total_assets"]), _money(r["total_liabilities"]), _money(r["net_worth"]))
        for r in liquid["excluded_holdings"]
    }
    assert excluded == {
        "real_estate": (PROPERTY, MORTGAGE, PROPERTY - MORTGAGE),
        "restricted_comp": (ESOP, Decimal("0.00"), ESOP),
    }
    assert [r["asset_class"] for r in liquid["excluded_holdings"]] == ["real_estate", "restricted_comp"] and full[
        "excluded_holdings"
    ] == []
    assert (_money(full["total_assets"]) - _money(full["total_liabilities"])) - sum(
        n for _, _, n in excluded.values()
    ) == _money(liquid["total_assets"]) - _money(liquid["total_liabilities"])

    assert (
        await client.get(
            f"/reports/net-worth/allocation?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false"
        )
    ).json()["excluded_holdings"] == liquid["excluded_holdings"]
    alloc_full = (
        await client.get(
            f"/reports/net-worth/allocation?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=true"
        )
    ).json()
    lines = [line for row in alloc_full["rows"] for line in row["source_lines"]]
    assert {frozenset(line) for line in lines} == {frozenset({"source_type", "source_id", "label", "value"})}
    by_label = {line["label"]: line for line in lines}
    assert (by_label["DBS Savings"]["source_type"], by_label["Valuation: Condo (property value)"]["source_type"]) == (
        "ledger_account",
        "manual_valuation",
    )
    assert (
        by_label["DBS Savings"]["source_id"] is not None
        and by_label["Valuation: Condo (property value)"]["source_id"] is not None
    )


async def test_AC_reporting_net_worth_scope_9_10_13_14_missing_valuation_fx_rate(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    await _seed_issue_2645_account(db, test_user.id)
    dq_normal = (await client.get(f"/reports/data-quality?as_of_date={AS_OF.isoformat()}&currency=SGD")).json()
    await seed_valuations(
        db,
        test_user.id,
        (
            ManualValuationComponentType.RSU,
            ManualValuationLiquidityClass.RESTRICTED,
            "1000.00",
            "USD",
            VALUATION_DATE,
            "Employer RSU",
        ),
        commit=True,
    )

    liquid = (
        await client.get(f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false")
    ).json()
    assert _money(liquid["total_assets"]) - _money(liquid["total_liabilities"]) == LIQUID_NET_WORTH
    rows = {r["asset_class"]: r for r in liquid["excluded_holdings"]}
    assert _money(rows["real_estate"]["net_worth"]) == PROPERTY - MORTGAGE and rows["real_estate"]["warnings"] == []
    restricted = rows["restricted_comp"]
    assert (restricted["total_assets"], restricted["total_liabilities"], restricted["net_worth"]) == (None, None, None)
    assert [(w["type"], w["source"], w["currency"], w["target_currency"]) for w in restricted["warnings"]] == [
        ("missing_fx_rate_excluded_holding", "Employer RSU", "USD", "SGD")
    ]

    full_resp = await client.get(
        f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=true"
    )
    assert full_resp.status_code == 400 and "No FX rate available" in full_resp.text

    dq_gap = (await client.get(f"/reports/data-quality?as_of_date={AS_OF.isoformat()}&currency=SGD")).json()
    assert "resolve_valuation_fx_rate" not in [i["id"] for i in dq_normal["action_items"]]
    fx_items = [i for i in dq_gap["action_items"] if i["id"] == "resolve_valuation_fx_rate"]
    assert [(i["action_type"], i["score_boost"], i["title"]) for i in fx_items] == [
        ("RESOLVE_FX_RATE", 0, "A Restricted Holding Has No FX Rate")
    ] and "No FX rate available for USD/SGD" in fx_items[0]["description"]
    assert (dq_gap["score"], dq_gap["equation_invariant"]) == (dq_normal["score"], dq_normal["equation_invariant"])

    doc = await _assemble(db, test_user.id, include_restricted=False)
    sched = doc.sections.annualized_income_long_term
    assert (
        sorted(h.ticker for h in sched.restricted_holdings) == ["Employer ESOP", "Employer RSU"]
        and sched.restricted_fair_value_total == ESOP
    )
    [excl] = sched.restricted_fair_value_total_excludes
    assert {k: v for k, v in excl.items() if k != "message"} == {
        "type": "missing_fx_rate_excluded_holding",
        "component_type": "rsu",
        "source": "Employer RSU",
        "currency": "USD",
        "target_currency": "SGD",
        "as_of_date": AS_OF.isoformat(),
        "amount": "1000.00",
    }
    assert (
        excl["message"].startswith("No FX rate available for USD/SGD")
        and any("Employer RSU (USD 1,000.00)" in n for n in sched.notes)
        and "restricted_holding_fx_unavailable" in [b.code for b in doc.readiness.blockers]
    )


async def test_AC_reporting_net_worth_scope_11_12_20_package_scope_and_disclosures(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    await _seed_issue_2645_account(db, test_user.id)
    liquid, full = (
        await _assemble(db, test_user.id, include_restricted=False),
        await _assemble(db, test_user.id, include_restricted=True),
    )
    note_fn = lambda d: next(n.disclosure for n in d.sections.notes.notes if n.note_id == "restricted-asset-treatment")
    assert [(r.asset_class, r.net_worth) for r in liquid.sections.balance_sheet.excluded_holdings] == [
        ("real_estate", PROPERTY - MORTGAGE),
        ("restricted_comp", ESOP),
    ]
    assert (
        liquid.sections.balance_sheet.total_assets - liquid.sections.balance_sheet.total_liabilities == LIQUID_NET_WORTH
    )
    assert "real estate SGD 550,000.00 net" in note_fn(liquid) and "restricted comp SGD 42,000.00 net" in note_fn(
        liquid
    )
    assert (
        full.sections.balance_sheet.excluded_holdings == []
        and "This package includes restricted and illiquid holdings" in note_fn(full)
    )
    assert (
        liquid.context.include_restricted,
        full.context.include_restricted,
        liquid.context.model_dump(mode="json")["include_restricted"],
    ) == (False, True, False)

    snap_resp = await client.post(
        "/reports/package/snapshots",
        json={
            "framework_id": "personal_us_gaap_like",
            "start_date": PERIOD_START.isoformat(),
            "end_date": AS_OF.isoformat(),
            "as_of_date": AS_OF.isoformat(),
            "currency": "SGD",
        },
    )
    assert snap_resp.status_code == 200 and [
        r["asset_class"] for r in snap_resp.json()["document"]["sections"]["balance_sheet"]["excluded_holdings"]
    ] == ["real_estate", "restricted_comp"]


def test_AC_reporting_net_worth_scope_11_20_22_pure_disclosures_and_legacy_shape() -> None:
    unconv = ExcludedHoldingRow(
        asset_class="restricted_comp",
        total_assets=None,
        total_liabilities=None,
        net_worth=None,
        warnings=[
            {"type": "missing_fx_rate_excluded_holding", "currency": "USD", "target_currency": "SGD"},
            {"type": "fx_conversion_failed_excluded_holding", "currency": "HKD", "target_currency": "SGD"},
        ],
    )
    assert (
        _restricted_asset_treatment_disclosure(
            "Base.", include_restricted=False, excluded_holdings=[unconv], currency="SGD"
        )
        == "Base. This package excludes these restricted and illiquid holdings, with the liabilities of their class, from the balance sheet: restricted comp: amount not available, FX conversion failed for HKD to SGD, no FX rate for USD to SGD."
    )
    assert (
        _restricted_asset_treatment_disclosure("Base.", include_restricted=False, excluded_holdings=[], currency="SGD")
        == "Base. On the as-of date this package excludes no restricted or illiquid holding: no such valuation is current on that date."
    )

    old_ctx = PersonalReportPackageContext.model_validate(
        {
            "framework_id": "personal_us_gaap_like",
            "start_date": "2025-11-01",
            "end_date": "2026-10-23",
            "as_of_date": "2026-10-23",
            "currency": "SGD",
        }
    )
    assert old_ctx.include_restricted is None and "include_restricted" not in old_ctx.model_dump(mode="json")

    stored = json.loads(MAIN_SHAPE_DOCUMENT.read_text(encoding="utf-8"))
    assert (
        "include_restricted" not in stored["context"]
        and "restricted_fair_value_total_excludes" not in stored["sections"]["annualized_income_long_term"]
    )
    assert (
        personal_report_package_target(
            snapshot_id=UUID(stored["snapshot_id"]),
            context=stored["context"],
            framework_policy=stored["framework_policy"],
            statement_disposition_policy=stored["statement_disposition_policy"],
            input_manifest=stored["input_manifest"],
            sections=stored["sections"],
        ).version
        == MAIN_SHAPE_DECISION_VERSION
    )
    doc = PersonalReportPackageDocument.model_validate(stored)
    assert (
        doc.model_dump(mode="json") == stored
        and personal_report_package_decision_ref(doc).target.version == MAIN_SHAPE_DECISION_VERSION
    )


@pytest.mark.parametrize(
    ("cause_name", "second_err", "expected_calls", "expected_title", "raises_match"),
    [
        ("NoObservationError", None, [True, False], "A Restricted Holding Has No FX Rate", None),
        ("PricingError", None, [True, False], "A Restricted Holding Did Not Convert to SGD", None),
        ("NoObservationError", ReportError("ledger FX rate missing"), [True, False], None, "ledger FX rate missing"),
        (None, ValueError("unsupported period"), [True], None, "unsupported period"),
    ],
)
async def test_AC_reporting_net_worth_scope_18_19_data_quality_fx_fallback_and_errors(
    db: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    cause_name: str | None,
    second_err: Exception | None,
    expected_calls: list[bool],
    expected_title: str | None,
    raises_match: str | None,
) -> None:
    import src.pricing as pricing
    import src.reporting.extension.data_quality_service as service

    calls: list[bool] = []

    def wrap(exc: Exception) -> ReportError:
        e = ReportError(str(exc))
        e.__cause__ = exc
        return e

    async def diagnostics(*_a, include_restricted: bool = True, **_kw):
        calls.append(include_restricted)
        if include_restricted and cause_name:
            raise wrap(getattr(pricing, cause_name)("No FX rate available for USD/SGD on 2026-10-23"))
        if second_err is not None:
            raise (second_err if isinstance(second_err, ReportError) else wrap(second_err))
        return EquationDiagnosticResult(
            is_balanced=False,
            equation_delta=Decimal("12.34"),
            primary_category=EquationDiagnosticCategory.UNKNOWN_DISCREPANCY,
            confidence=1.0,
            suggested_action="Check.",
        )

    monkeypatch.setattr(service, "run_balance_sheet_diagnostics", diagnostics)
    if raises_match:
        with pytest.raises(ReportError, match=raises_match):
            await service.compute_personal_data_quality(db, test_user.id, as_of_date=AS_OF, currency="SGD")
    else:
        res = await service.compute_personal_data_quality(db, test_user.id, as_of_date=AS_OF, currency="SGD")
        assert (res.equation_invariant.is_healthy, res.equation_invariant.delta) == (False, Decimal("12.34"))
        assert [i.title for i in res.action_items if i.id == "resolve_valuation_fx_rate"] == [expected_title]
    assert calls == expected_calls


async def test_issue_2659_cases_1_2_3_mixed_liquidity_and_coherence(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    bank, loan, opening = await seed_accounts(
        db,
        test_user.id,
        ("DBS Savings", AccountType.ASSET),
        ("Condo loan", AccountType.LIABILITY),
        ("Opening Balance", AccountType.EQUITY),
    )
    await post_pair(db, test_user.id, date(2025, 12, 1), "Opening cash", bank, opening, BANK_BALANCE)
    await post_pair(db, test_user.id, date(2025, 12, 1), "Opening mortgage", opening, loan, MORTGAGE)
    await seed_valuations(
        db,
        test_user.id,
        (
            ManualValuationComponentType.PROPERTY_VALUE,
            ManualValuationLiquidityClass.ILLIQUID,
            PROPERTY,
            "SGD",
            VALUATION_DATE,
            "Condo",
        ),
        commit=True,
    )
    assert await _surface_net_worths(client, False) == {
        "home": BANK_BALANCE,
        "bs_eq": BANK_BALANCE,
        "chart": BANK_BALANCE,
        "portfolio": BANK_BALANCE,
    }
    sheet = (
        await client.get(f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false")
    ).json()
    assert sheet["is_balanced"] is True and (_money(sheet["total_assets"]), _money(sheet["total_liabilities"])) == (
        BANK_BALANCE,
        Decimal("0.00"),
    )
    assert sheet["excluded_holdings"] == [
        {
            "asset_class": "real_estate",
            "total_assets": "1200000.00",
            "total_liabilities": "650000.00",
            "net_worth": "550000.00",
            "warnings": [],
        }
    ]
    assert await _surface_net_worths(client, True) == dict.fromkeys(
        ("home", "bs_eq", "chart", "portfolio"), BANK_BALANCE + PROPERTY - MORTGAGE
    )

    for payload in (
        {
            "component_type": "property_value",
            "as_of_date": "2026-09-30",
            "value": "1000000.00",
            "currency": "SGD",
            "source": "Property A",
        },
        {
            "component_type": "mortgage_balance",
            "as_of_date": "2026-09-30",
            "value": "400000.00",
            "currency": "SGD",
            "source": "Mortgage A",
        },
        {
            "component_type": "property_value",
            "as_of_date": "2026-09-30",
            "value": "500000.00",
            "currency": "SGD",
            "source": "Property B",
        },
        {
            "component_type": "mortgage_balance",
            "as_of_date": "2026-09-30",
            "value": "200000.00",
            "currency": "SGD",
            "source": "Mortgage B",
        },
        {
            "component_type": "property_value",
            "as_of_date": "2026-09-30",
            "value": "500000.00",
            "currency": "SGD",
            "source": "Property B",
            "liquidity_class": "liquid",
        },
    ):
        assert (await client.post("/pricing/manual-valuations", json=payload)).status_code == 201
    mixed = (
        await client.get(f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false")
    ).json()
    assert (_money(mixed["total_assets"]), _money(mixed["total_liabilities"]), mixed["is_balanced"]) == (
        Decimal("520360.65"),
        Decimal("200000.00"),
        True,
    )


async def test_issue_2659_case_3_different_first_dates_for_mortgage_and_property(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    bank, opening = await seed_accounts(
        db, test_user.id, ("DBS Savings", AccountType.ASSET), ("Opening Balance", AccountType.EQUITY)
    )
    await post_lines(
        db,
        test_user.id,
        date(2026, 1, 1),
        "Opening cash",
        [(bank, Direction.DEBIT, BANK_BALANCE), (opening, Direction.CREDIT, BANK_BALANCE)],
    )
    await seed_valuations(
        db,
        test_user.id,
        (
            ManualValuationComponentType.MORTGAGE_BALANCE,
            ManualValuationLiquidityClass.LIABILITY,
            MORTGAGE,
            "SGD",
            date(2026, 1, 31),
            "Condo loan",
        ),
        (
            ManualValuationComponentType.PROPERTY_VALUE,
            ManualValuationLiquidityClass.ILLIQUID,
            PROPERTY,
            "SGD",
            date(2026, 3, 31),
            "Condo",
        ),
        commit=True,
    )
    series = (
        await client.get(
            "/reports/net-worth/timeseries?from=2026-01-01&to=2026-04-30&granularity=monthly&currency=SGD&include_restricted=false"
        )
    ).json()
    assert [(p["date"], _money(p["total_liabilities"]), _money(p["net_worth"])) for p in series["points"]] == [
        ("2026-01-31", Decimal("0.00"), BANK_BALANCE),
        ("2026-02-28", Decimal("0.00"), BANK_BALANCE),
        ("2026-03-31", Decimal("0.00"), BANK_BALANCE),
        ("2026-04-30", Decimal("0.00"), BANK_BALANCE),
    ]
