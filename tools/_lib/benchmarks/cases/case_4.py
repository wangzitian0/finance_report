"""
Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet benchmark scenario.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from tools._lib.benchmarks.case_types import CaseResult
from tools._lib.benchmarks.statement_generators import (
    generate_multicurrency_hkd_csv,
    generate_multicurrency_usd_csv,
    generate_standard_operations_csv,
)

if TYPE_CHECKING:
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def _upload_multicurrency_statements(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    # 1. SGD Statement
    print("  [2/6] Uploading SGD operating statement...")
    sgd_bytes = generate_standard_operations_csv(Decimal("10000.00"))
    sgd_id = runner.upload_statement(
        client, sgd_bytes, "operations_sgd.csv", institution="DBS Singapore"
    )
    sgd_data = runner.wait_for_statement_parsed(client, sgd_id)
    assert sgd_data.get("balance_validated") is True, f"SGD balance invalid: {sgd_data}"
    runner.adjudicate_unmatched_items(client, sgd_id)
    runner.approve_statement(client, sgd_id)
    print(f"        SGD statement approved: Closing={sgd_data['closing_balance']} SGD")

    # 2. USD Statement
    print("  [3/6] Uploading USD operating statement...")
    usd_bytes = generate_multicurrency_usd_csv(Decimal("5000.00"))
    usd_id = runner.upload_statement(
        client,
        usd_bytes,
        "operations_usd.csv",
        institution="Silicon Valley Bank",
        currency="USD",
    )
    usd_data = runner.wait_for_statement_parsed(client, usd_id)
    assert usd_data.get("balance_validated") is True, f"USD balance invalid: {usd_data}"
    runner.adjudicate_unmatched_items(client, usd_id)
    runner.approve_statement(client, usd_id)
    print(f"        USD statement approved: Closing={usd_data['closing_balance']} USD")

    # 3. HKD Statement
    print("  [4/6] Uploading HKD operating statement...")
    hkd_bytes = generate_multicurrency_hkd_csv(Decimal("20000.00"))
    hkd_id = runner.upload_statement(
        client,
        hkd_bytes,
        "operations_hkd.csv",
        institution="HSBC Hong Kong",
        currency="HKD",
    )
    hkd_data = runner.wait_for_statement_parsed(client, hkd_id)
    assert hkd_data.get("balance_validated") is True, f"HKD balance invalid: {hkd_data}"
    runner.adjudicate_unmatched_items(client, hkd_id)
    runner.approve_statement(client, hkd_id)
    print(f"        HKD statement approved: Closing={hkd_data['closing_balance']} HKD")

    return sgd_data, usd_data, hkd_data


def _verify_multicurrency_balance_sheets(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[Decimal, Decimal, bool, Decimal, Decimal, bool]:
    # 4. Consolidated Balance Sheet in Base Currency (SGD)
    print("  [5/6] Verifying Consolidated Balance Sheet in SGD (as of 2025-04-30)...")
    bs_sgd = runner.get_balance_sheet(client, as_of_date="2025-04-30", currency="SGD")
    assets_sgd = Decimal(bs_sgd["total_assets"])
    liab_sgd = Decimal(bs_sgd["total_liabilities"])
    equity_sgd = Decimal(bs_sgd["total_equity"])
    delta_sgd = Decimal(bs_sgd["equation_delta"])
    balanced_sgd = bs_sgd["is_balanced"]

    print(
        f"        SGD Balance Sheet: Assets={assets_sgd}, Liab={liab_sgd}, "
        f"Equity={equity_sgd}, Delta={delta_sgd}, Balanced={balanced_sgd}"
    )
    assert assets_sgd > Decimal("12800.00"), (
        "Multi-currency assets must be consolidated into SGD"
    )
    assert balanced_sgd is True, (
        f"SGD balance sheet must be balanced under IAS 21 CTA: delta={delta_sgd}"
    )
    assert abs(delta_sgd) < Decimal("0.05"), (
        f"SGD equation delta exceeds tolerance: {delta_sgd}"
    )

    # 5. Consolidated Balance Sheet in Target Currency (USD)
    print("  [6/6] Verifying Consolidated Balance Sheet in USD (as of 2025-04-30)...")
    bs_usd = runner.get_balance_sheet(client, as_of_date="2025-04-30", currency="USD")
    assets_usd = Decimal(bs_usd["total_assets"])
    delta_usd = Decimal(bs_usd["equation_delta"])
    balanced_usd = bs_usd["is_balanced"]

    print(
        f"        USD Balance Sheet: Assets={assets_usd}, Delta={delta_usd}, Balanced={balanced_usd}"
    )
    assert assets_usd > Decimal("0.00"), "Consolidated USD assets must be positive"
    assert balanced_usd is True, (
        f"USD balance sheet must be balanced under IAS 21 CTA: delta={delta_usd}"
    )
    assert abs(delta_usd) < Decimal("0.05"), (
        f"USD equation delta exceeds tolerance: {delta_usd}"
    )
    return assets_sgd, delta_sgd, balanced_sgd, assets_usd, delta_usd, balanced_usd


def execute_case_4(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet.
    """
    start_time = time.time()
    case_name = "Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case4")
        print(f"  [1/6] Registered test user: {user_email}")

        sgd_data, usd_data, hkd_data = _upload_multicurrency_statements(runner, client)
        (
            assets_sgd,
            delta_sgd,
            balanced_sgd,
            assets_usd,
            delta_usd,
            balanced_usd,
        ) = _verify_multicurrency_balance_sheets(runner, client)

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
                "cta_variance_explained": (
                    "Translation variance between spot rate balance sheet items and period-average "
                    "net income is fully absorbed by the IAS 21 CTA equity reserve."
                ),
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
