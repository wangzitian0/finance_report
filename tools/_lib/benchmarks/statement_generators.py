"""
Synthetic statement generators for benchmark scenarios.

Generates deterministic ReportLab PDF and CSV banking/brokerage statements
for financial scenario assertions.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_consecutive_month2_pdf(
    output_path: Path, opening_balance: Decimal = Decimal("15271.23")
) -> bytes:
    """Generate deterministic Month 2 PDF chained to Month 1 closing balance."""
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    elements = []

    # Institution matches Month 1: Standard Chartered Bank
    elements.append(Paragraph("<b>Standard Chartered Bank</b>", styles["Heading1"]))
    elements.append(
        Paragraph("eStatement - Personal Banking Account", styles["Heading2"])
    )
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("Account Name: Test Benchmark User", styles["Normal"]))
    elements.append(Paragraph("Account Number: 01-0-123-1657", styles["Normal"]))
    elements.append(Paragraph("Currency: SGD", styles["Normal"]))
    elements.append(
        Paragraph("Statement Period: 01 Feb 2025 - 28 Feb 2025", styles["Normal"])
    )
    elements.append(Spacer(1, 15))

    closing_balance = opening_balance + Decimal("2978.77")

    summary_data = [
        ["Opening Balance (01 Feb 2025)", f"SGD {opening_balance:,.2f}"],
        ["Total Deposits / Credits", "SGD 3,500.00"],
        ["Total Withdrawals / Debits", "SGD 521.23"],
        ["Closing Balance (28 Feb 2025)", f"SGD {closing_balance:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[250, 150])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("<b>Transaction Details</b>", styles["Heading3"]))
    elements.append(Spacer(1, 5))

    tx_data = [
        ["Date", "Description", "Withdrawals (-)", "Deposits (+)", "Balance"],
        [
            "05/02/2025",
            "PAYNOW FROM TECH CORP SALARY",
            "",
            "3,500.00",
            f"{opening_balance + Decimal('3500.00'):,.2f}",
        ],
        [
            "12/02/2025",
            "NTUC FAIRPRICE GROCERIES",
            "250.00",
            "",
            f"{opening_balance + Decimal('3250.00'):,.2f}",
        ],
        [
            "18/02/2025",
            "RESTAURANT PAYMENT DINING",
            "150.00",
            "",
            f"{opening_balance + Decimal('3100.00'):,.2f}",
        ],
        [
            "25/02/2025",
            "SP GROUP UTILITIES BILL",
            "121.23",
            "",
            f"{closing_balance:,.2f}",
        ],
    ]
    tx_table = Table(tx_data, colWidths=[70, 230, 80, 80, 80])
    tx_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(tx_table)

    doc.build(elements)
    return output_path.read_bytes()


def generate_bank_asset_transfer_pdf(output_path: Path) -> bytes:
    """Generate bank statement representing a 5000 SGD transfer to brokerage."""
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(
        Paragraph("<b>GLOBAL WEALTH BANK (SINGAPORE) LIMITED</b>", styles["Heading1"])
    )
    elements.append(Paragraph("Monthly Account Statement", styles["Heading2"]))
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("Account Name: Benchmark Case 3 User", styles["Normal"]))
    elements.append(Paragraph("Account Number: 888-001-9988", styles["Normal"]))
    elements.append(Paragraph("Currency: SGD", styles["Normal"]))
    elements.append(
        Paragraph("Statement Period: 01 Mar 2025 - 31 Mar 2025", styles["Normal"])
    )
    elements.append(Spacer(1, 15))

    summary_data = [
        ["Opening Balance (01 Mar 2025)", "SGD 20,000.00"],
        ["Total Withdrawals / Debits", "SGD 5,000.00"],
        ["Total Deposits / Credits", "SGD 0.00"],
        ["Closing Balance (31 Mar 2025)", "SGD 15,000.00"],
    ]
    summary_table = Table(summary_data, colWidths=[250, 150])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("<b>Transaction Details</b>", styles["Heading3"]))
    elements.append(Spacer(1, 5))

    tx_data = [
        ["Date", "Description", "Withdrawals (-)", "Deposits (+)", "Balance"],
        [
            "15/03/2025",
            "TRANSFER TO FIDELITY BROKERAGE ACCT 8821",
            "5,000.00",
            "",
            "15,000.00",
        ],
    ]
    tx_table = Table(tx_data, colWidths=[70, 230, 80, 80, 80])
    tx_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(tx_table)

    doc.build(elements)
    return output_path.read_bytes()


def generate_credit_card_repayment_bank_pdf(
    output_path: Path, opening_balance: Decimal = Decimal("10000.00")
) -> bytes:
    """Generate bank statement representing a 1,200 SGD credit card debt repayment."""
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(
        Paragraph("<b>DBS BANK (SINGAPORE) LIMITED</b>", styles["Heading1"])
    )
    elements.append(Paragraph("Monthly Account Statement", styles["Heading2"]))
    elements.append(Spacer(1, 10))

    elements.append(
        Paragraph("Account Name: Benchmark Household User", styles["Normal"])
    )
    elements.append(Paragraph("Account Number: 003-882-9110", styles["Normal"]))
    elements.append(Paragraph("Currency: SGD", styles["Normal"]))
    elements.append(
        Paragraph("Statement Period: 01 Apr 2025 - 30 Apr 2025", styles["Normal"])
    )
    elements.append(Spacer(1, 15))

    repayment_amount = Decimal("1200.00")
    closing_balance = opening_balance - repayment_amount

    summary_data = [
        ["Opening Balance (01 Apr 2025)", f"SGD {opening_balance:,.2f}"],
        ["Total Withdrawals / Debits", f"SGD {repayment_amount:,.2f}"],
        ["Total Deposits / Credits", "SGD 0.00"],
        ["Closing Balance (30 Apr 2025)", f"SGD {closing_balance:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[250, 150])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("<b>Transaction Details</b>", styles["Heading3"]))
    elements.append(Spacer(1, 5))

    tx_data = [
        ["Date", "Description", "Withdrawals (-)", "Deposits (+)", "Balance"],
        [
            "20/04/2025",
            "PAYMENT TO CITI CREDIT CARD 4321",
            "1,200.00",
            "",
            f"{closing_balance:,.2f}",
        ],
    ]
    tx_table = Table(tx_data, colWidths=[70, 230, 80, 80, 80])
    tx_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(tx_table)

    doc.build(elements)
    return output_path.read_bytes()


def generate_standard_operations_csv(
    opening_balance: Decimal = Decimal("10000.00"),
) -> bytes:
    """Generate standard operations CSV statement rows representing balanced revenue and expenses."""
    closing_balance = opening_balance + Decimal("2800.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-05,CONSULTING SERVICES REVENUE,5000.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-10,COMMERCIAL OFFICE LEASE RENT,-1500.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-15,AWS CLOUD HOSTING AND SAAS,-500.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-20,BUSINESS CLIENT DINING DINNER,-200.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_household_wife_operations_csv(
    opening_balance: Decimal = Decimal("5000.00"),
) -> bytes:
    """Generate wife's operating CSV statement rows representing household salary and daily living expenses."""
    closing_balance = opening_balance + Decimal("3100.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-08,TECH ENTERPRISE PAYROLL SALARY,3500.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-16,NTUC FAIRPRICE GROCERIES,-250.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-24,SP SERVICES RESIDENTIAL UTILITIES,-150.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_consecutive_month3_pdf(
    output_path: Path, opening_balance: Decimal = Decimal("18250.00")
) -> bytes:
    """Generate deterministic Month 3 (Mar 2025) PDF chained to Month 2 closing balance."""
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("<b>Standard Chartered Bank</b>", styles["Heading1"]))
    elements.append(
        Paragraph("eStatement - Personal Banking Account", styles["Heading2"])
    )
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("Account Name: Test Benchmark User", styles["Normal"]))
    elements.append(Paragraph("Account Number: 01-0-123-1657", styles["Normal"]))
    elements.append(Paragraph("Currency: SGD", styles["Normal"]))
    elements.append(
        Paragraph("Statement Period: 01 Mar 2025 - 31 Mar 2025", styles["Normal"])
    )
    elements.append(Spacer(1, 15))

    closing_balance = opening_balance + Decimal("3050.00")

    summary_data = [
        ["Opening Balance (01 Mar 2025)", f"SGD {opening_balance:,.2f}"],
        ["Total Deposits / Credits", "SGD 3,500.00"],
        ["Total Withdrawals / Debits", "SGD 450.00"],
        ["Closing Balance (31 Mar 2025)", f"SGD {closing_balance:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[250, 150])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("<b>Transaction Details</b>", styles["Heading3"]))
    elements.append(Spacer(1, 5))

    tx_data = [
        ["Date", "Description", "Withdrawals (-)", "Deposits (+)", "Balance"],
        [
            "05/03/2025",
            "PAYNOW FROM TECH CORP SALARY",
            "",
            "3,500.00",
            f"{opening_balance + Decimal('3500.00'):,.2f}",
        ],
        [
            "14/03/2025",
            "NTUC FAIRPRICE GROCERIES",
            "200.00",
            "",
            f"{opening_balance + Decimal('3300.00'):,.2f}",
        ],
        [
            "20/03/2025",
            "RESTAURANT PAYMENT DINING",
            "150.00",
            "",
            f"{opening_balance + Decimal('3150.00'):,.2f}",
        ],
        [
            "28/03/2025",
            "SP GROUP UTILITIES BILL",
            "100.00",
            "",
            f"{closing_balance:,.2f}",
        ],
    ]
    tx_table = Table(tx_data, colWidths=[70, 230, 80, 80, 80])
    tx_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(tx_table)

    doc.build(elements)
    return output_path.read_bytes()


def generate_consecutive_month4_pdf(
    output_path: Path, opening_balance: Decimal = Decimal("21300.00")
) -> bytes:
    """Generate deterministic Month 4 (Apr 2025) PDF chained to Month 3 closing balance."""
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("<b>Standard Chartered Bank</b>", styles["Heading1"]))
    elements.append(
        Paragraph("eStatement - Personal Banking Account", styles["Heading2"])
    )
    elements.append(Spacer(1, 10))

    elements.append(Paragraph("Account Name: Test Benchmark User", styles["Normal"]))
    elements.append(Paragraph("Account Number: 01-0-123-1657", styles["Normal"]))
    elements.append(Paragraph("Currency: SGD", styles["Normal"]))
    elements.append(
        Paragraph("Statement Period: 01 Apr 2025 - 30 Apr 2025", styles["Normal"])
    )
    elements.append(Spacer(1, 15))

    closing_balance = opening_balance + Decimal("2900.00")

    summary_data = [
        ["Opening Balance (01 Apr 2025)", f"SGD {opening_balance:,.2f}"],
        ["Total Deposits / Credits", "SGD 3,500.00"],
        ["Total Withdrawals / Debits", "SGD 600.00"],
        ["Closing Balance (30 Apr 2025)", f"SGD {closing_balance:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[250, 150])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("<b>Transaction Details</b>", styles["Heading3"]))
    elements.append(Spacer(1, 5))

    tx_data = [
        ["Date", "Description", "Withdrawals (-)", "Deposits (+)", "Balance"],
        [
            "05/04/2025",
            "PAYNOW FROM TECH CORP SALARY",
            "",
            "3,500.00",
            f"{opening_balance + Decimal('3500.00'):,.2f}",
        ],
        [
            "15/04/2025",
            "NTUC FAIRPRICE GROCERIES",
            "300.00",
            "",
            f"{opening_balance + Decimal('3200.00'):,.2f}",
        ],
        [
            "22/04/2025",
            "RESTAURANT PAYMENT DINING",
            "180.00",
            "",
            f"{opening_balance + Decimal('3020.00'):,.2f}",
        ],
        [
            "28/04/2025",
            "SP GROUP UTILITIES BILL",
            "120.00",
            "",
            f"{closing_balance:,.2f}",
        ],
    ]
    tx_table = Table(tx_data, colWidths=[70, 230, 80, 80, 80])
    tx_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.navy),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(tx_table)

    doc.build(elements)
    return output_path.read_bytes()


def generate_multicurrency_usd_csv(
    opening_balance: Decimal = Decimal("5000.00"),
) -> bytes:
    """Generate US Dollar operating CSV statement rows."""
    closing_balance = opening_balance + Decimal("1800.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"USD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-05,US CLIENT CONSULTING RETAINER,2000.00",
        f"USD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-20,GLOBAL INFRASTRUCTURE SUBSCRIPTION,-200.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_multicurrency_hkd_csv(
    opening_balance: Decimal = Decimal("20000.00"),
) -> bytes:
    """Generate Hong Kong Dollar operating CSV statement rows."""
    closing_balance = opening_balance + Decimal("4000.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"HKD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-10,GREATER CHINA TECH DIVIDEND,5000.00",
        f"HKD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-25,HK CUSTODIAN AND ACCOUNT FEE,-1000.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")
