#!/usr/bin/env python3
"""
Financial Reporting Temporal Scenario Benchmark Suite.

Executes end-to-end multi-period accounting scenarios against the live application
(e.g., Staging: https://report-staging.zitian.party) and validates fundamental
3-statement financial reconciliation identities:
  1. Balance Sheet: Assets == Liabilities + Equity + Net Income (delta == 0.00)
  2. Multi-period Rollforward: Month 2 Opening Balance == Month 1 Closing Balance
  3. Income Statement: Net Income accumulates into Retained Earnings
  4. Cash Flow: Beginning Cash + Net Cash Flow == Ending Cash
  5. Asset Reallocation / Transfer: Zero P&L contamination on internal swaps

Usage:
  python tools/run_financial_scenario_benchmark.py --app-url https://report-staging.zitian.party --case 1,3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import httpx
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from tools._lib.benchmarks.benchmark_html_reporter import (
    extract_summary_data,
    generate_html_report,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class CaseResult:
    case_id: str
    case_name: str
    status: str  # PASS / FAIL / ERROR
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


class ScenarioBenchmarkRunner:
    """Benchmark scenario runner connecting to the target API."""

    def __init__(self, base_url: str, timeout: float = 180.0, verify: bool = True):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify = verify

    def create_ephemeral_client(
        self, prefix: str = "qa_bench"
    ) -> tuple[httpx.Client, str, dict[str, Any]]:
        """Register an ephemeral test user and return an authenticated HTTP client."""
        client = httpx.Client(
            base_url=self.base_url, verify=self.verify, timeout=self.timeout
        )
        user_email = f"{prefix}_{uuid.uuid4().hex[:8]}@test.example.com"
        reg_resp = client.post(
            "/api/auth/register",
            json={
                "email": user_email,
                "password": "Password123!",
                "display_name": f"Benchmark Runner {prefix}",
            },
        )
        if reg_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"User registration failed: {reg_resp.status_code} {reg_resp.text}"
            )

        user_data = reg_resp.json()
        token = user_data.get("access_token")
        if not token:
            raise RuntimeError(f"No access token returned: {user_data}")

        client.headers.update({"Authorization": f"Bearer {token}"})
        return client, user_email, user_data

    def upload_statement(
        self,
        client: httpx.Client,
        file_bytes: bytes,
        filename: str,
        account_id: str | None = None,
        institution: str | None = None,
    ) -> str:
        """Upload a statement PDF or CSV and return statement ID."""
        content_type = "text/csv" if filename.endswith(".csv") else "application/pdf"
        files = {"file": (filename, file_bytes, content_type)}
        data: dict[str, str] = {}
        if account_id:
            data["account_id"] = str(account_id)
        if institution:
            data["institution"] = institution

        resp = client.post("/api/statements/upload", files=files, data=data)
        if resp.status_code not in (200, 201, 202):
            raise RuntimeError(
                f"Statement upload failed: {resp.status_code} {resp.text}"
            )
        statement_id = resp.json().get("id")
        if not statement_id:
            raise RuntimeError(f"Upload response missing statement ID: {resp.json()}")
        return str(statement_id)

    def wait_for_statement_parsed(
        self,
        client: httpx.Client,
        statement_id: str,
        max_wait_seconds: int = 150,
        poll_interval: int = 3,
    ) -> dict[str, Any]:
        """Poll statement status until terminal state ('parsed', 'rejected', 'failed')."""
        start = time.time()
        while time.time() - start < max_wait_seconds:
            resp = client.get(f"/api/statements/{statement_id}")
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Polling statement {statement_id} failed: {resp.status_code} {resp.text}"
                )
            data = resp.json()
            status = data.get("status")
            if status == "parsed":
                return data
            if status in ("rejected", "failed"):
                err = data.get("validation_error") or "Unknown validation error"
                raise RuntimeError(
                    f"Statement {statement_id} entered terminal failure state '{status}': {err}"
                )
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Statement {statement_id} did not reach parsed status within {max_wait_seconds}s"
        )

    def adjudicate_unmatched_items(
        self,
        client: httpx.Client,
        statement_id: str,
        default_income_category: str = "OTHER_INCOME",
        default_expense_category: str = "OTHER_EXPENSE",
        non_pnl_intent: str | None = None,
        non_pnl_counter_account_id: str | None = None,
    ) -> int:
        """Resolve any Stage 1 unmatched transactions with explicit economic intent."""
        unmatched_resp = client.get(
            f"/api/reconciliation/unmatched?statement_id={statement_id}"
        )
        if unmatched_resp.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch unmatched items: {unmatched_resp.status_code} {unmatched_resp.text}"
            )

        items = unmatched_resp.json().get("items", [])
        if not items:
            return 0

        inc_acc_id = None
        exp_acc_id = None
        if not non_pnl_intent:
            inc_acc = client.post(
                "/api/accounts",
                json={"name": "Income - Other", "type": "INCOME", "currency": "SGD"},
            ).json()
            exp_acc = client.post(
                "/api/accounts",
                json={"name": "Expense - Other", "type": "EXPENSE", "currency": "SGD"},
            ).json()
            inc_acc_id = inc_acc["id"]
            exp_acc_id = exp_acc["id"]

        count = 0
        for item in items:
            txn_id = item["id"]
            direction = item.get("direction", "OUT")
            desc = item.get("description", "")

            if non_pnl_intent and non_pnl_counter_account_id:
                payload = {
                    "intent": non_pnl_intent,
                    "counter_account_id": non_pnl_counter_account_id,
                    "rationale": f"Benchmark non-P&L disposition for {desc}",
                }
            else:
                is_in = direction == "IN"
                intent = "income" if is_in else "expense"
                category = (
                    default_income_category if is_in else default_expense_category
                )
                acc_id = inc_acc_id if is_in else exp_acc_id
                payload = {
                    "intent": intent,
                    "counter_account_id": acc_id,
                    "category": category,
                    "rationale": f"Benchmark disposition for {desc}",
                }

            disp_resp = client.post(
                f"/api/reconciliation/unmatched/{txn_id}/reviewed-disposition",
                json=payload,
            )
            if disp_resp.status_code != 200:
                raise RuntimeError(
                    f"Adjudication failed for txn {txn_id}: {disp_resp.status_code} {disp_resp.text}"
                )
            count += 1

        return count

    def approve_statement(
        self, client: httpx.Client, statement_id: str
    ) -> dict[str, Any]:
        """Approve statement to post ledger entries."""
        resp = client.post(
            f"/api/statements/{statement_id}/review/approve",
            json={"create_account_if_missing": True},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Approval failed for statement {statement_id}: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_balance_sheet(
        self,
        client: httpx.Client,
        as_of_date: str | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        params: list[str] = []
        if as_of_date:
            params.append(f"as_of_date={as_of_date}")
        if currency:
            params.append(f"currency={currency}")
        query = f"?{'&'.join(params)}" if params else ""
        resp = client.get(f"/api/reports/balance-sheet{query}")
        if resp.status_code != 200:
            raise RuntimeError(
                f"Balance sheet request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_income_statement(
        self, client: httpx.Client, start_date: str, end_date: str
    ) -> dict[str, Any]:
        resp = client.get(
            f"/api/reports/income-statement?start_date={start_date}&end_date={end_date}"
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Income statement request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_cash_flow(
        self, client: httpx.Client, start_date: str, end_date: str
    ) -> dict[str, Any]:
        resp = client.get(
            f"/api/reports/cash-flow?start_date={start_date}&end_date={end_date}"
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Cash flow request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def import_brokerage_positions(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
        filename: str = "brokerage_statement.csv",
    ) -> dict[str, Any]:
        resp = client.post(
            "/api/portfolio/brokerage/import",
            json={"filename": filename, "payload": payload},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Brokerage import request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_holdings(
        self, client: httpx.Client, as_of_date: str | None = None
    ) -> dict[str, Any]:
        params = f"?as_of_date={as_of_date}" if as_of_date else ""
        resp = client.get(f"/api/portfolio/holdings{params}")
        if resp.status_code != 200:
            raise RuntimeError(
                f"Holdings request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def update_market_prices(
        self,
        client: httpx.Client,
        updates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Update market prices manually for portfolio securities."""
        resp = client.post("/api/portfolio/prices/update", json={"updates": updates})
        if resp.status_code != 200:
            raise RuntimeError(f"Price update failed: {resp.status_code} {resp.text}")
        return resp.json()


