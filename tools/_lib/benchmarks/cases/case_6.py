"""
Case 6: Bank Overdraft & Capital Gain Asset Disposal benchmark scenario.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from tools._lib.benchmarks.case_types import CaseResult

if TYPE_CHECKING:
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def _setup_overdraft_accounts(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    print(
        "  [2/6] Creating Checking, Expense, Equity, Asset, and Capital Gain accounts..."
    )
    checking = runner.create_account(
        client, name="Primary Checking Account", type="ASSET", currency="SGD"
    )
    emergency_exp = runner.create_account(
        client, name="Emergency Medical Expense", type="EXPENSE", currency="SGD"
    )
    owner_equity = runner.create_account(
        client, name="Owner Capital Equity", type="EQUITY", currency="SGD"
    )
    art_asset = runner.create_account(
        client, name="Collectible Art Investment", type="ASSET", currency="SGD"
    )
    capital_gain = runner.create_account(
        client, name="Realized Capital Gain on Art", type="INCOME", currency="SGD"
    )
    return checking, emergency_exp, owner_equity, art_asset, capital_gain


def _post_initial_deposit_and_overdraft(
    runner: ScenarioBenchmarkRunner,
    client: httpx.Client,
    checking: dict[str, Any],
    emergency_exp: dict[str, Any],
    owner_equity: dict[str, Any],
) -> None:
    print(
        "  [3/6] Posting Initial Checking Deposit (1,000 SGD) and Overdraft Expense (2,500 SGD)..."
    )
    # 1. Deposit 1,000 SGD
    runner.post_manual_journal_entry(
        client,
        memo="Initial Checking Deposit",
        entry_date="2025-05-01",
        lines=[
            {
                "account_id": checking["id"],
                "direction": "DEBIT",
                "amount": "1000.00",
                "currency": "SGD",
            },
            {
                "account_id": owner_equity["id"],
                "direction": "CREDIT",
                "amount": "1000.00",
                "currency": "SGD",
            },
        ],
        rationale="Initial cash capital",
    )

    # 2. Overdraft Expense 2,500 SGD (Checking balance becomes -1,500 SGD)
    runner.post_manual_journal_entry(
        client,
        memo="Emergency Medical Expense Paid via Checking Overdraft",
        entry_date="2025-05-05",
        lines=[
            {
                "account_id": emergency_exp["id"],
                "direction": "DEBIT",
                "amount": "2500.00",
                "currency": "SGD",
            },
            {
                "account_id": checking["id"],
                "direction": "CREDIT",
                "amount": "2500.00",
                "currency": "SGD",
            },
        ],
        rationale="Overdraft expenditure",
    )


def _verify_overdraft_balance_sheet(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[Decimal, Decimal, Decimal, Decimal, bool]:
    print("  [4/6] Verifying Overdraft Balance Sheet as of 2025-05-10...")
    bs = runner.get_balance_sheet(client, as_of_date="2025-05-10", currency="SGD")
    total_assets = Decimal(bs["total_assets"])
    total_equity = Decimal(bs["total_equity"])
    net_income = Decimal(bs["net_income"])
    equation_delta = Decimal(bs["equation_delta"])
    is_balanced = bs["is_balanced"]

    print(
        f"        Overdraft State: Assets={total_assets}, Equity={total_equity}, "
        f"Net Income={net_income}, Delta={equation_delta}, Balanced={is_balanced}"
    )
    assert total_assets == Decimal("-1500.00"), (
        f"Expected -1500.00 total assets, got {total_assets}"
    )
    assert net_income == Decimal("-2500.00"), (
        f"Expected -2500.00 net income, got {net_income}"
    )
    assert total_equity == Decimal("1000.00"), (
        f"Expected 1000.00 equity, got {total_equity}"
    )
    assert is_balanced is True, f"Balance sheet not balanced: {bs}"
    assert equation_delta == Decimal("0.00"), (
        f"Equation delta not zero: {equation_delta}"
    )
    return total_assets, total_equity, net_income, equation_delta, is_balanced


def _post_capital_injection_and_art_disposal(
    runner: ScenarioBenchmarkRunner,
    client: httpx.Client,
    checking: dict[str, Any],
    owner_equity: dict[str, Any],
    art_asset: dict[str, Any],
    capital_gain: dict[str, Any],
) -> None:
    print(
        "  [5/6] Posting Capital Injection (10k), Art Purchase (4k), and Art Disposal (6.5k)..."
    )
    # 1. Capital Injection 10,000 SGD on 2025-05-15
    runner.post_manual_journal_entry(
        client,
        memo="Emergency Capital Injection",
        entry_date="2025-05-15",
        lines=[
            {
                "account_id": checking["id"],
                "direction": "DEBIT",
                "amount": "10000.00",
                "currency": "SGD",
            },
            {
                "account_id": owner_equity["id"],
                "direction": "CREDIT",
                "amount": "10000.00",
                "currency": "SGD",
            },
        ],
        rationale="Owner equity contribution",
    )

    # 2. Purchase Collectible Art 4,000 SGD on 2025-05-18
    runner.post_manual_journal_entry(
        client,
        memo="Purchase Collectible Art",
        entry_date="2025-05-18",
        lines=[
            {
                "account_id": art_asset["id"],
                "direction": "DEBIT",
                "amount": "4000.00",
                "currency": "SGD",
            },
            {
                "account_id": checking["id"],
                "direction": "CREDIT",
                "amount": "4000.00",
                "currency": "SGD",
            },
        ],
        rationale="Asset acquisition",
    )

    # 3. Sell Collectible Art for 6,500 SGD on 2025-05-25 (Cost: 4,000, Realized Gain: 2,500)
    runner.post_manual_journal_entry(
        client,
        memo="Sell Collectible Art with Realized Gain",
        entry_date="2025-05-25",
        lines=[
            {
                "account_id": checking["id"],
                "direction": "DEBIT",
                "amount": "6500.00",
                "currency": "SGD",
            },
            {
                "account_id": art_asset["id"],
                "direction": "CREDIT",
                "amount": "4000.00",
                "currency": "SGD",
            },
            {
                "account_id": capital_gain["id"],
                "direction": "CREDIT",
                "amount": "2500.00",
                "currency": "SGD",
            },
        ],
        rationale="Asset disposal with capital gain",
    )


def _verify_final_articulated_balance_sheet(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[Decimal, Decimal, Decimal, Decimal, bool]:
    print("  [6/6] Verifying Final Month-End Balance Sheet as of 2025-05-31...")
    bs = runner.get_balance_sheet(client, as_of_date="2025-05-31", currency="SGD")
    total_assets = Decimal(bs["total_assets"])
    total_equity = Decimal(bs["total_equity"])
    net_income = Decimal(bs["net_income"])
    equation_delta = Decimal(bs["equation_delta"])
    is_balanced = bs["is_balanced"]

    print(
        f"        Final State: Assets={total_assets}, Equity={total_equity}, "
        f"Net Income={net_income}, Delta={equation_delta}, Balanced={is_balanced}"
    )
    assert total_assets == Decimal("11000.00"), (
        f"Expected 11000.00 total assets, got {total_assets}"
    )
    assert total_equity == Decimal("11000.00"), (
        f"Expected 11000.00 equity, got {total_equity}"
    )
    assert net_income == Decimal("0.00"), f"Expected 0.00 net income, got {net_income}"
    assert is_balanced is True, f"Balance sheet not balanced: {bs}"
    assert equation_delta == Decimal("0.00"), (
        f"Equation delta not zero: {equation_delta}"
    )
    return total_assets, total_equity, net_income, equation_delta, is_balanced


def execute_case_6(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 6: Bank Overdraft & Capital Gain Asset Disposal.
    """
    start_time = time.time()
    case_name = "Case 6: Bank Overdraft & Capital Gain Disposal"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case6_overdraft")
        print(f"  [1/6] Registered test user: {user_email}")

        checking, emergency_exp, owner_equity, art_asset, capital_gain = (
            _setup_overdraft_accounts(runner, client)
        )
        _post_initial_deposit_and_overdraft(
            runner, client, checking, emergency_exp, owner_equity
        )
        (
            od_assets,
            od_equity,
            od_net_income,
            od_delta,
            od_balanced,
        ) = _verify_overdraft_balance_sheet(runner, client)

        _post_capital_injection_and_art_disposal(
            runner, client, checking, owner_equity, art_asset, capital_gain
        )
        (
            final_assets,
            final_equity,
            final_net_income,
            final_delta,
            final_balanced,
        ) = _verify_final_articulated_balance_sheet(runner, client)

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_6",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details={
                "overdraft_cash": str(od_assets),
                "ending_cash": str(final_assets),
                "capital_gain": "2500.00",
                "net_income": str(final_net_income),
                "total_assets": str(final_assets),
                "total_equity": str(final_equity),
                "equation_delta": str(final_delta),
                "is_balanced": final_balanced,
            },
        )
    except Exception as exc:
        duration = time.time() - start_time
        print(f"❌ {case_name} FAILED in {duration:.2f}s: {exc}\n")
        return CaseResult(
            case_id="case_6",
            case_name=case_name,
            status="FAIL",
            duration_seconds=duration,
            error_message=str(exc),
        )
