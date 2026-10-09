#!/usr/bin/env python
"""Generate deterministic PDF + JSON fixtures for statement parsing tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from tools._lib.fixtures.statement_fixture_data import (
    STATEMENT_FIXTURES,
    StatementFixture,
    Transaction,
)

ROOT_DIR = Path(__file__).resolve().parents[3]
OUTPUT_DIR = ROOT_DIR / "common/testing/fixtures/pdf/generated"
PENNY = Decimal("0.01")


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
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Generated {pdf_path.relative_to(ROOT_DIR)}")
    print(f"Generated {json_path.relative_to(ROOT_DIR)}")


def get_fixtures() -> tuple[StatementFixture, ...]:
    return STATEMENT_FIXTURES


def main(argv: Sequence[str] | None = None) -> int:
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
    raise SystemExit(main())