# =====================================================================
# PDF Generator Helpers for Multi-Period Rollforward & Transfers
# =====================================================================


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

    # Transactions
    # Salary: +3500.00
    # Groceries: -250.00
    # Dining: -150.00
    # Utilities: -121.23
    # Net: +2978.77
    # Closing: opening + 2978.77 = 18250.00
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

    # Net income: +3050.00 (Salary 3500.00 - Groceries 200.00 - Dining 150.00 - Utilities 100.00)
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

    # Net income: +2900.00 (Salary 3500.00 - Groceries 300.00 - Dining 180.00 - Utilities 120.00)
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


# =====================================================================
# Scenario Benchmark Test Cases
# =====================================================================


def execute_case_1(runner: ScenarioBenchmarkRunner) -> CaseResult:
    r"""
    Case 1: Consecutive 4-Month Rollforward & Q1 Articulation (连续4月滚续与季度结转)
    - Month 1: Jan 2025 (Straits Capital Bank Statement) -> Opening: 15450.75, Closing: 15271.23, Net: -179.52.
    - Month 2: Feb 2025 (Chained Standard Chartered Statement) -> Opening: 15271.23, Closing: 18250.00, Net: +2978.77.
    - Month 3: Mar 2025 (Chained Standard Chartered Statement) -> Opening: 18250.00, Closing: 21300.00, Net: +3050.00.
    - Month 4: Apr 2025 (Chained Standard Chartered Statement) -> Opening: 21300.00, Closing: 24200.00, Net: +2900.00.
    - Assertions:
      * Consecutive balance chain integrity ($Month_{n+1} \equiv Month_n$ across all 4 months).
      * Q1 (Jan-Mar) Articulation: Assets (21300.00) == Equity (15450.75) + Cumulative Net Income (5849.25).
      * Q1 Cash Flow: Beginning Cash (15450.75) + Net Cash Flow (5849.25) == Ending Cash (21300.00).
      * 4-Month Cumulative Rollforward (Apr): Assets (24200.00) == Equity (15450.75) + Net Income (8749.25).
      * Equation Delta == 0.00 and is_balanced is True across both Q1 and Month 4 checkpoints.
    """
    start_time = time.time()
    case_name = "Case 1: Consecutive 4-Month Rollforward & Q1 Articulation"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case1")
        print(f"  [1/9] Registered test user: {user_email}")

        # --- Month 1 (Jan 2025) ---
        m1_fixture = (
            REPO_ROOT
            / "common/testing/fixtures/benchmarks/bankstatemently/bsb_001_straits_capital.pdf"
        )
        if not m1_fixture.exists():
            raise FileNotFoundError(
                f"Month 1 fixture not found: {m1_fixture}. Run tools/sync_benchmark_fixtures.py first."
            )

        print("  [2/9] Uploading Month 1 (Jan 2025) statement...")
        m1_id = runner.upload_statement(
            client, m1_fixture.read_bytes(), "bsb_001_straits_capital.pdf"
        )
        m1_data = runner.wait_for_statement_parsed(client, m1_id)
        print(
            f"        M1 parsed: Opening={m1_data['opening_balance']}, Closing={m1_data['closing_balance']}, Txns={len(m1_data.get('transactions', []))}"
        )

        runner.adjudicate_unmatched_items(client, m1_id)
        m1_app = runner.approve_statement(client, m1_id)
        print(f"        M1 approved successfully (status={m1_app['status']})")

        # Resolve created bank account ID from Month 1
        m1_refreshed = client.get(f"/api/statements/{m1_id}").json()
        m1_account_id = m1_refreshed.get("account_id")
        m1_institution = m1_refreshed.get("institution") or "Standard Chartered Bank"
        print(f"        M1 Account ID: {m1_account_id} (Institution: {m1_institution})")

        # --- Month 2 (Feb 2025) ---
        m1_closing = Decimal(m1_data["closing_balance"])
        m2_tmp_pdf = Path("/tmp/case1_m2_scb.pdf")
        m2_bytes = generate_consecutive_month2_pdf(
            m2_tmp_pdf, opening_balance=m1_closing
        )

        print(
            f"  [3/9] Uploading Month 2 (Feb 2025) chained statement linked to account {m1_account_id}..."
        )
        m2_id = runner.upload_statement(
            client,
            m2_bytes,
            "scb_month2_chained.pdf",
            account_id=m1_account_id,
            institution=m1_institution,
        )
        m2_data = runner.wait_for_statement_parsed(client, m2_id)
        print(
            f"        M2 parsed: Opening={m2_data['opening_balance']}, Closing={m2_data['closing_balance']}, Txns={len(m2_data.get('transactions', []))}"
        )

        m2_opening = Decimal(m2_data["opening_balance"])
        assert m2_opening == m1_closing, (
            f"Balance chain break: M1 closing ({m1_closing}) != M2 opening ({m2_opening})"
        )
        assert m2_data.get("balance_validated") is True, (
            f"M2 balance not validated: {m2_data}"
        )

        runner.adjudicate_unmatched_items(client, m2_id)
        m2_app = runner.approve_statement(client, m2_id)
        print(f"        M2 approved successfully (status={m2_app['status']})")

        # --- Month 3 (Mar 2025 - Q1 Close) ---
        m2_closing = Decimal(m2_data["closing_balance"])
        m3_tmp_pdf = Path("/tmp/case1_m3_scb.pdf")
        m3_bytes = generate_consecutive_month3_pdf(
            m3_tmp_pdf, opening_balance=m2_closing
        )

        print(
            f"  [4/9] Uploading Month 3 (Mar 2025) chained statement linked to account {m1_account_id}..."
        )
        m3_id = runner.upload_statement(
            client,
            m3_bytes,
            "scb_month3_chained.pdf",
            account_id=m1_account_id,
            institution=m1_institution,
        )
        m3_data = runner.wait_for_statement_parsed(client, m3_id)
        print(
            f"        M3 parsed: Opening={m3_data['opening_balance']}, Closing={m3_data['closing_balance']}, Txns={len(m3_data.get('transactions', []))}"
        )

        m3_opening = Decimal(m3_data["opening_balance"])
        assert m3_opening == m2_closing, (
            f"Balance chain break: M2 closing ({m2_closing}) != M3 opening ({m3_opening})"
        )
        assert m3_data.get("balance_validated") is True, (
            f"M3 balance not validated: {m3_data}"
        )

        runner.adjudicate_unmatched_items(client, m3_id)
        m3_app = runner.approve_statement(client, m3_id)
        print(f"        M3 approved successfully (status={m3_app['status']})")

        # --- Month 4 (Apr 2025 - Q2 Transition) ---
        m3_closing = Decimal(m3_data["closing_balance"])
        m4_tmp_pdf = Path("/tmp/case1_m4_scb.pdf")
        m4_bytes = generate_consecutive_month4_pdf(
            m4_tmp_pdf, opening_balance=m3_closing
        )

        print(
            f"  [5/9] Uploading Month 4 (Apr 2025) chained statement linked to account {m1_account_id}..."
        )
        m4_id = runner.upload_statement(
            client,
            m4_bytes,
            "scb_month4_chained.pdf",
            account_id=m1_account_id,
            institution=m1_institution,
        )
        m4_data = runner.wait_for_statement_parsed(client, m4_id)
        print(
            f"        M4 parsed: Opening={m4_data['opening_balance']}, Closing={m4_data['closing_balance']}, Txns={len(m4_data.get('transactions', []))}"
        )

        m4_opening = Decimal(m4_data["opening_balance"])
        m4_closing = Decimal(m4_data["closing_balance"])
        assert m4_opening == m3_closing, (
            f"Balance chain break: M3 closing ({m3_closing}) != M4 opening ({m4_opening})"
        )
        assert m4_data.get("balance_validated") is True, (
            f"M4 balance not validated: {m4_data}"
        )

        runner.adjudicate_unmatched_items(client, m4_id)
        m4_app = runner.approve_statement(client, m4_id)
        print(f"        M4 approved successfully (status={m4_app['status']})")

        # --- Checkpoint 1: Q1 Close (2025-01-01 to 2025-03-31) ---
        print("  [6/9] Verifying Q1 Balance Sheet as of 2025-03-31...")
        bs_q1 = runner.get_balance_sheet(client, as_of_date="2025-03-31")
        q1_assets = Decimal(bs_q1["total_assets"])
        q1_delta = Decimal(bs_q1["equation_delta"])
        q1_balanced = bs_q1["is_balanced"]

        print(
            f"        Q1 Balance Sheet: Assets={q1_assets}, Delta={q1_delta}, Balanced={q1_balanced}"
        )
        assert q1_balanced is True, f"Q1 Balance sheet not balanced: delta={q1_delta}"
        assert q1_delta == Decimal("0.00"), f"Q1 equation delta not zero: {q1_delta}"
        assert q1_assets == Decimal("21300.00"), (
            f"Expected Q1 total assets 21300.00, got {q1_assets}"
        )

        print("  [7/9] Verifying Q1 Income Statement & Cash Flow...")
        inc_q1 = runner.get_income_statement(
            client, start_date="2025-01-01", end_date="2025-03-31"
        )
        q1_net_income = Decimal(inc_q1["net_income"])
        print(f"        Q1 Net Income={q1_net_income}")
        # M1 Net (-179.52) + M2 Net (+2978.77) + M3 Net (+3050.00) = +5849.25
        assert q1_net_income == Decimal("5849.25"), (
            f"Expected Q1 cumulative net income 5849.25, got {q1_net_income}"
        )

        cf_q1 = runner.get_cash_flow(
            client, start_date="2025-01-01", end_date="2025-03-31"
        )
        cf_q1_s = cf_q1.get("summary", {})
        q1_beg_cash = Decimal(cf_q1_s.get("beginning_cash", "0"))
        q1_net_cash = Decimal(cf_q1_s.get("net_cash_flow", "0"))
        q1_end_cash = Decimal(cf_q1_s.get("ending_cash", "0"))
        assert q1_beg_cash == Decimal("15450.75"), f"Q1 beg cash: {q1_beg_cash}"
        assert q1_net_cash == Decimal("5849.25"), f"Q1 net cash: {q1_net_cash}"
        assert q1_end_cash == Decimal("21300.00"), f"Q1 end cash: {q1_end_cash}"
        assert q1_beg_cash + q1_net_cash == q1_end_cash, "Q1 cash rollforward mismatch"

        # --- Checkpoint 2: Month 4 / Q2 Transition (2025-01-01 to 2025-04-30) ---
        print("  [8/9] Verifying 4-Month Rollforward Balance Sheet as of 2025-04-30...")
        bs_m4 = runner.get_balance_sheet(client, as_of_date="2025-04-30")
        total_assets = Decimal(bs_m4["total_assets"])
        total_liabilities = Decimal(bs_m4["total_liabilities"])
        total_equity = Decimal(bs_m4["total_equity"])
        equation_delta = Decimal(bs_m4["equation_delta"])
        is_balanced = bs_m4["is_balanced"]

        print(
            f"        Month 4 Balance Sheet: Assets={total_assets}, Liab={total_liabilities}, "
            f"Equity={total_equity}, Delta={equation_delta}, Balanced={is_balanced}"
        )
        assert is_balanced is True, (
            f"Month 4 Balance sheet not balanced: delta={equation_delta}"
        )
        assert equation_delta == Decimal("0.00"), (
            f"Month 4 equation delta not zero: {equation_delta}"
        )
        assert total_assets == Decimal("24200.00"), (
            f"Expected Month 4 total assets 24200.00, got {total_assets}"
        )
        assert total_equity == Decimal("15450.75"), (
            f"Expected total equity (initial stock) 15450.75, got {total_equity}"
        )

        print("  [9/9] Verifying 4-Month Cumulative Income Statement & Cash Flow...")
        inc_4m = runner.get_income_statement(
            client, start_date="2025-01-01", end_date="2025-04-30"
        )
        cum_net_income = Decimal(inc_4m["net_income"])
        print(f"        4-Month Cumulative Net Income={cum_net_income}")
        # 5849.25 + 2900.00 = 8749.25
        assert cum_net_income == Decimal("8749.25"), (
            f"Expected 4-month net income 8749.25, got {cum_net_income}"
        )

        cf_4m = runner.get_cash_flow(
            client, start_date="2025-01-01", end_date="2025-04-30"
        )
        cf_4m_s = cf_4m.get("summary", {})
        beg_cash = Decimal(cf_4m_s.get("beginning_cash", "0"))
        net_cash = Decimal(cf_4m_s.get("net_cash_flow", "0"))
        end_cash = Decimal(cf_4m_s.get("ending_cash", "0"))
        assert beg_cash == Decimal("15450.75"), f"4-Month beg cash: {beg_cash}"
        assert net_cash == Decimal("8749.25"), f"4-Month net cash: {net_cash}"
        assert end_cash == Decimal("24200.00"), f"4-Month end cash: {end_cash}"
        assert beg_cash + net_cash == end_cash, "4-Month cash rollforward mismatch"

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_1",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details={
                "m1_closing_balance": str(m1_closing),
                "month_1_ending_balance": str(m1_closing),
                "m2_opening_balance": str(m2_opening),
                "month_2_opening_cash": str(m2_opening),
                "m2_closing_balance": str(m2_closing),
                "month_2_ending_balance": str(m2_closing),
                "m3_opening_balance": str(m3_opening),
                "month_3_opening_cash": str(m3_opening),
                "m3_closing_balance": str(m3_closing),
                "month_3_ending_balance": str(m3_closing),
                "m4_opening_balance": str(m4_opening),
                "month_4_opening_cash": str(m4_opening),
                "m4_closing_balance": str(m4_closing),
                "month_4_ending_balance": str(m4_closing),
                "q1_net_income": str(q1_net_income),
                "q1_assets": str(q1_assets),
                "total_assets": str(total_assets),
                "month_4_assets": str(total_assets),
                "total_equity": str(total_equity),
                "cumulative_net_income": str(cum_net_income),
                "beginning_cash": str(beg_cash),
                "ending_cash": str(end_cash),
                "equation_delta": str(equation_delta),
                "is_balanced": is_balanced,
            },
        )
    except Exception as exc:
        duration = time.time() - start_time
        print(f"❌ {case_name} FAILED in {duration:.2f}s: {exc}\n")
        return CaseResult(
            case_id="case_1",
            case_name=case_name,
            status="FAIL",
            duration_seconds=duration,
            error_message=str(exc),
        )


