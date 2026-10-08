"""Tests for reporting service."""

from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import AccountType
from src.pricing import (
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
)
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)
from tests.reporting._report_fixtures import build_standard_chart_of_accounts, make_pair_entry


@pytest.fixture
async def chart_of_accounts(db: AsyncSession, test_user_id):
    """Create a minimal chart of accounts for reporting (shared builder, #1158)."""
    return await build_standard_chart_of_accounts(db, test_user_id)


async def test_balance_sheet_equation(db: AsyncSession, chart_of_accounts, test_user_id):
    """AC-reporting.balance-sheet.1: [AC5.1.1] Balance sheet should satisfy Assets = Liabilities + Equity."""
    cash, _liability, equity, *_rest = chart_of_accounts

    db.add(make_pair_entry(test_user_id, date.today(), "Owner contribution", cash, equity, "1000.00"))
    await db.commit()

    report = await generate_balance_sheet(
        db,
        test_user_id,
        as_of_date=date.today(),
        currency="SGD",
    )

    assert report["total_assets"] == Decimal("1000.00")
    assert report["total_liabilities"] == Decimal("0.00")
    assert report["total_equity"] == Decimal("1000.00")
    assert report["equation_delta"] == Decimal("0.00")
    assert report["is_balanced"] is True


async def test_AC22_13_1_report_amount_lines_expose_normalized_provenance(
    db: AsyncSession, chart_of_accounts, test_user_id
):
    """AC-reporting.provenance.1: AC22.13.1: report amount lines expose Imported/Manual/Derived provenance when known."""
    cash, _liability, equity, income, expense = chart_of_accounts

    manual_valuation = ManualValuationSnapshot(
        user_id=test_user_id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=date(2026, 1, 31),
        value=Decimal("900000.00"),
        currency="SGD",
        source="manual appraisal",
    )
    db.add_all(
        [
            make_pair_entry(
                test_user_id,
                date(2026, 1, 1),
                "Owner contribution",
                cash,
                equity,
                "1000.00",
                source_type=JournalEntrySourceType.MANUAL,
            ),
            make_pair_entry(
                test_user_id,
                date(2026, 1, 15),
                "Imported salary",
                cash,
                income,
                "5000.00",
                source_type=JournalEntrySourceType.AUTO_PARSED,
            ),
            make_pair_entry(
                test_user_id,
                date(2026, 1, 20),
                "System fee adjustment",
                expense,
                cash,
                "120.00",
                source_type=JournalEntrySourceType.SYSTEM,
            ),
            manual_valuation,
        ]
    )
    await db.commit()

    balance_sheet = await generate_balance_sheet(
        db,
        test_user_id,
        as_of_date=date(2026, 1, 31),
        currency="SGD",
    )
    income_statement = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        currency="SGD",
    )

    asset_by_name = {line["name"]: line for line in balance_sheet["assets"]}
    income_by_name = {line["name"]: line for line in income_statement["income"]}
    expense_by_name = {line["name"]: line for line in income_statement["expenses"]}

    assert asset_by_name["Cash"]["provenance"] == "derived"
    assert asset_by_name["Valuation: manual appraisal (property value)"]["provenance"] == "manual"
    assert income_by_name["Salary"]["provenance"] == "imported"
    assert expense_by_name["Dining"]["provenance"] == "derived"


