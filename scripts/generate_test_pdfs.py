#!/usr/bin/env python
"""Generate deterministic PDF + JSON fixtures for statement parsing tests."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "apps/backend/tests/fixtures/generated"
PENNY = Decimal("0.01")


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


def money_str(value: Decimal) -> str:
    return format(value.quantize(PENNY, rounding=ROUND_HALF_UP), ".2f")


def money_with_commas(value: Decimal) -> str:
    return f"{value.quantize(PENNY, rounding=ROUND_HALF_UP):,.2f}"


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    gitkeep_path = OUTPUT_DIR / ".gitkeep"
    if not gitkeep_path.exists():
        gitkeep_path.write_text("", encoding="utf-8")


def compute_balances(
    opening_balance: Decimal, txns: tuple[Transaction, ...]
) -> list[Decimal]:
    running = opening_balance
    balances: list[Decimal] = []
    for txn in txns:
        signed = txn.amount if txn.direction == "IN" else -txn.amount
        running = (running + signed).quantize(PENNY, rounding=ROUND_HALF_UP)
        balances.append(running)
    return balances


def dbs_raw_text(txn: Transaction) -> str:
    year, month, day = txn.date.split("-")
    month_lookup = {
        "01": "Jan",
        "02": "Feb",
        "03": "Mar",
        "04": "Apr",
        "05": "May",
        "06": "Jun",
        "07": "Jul",
        "08": "Aug",
        "09": "Sep",
        "10": "Oct",
        "11": "Nov",
        "12": "Dec",
    }
    display = f"{int(day):02d} {month_lookup[month]} {year}"
    amount = money_with_commas(txn.amount)
    suffix = " CR" if txn.direction == "IN" else ""
    return f"{display} {txn.description} {amount}{suffix}"


def dd_mmm_yyyy(iso_date: str) -> str:
    parsed = date.fromisoformat(iso_date)
    return parsed.strftime("%d %b %Y")


def build_expected_json(fixture: StatementFixture, balances: list[Decimal]) -> dict:
    events = []
    for txn, balance_after in zip(fixture.transactions, balances, strict=True):
        if fixture.institution == "DBS":
            raw_text = dbs_raw_text(txn)
        elif fixture.institution == "CMB":
            signed = txn.amount if txn.direction == "IN" else -txn.amount
            raw_text = (
                f"{txn.date} {txn.description} {money_str(signed)} "
                f"{money_str(balance_after)}"
            )
        elif fixture.institution == "GXS":
            sign = "+" if txn.direction == "IN" else "-"
            raw_text = f"{txn.date} {txn.description} {sign}{money_str(txn.amount)}"
        else:
            sign = "+" if txn.direction == "IN" else "-"
            raw_text = f"{txn.date} {txn.description} {sign}{money_str(txn.amount)}"

        events.append(
            {
                "date": txn.date,
                "description": txn.description,
                "amount": money_str(txn.amount),
                "direction": txn.direction,
                "reference": txn.reference,
                "currency": fixture.currency,
                "balance_after": money_str(balance_after),
                "confidence": 0.95,
                "raw_text": raw_text,
                "suggested_category": txn.suggested_category,
                "category_confidence": float(txn.category_confidence),
            }
        )

    closing_balance = balances[-1]
    return {
        "file": fixture.pdf_name,
        "institution": fixture.institution,
        "success": True,
        "statement": {
            "period_start": fixture.period_start,
            "period_end": fixture.period_end,
            "opening_balance": money_str(fixture.opening_balance),
            "closing_balance": money_str(closing_balance),
            "currency": fixture.currency,
            "confidence_score": fixture.confidence_score,
            "balance_validated": True,
            "account_last4": fixture.account_last4,
        },
        "events": events,
    }


def draw_common_header(
    pdf: canvas.Canvas,
    fixture: StatementFixture,
    closing_balance: Decimal,
    font_name: str,
) -> float:
    width, height = A4
    y = height - 56
    pdf.setFont(font_name, 16)
    pdf.drawString(48, y, fixture.header)

    y -= 24
    pdf.setFont(font_name, 10)
    pdf.drawString(48, y, f"Account Number: {fixture.account_masked}")
    y -= 16
    pdf.drawString(
        48, y, f"Statement Period: {fixture.period_start} to {fixture.period_end}"
    )
    y -= 16
    pdf.drawString(
        48,
        y,
        f"Opening Balance: {fixture.currency} {money_str(fixture.opening_balance)}",
    )
    y -= 16
    pdf.drawString(
        48, y, f"Closing Balance: {fixture.currency} {money_str(closing_balance)}"
    )
    return y - 24


def draw_dbs_table(
    pdf: canvas.Canvas, fixture: StatementFixture, balances: list[Decimal], y: float
) -> None:
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(48, y, "Date")
    pdf.drawString(128, y, "Description")
    pdf.drawString(350, y, "Amount")
    pdf.drawString(440, y, "Balance")
    pdf.line(48, y - 4, 545, y - 4)

    y -= 20
    pdf.setFont("Helvetica", 9)
    for txn, balance_after in zip(fixture.transactions, balances, strict=True):
        suffix = " CR" if txn.direction == "IN" else ""
        pdf.drawString(48, y, dd_mmm_yyyy(txn.date))
        pdf.drawString(128, y, txn.description)
        pdf.drawRightString(420, y, f"{money_with_commas(txn.amount)}{suffix}")
        pdf.drawRightString(540, y, money_with_commas(balance_after))
        y -= 17


def draw_cmb_table(
    pdf: canvas.Canvas, fixture: StatementFixture, balances: list[Decimal], y: float
) -> None:
    pdf.setFont("STSong-Light", 10)
    pdf.drawString(48, y, "交易日期")
    pdf.drawString(136, y, "摘要")
    pdf.drawString(320, y, "交易金额")
    pdf.drawString(430, y, "账户余额")
    pdf.line(48, y - 4, 545, y - 4)

    y -= 20
    for txn, balance_after in zip(fixture.transactions, balances, strict=True):
        signed = txn.amount if txn.direction == "IN" else -txn.amount
        pdf.drawString(48, y, txn.date)
        pdf.drawString(136, y, txn.description)
        pdf.drawRightString(410, y, money_with_commas(signed))
        pdf.drawRightString(540, y, money_with_commas(balance_after))
        y -= 17


def draw_gxs_table(
    pdf: canvas.Canvas, fixture: StatementFixture, balances: list[Decimal], y: float
) -> None:
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(48, y, "Date")
    pdf.drawString(122, y, "Description")
    pdf.drawString(356, y, "Money In")
    pdf.drawString(430, y, "Money Out")
    pdf.drawString(500, y, "Balance")
    pdf.line(48, y - 4, 545, y - 4)

    y -= 20
    pdf.setFont("Helvetica", 9)
    for txn, balance_after in zip(fixture.transactions, balances, strict=True):
        money_in = money_with_commas(txn.amount) if txn.direction == "IN" else ""
        money_out = money_with_commas(txn.amount) if txn.direction == "OUT" else ""
        pdf.drawString(48, y, txn.date)
        pdf.drawString(122, y, txn.description)
        pdf.drawRightString(410, y, money_in)
        pdf.drawRightString(486, y, money_out)
        pdf.drawRightString(540, y, money_with_commas(balance_after))
        y -= 17


def draw_maribank_table(
    pdf: canvas.Canvas, fixture: StatementFixture, balances: list[Decimal], y: float
) -> None:
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(48, y, "Date")
    pdf.drawString(126, y, "Activity")
    pdf.drawString(390, y, "Amount")
    pdf.drawString(470, y, "Running Bal")
    pdf.line(48, y - 4, 545, y - 4)

    y -= 20
    pdf.setFont("Helvetica", 9)
    for txn, balance_after in zip(fixture.transactions, balances, strict=True):
        sign = "+" if txn.direction == "IN" else "-"
        pdf.drawString(48, y, txn.date)
        pdf.drawString(126, y, txn.description)
        pdf.drawRightString(446, y, f"{sign}{money_with_commas(txn.amount)}")
        pdf.drawRightString(540, y, money_with_commas(balance_after))
        y -= 17


def write_fixture_pdf_and_json(fixture: StatementFixture) -> None:
    balances = compute_balances(fixture.opening_balance, fixture.transactions)
    closing_balance = balances[-1]
    pdf_path = OUTPUT_DIR / fixture.pdf_name
    json_path = OUTPUT_DIR / fixture.json_name

    pdf = canvas.Canvas(str(pdf_path), pagesize=A4, pageCompression=0, invariant=1)
    pdf.setTitle(f"{fixture.institution} Statement Fixture")
    pdf.setAuthor("finance-report-tests")
    pdf.setCreator("generate_test_pdfs.py")
    pdf.setSubject("Deterministic extraction test fixture")

    font_name = "Helvetica"
    if fixture.institution == "CMB":
        font_name = "STSong-Light"

    y = draw_common_header(pdf, fixture, closing_balance, font_name)
    if fixture.institution == "DBS":
        draw_dbs_table(pdf, fixture, balances, y)
    elif fixture.institution == "CMB":
        draw_cmb_table(pdf, fixture, balances, y)
    elif fixture.institution == "GXS":
        draw_gxs_table(pdf, fixture, balances, y)
    else:
        draw_maribank_table(pdf, fixture, balances, y)

    pdf.showPage()
    pdf.save()

    payload = build_expected_json(fixture, balances)
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Generated {pdf_path.relative_to(ROOT_DIR)}")
    print(f"Generated {json_path.relative_to(ROOT_DIR)}")


def get_fixtures() -> tuple[StatementFixture, ...]:
    return (
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


def main() -> int:
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception as exc:
        print(f"Failed to register Chinese font: {exc}")
        return 1

    ensure_output_dir()
    for fixture in get_fixtures():
        write_fixture_pdf_and_json(fixture)

    print("Done: generated 4 deterministic PDF fixtures with expected JSON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
