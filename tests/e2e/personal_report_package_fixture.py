"""Reusable representative fixture contract for the personal report package E2E."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class BankTransactionFixture:
    txn_date: date
    description: str
    amount: Decimal


@dataclass(frozen=True)
class ManualValuationFixture:
    component_type: str
    value: Decimal
    source: str
    notes: str


@dataclass(frozen=True)
class PersonalReportPackageFixture:
    """Deterministic package-completeness fixture and exact expected outputs."""

    institution: str
    brokerage_source: str
    brokerage_institution: str
    currency: str
    bank_transactions: tuple[BankTransactionFixture, ...]
    property_value: ManualValuationFixture
    mortgage_balance: ManualValuationFixture
    esop: ManualValuationFixture
    rsu: ManualValuationFixture
    stock_options: ManualValuationFixture
    required_sections: frozenset[str]
    required_note_ids: frozenset[str]
    required_traceability_lines: frozenset[str]
    required_traceability_warnings: frozenset[str]

    @property
    def period_start(self) -> date:
        return min(row.txn_date for row in self.bank_transactions)

    @property
    def period_end(self) -> date:
        return max(row.txn_date for row in self.bank_transactions)

    @property
    def transaction_count(self) -> int:
        return len(self.bank_transactions)

    @property
    def income(self) -> Decimal:
        return _money(sum((row.amount for row in self.bank_transactions if row.amount > 0), Decimal("0.00")))

    @property
    def expenses(self) -> Decimal:
        return _money(sum((-row.amount for row in self.bank_transactions if row.amount < 0), Decimal("0.00")))

    @property
    def net_income(self) -> Decimal:
        return _money(self.income - self.expenses)

    @property
    def bank_cash(self) -> Decimal:
        return self.net_income

    @property
    def restricted_fair_value_total(self) -> Decimal:
        return _money(self.esop.value + self.rsu.value + self.stock_options.value)

    @property
    def mortgage_liability(self) -> Decimal:
        return self.mortgage_balance.value

    @property
    def net_worth_adjustment_gain_loss(self) -> Decimal:
        return _money(
            self.property_value.value
            + self.restricted_fair_value_total
            - self.mortgage_balance.value
        )

    def total_assets(self, brokerage_value: Decimal) -> Decimal:
        return _money(
            brokerage_value
            + self.property_value.value
            + self.restricted_fair_value_total
            + self.bank_cash
        )

    def write_bank_csv(self, directory: Path) -> Path:
        path = directory / "personal_report_package_bank_statement.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Date", "Description", "Amount"])
            for row in self.bank_transactions:
                writer.writerow([row.txn_date.isoformat(), row.description, str(row.amount)])
        return path


PERSONAL_REPORT_PACKAGE_FIXTURE = PersonalReportPackageFixture(
    institution="Personal Report Package Bank",
    brokerage_source="moomoo",
    brokerage_institution="Moomoo Personal Package",
    currency="SGD",
    bank_transactions=(
        BankTransactionFixture(date(2026, 5, 2), "Salary", Decimal("5000.00")),
        BankTransactionFixture(date(2026, 5, 3), "Freelance", Decimal("600.00")),
        BankTransactionFixture(date(2026, 5, 5), "Rent", Decimal("-1500.00")),
        BankTransactionFixture(date(2026, 5, 12), "Groceries", Decimal("-250.00")),
        BankTransactionFixture(date(2026, 5, 18), "Utilities", Decimal("-120.00")),
        BankTransactionFixture(date(2026, 5, 19), "Travel", Decimal("-3730.00")),
    ),
    property_value=ManualValuationFixture(
        component_type="property_value",
        value=Decimal("1100000.00"),
        source="Family Home",
        notes="Independent appraisal report reference A-12",
    ),
    mortgage_balance=ManualValuationFixture(
        component_type="mortgage_balance",
        value=Decimal("360000.00"),
        source="Home Loan",
        notes="Loan reference 2026-01",
    ),
    esop=ManualValuationFixture(
        component_type="esop",
        value=Decimal("85000.00"),
        source="ACME ESOP",
        notes="ESOP vesting starts over 4 years",
    ),
    rsu=ManualValuationFixture(
        component_type="rsu",
        value=Decimal("42000.00"),
        source="ACME RSU",
        notes="RSU vesting 25% annually",
    ),
    stock_options=ManualValuationFixture(
        component_type="stock_options",
        value=Decimal("29000.00"),
        source="ACME Options",
        notes="Stock options cliff vest at 3 years",
    ),
    required_sections=frozenset(
        {
            "balance_sheet",
            "income_statement",
            "cash_flow",
            "investment_performance",
            "annualized_income_long_term",
            "notes",
            "traceability_appendix",
        }
    ),
    required_note_ids=frozenset(
        {
            "basis-of-preparation",
            "reporting-period-and-currency",
            "valuation-basis",
            "investment-market-data",
            "source-confidence-review",
            "restricted-asset-treatment",
        }
    ),
    required_traceability_lines=frozenset(
        {
            "balance_sheet.total_assets",
            "income_statement.total_income",
            "income_statement.total_expenses",
            "cash_flow.net_cash_flow",
            "investment_performance.market_value",
            "annualized_income_long_term.annualized_total",
            "annualized_income_long_term.restricted_fair_value_total",
            "notes.non_compliance_statement",
        }
    ),
    required_traceability_warnings=frozenset(
        {
            "missing_source_anchor",
            "manual_only_source",
            "stale_market_data",
            "duplicate_source_coverage",
            "overlapping_statement_period",
        }
    ),
)