async def test_income_statement_calculation(db: AsyncSession, chart_of_accounts, test_user_id):
    """AC-reporting.income-statement.1: [AC5.2.1] Income statement should satisfy Net Income = Income - Expenses."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    db.add_all(
        [
            make_pair_entry(test_user_id, date(2025, 1, 15), "Salary", cash, income, "5000.00"),
            make_pair_entry(test_user_id, date(2025, 1, 20), "Dinner", expense, cash, "200.00"),
        ]
    )
    await db.commit()

    report = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
    )

    assert report["total_income"] == Decimal("5000.00")
    assert report["total_expenses"] == Decimal("200.00")
    assert report["net_income"] == Decimal("4800.00")


async def test_reporting_dashboard_fixture_exact_totals(db: AsyncSession, chart_of_accounts, test_user_id, ac_evidence):
    """AC-reporting.kpis.2 · AC-reporting.lineage.2: [AC5.1.1][AC5.2.1][AC5.3.1][AC5.6.5] Deterministic fixture yields exact report totals."""
    cash, liability, equity, income, expense = chart_of_accounts

    db.add_all(
        [
            make_pair_entry(test_user_id, date(2025, 1, 1), "Owner contribution", cash, equity, "1000.00"),
            make_pair_entry(test_user_id, date(2025, 1, 10), "Salary", cash, income, "500.00"),
            make_pair_entry(test_user_id, date(2025, 1, 15), "Rent", expense, cash, "200.00"),
            make_pair_entry(test_user_id, date(2025, 1, 20), "Credit card drawdown", cash, liability, "300.00"),
        ]
    )
    await db.commit()

    balance_sheet = await generate_balance_sheet(
        db,
        test_user_id,
        as_of_date=date(2025, 1, 31),
        currency="SGD",
    )
    income_statement = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
    )
    cash_flow = await generate_cash_flow(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
    )

    assert balance_sheet["total_assets"] == Decimal("1600.00")
    assert balance_sheet["total_liabilities"] == Decimal("300.00")
    assert balance_sheet["total_equity"] == Decimal("1000.00")
    assert balance_sheet["net_income"] == Decimal("300.00")
    assert balance_sheet["unrealized_fx_gain_loss"] == Decimal("0.00")
    assert balance_sheet["net_worth_adjustment_gain_loss"] == Decimal("0.00")
    assert balance_sheet["equation_delta"] == Decimal("0.00")
    assert balance_sheet["is_balanced"] is True
    assert balance_sheet["assets"] == [
        {
            "account_id": cash.id,
            "name": "Cash",
            "type": AccountType.ASSET,
            "parent_id": None,
            "amount": Decimal("1600.00"),
            "provenance": "manual",
        }
    ]
    assert balance_sheet["liabilities"] == [
        {
            "account_id": liability.id,
            "name": "Credit Card",
            "type": AccountType.LIABILITY,
            "parent_id": None,
            "amount": Decimal("300.00"),
            "provenance": "manual",
        }
    ]
    # The day-one capital is a regular equity entry, not a recorded opening
    # balance, so completeness remains an explicit warning.
    assert any(w.get("type") == "missing_opening_balance" for w in balance_sheet["opening_balance_warnings"])

    assert income_statement["total_income"] == Decimal("500.00")
    assert income_statement["total_expenses"] == Decimal("200.00")
    assert income_statement["net_income"] == Decimal("300.00")
    assert income_statement["unrealized_fx_gain_loss"] == Decimal("0.00")
    assert income_statement["comprehensive_income"] == Decimal("300.00")
    assert income_statement["trends"] == [
        {
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 1, 31),
            "total_income": Decimal("500.00"),
            "total_expenses": Decimal("200.00"),
            "net_income": Decimal("300.00"),
        }
    ]

    assert cash_flow["operating"] == [
        {
            "category": "Operating",
            "subcategory": "Salary",
            "amount": Decimal("500.00"),
            "description": "Inflow - Salary",
            "account_id": income.id,
        },
        {
            "category": "Operating",
            "subcategory": "Dining",
            "amount": Decimal("-200.00"),
            "description": "Outflow - Dining",
            "account_id": expense.id,
        },
    ]
    assert cash_flow["investing"] == []
    assert cash_flow["financing"] == []
    # EPIC-022 AC22.7.1 (#887): every cash-flow line carries the account anchor
    # used for report drill-down.
    for line in cash_flow["operating"] + cash_flow["investing"] + cash_flow["financing"]:
        assert line["account_id"] is not None
    assert cash_flow["summary"] == {
        "operating_activities": Decimal("300.00"),
        "investing_activities": Decimal("0.00"),
        "financing_activities": Decimal("0.00"),
        "net_cash_flow": Decimal("1600.00"),
        "beginning_cash": Decimal("0.00"),
        "ending_cash": Decimal("1600.00"),
    }
    assert cash_flow["cash_bridge"]["unclassified_cash"] == Decimal("1300.00")
    assert cash_flow["proof_state"] == "unproven"

    # Behavioral evidence: each statement's headline total matches the golden value
    # computed from the deterministic fixture above; any drift in the report math
    # (sign rules, status/date filtering, FX) would move these numbers off the golden.
    ac_evidence(
        ac_id="AC-reporting.balance-sheet.1",
        score=1.0,
        metric="balance_sheet_totals_match_golden",
        comment="assets 1600.00, liabilities 300.00, equity 1000.00; equation balanced (delta 0.00)",
        provenance="deterministic",
    )
    ac_evidence(
        ac_id="AC-reporting.income-statement.1",
        score=1.0,
        metric="income_statement_net_income_match_golden",
        comment="income 500.00 - expenses 200.00 == net_income 300.00",
        provenance="deterministic",
    )
    ac_evidence(
        ac_id="AC-reporting.cash-flow.1",
        score=1.0,
        metric="cash_flow_net_match_golden",
        comment="operating 300.00 + unclassified 1300.00 == net_cash_flow 1600.00; ending_cash 1600.00",
        provenance="deterministic",
    )


async def test_balance_sheet_fx_error(db: AsyncSession, chart_of_accounts, test_user_id):
    cash, _liability, equity, *_rest = chart_of_accounts
    db.add(
        make_pair_entry(
            test_user_id, date.today(), "FX entry", cash, equity, "100.00", currency="USD", fx_rate=Decimal("1.00")
        )
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user_id, as_of_date=date.today(), currency="SGD")

    assert report["total_assets"] == Decimal("0.00")
    assert any(warning["type"] == "missing_fx_rate_partial_skip" for warning in report["fx_warnings"])


async def test_income_statement_invalid_range(db: AsyncSession, test_user_id):
    """AC-reporting.income-statement.3: [AC5.2.3] Test income statement invalid date range validation."""
    with pytest.raises(ReportError, match="start_date must be before end_date"):
        await generate_income_statement(
            db,
            test_user_id,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 1, 1),
            currency="SGD",
        )


async def test_income_statement_fx_error(db: AsyncSession, chart_of_accounts, test_user_id):
    cash, _liability, _equity, income, _expense = chart_of_accounts
    db.add(
        make_pair_entry(
            test_user_id, date(2025, 1, 15), "FX income", cash, income, "50.00", currency="USD", fx_rate=Decimal("1.00")
        )
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_income_statement(
            db,
            test_user_id,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            currency="SGD",
        )


async def test_account_trend_account_not_found(db: AsyncSession, test_user_id):
    with pytest.raises(ReportError, match="Account not found"):
        await get_account_trend(
            db,
            test_user_id,
            account_id=uuid4(),
            period="monthly",
            currency="SGD",
        )


async def test_account_trend_invalid_period(db: AsyncSession, chart_of_accounts, test_user_id):
    account = chart_of_accounts[0]
    with pytest.raises(ReportError, match="Unsupported period"):
        await get_account_trend(
            db,
            test_user_id,
            account_id=account.id,
            period="yearly",
            currency="SGD",
        )


async def test_account_trend_fx_error(db: AsyncSession, chart_of_accounts, test_user_id):
    account = chart_of_accounts[0]
    equity = chart_of_accounts[2]
    db.add(
        make_pair_entry(
            test_user_id, date.today(), "FX trend", account, equity, "10.00", currency="USD", fx_rate=Decimal("1.00")
        )
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available"):
        await get_account_trend(
            db,
            test_user_id,
            account_id=account.id,
            period="monthly",
            currency="SGD",
        )


async def test_category_breakdown_invalid_type(db: AsyncSession, test_user_id):
    with pytest.raises(ReportError, match="Breakdown type must be income or expense"):
        await get_category_breakdown(
            db,
            test_user_id,
            breakdown_type=AccountType.ASSET,
            period="monthly",
            currency="SGD",
        )


async def test_category_breakdown_invalid_period(db: AsyncSession, test_user_id):
    with pytest.raises(ReportError, match="Unsupported period"):
        await get_category_breakdown(
            db,
            test_user_id,
            breakdown_type=AccountType.INCOME,
            period="weekly",
            currency="SGD",
        )


async def test_category_breakdown_fx_error(db: AsyncSession, chart_of_accounts, test_user_id):
    cash = chart_of_accounts[0]
    expense = chart_of_accounts[-1]
    db.add(
        make_pair_entry(
            test_user_id, date.today(), "FX expense", expense, cash, "15.00", currency="USD", fx_rate=Decimal("1.00")
        )
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available"):
        await get_category_breakdown(
            db,
            test_user_id,
            breakdown_type=AccountType.EXPENSE,
            period="monthly",
            currency="SGD",
        )


async def test_cash_flow_invalid_range(db: AsyncSession, test_user_id):
    with pytest.raises(ReportError, match="start_date must be before end_date"):
        await generate_cash_flow(
            db,
            test_user_id,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 1, 1),
            currency="SGD",
        )


async def test_cash_flow_fx_error_before(db: AsyncSession, chart_of_accounts, test_user_id):
    account = chart_of_accounts[0]
    equity = chart_of_accounts[2]
    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 1, 1),
            "FX before",
            account,
            equity,
            "5.00",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_cash_flow(
            db,
            test_user_id,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 2, 28),
            currency="SGD",
        )


async def test_cash_flow_fx_error_during(db: AsyncSession, chart_of_accounts, test_user_id):
    account = chart_of_accounts[0]
    equity = chart_of_accounts[2]
    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 2, 10),
            "FX during",
            account,
            equity,
            "7.00",
            currency="USD",
            fx_rate=Decimal("1.00"),
        )
    )
    await db.commit()

    with pytest.raises(ReportError, match="No FX rate available"):
        await generate_cash_flow(
            db,
            test_user_id,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 2, 28),
            currency="SGD",
        )


async def test_account_trend_daily_weekly(db: AsyncSession, chart_of_accounts, test_user_id):
    account = chart_of_accounts[0]

    daily = await get_account_trend(
        db,
        test_user_id,
        account_id=account.id,
        period="daily",
        currency="SGD",
    )
    weekly = await get_account_trend(
        db,
        test_user_id,
        account_id=account.id,
        period="weekly",
        currency="SGD",
    )

    assert daily["period"] == "daily"
    assert weekly["period"] == "weekly"


async def test_category_breakdown_annual(db: AsyncSession, test_user_id):
    report = cast(
        dict[str, Any],
        await get_category_breakdown(
            db,
            test_user_id,
            breakdown_type=AccountType.INCOME,
            period="annual",
            currency="SGD",
        ),
    )

    assert cast(date, report["period_start"]).year == date.today().year


async def test_cash_flow_balances_before_period(db: AsyncSession, chart_of_accounts, test_user_id) -> None:
    account = chart_of_accounts[0]
    equity = chart_of_accounts[2]
    db.add(make_pair_entry(test_user_id, date(2025, 1, 1), "Before period", account, equity, "20.00"))
    await db.commit()

    report = await generate_cash_flow(
        db,
        test_user_id,
        start_date=date(2025, 2, 1),
        end_date=date(2025, 2, 28),
        currency="SGD",
    )

    assert "summary" in report


async def test_account_trend_monthly(db: AsyncSession, chart_of_accounts, test_user_id, monkeypatch):
    """Account trend should bucket entries by month."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    class FixedDate(date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2025, 3, 15)

    monkeypatch.setattr("src.reporting.extension.net_worth.date", FixedDate)

    db.add_all(
        [
            make_pair_entry(test_user_id, FixedDate(2024, 12, 10), "Salary", cash, income, "100.00"),
            make_pair_entry(test_user_id, FixedDate(2025, 2, 5), "Dinner", expense, cash, "40.00"),
        ]
    )
    await db.commit()

    report = cast(
        dict[str, Any],
        await get_account_trend(
            db,
            test_user_id,
            account_id=cash.id,
            period="monthly",
            currency="SGD",
        ),
    )

    points = {point["period_start"]: point["amount"] for point in cast(list[dict[str, Any]], report["points"])}
    assert points[FixedDate(2024, 12, 1)] == Decimal("100.00")
    assert points[FixedDate(2025, 2, 1)] == Decimal("-40.00")


