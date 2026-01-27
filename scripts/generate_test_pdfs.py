#!/usr/bin/env python
"""Generate bank statement PDF fixtures for testing."""

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate,
        Table,
        TableStyle,
        Paragraph,
        Spacer,
    )
except ImportError:
    print("Error: reportlab not installed. Run 'uv sync' in apps/backend.")
    sys.exit(1)

OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent / "apps/backend/tests/fixtures/generated"
)


def generate_statement(
    filename: str,
    bank_name: str,
    account_number: str,
    period_start: date,
    period_end: date,
    transactions: list[dict],
    opening_balance: Decimal,
):
    """Generate a PDF bank statement."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / filename
    doc = SimpleDocTemplate(str(filepath), pagesize=A4)
    elements = []
    styles = getSampleStyleSheet()

    # Header
    elements.append(Paragraph(f"{bank_name} Statement", styles["Heading1"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Account: {account_number}", styles["Normal"]))
    elements.append(
        Paragraph(f"Period: {period_start} to {period_end}", styles["Normal"])
    )
    elements.append(Spacer(1, 12))

    # Summary
    elements.append(
        Paragraph(f"Opening Balance: {opening_balance:.2f}", styles["Normal"])
    )

    closing_balance = opening_balance + sum(t["amount"] for t in transactions)
    elements.append(
        Paragraph(f"Closing Balance: {closing_balance:.2f}", styles["Normal"])
    )
    elements.append(Spacer(1, 24))

    # Transactions Table
    data = [["Date", "Description", "Debit", "Credit", "Balance"]]

    balance = opening_balance
    for txn in transactions:
        balance += txn["amount"]
        debit = f"{abs(txn['amount']):.2f}" if txn["amount"] < 0 else ""
        credit = f"{txn['amount']:.2f}" if txn["amount"] > 0 else ""
        data.append(
            [str(txn["date"]), txn["description"], debit, credit, f"{balance:.2f}"]
        )

    table = Table(data)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )
    elements.append(table)

    doc.build(elements)
    print(f"Generated: {filepath}")


def main():
    """Generate all fixtures."""

    # 1. Simple Statement
    generate_statement(
        "simple_dbs.pdf",
        "DBS Bank",
        "123-456-789",
        date(2025, 1, 1),
        date(2025, 1, 31),
        [
            {
                "date": date(2025, 1, 5),
                "description": "Salary",
                "amount": Decimal("5000.00"),
            },
            {
                "date": date(2025, 1, 10),
                "description": "Grocery Store",
                "amount": Decimal("-150.50"),
            },
            {
                "date": date(2025, 1, 20),
                "description": "Electric Bill",
                "amount": Decimal("-89.90"),
            },
        ],
        Decimal("1000.00"),
    )

    # 2. Complex Statement (Many txns)
    txns = []
    for i in range(1, 60):
        txns.append(
            {
                "date": date(2025, 2, 1) + timedelta(days=i % 28),
                "description": f"Transaction #{i}",
                "amount": Decimal(f"{10 + i}.00")
                if i % 2 == 0
                else Decimal(f"-{5 + i}.00"),
            }
        )
    generate_statement(
        "complex_ocbc.pdf",
        "OCBC Bank",
        "987-654-321",
        date(2025, 2, 1),
        date(2025, 2, 28),
        txns,
        Decimal("5000.00"),
    )

    # 3. Multi-currency (Simulated by description/format)
    generate_statement(
        "multi_currency_uob.pdf",
        "UOB Bank (USD Account)",
        "111-222-333",
        date(2025, 3, 1),
        date(2025, 3, 31),
        [
            {
                "date": date(2025, 3, 1),
                "description": "Transfer from SGD",
                "amount": Decimal("1000.00"),
            },
            {
                "date": date(2025, 3, 5),
                "description": "AWS Subscription (USD)",
                "amount": Decimal("-12.00"),
            },
        ],
        Decimal("0.00"),
    )

    # 4. Edge Cases
    generate_statement(
        "edge_cases.pdf",
        "Edge Bank",
        "000-000",
        date(2025, 4, 1),
        date(2025, 4, 30),
        [
            {
                "date": date(2025, 4, 1),
                "description": "Reversal of Fee",
                "amount": Decimal("10.00"),
            },
            {
                "date": date(2025, 4, 1),
                "description": "Fee Charge",
                "amount": Decimal("-10.00"),
            },
            {
                "date": date(2025, 4, 15),
                "description": "Negative Balance txn",
                "amount": Decimal("-2000.00"),
            },
        ],
        Decimal("100.00"),
    )


if __name__ == "__main__":
    main()
