"""
Case 2: Multi-PII Household Operations and Category Reconciliation benchmark scenario.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from tools._lib.benchmarks.case_types import CaseResult
from tools._lib.benchmarks.oracles import assert_triple_accounting_articulation
from tools._lib.benchmarks.statement_generators import (
    generate_household_wife_operations_csv,
    generate_standard_operations_csv,
)

if TYPE_CHECKING:
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def _upload_household_statements(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Husband DBS Statement
    print("  [2/6] Uploading Husband's DBS Bank CSV statement...")
    husband_bytes = generate_standard_operations_csv(Decimal("10000.00"))
    h_id = runner.upload_statement(
        client, husband_bytes, "husband_dbs_operations.csv", institution="DBS Bank"
    )
    h_data = runner.wait_for_statement_parsed(client, h_id)
    print(
        f"        Husband DBS Parsed: Opening={h_data.get('opening_balance')}, "
        f"Closing={h_data.get('closing_balance')}, Txns={len(h_data.get('transactions', []))}"
    )
    assert Decimal(h_data["opening_balance"]) == Decimal("10000.00")
    assert Decimal(h_data["closing_balance"]) == Decimal("12800.00")
    runner.adjudicate_unmatched_items(client, h_id)
    runner.approve_statement(client, h_id)
    print("        Husband DBS statement approved.")

    # Wife SCB Statement
    print("  [3/6] Uploading Wife's Standard Chartered CSV statement...")
    wife_bytes = generate_household_wife_operations_csv(Decimal("5000.00"))
    w_id = runner.upload_statement(
        client,
        wife_bytes,
        "wife_scb_operations.csv",
        institution="Standard Chartered Bank",
    )
    w_data = runner.wait_for_statement_parsed(client, w_id)
    print(
        f"        Wife SCB Parsed: Opening={w_data.get('opening_balance')}, "
        f"Closing={w_data.get('closing_balance')}, Txns={len(w_data.get('transactions', []))}"
    )
    assert Decimal(w_data["opening_balance"]) == Decimal("5000.00")
    assert Decimal(w_data["closing_balance"]) == Decimal("8100.00")
    runner.adjudicate_unmatched_items(client, w_id)
    runner.approve_statement(client, w_id)
    print("        Wife SCB statement approved.")
    return h_data, w_data


def _verify_household_statements(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    bool,
]:
    # Balance Sheet
    print("  [4/6] Verifying Consolidated Household Balance Sheet as of 2025-04-30...")
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
    assert is_balanced is True, f"Balance sheet not balanced: delta={equation_delta}"
    assert equation_delta == Decimal("0.00"), (
        f"Equation delta not zero: {equation_delta}"
    )
    assert total_assets == Decimal("20900.00"), (
        f"Expected total assets 20900.00 (12800 DBS + 8100 SCB), got {total_assets}"
    )
    assert total_equity == Decimal("15000.00"), (
        f"Expected total equity 15000.00, got {total_equity}"
    )

    # Income Statement & Cash Flow
    print(
        "  [5/6] Verifying Consolidated Income Statement (2025-04-01 to 2025-04-30)..."
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
    assert total_income == Decimal("8500.00"), (
        f"Expected total income 8500.00 (5000 + 3500), got {total_income}"
    )
    assert total_expenses == Decimal("2600.00"), (
        f"Expected total expenses 2600.00 (2200 + 400), got {total_expenses}"
    )
    assert net_income == Decimal("5900.00"), (
        f"Expected net income 5900.00, got {net_income}"
    )

    print("  [6/6] Verifying Consolidated Cash Flow...")
    cf = runner.get_cash_flow(client, start_date="2025-04-01", end_date="2025-04-30")
    cfs = cf.get("summary", {})
    beg_cash = Decimal(cfs.get("beginning_cash", "0"))
    net_cash = Decimal(cfs.get("net_cash_flow", "0"))
    end_cash = Decimal(cfs.get("ending_cash", "0"))
    print(
        f"        Beginning Cash={beg_cash}, Net Cash Flow={net_cash}, Ending Cash={end_cash}"
    )
    assert beg_cash == Decimal("15000.00"), (
        f"Expected beginning cash 15000.00, got {beg_cash}"
    )
    assert net_cash == Decimal("5900.00"), (
        f"Expected net cash flow 5900.00, got {net_cash}"
    )
    assert end_cash == Decimal("20900.00"), (
        f"Expected ending cash 20900.00, got {end_cash}"
    )
    assert beg_cash + net_cash == end_cash, "Cash flow rollforward mismatch"
    assert_triple_accounting_articulation(bs, inc)

    return (
        total_assets,
        total_equity,
        total_income,
        total_expenses,
        net_income,
        beg_cash,
        end_cash,
        equation_delta,
        is_balanced,
    )


def execute_case_2(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 2: Multi-PII Household Operations & Category Reconciliation.
    """
    start_time = time.time()
    case_name = "Case 2: Multi-PII Household Operations & Category Reconciliation"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case2_household")
        print(f"  [1/6] Registered test user: {user_email}")

        _upload_household_statements(runner, client)
        (
            total_assets,
            total_equity,
            total_income,
            total_expenses,
            net_income,
            beg_cash,
            end_cash,
            equation_delta,
            is_balanced,
        ) = _verify_household_statements(runner, client)

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_2",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details={
                "household_husband_cash": "12800.00",
                "household_wife_cash": "8100.00",
                "opening_balance": "15000.00",
                "closing_balance": "20900.00",
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