async def test_category_breakdown_quarterly(db: AsyncSession, chart_of_accounts, test_user_id, monkeypatch):
    """Category breakdown should aggregate within the selected period."""
    cash, _liability, _equity, _income, expense = chart_of_accounts

    class FixedDate(date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2025, 3, 15)

    monkeypatch.setattr("src.reporting.extension.net_worth.date", FixedDate)

    db.add(make_pair_entry(test_user_id, FixedDate(2025, 2, 10), "Expense", expense, cash, "120.00"))
    await db.commit()

    report = cast(
        dict[str, Any],
        await get_category_breakdown(
            db,
            test_user_id,
            breakdown_type=AccountType.EXPENSE,
            period="quarterly",
            currency="SGD",
        ),
    )

    assert cast(list[dict[str, Any]], report["items"])[0]["total"] == Decimal("120.00")


async def test_cash_flow_statement(db: AsyncSession, chart_of_accounts, test_user_id):
    """AC-reporting.cash-flow.1: [AC5.3.1] Cash flow statement should track movements across periods."""
    cash, _liability, equity, income, expense = chart_of_accounts

    db.add_all(
        [
            make_pair_entry(test_user_id, date(2025, 1, 15), "Owner contribution", cash, equity, "5000.00"),
            make_pair_entry(test_user_id, date(2025, 1, 20), "Salary income", cash, income, "3000.00"),
            make_pair_entry(test_user_id, date(2025, 1, 25), "Office supplies", expense, cash, "500.00"),
        ]
    )
    await db.commit()

    report = cast(
        dict[str, Any],
        await generate_cash_flow(
            db,
            test_user_id,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            currency="SGD",
        ),
    )

    assert "operating" in report
    assert "investing" in report
    assert "financing" in report
    assert "summary" in report
    assert report["currency"] == "SGD"
    assert report["start_date"] == date(2025, 1, 1)
    assert report["end_date"] == date(2025, 1, 31)

    operating: list[dict] = report["operating"]
    investing: list[dict] = report["investing"]
    financing: list[dict] = report["financing"]

    operating_names = [item["subcategory"] for item in operating]
    investing_names = [item["subcategory"] for item in investing]
    assert income.name in operating_names, "Income account should be in operating activities"
    assert expense.name in operating_names, "Expense account should be in operating activities"
    assert financing == [], "Equity without explicit event semantics must remain unclassified"
    # Cash accounts are excluded from activity categories - they ARE the cash flow
    # Their movements are reflected in beginning_cash and ending_cash
    assert cash.name not in investing_names, "Cash account should NOT be in investing (it's the subject of the report)"

    summary: dict = report["summary"]
    assert "operating_activities" in summary
    assert "investing_activities" in summary
    assert "financing_activities" in summary
    assert "net_cash_flow" in summary
    assert "beginning_cash" in summary
    assert "ending_cash" in summary
    assert summary == {
        "operating_activities": Decimal("2500.00"),
        "investing_activities": Decimal("0.00"),
        "financing_activities": Decimal("0.00"),
        "net_cash_flow": Decimal("7500.00"),
        "beginning_cash": Decimal("0.00"),
        "ending_cash": Decimal("7500.00"),
    }
    assert report["cash_bridge"]["unclassified_cash"] == Decimal("5000.00")
    assert report["proof_state"] == "unproven"


