"""
Case 3: Credit Card Liability & Non-P&L Repayment Clearance benchmark scenario.
"""

from __future__ import annotations

import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from tools._lib.benchmarks.case_types import CaseResult
from tools._lib.benchmarks.oracles import assert_triple_accounting_articulation
from tools._lib.benchmarks.statement_generators import (
    generate_credit_card_repayment_bank_pdf,
)

if TYPE_CHECKING:
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def _setup_card_liability_and_expenses(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[dict[str, Any], dict[str, Any]]:
    print("  [2/6] Creating Credit Card Liability and Operating Expense Accounts...")
    cc_acc = runner.create_account(
        client,
        name="Citi Rewards Visa Card",
        type="LIABILITY",
        currency="SGD",
    )
    exp_acc = runner.create_account(
        client,
        name="Card Operating Expenses - Dining & SaaS",
        type="EXPENSE",
        currency="SGD",
    )
    print(
        f"        Created Liability Account '{cc_acc['name']}' (ID: {cc_acc['id']}) "
        f"and Expense Account '{exp_acc['name']}' (ID: {exp_acc['id']})"
    )
    return cc_acc, exp_acc


def _post_card_purchases(
    runner: ScenarioBenchmarkRunner,
    client: httpx.Client,
    cc_acc: dict[str, Any],
    exp_acc: dict[str, Any],
) -> None:
    print("  [3/6] Posting Credit Card purchases (1,200.00 SGD)...")
    lines = [
        {
            "account_id": exp_acc["id"],
            "direction": "DEBIT",
            "amount": "1200.00",
            "currency": "SGD",
        },
        {
            "account_id": cc_acc["id"],
            "direction": "CREDIT",
            "amount": "1200.00",
            "currency": "SGD",
        },
    ]
    runner.post_manual_journal_entry(
        client,
        memo="Monthly credit card purchases for dining and software",
        lines=lines,
        entry_date="2025-04-10",
        rationale="Benchmark credit card liability incurrence",
    )
    print(
        "        Card purchases posted: Liability=+1,200.00 SGD, Expenses=+1,200.00 SGD"
    )


def _upload_bank_card_repayment(
    runner: ScenarioBenchmarkRunner, client: httpx.Client, cc_acc: dict[str, Any]
) -> None:
    print("  [4/6] Uploading Bank Statement with 1,200.00 SGD Card Payment...")
    with tempfile.TemporaryDirectory() as td:
        pdf_tmp = Path(td) / "case3_cc_repay_bank.pdf"
        pdf_bytes = generate_credit_card_repayment_bank_pdf(
            pdf_tmp, opening_balance=Decimal("10000.00")
        )
        stmt_id = runner.upload_statement(
            client, pdf_bytes, "dbs_bank_cc_repayment.pdf", institution="DBS Bank"
        )
    stmt_data = runner.wait_for_statement_parsed(client, stmt_id)
    print(
        f"        Bank Statement Parsed: Opening={stmt_data['opening_balance']}, "
        f"Closing={stmt_data['closing_balance']}"
    )

    runner.adjudicate_unmatched_items(
        client,
        stmt_id,
        non_pnl_intent="card_repayment",
        non_pnl_counter_account_id=cc_acc["id"],
    )
    runner.approve_statement(client, stmt_id)
    print("        Bank payment approved with intent=card_repayment.")


def _verify_card_repayment_invariants(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, bool]:
    print("  [5/6] Verifying Balance Sheet Debt Clearance (as of 2025-04-30)...")
    bs = runner.get_balance_sheet(client, as_of_date="2025-04-30")
    total_assets = Decimal(bs["total_assets"])
    total_liabilities = Decimal(bs["total_liabilities"])
    total_equity = Decimal(bs["total_equity"])
    equation_delta = Decimal(bs["equation_delta"])
    is_balanced = bs["is_balanced"]

    print(
        f"        Balance Sheet: Total Assets={total_assets}, Total Liab={total_liabilities}, "
        f"Total Equity={total_equity}, Delta={equation_delta}, Balanced={is_balanced}"
    )
    assert is_balanced is True, f"Balance sheet not balanced: delta={equation_delta}"
    assert equation_delta == Decimal("0.00"), (
        f"Equation delta not zero: {equation_delta}"
    )
    assert total_assets == Decimal("8800.00"), (
        f"Expected bank cash assets 8800.00 (10000 - 1200), got {total_assets}"
    )
    assert total_liabilities == Decimal("0.00"), (
        f"Expected credit card liability 0.00 (cleared), got {total_liabilities}"
    )
    assert total_equity == Decimal("10000.00"), (
        f"Expected total equity 10000.00, got {total_equity}"
    )

    print("  [6/6] Verifying Zero Double-Counting on Income Statement...")
    inc = runner.get_income_statement(
        client, start_date="2025-04-01", end_date="2025-04-30"
    )
    total_income = Decimal(inc["total_income"])
    total_expenses = Decimal(inc["total_expenses"])
    net_income = Decimal(inc["net_income"])
    print(
        f"        Total Income={total_income}, Total Expenses={total_expenses}, Net Income={net_income}"
    )
    assert total_income == Decimal("0.00"), (
        f"Expected total income 0.00, got {total_income}"
    )
    assert total_expenses == Decimal("1200.00"), (
        f"Expected total expenses 1200.00 (single count), got {total_expenses}"
    )
    assert net_income == Decimal("-1200.00"), (
        f"Expected net income -1200.00, got {net_income}"
    )
    assert_triple_accounting_articulation(bs, inc)
    return (
        total_assets,
        total_equity,
        total_liabilities,
        total_income,
        total_expenses,
        net_income,
        equation_delta,
        is_balanced,
    )


def execute_case_3(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 3: Credit Card Liability & Non-P&L Repayment Clearance.
    """
    start_time = time.time()
    case_name = "Case 3: Credit Card Liability & Non-P&L Repayment Clearance"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case3_card_liability")
        print(f"  [1/6] Registered test user: {user_email}")

        cc_acc, exp_acc = _setup_card_liability_and_expenses(runner, client)
        _post_card_purchases(runner, client, cc_acc, exp_acc)
        _upload_bank_card_repayment(runner, client, cc_acc)
        (
            total_assets,
            total_equity,
            total_liabilities,
            total_income,
            total_expenses,
            net_income,
            equation_delta,
            is_balanced,
        ) = _verify_card_repayment_invariants(runner, client)

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_3",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details={
                "card_spend_recorded": "1200.00",
                "bank_repayment": "1200.00",
                "ending_bank_cash": "8800.00",
                "credit_card_liability_cleared": "0.00",
                "total_assets": str(total_assets),
                "total_equity": str(total_equity),
                "total_liabilities": str(total_liabilities),
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
