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

from datetime import date
from decimal import Decimal
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