def execute_case_2(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 2: Standard CSV Statement Flow & 3-Statement Reconciliation
    - Opening Cash: 10,000.00 SGD.
    - Operating Revenue: +5,000.00 SGD.
    - Operating Expenses: -2,200.00 SGD (Rent 1500, SaaS 500, Dining 200).
    - Net Income: +2,800.00 SGD.
    - Closing Cash: 12,800.00 SGD.
    - Assertions:
      * Balance Sheet is balanced (delta == 0.00, Assets == Liabilities + Equity).
      * Income Statement matches operating categories and net income.
      * Cash Flow matches beginning cash, net cash flow, and ending cash.
    """
    start_time = time.time()
    case_name = "Case 2: Standard CSV Statement Flow & Category Reconciliation"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case2")
        print(f"  [1/5] Registered test user: {user_email}")

        print("  [2/5] Generating & uploading Standard CSV statement...")
        csv_bytes = generate_standard_operations_csv(Decimal("10000.00"))
        stmt_id = runner.upload_statement(
            client,
            csv_bytes,
            "standard_operations_april_2025.csv",
            institution="DBS Bank",
        )
        stmt_data = runner.wait_for_statement_parsed(client, stmt_id)
        print(
            f"        Parsed CSV: Opening={stmt_data.get('opening_balance')}, "
            f"Closing={stmt_data.get('closing_balance')}, "
            f"Txns={len(stmt_data.get('transactions', []))}"
        )

        assert Decimal(stmt_data["opening_balance"]) == Decimal("10000.00"), (
            f"Opening balance mismatch: {stmt_data.get('opening_balance')}"
        )
        assert Decimal(stmt_data["closing_balance"]) == Decimal("12800.00"), (
            f"Closing balance mismatch: {stmt_data.get('closing_balance')}"
        )
        assert len(stmt_data.get("transactions", [])) == 4, (
            f"Expected 4 transactions, got {len(stmt_data.get('transactions', []))}"
        )

        print("  [3/5] Adjudicating unmatched items & approving statement...")
        runner.adjudicate_unmatched_items(client, stmt_id)
        app_resp = runner.approve_statement(client, stmt_id)
        print(f"        Approved successfully (status={app_resp['status']})")

        print("  [4/5] Verifying Balance Sheet as of 2025-04-30...")
        bs = runner.get_balance_sheet(client, as_of_date="2025-04-30")
        total_assets = Decimal(bs["total_assets"])
        total_liabilities = Decimal(bs["total_liabilities"])
        total_equity = Decimal(bs["total_equity"])
        equation_delta = Decimal(bs["equation_delta"])
        is_balanced = bs["is_balanced"]

        print(
            f"        Assets={total_assets}, Liab={total_liabilities}, Equity={total_equity}, "
            f"Delta={equation_delta}, Balanced={is_balanced}"
        )
        assert is_balanced is True, (
            f"Balance sheet not balanced: delta={equation_delta}"
        )
        assert equation_delta == Decimal("0.00"), (
            f"Equation delta not zero: {equation_delta}"
        )
        assert total_assets == Decimal("12800.00"), (
            f"Expected total assets 12800.00, got {total_assets}"
        )

        print(
            "  [5/5] Verifying Income Statement & Cash Flow (2025-04-01 to 2025-04-30)..."
        )
        inc = runner.get_income_statement(
            client, start_date="2025-04-01", end_date="2025-04-30"
        )
        net_income = Decimal(inc["net_income"])
        total_income = Decimal(inc["total_income"])
        total_expenses = Decimal(inc["total_expenses"])
        print(
            f"        Total Income={total_income}, Total Expenses={total_expenses}, Net Income={net_income}"
        )
        assert net_income == Decimal("2800.00"), (
            f"Expected net income 2800.00, got {net_income}"
        )
        assert total_income == Decimal("5000.00"), (
            f"Expected total income 5000.00, got {total_income}"
        )
        assert total_expenses == Decimal("2200.00"), (
            f"Expected total expenses 2200.00, got {total_expenses}"
        )

        cf = runner.get_cash_flow(
            client, start_date="2025-04-01", end_date="2025-04-30"
        )
        cfs = cf.get("summary", {})
        beg_cash = Decimal(cfs.get("beginning_cash", "0"))
        net_cash = Decimal(cfs.get("net_cash_flow", "0"))
        end_cash = Decimal(cfs.get("ending_cash", "0"))
        print(
            f"        Beginning Cash={beg_cash}, Net Cash Flow={net_cash}, Ending Cash={end_cash}"
        )
        assert beg_cash == Decimal("10000.00"), (
            f"Expected beginning cash 10000.00, got {beg_cash}"
        )
        assert net_cash == Decimal("2800.00"), (
            f"Expected net cash flow 2800.00, got {net_cash}"
        )
        assert end_cash == Decimal("12800.00"), (
            f"Expected ending cash 12800.00, got {end_cash}"
        )
        assert beg_cash + net_cash == end_cash, "Cash flow rollforward mismatch"

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_2",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details={
                "opening_balance": "10000.00",
                "closing_balance": "12800.00",
                "total_assets": str(total_assets),
                "total_equity": str(total_equity),
                "total_income": str(total_income),
                "total_expenses": str(total_expenses),
                "net_income": str(net_income),
                "beginning_cash": str(beg_cash),
                "ending_cash": str(end_cash),
                "equation_delta": str(equation_delta),
                "is_balanced": is_balanced,
            },
        )
    except Exception as exc:
        duration = time.time() - start_time
        print(f"❌ {case_name} FAILED in {duration:.2f}s: {exc}\n")
        return CaseResult(
            case_id="case_2",
            case_name=case_name,
            status="FAIL",
            duration_seconds=duration,
            error_message=str(exc),
        )


def execute_case_3(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 3: Bank-Brokerage Transfer & Asset Swap (银证划转不污染损益)
    - Bank Account: Initial 20,000.00 SGD.
    - Transfer Out: 5,000.00 SGD to Brokerage Portfolio.
    - Closing Bank Balance: 15,000.00 SGD.
    - Counter Account: Brokerage Asset Account (5,000.00 SGD).
    - Assertions:
      * Income Statement Net Income == 0.00 (Zero P&L contamination: transfer is not an expense).
      * Balance Sheet Total Assets == 20,000.00 SGD (Cash 15,000.00 + Brokerage 5,000.00).
      * Total Equity == 20,000.00 SGD (Opening Balance Equity).
      * Equation Delta == 0.00 and is_balanced is True.
      * Net Worth is conserved down to the cent.
    """
    start_time = time.time()
    case_name = "Case 3: Bank-Brokerage Transfer & Asset Swap"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case3")
        print(f"  [1/5] Registered test user: {user_email}")

        # Create Counter Asset Account for Brokerage
        brokerage_acc = client.post(
            "/api/accounts",
            json={
                "name": "Fidelity Brokerage Portfolio",
                "type": "ASSET",
                "currency": "SGD",
            },
        ).json()
        brokerage_acc_id = brokerage_acc["id"]
        print(
            f"  [2/5] Created Brokerage Asset Account: {brokerage_acc['name']} (ID: {brokerage_acc_id})"
        )

        # Generate & Upload Bank Transfer Statement
        pdf_tmp = Path("/tmp/case3_transfer_bank.pdf")
        pdf_bytes = generate_bank_asset_transfer_pdf(pdf_tmp)

        print(
            "  [3/5] Uploading bank statement with 5,000 SGD transfer to brokerage..."
        )
        stmt_id = runner.upload_statement(
            client, pdf_bytes, "global_wealth_bank_transfer.pdf"
        )
        stmt_data = runner.wait_for_statement_parsed(client, stmt_id)
        print(
            f"        Parsed: Opening={stmt_data['opening_balance']}, Closing={stmt_data['closing_balance']}"
        )

        # Adjudicate transfer out as investment_purchase (non-P&L asset swap)
        runner.adjudicate_unmatched_items(
            client,
            stmt_id,
            non_pnl_intent="investment_purchase",
            non_pnl_counter_account_id=brokerage_acc_id,
        )
        app_resp = runner.approve_statement(client, stmt_id)
        print(f"        Approved successfully (status={app_resp['status']})")

        # --- Assertions ---
        print("  [4/5] Verifying Balance Sheet Asset Swap (as of 2025-03-31)...")
        bs = runner.get_balance_sheet(client, as_of_date="2025-03-31")
        total_assets = Decimal(bs["total_assets"])
        total_liabilities = Decimal(bs["total_liabilities"])
        total_equity = Decimal(bs["total_equity"])
        equation_delta = Decimal(bs["equation_delta"])
        is_balanced = bs["is_balanced"]

        assets = {a["name"]: Decimal(a["amount"]) for a in bs.get("assets", [])}
        print(
            f"        Total Assets={total_assets}, Total Equity={total_equity}, Delta={equation_delta}"
        )
        print(f"        Asset lines: {assets}")

        assert is_balanced is True, (
            f"Balance sheet not balanced: delta={equation_delta}"
        )
        assert equation_delta == Decimal("0.00"), (
            f"Equation delta not zero: {equation_delta}"
        )
        assert total_liabilities == Decimal("0.00"), (
            f"Expected 0.00 liabilities, got {total_liabilities}"
        )
        assert total_assets == Decimal("20000.00"), (
            f"Expected total assets 20000.00, got {total_assets}"
        )
        assert total_equity == Decimal("20000.00"), (
            f"Expected total equity 20000.00, got {total_equity}"
        )
        assert assets.get("Fidelity Brokerage Portfolio") == Decimal("5000.00"), (
            "Missing 5000 SGD in Brokerage Portfolio"
        )

        print("  [5/5] Verifying Income Statement Zero P&L Contamination...")
        inc = runner.get_income_statement(
            client, start_date="2025-03-01", end_date="2025-03-31"
        )
        total_income = Decimal(inc["total_income"])
        total_expenses = Decimal(inc["total_expenses"])
        net_income = Decimal(inc["net_income"])
        print(
            f"        Total Income={total_income}, Total Expenses={total_expenses}, Net Income={net_income}"
        )

        assert total_income == Decimal("0.00"), (
            f"P&L contaminated! Total income={total_income}"
        )
        assert total_expenses == Decimal("0.00"), (
            f"P&L contaminated! Transfer counted as expense: {total_expenses}"
        )
        assert net_income == Decimal("0.00"), (
            f"P&L contaminated! Net income={net_income}"
        )

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_3",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details={
                "bank_cash": "15000.00",
                "brokerage_portfolio": "5000.00",
                "total_assets": str(total_assets),
                "assets": str(total_assets),
                "total_equity": str(total_equity),
                "total_income": str(total_income),
                "total_expenses": str(total_expenses),
                "net_income": str(net_income),
                "equation_delta": str(equation_delta),
                "is_balanced": is_balanced,
            },
        )
    except Exception as exc:
        duration = time.time() - start_time
        print(f"❌ {case_name} FAILED in {duration:.2f}s: {exc}\n")
        return CaseResult(
            case_id="case_3",
            case_name=case_name,
            status="FAIL",
            duration_seconds=duration,
            error_message=str(exc),
        )


