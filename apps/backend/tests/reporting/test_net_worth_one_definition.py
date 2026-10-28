"""One net worth for Home, the balance sheet, the net worth chart and Portfolio (#2645).

The fixture is the data of the #2645 report: one SGD bank account that statements
fill, and three manual valuations dated 2026-09-30 (property, mortgage, ESOP).
Each test reads the API routes that the four surfaces read:

- Home and the `/reports` Overview: ``total_assets - total_liabilities`` of
  ``GET /reports/balance-sheet`` (``StatementCockpit``).
- The Balance sheet tab: the equity side total of the same response.
- The net worth chart: the last point of ``GET /reports/net-worth/timeseries``.
- Portfolio: ``net_worth`` of ``GET /reports/net-worth/allocation``.
"""

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
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass
from src.pricing.orm.manual_valuation import ManualValuationSnapshot

AS_OF = date(2026, 10, 23)
# The first day of the default 1Y period of the dimension bar that ends on AS_OF.
PERIOD_START = date(2025, 11, 1)
VALUATION_DATE = date(2026, 9, 30)

BANK_BALANCE = Decimal("20360.65")
PROPERTY = Decimal("1200000.00")
MORTGAGE = Decimal("650000.00")
ESOP = Decimal("42000.00")

FULL_NET_WORTH = BANK_BALANCE + PROPERTY + ESOP - MORTGAGE  # 612,360.65
# Without restricted holdings, the property, its mortgage and the ESOP are all out.
LIQUID_NET_WORTH = BANK_BALANCE


async def _post(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    memo: str,
    debit: Account,
    credit: Account,
    amount: Decimal,
) -> None:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        source_type=JournalEntrySourceType.AUTO_PARSED,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=debit.id,
                direction=Direction.DEBIT,
                amount=amount,
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency="SGD",
            ),
        ]
    )
    await db.flush()


