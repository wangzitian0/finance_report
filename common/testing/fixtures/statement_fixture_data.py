"""
Deterministic static test fixture data for banking statement parsing.

Defines StatementFixture and Transaction dataclasses and the four standard
sample statements (DBS, CMB, GXS, and MariBank).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Transaction:
    date: str
    description: str
    amount: Decimal
    direction: str
    reference: str | None
    suggested_category: str
    category_confidence: Decimal


@dataclass(frozen=True)
class StatementFixture:
    institution: str
    pdf_name: str
    json_name: str
    header: str
    account_masked: str
    account_last4: str
    currency: str
    period_start: str
    period_end: str
    opening_balance: Decimal
    confidence_score: int
    transactions: tuple[Transaction, ...]


STATEMENT_FIXTURES: tuple[StatementFixture, ...] = (
    StatementFixture(
        institution="DBS",
        pdf_name="dbs_statement_fixture.pdf",
        json_name="dbs_statement_fixture_expected.json",
        header="DBS BANK LTD - DEPOSIT ACCOUNT STATEMENT",
        account_masked="XXX-X-3456",
        account_last4="3456",
        currency="SGD",
        period_start="2025-01-01",
        period_end="2025-01-31",
        opening_balance=Decimal("12000.00"),
        confidence_score=96,
        transactions=(
            Transaction(
                "2025-01-03",
                "FAST CREDIT PAYROLL ACME PTE LTD",
                Decimal("5200.00"),
                "IN",
                None,
                "Salary",
                Decimal("0.95"),
            ),
            Transaction(
                "2025-01-05",
                "PAYNOW TO UEN 201912345A RENT JAN",
                Decimal("2200.00"),
                "OUT",
                None,
                "Rent",
                Decimal("0.92"),
            ),
            Transaction(
                "2025-01-09",
                "GIRO SINGTEL MOBILE BILL",
                Decimal("86.40"),
                "OUT",
                None,
                "Utilities",
                Decimal("0.87"),
            ),
            Transaction(
                "2025-01-12",
                "POS NTUC FAIRPRICE BEDOK",
                Decimal("128.75"),
                "OUT",
                None,
                "Food & Dining",
                Decimal("0.86"),
            ),
            Transaction(
                "2025-01-16",
                "FAST CREDIT FREELANCE PROJECT",
                Decimal("900.00"),
                "IN",
                None,
                "Salary",
                Decimal("0.82"),
            ),
            Transaction(
                "2025-01-21",
                "PAYNOW TO JOHN TAN",
                Decimal("300.00"),
                "OUT",
                None,
                "Transfer",
                Decimal("0.84"),
            ),
            Transaction(
                "2025-01-28",
                "GIRO SP SERVICES UTILITIES",
                Decimal("142.80"),
                "OUT",
                None,
                "Utilities",
                Decimal("0.88"),
            ),
        ),
    ),
    StatementFixture(
        institution="CMB",
        pdf_name="cmb_statement_fixture.pdf",
        json_name="cmb_statement_fixture_expected.json",
        header="招商银行个人账户月结单",
        account_masked="6225 **** **** 7788",
        account_last4="7788",
        currency="CNY",
        period_start="2025-02-01",
        period_end="2025-02-28",
        opening_balance=Decimal("38500.00"),
        confidence_score=95,
        transactions=(
            Transaction(
                "2025-02-03",
                "工资入账",
                Decimal("18000.00"),
                "IN",
                None,
                "Salary",
                Decimal("0.95"),
            ),
            Transaction(
                "2025-02-05",
                "转账-房租",
                Decimal("6800.00"),
                "OUT",
                None,
                "Rent",
                Decimal("0.93"),
            ),
            Transaction(
                "2025-02-08",
                "微信支付-超市",
                Decimal("356.20"),
                "OUT",
                None,
                "Food & Dining",
                Decimal("0.86"),
            ),
            Transaction(
                "2025-02-12",
                "转账-父母",
                Decimal("2000.00"),
                "OUT",
                None,
                "Transfer",
                Decimal("0.88"),
            ),
            Transaction(
                "2025-02-18",
                "报销入账",
                Decimal("980.50"),
                "IN",
                None,
                "Other",
                Decimal("0.74"),
            ),
            Transaction(
                "2025-02-23",
                "水电费代扣",
                Decimal("420.75"),
                "OUT",
                None,
                "Utilities",
                Decimal("0.85"),
            ),
            Transaction(
                "2025-02-27",
                "利息收入",
                Decimal("35.88"),
                "IN",
                None,
                "Investment",
                Decimal("0.78"),
            ),
        ),
    ),
    StatementFixture(
        institution="GXS",
        pdf_name="gxs_statement_fixture.pdf",
        json_name="gxs_statement_fixture_expected.json",
        header="GXS BANK - DIGITAL SAVINGS STATEMENT",
        account_masked="GXS-ACC-****-9912",
        account_last4="9912",
        currency="SGD",
        period_start="2025-03-01",
        period_end="2025-03-31",
        opening_balance=Decimal("8500.00"),
        confidence_score=97,
        transactions=(
            Transaction(
                "2025-03-02",
                "Interest Earned",
                Decimal("1.20"),
                "IN",
                None,
                "Investment",
                Decimal("0.92"),
            ),
            Transaction(
                "2025-03-03",
                "PayNow from ALVIN GOH",
                Decimal("450.00"),
                "IN",
                None,
                "Transfer",
                Decimal("0.84"),
            ),
            Transaction(
                "2025-03-05",
                "Payment to GrabPay Wallet",
                Decimal("120.00"),
                "OUT",
                None,
                "Transport",
                Decimal("0.80"),
            ),
            Transaction(
                "2025-03-09",
                "Interest Earned",
                Decimal("1.22"),
                "IN",
                None,
                "Investment",
                Decimal("0.92"),
            ),
            Transaction(
                "2025-03-14",
                "PayNow to MERCHANT HAWKER",
                Decimal("45.60"),
                "OUT",
                None,
                "Food & Dining",
                Decimal("0.83"),
            ),
            Transaction(
                "2025-03-18",
                "Interest Earned",
                Decimal("1.18"),
                "IN",
                None,
                "Investment",
                Decimal("0.92"),
            ),
            Transaction(
                "2025-03-26",
                "Payment to GrabPay Wallet",
                Decimal("80.00"),
                "OUT",
                None,
                "Transport",
                Decimal("0.80"),
            ),
            Transaction(
                "2025-03-30",
                "Interest Earned",
                Decimal("1.21"),
                "IN",
                None,
                "Investment",
                Decimal("0.92"),
            ),
        ),
    ),
    StatementFixture(
        institution="MariBank",
        pdf_name="maribank_statement_fixture.pdf",
        json_name="maribank_statement_fixture_expected.json",
        header="MARIBANK ACCOUNT ACTIVITY STATEMENT",
        account_masked="MB-****-4421",
        account_last4="4421",
        currency="SGD",
        period_start="2025-04-01",
        period_end="2025-04-30",
        opening_balance=Decimal("4200.00"),
        confidence_score=96,
        transactions=(
            Transaction(
                "2025-04-02",
                "PayNow to KOPI SHOP PTE LTD",
                Decimal("18.50"),
                "OUT",
                None,
                "Food & Dining",
                Decimal("0.89"),
            ),
            Transaction(
                "2025-04-04",
                "Interest Credited",
                Decimal("0.88"),
                "IN",
                None,
                "Investment",
                Decimal("0.90"),
            ),
            Transaction(
                "2025-04-07",
                "PayNow to RIDE-HAIL SERVICES",
                Decimal("26.30"),
                "OUT",
                None,
                "Transport",
                Decimal("0.85"),
            ),
            Transaction(
                "2025-04-11",
                "Credit Card Repayment",
                Decimal("1200.00"),
                "OUT",
                None,
                "Transfer",
                Decimal("0.91"),
            ),
            Transaction(
                "2025-04-15",
                "PayNow from LEE WEI",
                Decimal("300.00"),
                "IN",
                None,
                "Transfer",
                Decimal("0.83"),
            ),
            Transaction(
                "2025-04-22",
                "Interest Credited",
                Decimal("0.91"),
                "IN",
                None,
                "Investment",
                Decimal("0.90"),
            ),
            Transaction(
                "2025-04-27",
                "PayNow to ONLINE GROCER",
                Decimal("142.70"),
                "OUT",
                None,
                "Food & Dining",
                Decimal("0.86"),
            ),
        ),
    ),
)