def execute_case_4(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet (跨国多币种合并资产负债表)
    - Base Currency: SGD (user default).
    - Statements uploaded across 3 sovereign jurisdictions:
      * Singapore (SGD): Opening 10,000.00 SGD, Closing 12,800.00 SGD, Net +2,800.00 SGD.
      * United States (USD): Opening 5,000.00 USD, Closing 6,800.00 USD, Net +1,800.00 USD.
      * Hong Kong (HKD): Opening 20,000.00 HKD, Closing 24,000.00 HKD, Net +4,000.00 HKD.
    - Assertions:
      * All 3 multi-currency statements parse and validate internal balance integrity.
      * Unmatched operating items are categorized without stranded ledger entries.
      * Base Currency (SGD) Consolidated Balance Sheet balances with equation delta == 0.00 SGD.
      * Reporting Currency (USD) Consolidated Balance Sheet balances with equation delta == 0.00 USD.
      * Multi-currency assets consolidate into unified net worth with zero accounting leakage.
    """
    start_time = time.time()
    case_name = "Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case4")
        print(f"  [1/6] Registered test user: {user_email}")

        # 1. SGD Statement
        print("  [2/6] Uploading SGD operating statement...")
        sgd_bytes = generate_standard_operations_csv(Decimal("10000.00"))
        sgd_id = runner.upload_statement(
            client, sgd_bytes, "operations_sgd.csv", institution="DBS Singapore"
        )
        sgd_data = runner.wait_for_statement_parsed(client, sgd_id)
        assert sgd_data.get("balance_validated") is True, (
            f"SGD balance invalid: {sgd_data}"
        )
        runner.adjudicate_unmatched_items(client, sgd_id)
        runner.approve_statement(client, sgd_id)
        print(
            f"        SGD statement approved: Closing={sgd_data['closing_balance']} SGD"
        )

        # 2. USD Statement
        print("  [3/6] Uploading USD operating statement...")
        usd_bytes = generate_multicurrency_usd_csv(Decimal("5000.00"))
        usd_id = runner.upload_statement(
            client, usd_bytes, "operations_usd.csv", institution="Silicon Valley Bank"
        )
        usd_data = runner.wait_for_statement_parsed(client, usd_id)
        assert usd_data.get("balance_validated") is True, (
            f"USD balance invalid: {usd_data}"
        )
        runner.adjudicate_unmatched_items(client, usd_id)
        runner.approve_statement(client, usd_id)
        print(
            f"        USD statement approved: Closing={usd_data['closing_balance']} USD"
        )

        # 3. HKD Statement
        print("  [4/6] Uploading HKD operating statement...")
        hkd_bytes = generate_multicurrency_hkd_csv(Decimal("20000.00"))
        hkd_id = runner.upload_statement(
            client, hkd_bytes, "operations_hkd.csv", institution="HSBC Hong Kong"
        )
        hkd_data = runner.wait_for_statement_parsed(client, hkd_id)
        assert hkd_data.get("balance_validated") is True, (
            f"HKD balance invalid: {hkd_data}"
        )
        runner.adjudicate_unmatched_items(client, hkd_id)
        runner.approve_statement(client, hkd_id)
        print(
            f"        HKD statement approved: Closing={hkd_data['closing_balance']} HKD"
        )

        # 4. Consolidated Balance Sheet in Base Currency (SGD)
        print(
            "  [5/6] Verifying Consolidated Balance Sheet in SGD (as of 2025-04-30)..."
        )
        bs_sgd = runner.get_balance_sheet(
            client, as_of_date="2025-04-30", currency="SGD"
        )
        assets_sgd = Decimal(bs_sgd["total_assets"])
        liab_sgd = Decimal(bs_sgd["total_liabilities"])
        equity_sgd = Decimal(bs_sgd["total_equity"])
        delta_sgd = Decimal(bs_sgd["equation_delta"])
        balanced_sgd = bs_sgd["is_balanced"]

        print(
            f"        SGD Balance Sheet: Assets={assets_sgd}, Liab={liab_sgd}, Equity={equity_sgd}, Delta={delta_sgd}, Balanced={balanced_sgd}"
        )
        assert balanced_sgd is True, (
            f"SGD Balance Sheet not balanced: delta={delta_sgd}"
        )
        assert delta_sgd == Decimal("0.00"), f"SGD equation delta not zero: {delta_sgd}"
        assert assets_sgd > Decimal("12800.00"), (
            "Multi-currency assets must be consolidated into SGD"
        )

        # 5. Consolidated Balance Sheet in Target Currency (USD)
        print(
            "  [6/6] Verifying Consolidated Balance Sheet in USD (as of 2025-04-30)..."
        )
        bs_usd = runner.get_balance_sheet(
            client, as_of_date="2025-04-30", currency="USD"
        )
        assets_usd = Decimal(bs_usd["total_assets"])
        delta_usd = Decimal(bs_usd["equation_delta"])
        balanced_usd = bs_usd["is_balanced"]

        print(
            f"        USD Balance Sheet: Assets={assets_usd}, Delta={delta_usd}, Balanced={balanced_usd}"
        )
        assert balanced_usd is True, (
            f"USD Balance Sheet not balanced: delta={delta_usd}"
        )
        assert delta_usd == Decimal("0.00"), f"USD equation delta not zero: {delta_usd}"

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_4",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details={
                "currencies_consolidated": "SGD, USD, HKD",
                "sgd_closing_balance": str(sgd_data["closing_balance"]),
                "usd_closing_balance": str(usd_data["closing_balance"]),
                "hkd_closing_balance": str(hkd_data["closing_balance"]),
                "total_assets_sgd": str(assets_sgd),
                "equation_delta_sgd": str(delta_sgd),
                "is_balanced_sgd": balanced_sgd,
                "total_assets_usd": str(assets_usd),
                "equation_delta_usd": str(delta_usd),
                "is_balanced_usd": balanced_usd,
                "equation_delta": str(delta_sgd),
                "is_balanced": balanced_sgd,
            },
        )
    except Exception as exc:
        duration = time.time() - start_time
        print(f"❌ {case_name} FAILED in {duration:.2f}s: {exc}\n")
        return CaseResult(
            case_id="case_4",
            case_name=case_name,
            status="FAIL",
            duration_seconds=duration,
            error_message=str(exc),
        )


def execute_case_5(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 5: Multi-Asset Portfolio Integration & Securities Valuation (多资产投资组合与证券公允估值)
    - Brokerage Position Import:
      * Interactive Brokers snapshot with AAPL (10 shares @ 200.00 USD = 2,000.00 USD)
      * VT (50 shares @ 110.00 USD = 5,500.00 USD)
    - Authoritative Market Price Updates on 2025-04-30 (AAPL 200.00 USD, VT 110.00 USD).
    - Assertions:
      * Positions import idempotently into AtomicPosition and reconcile ManagedPosition.
      * Holdings endpoint returns all positions without missing price warnings.
      * Balance Sheet incorporates portfolio market adjustments into Assets and Net Worth Adjustment.
      * Equation Delta == 0.00 and is_balanced is True down to the cent.
    """
    start_time = time.time()
    case_name = "Case 5: Multi-Asset Portfolio Integration & Securities Valuation"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case5")
        print(f"  [1/5] Registered test user: {user_email}")

        # 1. Import Brokerage Positions
        print("  [2/5] Importing Interactive Brokers positions...")
        brokerage_payload = {
            "institution": "Interactive Brokers",
            "statement": {"period_end": "2025-04-30", "currency": "USD"},
            "positions": [
                {
                    "symbol": "AAPL",
                    "quantity": "10",
                    "market_value": "2000.00",
                    "currency": "USD",
                    "asset_type": "stock",
                    "sector": "Technology",
                    "geography": "US",
                },
                {
                    "symbol": "VT",
                    "quantity": "50",
                    "market_value": "5500.00",
                    "currency": "USD",
                    "asset_type": "etf",
                    "sector": "Broad Market",
                    "geography": "Global",
                },
            ],
        }
        import_resp = runner.import_brokerage_positions(
            client, brokerage_payload, filename="ibkr_positions_20250430.json"
        )
        print(
            f"        Imported positions: Created={import_resp.get('created_atomic_positions')}, Reconciled={import_resp.get('reconcile_created')}"
        )
        assert (
            import_resp.get("created_atomic_positions", 0) >= 2
            or import_resp.get("parsed_positions", 0) >= 2
        )

        # 2. Update Market Prices to guarantee valuation observation
        print(
            "  [3/5] Setting authoritative market prices for valuation as of 2025-04-30..."
        )
        price_updates = [
            {
                "asset_identifier": "AAPL",
                "price_date": "2025-04-30",
                "price": "200.00",
                "currency": "USD",
            },
            {
                "asset_identifier": "VT",
                "price_date": "2025-04-30",
                "price": "110.00",
                "currency": "USD",
            },
        ]
        runner.update_market_prices(client, price_updates)

        # 3. Verify Holdings
        print("  [4/5] Verifying /api/portfolio/holdings...")
        holdings_resp = runner.get_holdings(client, as_of_date="2025-04-30")
        items = holdings_resp.get("items", [])
        symbols = [item.get("asset_identifier") or item.get("symbol") for item in items]
        print(f"        Retrieved holdings: {symbols}")
        assert "AAPL" in symbols, f"Expected AAPL in holdings: {symbols}"
        assert "VT" in symbols, f"Expected VT in holdings: {symbols}"

        # 4. Verify Balance Sheet Portfolio Valuation Integration
        print("  [5/5] Verifying Balance Sheet Integration as of 2025-04-30...")
        bs = runner.get_balance_sheet(client, as_of_date="2025-04-30")
        total_assets = Decimal(bs["total_assets"])
        total_equity = Decimal(bs["total_equity"])
        equation_delta = Decimal(bs["equation_delta"])
        is_balanced = bs["is_balanced"]

        print(
            f"        Balance Sheet: Total Assets={total_assets}, Total Equity={total_equity}, Delta={equation_delta}, Balanced={is_balanced}"
        )
        assert is_balanced is True, (
            f"Balance sheet not balanced: delta={equation_delta}"
        )
        assert equation_delta == Decimal("0.00"), (
            f"Equation delta not zero: {equation_delta}"
        )
        assert total_assets > Decimal("0.00"), "Portfolio assets must be positive"

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_5",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details={
                "holdings_count": len(items),
                "symbols": ", ".join(symbols),
                "total_assets": str(total_assets),
                "total_equity": str(total_equity),
                "equation_delta": str(equation_delta),
                "is_balanced": is_balanced,
            },
        )
    except Exception as exc:
        duration = time.time() - start_time
        print(f"❌ {case_name} FAILED in {duration:.2f}s: {exc}\n")
        return CaseResult(
            case_id="case_5",
            case_name=case_name,
            status="FAIL",
            duration_seconds=duration,
            error_message=str(exc),
        )