async def _seed_issue_2645_account(db: AsyncSession, user_id: UUID) -> None:
    """Build the #2645 data: an SGD bank account and three manual valuations."""
    bank = Account(user_id=user_id, name="DBS Savings", type=AccountType.ASSET, currency="SGD")
    opening = Account(user_id=user_id, name="Opening Balance", type=AccountType.EQUITY, currency="SGD")
    salary = Account(user_id=user_id, name="Salary", type=AccountType.INCOME, currency="SGD")
    groceries = Account(user_id=user_id, name="Groceries", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([bank, opening, salary, groceries])
    await db.flush()

    await _post(db, user_id, date(2025, 12, 1), "Opening balance", bank, opening, Decimal("15000.00"))
    await _post(db, user_id, date(2026, 8, 25), "Salary", bank, salary, Decimal("8000.00"))
    await _post(db, user_id, date(2026, 9, 15), "Groceries", groceries, bank, Decimal("2639.35"))

    for component_type, liquidity_class, value, source in (
        (ManualValuationComponentType.PROPERTY_VALUE, ManualValuationLiquidityClass.ILLIQUID, PROPERTY, "Condo"),
        (
            ManualValuationComponentType.MORTGAGE_BALANCE,
            ManualValuationLiquidityClass.LIABILITY,
            MORTGAGE,
            "Condo loan",
        ),
        (ManualValuationComponentType.ESOP, ManualValuationLiquidityClass.RESTRICTED, ESOP, "Employer ESOP"),
    ):
        db.add(
            ManualValuationSnapshot(
                user_id=user_id,
                component_type=component_type,
                liquidity_class=liquidity_class,
                value=value,
                currency="SGD",
                as_of_date=VALUATION_DATE,
                source=source,
            )
        )
    await db.commit()


def _scope_query(include_restricted: bool | None) -> str:
    """The query parameter of one scope. None sends no parameter, so the route default applies."""
    if include_restricted is None:
        return ""
    return f"&include_restricted={'true' if include_restricted else 'false'}"


async def _get(client: AsyncClient, url: str) -> dict[str, Any]:
    response = await client.get(url)
    assert response.status_code == 200, f"GET {url} returned {response.status_code}: {response.text}"
    return response.json()


def _money(value: object) -> Decimal:
    return Decimal(str(value))


async def _surface_net_worths(client: AsyncClient, include_restricted: bool | None) -> dict[str, Decimal]:
    """Read the net worth of each surface for one as-of date and one scope."""
    scope = _scope_query(include_restricted)
    sheet = await _get(client, f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD{scope}")
    series = await _get(
        client,
        f"/reports/net-worth/timeseries?from={PERIOD_START.isoformat()}&to={AS_OF.isoformat()}"
        f"&granularity=monthly&currency=SGD{scope}",
    )
    allocation = await _get(client, f"/reports/net-worth/allocation?as_of_date={AS_OF.isoformat()}&currency=SGD{scope}")
    last_point = series["points"][-1]
    assert last_point["date"] == AS_OF.isoformat()
    equity_side_total = sum(
        (
            _money(sheet[key])
            for key in (
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
        "balance_sheet_equity_total": equity_side_total,
        "net_worth_chart_last_point": _money(last_point["net_worth"]),
        "portfolio": _money(allocation["net_worth"]),
    }


@pytest.mark.parametrize(
    ("include_restricted", "expected"),
    [
        (None, FULL_NET_WORTH),
        (True, FULL_NET_WORTH),
        (False, LIQUID_NET_WORTH),
    ],
    ids=["route-default", "include-restricted", "exclude-restricted"],
)
async def test_AC_reporting_net_worth_scope_1_every_surface_reads_one_net_worth(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    include_restricted: bool | None,
    expected: Decimal,
) -> None:
    """AC-reporting.net-worth-scope.1: for one as-of date and one scope, the four surfaces show one net worth.

    The route default is the full scope on each route, so a caller that sends no
    scope gets the same figure from each route.
    """
    await _seed_issue_2645_account(db, test_user.id)

    net_worths = await _surface_net_worths(client, include_restricted)

    assert net_worths == dict.fromkeys(net_worths, expected)


@pytest.mark.parametrize(
    ("include_restricted", "expected_valuation_net"),
    [(True, PROPERTY + ESOP - MORTGAGE), (False, Decimal("0.00"))],
    ids=["include-restricted", "exclude-restricted"],
)
async def test_AC_reporting_net_worth_scope_2_manual_valuations_stay_out_of_fx_and_cta(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    include_restricted: bool,
    expected_valuation_net: Decimal,
) -> None:
    """AC-reporting.net-worth-scope.2: a manual valuation goes to the valuation adjustment, never to FX or CTA.

    The data has one currency, so unrealized FX and CTA are zero. The valuation
    adjustment is the net of the manual valuations in the scope: an excluded
    property takes its mortgage out with it.
    """
    await _seed_issue_2645_account(db, test_user.id)

    sheet = await _get(
        client,
        f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD{_scope_query(include_restricted)}",
    )

    assert _money(sheet["unrealized_fx_gain_loss"]) == Decimal("0.00")
    assert _money(sheet["cta_adjustment"]) == Decimal("0.00")
    assert _money(sheet["net_worth_adjustment_gain_loss"]) == expected_valuation_net
    assert sheet["is_balanced"] is True


async def test_AC_reporting_net_worth_scope_3_balance_sheet_names_each_excluded_class_and_amount(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.net-worth-scope.3: a scope without restricted holdings names each excluded class and amount.

    Each excluded class carries its excluded assets, its excluded liabilities and
    their net. The full net worth minus the excluded nets is the scoped net worth.
    """
    await _seed_issue_2645_account(db, test_user.id)

    liquid = await _get(
        client, f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false"
    )
    full = await _get(
        client, f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=true"
    )

    excluded = {
        row["asset_class"]: (
            _money(row["total_assets"]),
            _money(row["total_liabilities"]),
            _money(row["net_worth"]),
        )
        for row in liquid["excluded_holdings"]
    }
    assert excluded == {
        "real_estate": (PROPERTY, MORTGAGE, PROPERTY - MORTGAGE),
        "restricted_comp": (ESOP, Decimal("0.00"), ESOP),
    }
    assert [row["asset_class"] for row in liquid["excluded_holdings"]] == ["real_estate", "restricted_comp"]
    assert full["excluded_holdings"] == []
    full_net_worth = _money(full["total_assets"]) - _money(full["total_liabilities"])
    liquid_net_worth = _money(liquid["total_assets"]) - _money(liquid["total_liabilities"])
    assert full_net_worth - sum(net for _, _, net in excluded.values()) == liquid_net_worth

    # Portfolio reads the same rows from the allocation route.
    allocation = await _get(
        client, f"/reports/net-worth/allocation?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false"
    )
    assert allocation["excluded_holdings"] == liquid["excluded_holdings"]


async def test_AC_reporting_net_worth_scope_8_allocation_sources_carry_no_link(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.net-worth-scope.8: an allocation source line carries its type and id, and no link.

    The API cannot know the app routes; it sent API paths as links (#2645). The
    app opens the lineage drawer for a ledger account and the evidence drawer for
    a manual valuation from ``source_type`` and ``source_id``.
    """
    await _seed_issue_2645_account(db, test_user.id)

    allocation = await _get(
        client, f"/reports/net-worth/allocation?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=true"
    )

    lines = [line for row in allocation["rows"] for line in row["source_lines"]]
    assert {frozenset(line) for line in lines} == {frozenset({"source_type", "source_id", "label", "value"})}
    by_label = {line["label"]: line for line in lines}
    bank = by_label["DBS Savings"]
    assert bank["source_type"] == "ledger_account"
    assert bank["source_id"] is not None
    condo = by_label["Valuation: Condo (property value)"]
    assert condo["source_type"] == "manual_valuation"
    assert condo["source_id"] is not None


async def _add_usd_rsu_without_fx_rate(db: AsyncSession, user_id: UUID) -> None:
    """Add a restricted USD valuation. The test database holds no USD rate, so it cannot convert."""
    db.add(
        ManualValuationSnapshot(
            user_id=user_id,
            component_type=ManualValuationComponentType.RSU,
            liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
            value=Decimal("1000.00"),
            currency="USD",
            as_of_date=VALUATION_DATE,
            source="Employer RSU",
        )
    )
    await db.commit()


async def test_AC_reporting_net_worth_scope_9_excluded_valuation_without_fx_rate_does_not_fail_the_report(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.net-worth-scope.9: an FX miss on an excluded valuation is a row warning, not an error.

    The liquid totals do not depend on the excluded rows. The row of the class with
    the unconverted valuation has no amounts and names the valuation. The other
    rows keep their amounts.
    """
    await _seed_issue_2645_account(db, test_user.id)
    await _add_usd_rsu_without_fx_rate(db, test_user.id)

    liquid = await _get(
        client, f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false"
    )

    assert _money(liquid["total_assets"]) - _money(liquid["total_liabilities"]) == LIQUID_NET_WORTH
    rows = {row["asset_class"]: row for row in liquid["excluded_holdings"]}
    assert _money(rows["real_estate"]["net_worth"]) == PROPERTY - MORTGAGE
    assert rows["real_estate"]["warnings"] == []
    restricted = rows["restricted_comp"]
    assert (restricted["total_assets"], restricted["total_liabilities"], restricted["net_worth"]) == (None, None, None)
    assert [(w["type"], w["source"], w["currency"], w["target_currency"]) for w in restricted["warnings"]] == [
        ("missing_fx_rate_excluded_holding", "Employer RSU", "USD", "SGD")
    ]


async def test_AC_reporting_net_worth_scope_10_included_valuation_without_fx_rate_still_fails_the_report(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.net-worth-scope.10: an FX miss on an included valuation fails the report as before.

    The full scope includes the USD RSU, so its total needs the rate: the route
    answers 400 with the FX error of ``ReportError``.
    """
    await _seed_issue_2645_account(db, test_user.id)
    await _add_usd_rsu_without_fx_rate(db, test_user.id)

    response = await client.get(
        f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=true"
    )

    assert response.status_code == 400, response.text
    assert "No FX rate available" in response.text


async def _assemble_package(db: AsyncSession, user_id: UUID, *, include_restricted: bool):
    from src.reporting import PersonalReportingFrameworkId
    from src.reporting.extension.package_document import PackageAssembler

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


def _restricted_treatment_note(document) -> str:
    return next(
        note.disclosure for note in document.sections.notes.notes if note.note_id == "restricted-asset-treatment"
    )


async def test_AC_reporting_net_worth_scope_11_package_discloses_each_excluded_class(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.net-worth-scope.11: the report package names each class that its scope excludes, with amounts.

    The package presents the liquid net worth by default. Its balance sheet carries
    the excluded rows, and the restricted-asset-treatment note names each class with
    its net, assets and liabilities, so the total reconciles to the full net worth.
    """
    await _seed_issue_2645_account(db, test_user.id)

    liquid = await _assemble_package(db, test_user.id, include_restricted=False)
    full = await _assemble_package(db, test_user.id, include_restricted=True)

    sheet = liquid.sections.balance_sheet
    assert [(row.asset_class, row.net_worth) for row in sheet.excluded_holdings] == [
        ("real_estate", PROPERTY - MORTGAGE),
        ("restricted_comp", ESOP),
    ]
    assert sheet.total_assets - sheet.total_liabilities == LIQUID_NET_WORTH
    note = _restricted_treatment_note(liquid)
    assert "real estate SGD 550,000.00 net (assets SGD 1,200,000.00, liabilities SGD 650,000.00)" in note, note
    assert "restricted comp SGD 42,000.00 net (assets SGD 42,000.00, liabilities SGD 0.00)" in note, note

    assert full.sections.balance_sheet.excluded_holdings == []
    assert full.sections.balance_sheet.total_assets - full.sections.balance_sheet.total_liabilities == FULL_NET_WORTH
    assert "This package includes restricted and illiquid holdings" in _restricted_treatment_note(full)


def test_AC_reporting_net_worth_scope_11_package_note_names_rows_without_amounts_and_the_empty_scope() -> None:
    """AC-reporting.net-worth-scope.11: the package note covers a row without amounts and a scope with no row."""
    from src.reporting.extension.package_document import _restricted_asset_treatment_disclosure
    from src.schemas.reporting import ExcludedHoldingRow

    unconverted = ExcludedHoldingRow(
        asset_class="restricted_comp",
        total_assets=None,
        total_liabilities=None,
        net_worth=None,
        warnings=[
            {"type": "missing_fx_rate_excluded_holding", "currency": "USD", "target_currency": "SGD"},
            {"type": "fx_conversion_failed_excluded_holding", "currency": "HKD", "target_currency": "SGD"},
        ],
    )
    note = _restricted_asset_treatment_disclosure(
        "Base.", include_restricted=False, excluded_holdings=[unconverted], currency="SGD"
    )
    assert note == (
        "Base. This package excludes these restricted and illiquid holdings, with the liabilities of their class, "
        "from the balance sheet: restricted comp: amount not available, FX conversion failed for HKD to SGD, "
        "no FX rate for USD to SGD."
    )

    empty = _restricted_asset_treatment_disclosure(
        "Base.", include_restricted=False, excluded_holdings=[], currency="SGD"
    )
    assert empty == (
        "Base. On the as-of date this package excludes no restricted or illiquid holding: "
        "no such valuation is current on that date."
    )


async def test_AC_reporting_net_worth_scope_12_generate_without_scope_reads_the_package_default(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.net-worth-scope.12: a generate body without include_restricted reads PACKAGE_INCLUDE_RESTRICTED.

    The app sends no scope. The route then builds the liquid package, so the frozen
    balance sheet names the excluded classes.
    """
    await _seed_issue_2645_account(db, test_user.id)

    response = await client.post(
        "/reports/package/generate",
        json={
            "framework_id": "personal_us_gaap_like",
            "start_date": PERIOD_START.isoformat(),
            "end_date": AS_OF.isoformat(),
            "as_of_date": AS_OF.isoformat(),
            "currency": "SGD",
        },
    )

    assert response.status_code == 200, response.text
    sheet = response.json()["document"]["sections"]["balance_sheet"]
    assert [row["asset_class"] for row in sheet["excluded_holdings"]] == ["real_estate", "restricted_comp"]


async def test_AC_reporting_net_worth_scope_13_data_quality_stays_available_without_a_valuation_fx_rate(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.net-worth-scope.13: a restricted valuation without an FX rate is an action item on data quality.

    The full scope cannot convert the USD RSU. The page still answers 200 with the same
    score, and one action item names the missing rate.
    """
    await _seed_issue_2645_account(db, test_user.id)
    url = f"/reports/data-quality?as_of_date={AS_OF.isoformat()}&currency=SGD"

    normal = await _get(client, url)
    await _add_usd_rsu_without_fx_rate(db, test_user.id)
    gap = await _get(client, url)

    assert "resolve_valuation_fx_rate" not in [item["id"] for item in normal["action_items"]]
    fx_items = [item for item in gap["action_items"] if item["id"] == "resolve_valuation_fx_rate"]
    assert [(item["action_type"], item["score_boost"], item["title"]) for item in fx_items] == [
        ("RESOLVE_FX_RATE", 0, "A Restricted Holding Has No FX Rate")
    ]
    assert "No FX rate available for USD/SGD" in fx_items[0]["description"]
    assert gap["score"] == normal["score"]
    assert gap["equation_invariant"] == normal["equation_invariant"]


async def test_AC_reporting_net_worth_scope_14_package_lists_a_restricted_holding_without_fx_rate(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.net-worth-scope.14: a restricted holding without an FX rate does not fail the package.

    The annualized schedule lists the USD RSU in its own currency, leaves it out of the
    restricted fair-value total and names it. The package readiness has a blocker for it.
    """
    await _seed_issue_2645_account(db, test_user.id)
    await _add_usd_rsu_without_fx_rate(db, test_user.id)

    document = await _assemble_package(db, test_user.id, include_restricted=False)

    schedule = document.sections.annualized_income_long_term
    assert sorted(holding.ticker for holding in schedule.restricted_holdings) == ["Employer ESOP", "Employer RSU"]
    assert schedule.restricted_fair_value_total == ESOP
    # A structured row with the conversion_warning shape of an excluded balance-sheet valuation.
    [row] = schedule.restricted_fair_value_total_excludes
    assert {key: value for key, value in row.items() if key != "message"} == {
        "type": "missing_fx_rate_excluded_holding",
        "component_type": "rsu",
        "source": "Employer RSU",
        "currency": "USD",
        "target_currency": "SGD",
        "as_of_date": AS_OF.isoformat(),
        "amount": "1000.00",
    }
    assert row["message"].startswith("No FX rate available for USD/SGD")
    assert any("Employer RSU (USD 1,000.00)" in note for note in schedule.notes)
    assert "restricted_holding_fx_unavailable" in [blocker.code for blocker in document.readiness.blockers]


def _diagnostic(*, is_balanced: bool):
    from src.reporting.base.diagnostics import EquationDiagnosticCategory, EquationDiagnosticResult

    return EquationDiagnosticResult(
        is_balanced=is_balanced,
        equation_delta=Decimal("0.00") if is_balanced else Decimal("12.34"),
        primary_category=(
            EquationDiagnosticCategory.BALANCED if is_balanced else EquationDiagnosticCategory.UNKNOWN_DISCREPANCY
        ),
        confidence=1.0,
        suggested_action="Check the ledger.",
    )


def _report_error_from(cause: Exception):
    from src.reporting import ReportError

    error = ReportError(str(cause))
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("cause_name", "title"),
    [
        ("NoObservationError", "A Restricted Holding Has No FX Rate"),
        ("PricingError", "A Restricted Holding Did Not Convert to SGD"),
    ],
)
async def test_AC_reporting_net_worth_scope_18_data_quality_reads_the_liquid_check_after_an_fx_error(
    db: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    cause_name: str,
    title: str,
) -> None:
    """AC-reporting.net-worth-scope.18: after a full-scope FX error, data quality reads the liquid check result.

    The second run excludes restricted holdings, and its result (here: out of balance)
    is the equation invariant. The action item title names the cause.
    """
    import src.pricing as pricing
    import src.reporting.extension.data_quality_service as service

    calls: list[bool] = []

    async def diagnostics(*_args, include_restricted: bool = True, **_kwargs):
        calls.append(include_restricted)
        if include_restricted:
            raise _report_error_from(getattr(pricing, cause_name)("No FX rate available for USD/SGD on 2026-10-23"))
        return _diagnostic(is_balanced=False)

    monkeypatch.setattr(service, "run_balance_sheet_diagnostics", diagnostics)

    result = await service.compute_personal_data_quality(db, test_user.id, as_of_date=AS_OF, currency="SGD")

    assert calls == [True, False]
    assert result.equation_invariant.is_healthy is False
    assert result.equation_invariant.delta == Decimal("12.34")
    assert [item.title for item in result.action_items if item.id == "resolve_valuation_fx_rate"] == [title]


async def test_AC_reporting_net_worth_scope_19_data_quality_raises_other_errors(
    db: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-reporting.net-worth-scope.19: data quality falls back only for an FX error of the full scope.

    An error of the liquid run propagates. A ReportError whose cause is not a pricing
    error propagates without a second run.
    """
    import src.reporting.extension.data_quality_service as service
    from src.pricing import NoObservationError
    from src.reporting import ReportError

    calls: list[bool] = []

    async def both_fail(*_args, include_restricted: bool = True, **_kwargs):
        calls.append(include_restricted)
        if include_restricted:
            raise _report_error_from(NoObservationError("No FX rate available for USD/SGD"))
        raise ReportError("ledger FX rate missing")

    monkeypatch.setattr(service, "run_balance_sheet_diagnostics", both_fail)
    with pytest.raises(ReportError, match="ledger FX rate missing"):
        await service.compute_personal_data_quality(db, test_user.id, as_of_date=AS_OF, currency="SGD")
    assert calls == [True, False]

    calls.clear()

    async def other_cause(*_args, include_restricted: bool = True, **_kwargs):
        calls.append(include_restricted)
        raise _report_error_from(ValueError("unsupported period"))

    monkeypatch.setattr(service, "run_balance_sheet_diagnostics", other_cause)
    with pytest.raises(ReportError, match="unsupported period"):
        await service.compute_personal_data_quality(db, test_user.id, as_of_date=AS_OF, currency="SGD")
    assert calls == [True]


async def test_AC_reporting_net_worth_scope_20_package_records_its_scope(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.net-worth-scope.20: the package context records include_restricted, and the dump of a
    document frozen before #2645 (no value) stays without the key, so its decision coordinates stay equal.
    """
    from src.schemas.reporting import PersonalReportPackageContext

    await _seed_issue_2645_account(db, test_user.id)

    liquid = await _assemble_package(db, test_user.id, include_restricted=False)
    full = await _assemble_package(db, test_user.id, include_restricted=True)

    assert liquid.context.include_restricted is False
    assert full.context.include_restricted is True
    assert liquid.context.model_dump(mode="json")["include_restricted"] is False

    old = PersonalReportPackageContext.model_validate(
        {
            "framework_id": "personal_us_gaap_like",
            "start_date": "2025-11-01",
            "end_date": "2026-10-23",
            "as_of_date": "2026-10-23",
            "currency": "SGD",
        }
    )
    assert old.include_restricted is None
    assert "include_restricted" not in old.model_dump(mode="json")


MAIN_SHAPE_DOCUMENT = Path(__file__).resolve().parents[1] / "fixtures" / "package_document_main_shape.json"
# personal_report_package_target over the stored JSON: the version that main bound at freeze time.
MAIN_SHAPE_DECISION_VERSION = "aacc713256b0f0411ce8c416598a2b75ddbb8a0634fe0e4036f773f2094da538"


def test_AC_reporting_net_worth_scope_22_main_shape_document_keeps_its_decision_version() -> None:
    """AC-reporting.net-worth-scope.22: a package frozen on main reloads to the same JSON and decision version.

    The fixture is a frozen document in the shape of main 685533f0f: its context has no
    include_restricted and its annualized section has no restricted_fair_value_total_excludes.
    A field that the reload adds to the dump changes the rebuilt decision version.
    """
    from src.reporting import personal_report_package_decision_ref
    from src.reporting.base.package_decision import personal_report_package_target
    from src.schemas.reporting import PersonalReportPackageDocument

    stored = json.loads(MAIN_SHAPE_DOCUMENT.read_text(encoding="utf-8"))
    assert "include_restricted" not in stored["context"]
    assert "restricted_fair_value_total_excludes" not in stored["sections"]["annualized_income_long_term"]
    at_freeze = personal_report_package_target(
        snapshot_id=UUID(stored["snapshot_id"]),
        context=stored["context"],
        framework_policy=stored["framework_policy"],
        statement_disposition_policy=stored["statement_disposition_policy"],
        input_manifest=stored["input_manifest"],
        sections=stored["sections"],
    ).version
    assert at_freeze == MAIN_SHAPE_DECISION_VERSION

    document = PersonalReportPackageDocument.model_validate(stored)

    assert document.model_dump(mode="json") == stored
    assert personal_report_package_decision_ref(document).target.version == MAIN_SHAPE_DECISION_VERSION


async def test_issue_2659_case_1_ledger_liability_and_manual_property_valuation(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
) -> None:
    """#2659 Case 1: a ledger liability account linked to an excluded property leaves with it in the liquid scope."""
    bank = Account(user_id=test_user.id, name="DBS Savings", type=AccountType.ASSET, currency="SGD")
    loan = Account(user_id=test_user.id, name="Condo loan", type=AccountType.LIABILITY, currency="SGD")
    opening = Account(user_id=test_user.id, name="Opening Balance", type=AccountType.EQUITY, currency="SGD")
    db.add_all([bank, loan, opening])
    await db.flush()

    await _post(db, test_user.id, date(2025, 12, 1), "Opening cash", bank, opening, BANK_BALANCE)
    await _post(db, test_user.id, date(2025, 12, 1), "Opening mortgage", opening, loan, MORTGAGE)
    db.add(
        ManualValuationSnapshot(
            user_id=test_user.id,
            component_type=ManualValuationComponentType.PROPERTY_VALUE,
            liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
            value=PROPERTY,
            currency="SGD",
            as_of_date=VALUATION_DATE,
            source="Condo",
        )
    )
    await db.commit()

    liquid_worths = await _surface_net_worths(client, False)
    assert liquid_worths == dict.fromkeys(liquid_worths, BANK_BALANCE)

    sheet = await _get(
        client, f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false"
    )
    assert sheet["is_balanced"] is True
    assert _money(sheet["total_assets"]) == BANK_BALANCE
    assert _money(sheet["total_liabilities"]) == Decimal("0.00")
    assert sheet["excluded_holdings"] == [
        {
            "asset_class": "real_estate",
            "total_assets": "1200000.00",
            "total_liabilities": "650000.00",
            "net_worth": "550000.00",
            "warnings": [],
        }
    ]


async def test_issue_2659_case_2_mixed_liquidity_in_one_class(
    client: AsyncClient,
) -> None:
    """#2659 Case 2: setting Property B to liquid via PATCH keeps Property B and Mortgage B while excluding A."""
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
    ):
        resp = await client.post("/assets/valuation-snapshots", json=payload)
        assert resp.status_code == 201
        if payload["source"] == "Property B":
            prop_b_id = resp.json()["id"]

    patch_resp = await client.patch(
        f"/assets/valuation-snapshots/{prop_b_id}",
        json={"liquidity_class": "liquid"},
    )
    assert patch_resp.status_code == 200

    sheet = await _get(
        client, f"/reports/balance-sheet?as_of_date={AS_OF.isoformat()}&currency=SGD&include_restricted=false"
    )
    assert _money(sheet["total_assets"]) == Decimal("500000.00")
    assert _money(sheet["total_liabilities"]) == Decimal("200000.00")
    assert _money(sheet["total_assets"]) - _money(sheet["total_liabilities"]) == Decimal("300000.00")
    assert sheet["is_balanced"] is True
    assert sheet["excluded_holdings"] == [
        {
            "asset_class": "real_estate",
            "total_assets": "1000000.00",
            "total_liabilities": "400000.00",
            "net_worth": "600000.00",
            "warnings": [],
        }
    ]


async def test_issue_2659_case_3_different_first_dates_for_mortgage_and_property(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
) -> None:
    """#2659 Case 3: a mortgage valuation dated 2026-01-31 with its illiquid property dated 2026-03-31 is excluded on all liquid series points."""
    bank = Account(user_id=test_user.id, name="DBS Savings", type=AccountType.ASSET, currency="SGD")
    opening = Account(user_id=test_user.id, name="Opening Balance", type=AccountType.EQUITY, currency="SGD")
    db.add_all([bank, opening])
    await db.flush()
    await _post(db, test_user.id, date(2026, 1, 1), "Opening cash", bank, opening, BANK_BALANCE)
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.MORTGAGE_BALANCE,
                liquidity_class=ManualValuationLiquidityClass.LIABILITY,
                value=MORTGAGE,
                currency="SGD",
                as_of_date=date(2026, 1, 31),
                source="Condo loan",
            ),
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.PROPERTY_VALUE,
                liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
                value=PROPERTY,
                currency="SGD",
                as_of_date=date(2026, 3, 31),
                source="Condo",
            ),
        ]
    )
    await db.commit()

    series = await _get(
        client,
        "/reports/net-worth/timeseries?from=2026-01-01&to=2026-04-30&granularity=monthly&currency=SGD&include_restricted=false",
    )
    assert [
        (point["date"], _money(point["total_liabilities"]), _money(point["net_worth"])) for point in series["points"]
    ] == [
        ("2026-01-31", Decimal("0.00"), BANK_BALANCE),
        ("2026-02-28", Decimal("0.00"), BANK_BALANCE),
        ("2026-03-31", Decimal("0.00"), BANK_BALANCE),
        ("2026-04-30", Decimal("0.00"), BANK_BALANCE),
    ]
