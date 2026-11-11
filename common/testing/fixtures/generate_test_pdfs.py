#!/usr/bin/env python
"""Generate deterministic PDF + JSON fixtures for statement parsing tests."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from common.testing.fixtures.statement_fixture_data import (
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
    gitkeep = OUTPUT_DIR / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")


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


def dd_mmm_yyyy(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%d %b %Y")


def mm_dd_yyyy(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%m/%d/%Y")


def de_date_str(iso_date: str) -> str:
    return date.fromisoformat(iso_date).strftime("%d.%m.%Y")


def money_de_str(value: Decimal) -> str:
    return (
        money_with_commas(value).replace(",", "_").replace(".", ",").replace("_", ".")
    )


def dbs_raw_text(txn: Transaction) -> str:
    suffix = " CR" if txn.direction == "IN" else ""
    return f"{dd_mmm_yyyy(txn.date)} {txn.description} {money_with_commas(txn.amount)}{suffix}"


def _raw_text(inst: str, txn: Transaction, bal: Decimal) -> str:
    sign = "+" if txn.direction == "IN" else "-"
    if inst == "DBS":
        return dbs_raw_text(txn)
    if inst in ("CMB", "ICBC"):
        signed = txn.amount if txn.direction == "IN" else -txn.amount
        return f"{txn.date} {txn.description} {money_str(signed)} {money_str(bal)}"
    if inst == "Sparkasse":
        marker = "H" if txn.direction == "IN" else "S"
        return f"{de_date_str(txn.date)} {txn.description} {money_de_str(txn.amount)} {marker}"
    if inst == "Barclays":
        return f"{dd_mmm_yyyy(txn.date)} {txn.description} {'IN' if txn.direction == 'IN' else 'OUT'} {money_str(txn.amount)}"
    if inst == "Chase":
        return f"{mm_dd_yyyy(txn.date)} {txn.description} {sign}{money_str(txn.amount)}"
    return f"{txn.date} {txn.description} {sign}{money_str(txn.amount)}"


def build_expected_json(fixture: StatementFixture, balances: list[Decimal]) -> dict:
    events = [
        {
            "date": txn.date,
            "description": txn.description,
            "amount": money_str(txn.amount),
            "direction": txn.direction,
            "reference": txn.reference,
            "currency": fixture.currency,
            "balance_after": money_str(bal),
            "confidence": 0.95,
            "raw_text": _raw_text(fixture.institution, txn, bal),
            "suggested_category": txn.suggested_category,
            "category_confidence": float(txn.category_confidence),
        }
        for txn, bal in zip(fixture.transactions, balances, strict=True)
    ]
    return {
        "file": fixture.pdf_name,
        "institution": fixture.institution,
        "success": True,
        "statement": {
            "period_start": fixture.period_start,
            "period_end": fixture.period_end,
            "opening_balance": money_str(fixture.opening_balance),
            "closing_balance": money_str(balances[-1]),
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
    _, height = A4
    y = height - 56
    pdf.setFont(font_name, 16)
    pdf.drawString(48, y, fixture.header)
    y -= 24
    pdf.setFont(font_name, 10)
    if fixture.institution in ("CMB", "ICBC"):
        lines = [
            f"账号: {fixture.account_masked}   币种: {fixture.currency}",
            f"起止日期: {fixture.period_start} 至 {fixture.period_end}",
        ]
        if fixture.institution == "ICBC":
            lines.append(
                f"期初余额: {fixture.currency} {money_str(fixture.opening_balance)}   期末余额: {fixture.currency} {money_str(closing_balance)}"
            )
    else:
        lines = [
            f"Account Number: {fixture.account_masked}",
            f"Statement Period: {fixture.period_start} to {fixture.period_end}",
            f"Opening Balance: {fixture.currency} {money_str(fixture.opening_balance)}",
            f"Closing Balance: {fixture.currency} {money_str(closing_balance)}",
        ]
    for idx, text in enumerate(lines):
        if idx:
            y -= 16
        pdf.drawString(48, y, text)
    return y - 24


def _draw_table(
    pdf: canvas.Canvas,
    fixture: StatementFixture,
    balances: list[Decimal],
    y: float,
    headers: Sequence[tuple[int, str]],
    row_fn: Callable[[Transaction, Decimal], Sequence[tuple[int, str, bool]]],
    header_font: str = "Helvetica-Bold",
    body_font: str | None = "Helvetica",
) -> None:
    pdf.setFont(header_font, 10)
    for x, label in headers:
        pdf.drawString(x, y, label)
    pdf.line(48, y - 4, 545, y - 4)
    y -= 20
    if body_font:
        pdf.setFont(body_font, 9)
    for txn, bal in zip(fixture.transactions, balances, strict=True):
        for x, text, right in row_fn(txn, bal):
            if right:
                pdf.drawRightString(x, y, text)
            else:
                pdf.drawString(x, y, text)
        y -= 17


def draw_cmb_table(
    pdf: canvas.Canvas, fixture: StatementFixture, balances: list[Decimal], y: float
) -> None:
    _, height = A4

    def _hdr(cur_y: float, page_num: int) -> float:
        pdf.setFont("STSong-Light", 10)
        for x, label in (
            (48, "交易日期"),
            (136, "摘要"),
            (320, "交易金额"),
            (430, "账户余额"),
        ):
            pdf.drawString(x, cur_y, label)
        pdf.drawRightString(540, cur_y, f"第 {page_num} 页")
        pdf.line(48, cur_y - 4, 545, cur_y - 4)
        return cur_y - 20

    page_num = 1
    y = _hdr(y, page_num)
    for idx, (txn, bal) in enumerate(zip(fixture.transactions, balances, strict=True)):
        if idx > 0 and idx % 14 == 0:
            pdf.showPage()
            page_num += 1
            y = _hdr(height - 56, page_num)
        signed = txn.amount if txn.direction == "IN" else -txn.amount
        pdf.drawString(48, y, txn.date)
        pdf.drawString(136, y, txn.description)
        pdf.drawRightString(410, y, money_with_commas(signed))
        pdf.drawRightString(540, y, money_with_commas(bal))
        y -= 17


_TABLE_SPECS: dict[
    str,
    tuple[
        Sequence[tuple[int, str]],
        Callable[[Transaction, Decimal], Sequence[tuple[int, str, bool]]],
        str,
        str | None,
    ],
] = {
    "DBS": (
        ((48, "Date"), (128, "Description"), (350, "Amount"), (440, "Balance")),
        lambda t, b: (
            (48, dd_mmm_yyyy(t.date), False),
            (128, t.description, False),
            (
                420,
                f"{money_with_commas(t.amount)}{' CR' if t.direction == 'IN' else ''}",
                True,
            ),
            (540, money_with_commas(b), True),
        ),
        "Helvetica-Bold",
        "Helvetica",
    ),
    "ICBC": (
        ((48, "交易日期"), (136, "摘要"), (320, "收支金额(+/-)"), (430, "余额")),
        lambda t, b: (
            (48, t.date, False),
            (136, t.description, False),
            (
                410,
                f"{'+' if t.direction == 'IN' else '-'}{money_with_commas(t.amount)}",
                True,
            ),
            (540, money_with_commas(b), True),
        ),
        "STSong-Light",
        None,
    ),
    "Sparkasse": (
        (
            (48, "Buchungstag"),
            (126, "Verwendungszweck"),
            (360, "Umsatz (S/H)"),
            (468, "Saldo (EUR)"),
        ),
        lambda t, b: (
            (48, de_date_str(t.date), False),
            (126, t.description, False),
            (
                440,
                f"{money_de_str(t.amount)} {'H' if t.direction == 'IN' else 'S'}",
                True,
            ),
            (540, f"{money_de_str(b)} H", True),
        ),
        "Helvetica-Bold",
        "Helvetica",
    ),
    "Barclays": (
        (
            (48, "Date"),
            (122, "Description"),
            (350, "Money Out"),
            (424, "Money In"),
            (496, "Balance"),
        ),
        lambda t, b: (
            (48, dd_mmm_yyyy(t.date), False),
            (122, t.description, False),
            (406, money_with_commas(t.amount) if t.direction == "OUT" else "", True),
            (476, money_with_commas(t.amount) if t.direction == "IN" else "", True),
            (540, money_with_commas(b), True),
        ),
        "Helvetica-Bold",
        "Helvetica",
    ),
    "Chase": (
        ((48, "Date"), (126, "Description"), (386, "Amount"), (468, "Balance")),
        lambda t, b: (
            (48, mm_dd_yyyy(t.date), False),
            (126, t.description, False),
            (
                440,
                f"{'+' if t.direction == 'IN' else '-'}{money_with_commas(t.amount)}",
                True,
            ),
            (540, money_with_commas(b), True),
        ),
        "Helvetica-Bold",
        "Helvetica",
    ),
    "GXS": (
        (
            (48, "Date"),
            (122, "Description"),
            (356, "Money In"),
            (430, "Money Out"),
            (500, "Balance"),
        ),
        lambda t, b: (
            (48, t.date, False),
            (122, t.description, False),
            (410, money_with_commas(t.amount) if t.direction == "IN" else "", True),
            (486, money_with_commas(t.amount) if t.direction == "OUT" else "", True),
            (540, money_with_commas(b), True),
        ),
        "Helvetica-Bold",
        "Helvetica",
    ),
    "DEFAULT": (
        ((48, "Date"), (126, "Activity"), (390, "Amount"), (470, "Running Bal")),
        lambda t, b: (
            (48, t.date, False),
            (126, t.description, False),
            (
                446,
                f"{'+' if t.direction == 'IN' else '-'}{money_with_commas(t.amount)}",
                True,
            ),
            (540, money_with_commas(b), True),
        ),
        "Helvetica-Bold",
        "Helvetica",
    ),
}
_TABLE_SPECS["HSBC HK"] = _TABLE_SPECS["GXS"]


def write_fixture_pdf_and_json(fixture: StatementFixture) -> None:
    balances = compute_balances(fixture.opening_balance, fixture.transactions)
    pdf_path = OUTPUT_DIR / fixture.pdf_name
    json_path = OUTPUT_DIR / fixture.json_name

    pdf = canvas.Canvas(str(pdf_path), pagesize=A4, pageCompression=0, invariant=1)
    pdf.setTitle(f"{fixture.institution} Statement Fixture")
    pdf.setAuthor("finance-report-tests")
    pdf.setCreator("generate_test_pdfs.py")
    pdf.setSubject("Deterministic extraction test fixture")

    font_name = (
        "STSong-Light" if fixture.institution in ("CMB", "ICBC") else "Helvetica"
    )
    y = draw_common_header(pdf, fixture, balances[-1], font_name)
    if fixture.institution == "CMB":
        draw_cmb_table(pdf, fixture, balances, y)
    else:
        headers, row_fn, h_font, b_font = _TABLE_SPECS.get(
            fixture.institution, _TABLE_SPECS["DEFAULT"]
        )
        _draw_table(pdf, fixture, balances, y, headers, row_fn, h_font, b_font)

    pdf.showPage()
    pdf.save()

    payload = build_expected_json(fixture, balances)
    json_path.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