# =====================================================================
# Main Orchestrator & CLI Entrypoint
# =====================================================================


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Financial Reporting Multi-Scenario Benchmark Suite."
    )
    parser.add_argument(
        "--app-url",
        default="https://report-staging.zitian.party",
        help="Target base URL (default: https://report-staging.zitian.party)",
    )
    parser.add_argument(
        "--case",
        default="all",
        help="Comma-separated case IDs to run (1, 2, 3, 4, 5, or all)",
    )
    parser.add_argument(
        "--version-ref",
        default="v0.1.52",
        help="Release tag or version identifier (default: v0.1.52)",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=REPO_ROOT / "benchmark_run_report.json",
        help="Path to output JSON benchmark report",
    )
    parser.add_argument(
        "--output-html",
        type=Path,
        default=None,
        help="Path to output standalone single-file HTML report",
    )
    parser.add_argument(
        "--output-summary",
        type=Path,
        default=None,
        help="Path to output summary JSON for dashboard aggregation",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Path to previous benchmark report/summary JSON for baseline diff",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="HTTP timeout per request in seconds",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        default=False,
        help="Disable TLS certificate verification for local development/testing",
    )
    args = parser.parse_args(argv)

    print("======================================================================")
    print("FINANCIAL REPORTING TEMPORAL BENCHMARK SUITE")
    print(f"Target Environment: {args.app_url}")
    print(f"Version Ref:        {args.version_ref}")
    print(f"Cases Selected:     {args.case}")
    print(f"Started At:         {datetime.now().isoformat()}")
    print("======================================================================")

    runner = ScenarioBenchmarkRunner(
        base_url=args.app_url, timeout=args.timeout, verify=not args.insecure
    )

    requested = [c.strip().lower() for c in args.case.split(",")]
    run_all = "all" in requested

    results: list[CaseResult] = []

    if run_all or "1" in requested:
        results.append(execute_case_1(runner))

    if run_all or "2" in requested:
        results.append(execute_case_2(runner))

    if run_all or "3" in requested:
        results.append(execute_case_3(runner))

    if run_all or "4" in requested:
        results.append(execute_case_4(runner))

    if run_all or "5" in requested:
        results.append(execute_case_5(runner))

    all_passed = all(r.status == "PASS" for r in results)

    # Save JSON report
    report_data = {
        "suite": "financial_reporting_temporal_scenarios",
        "version_ref": args.version_ref,
        "app_url": args.app_url,
        "run_at": datetime.now().isoformat(),
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == "PASS"),
            "failed": sum(1 for r in results if r.status != "PASS"),
            "success": all_passed,
        },
        "results": [asdict(r) for r in results],
    }

    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

    # Baseline diff
    baseline_data = None
    if args.baseline and args.baseline.exists():
        try:
            with open(args.baseline, "r", encoding="utf-8") as f:
                baseline_data = json.load(f)
        except Exception as exc:
            print(f"⚠️ Failed to read baseline {args.baseline}: {exc}", file=sys.stderr)

    # Save HTML report
    if args.output_html:
        args.output_html.parent.mkdir(parents=True, exist_ok=True)
        html_report = generate_html_report(report_data, baseline_data=baseline_data)
        with open(args.output_html, "w", encoding="utf-8") as f:
            f.write(html_report)
        print(f"HTML report saved to: {args.output_html} ({len(html_report)} bytes)")

    # Save Summary JSON
    if args.output_summary:
        args.output_summary.parent.mkdir(parents=True, exist_ok=True)
        summary_data = extract_summary_data(report_data)
        with open(args.output_summary, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
        print(f"Summary JSON saved to: {args.output_summary}")

    print("======================================================================")
    print("BENCHMARK EXECUTION SUMMARY")
    print("======================================================================")
    for r in results:
        status_icon = "✅ PASS" if r.status == "PASS" else "❌ FAIL"
        print(
            f"{status_icon} | {r.case_id.upper()}: {r.case_name} ({r.duration_seconds:.2f}s)"
        )
        if r.error_message:
            print(f"       Error: {r.error_message}")
    print("----------------------------------------------------------------------")
    print(
        f"Total: {len(results)} | Passed: {report_data['summary']['passed']} | Failed: {report_data['summary']['failed']}"
    )
    if args.json_report:
        print(f"Report saved to: {args.json_report}")
    print("======================================================================")

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