async def test_cash_flow_empty_period(db: AsyncSession, chart_of_accounts, test_user_id):
    """AC-reporting.cash-flow.2: [AC5.3.2] Cash flow statement with no transactions should return empty lists."""
    report = cast(
        dict[str, Any],
        await generate_cash_flow(
            db,
            test_user_id,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            currency="SGD",
        ),
    )

    assert report["operating"] == []
    assert report["investing"] == []
    assert report["financing"] == []
    assert cast(dict[str, Any], report["summary"])["net_cash_flow"] == Decimal("0.00")


async def test_income_statement_with_tags_filter(db: AsyncSession, chart_of_accounts, test_user_id):
    """Income statement should filter by tags when specified."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    db.add_all(
        [
            make_pair_entry(
                test_user_id,
                date(2025, 1, 15),
                "Tagged salary",
                cash,
                income,
                "5000.00",
                tags={"business": True, "project": "alpha"},
            ),
            make_pair_entry(test_user_id, date(2025, 1, 20), "Personal gift", cash, income, "1000.00"),
        ]
    )
    await db.commit()

    report_with_business_tag: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["business"],
    )

    assert report_with_business_tag["total_income"] == Decimal("5000.00")
    assert report_with_business_tag["filters_applied"]["tags"] == ["business"]

    report_with_all_tags: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["business", "personal"],
    )

    assert report_with_all_tags["total_income"] == Decimal("5000.00")


async def test_income_statement_with_account_type_filter(db: AsyncSession, chart_of_accounts, test_user_id):
    """Income statement should filter by account type when specified."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    db.add_all(
        [
            make_pair_entry(test_user_id, date(2025, 1, 15), "Income entry", cash, income, "5000.00"),
            make_pair_entry(test_user_id, date(2025, 1, 16), "Expense entry", expense, cash, "2000.00"),
        ]
    )
    await db.commit()

    report_income_only: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        account_type=AccountType.INCOME,
    )

    assert report_income_only["total_income"] == Decimal("5000.00")
    assert report_income_only["total_expenses"] == Decimal("0.00")
    assert report_income_only["filters_applied"]["account_type"] == "INCOME"
    assert len(report_income_only["expenses"]) == 0

    report_expense_only: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        account_type=AccountType.EXPENSE,
    )

    assert report_expense_only["total_income"] == Decimal("0.00")
    assert report_expense_only["total_expenses"] == Decimal("2000.00")
    assert report_expense_only["filters_applied"]["account_type"] == "EXPENSE"
    assert len(report_expense_only["income"]) == 0


async def test_income_statement_combined_filters(db: AsyncSession, chart_of_accounts, test_user_id):
    """Income statement should support combined tags and account_type filters."""
    cash, _liability, _equity, income, expense = chart_of_accounts

    db.add_all(
        [
            make_pair_entry(
                test_user_id, date(2025, 1, 15), "Business income", cash, income, "3000.00", tags={"business": True}
            ),
            make_pair_entry(test_user_id, date(2025, 1, 16), "Personal income", cash, income, "2000.00"),
        ]
    )
    await db.commit()

    report: dict = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        currency="SGD",
        tags=["business"],
        account_type=AccountType.INCOME,
    )

    assert report["total_income"] == Decimal("3000.00")
    assert report["filters_applied"]["tags"] == ["business"]
    assert report["filters_applied"]["account_type"] == "INCOME"


async def test_income_statement_fallback_rate(db: AsyncSession, chart_of_accounts, test_user_id, monkeypatch):
    """Test fallback to convert_amount when PrefetchedFxRates returns None."""
    from src.pricing import PrefetchedFxRates
    from src.pricing.orm.market_data import FxRate as FxRateModel

    cash, _liability, _equity, income, _expense = chart_of_accounts

    # Add rate to DB
    db.add(
        FxRateModel(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2025, 1, 31),
            source="test",
        )
    )

    db.add(
        make_pair_entry(
            test_user_id,
            date(2025, 1, 15),
            "USD income",
            cash,
            income,
            "100.00",
            currency="USD",
            fx_rate=Decimal("1.35"),
        )
    )
    await db.commit()

    # Mock get_rate to return None, forcing fallback
    monkeypatch.setattr(PrefetchedFxRates, "get_rate", lambda self, *args, **kwargs: None)

    report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
    )

    # If it didn't raise error and returned correct value, fallback worked
    assert report["total_income"] == Decimal("135.00")


def test_iter_periods_daily_limit():
    """Test that _iter_periods respects the MAX_TREND_POINTS limit."""
    from datetime import date, timedelta

    from src.reporting.extension.reporting_calc import MAX_TREND_POINTS, _iter_periods

    # 1000 days span
    start = date(2020, 1, 1)
    end = start + timedelta(days=999)

    spans = _iter_periods(start, end, "daily")
    assert len(spans) == MAX_TREND_POINTS + 1
