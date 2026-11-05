"""
Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet benchmark scenario.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from common.testing.benchmarks.case_types import CaseResult
from common.testing.benchmarks.oracles import assert_triple_accounting_articulation
from common.testing.benchmarks.statement_generators import (
    generate_multicurrency_hkd_csv,
    generate_multicurrency_usd_csv,
    generate_standard_operations_csv,
)

if TYPE_CHECKING:
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def _set_verdict(
    details: dict[str, Any] | None,
    key: str,
    passed: bool,
) -> bool:
    if details is not None:
        verdicts = details.setdefault("assertion_verdicts", {})
        verdicts[key] = "passed" if passed else "failed"
    return passed


def _upload_multicurrency_statements(
    runner: ScenarioBenchmarkRunner,
    client: httpx.Client,
    details: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    # 1. SGD Statement
    print("  [2/6] Uploading SGD operating statement...")
    sgd_bytes = generate_standard_operations_csv(Decimal("10000.00"))
    sgd_id = runner.upload_statement(
        client, sgd_bytes, "operations_sgd.csv", institution="DBS Singapore"
    )
    sgd_data = runner.wait_for_statement_parsed(client, sgd_id)
    if details is not None:
        details["sgd_closing_balance"] = str(sgd_data["closing_balance"])
    _set_verdict(
        details, "sgd_closing_balance", sgd_data.get("balance_validated") is True
    )
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
    if details is not None:
        details["usd_closing_balance"] = str(usd_data["closing_balance"])
    _set_verdict(
        details, "usd_closing_balance", usd_data.get("balance_validated") is True
    )
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
    if details is not None:
        details["hkd_closing_balance"] = str(hkd_data["closing_balance"])
    _set_verdict(
        details, "hkd_closing_balance", hkd_data.get("balance_validated") is True
    )
    assert hkd_data.get("balance_validated") is True, f"HKD balance invalid: {hkd_data}"
    runner.adjudicate_unmatched_items(client, hkd_id)
    runner.approve_statement(client, hkd_id)
    print(f"        HKD statement approved: Closing={hkd_data['closing_balance']} HKD")

    return sgd_data, usd_data, hkd_data


def _verify_multicurrency_balance_sheets(
    runner: ScenarioBenchmarkRunner,
    client: httpx.Client,
    details: dict[str, Any] | None = None,
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

    # 5. Consolidated Balance Sheet in Target Currency (USD)
    print("  [6/6] Verifying Consolidated Balance Sheet in USD (as of 2025-04-30)...")
    bs_usd = runner.get_balance_sheet(client, as_of_date="2025-04-30", currency="USD")
    assets_usd = Decimal(bs_usd["total_assets"])
    delta_usd = Decimal(bs_usd["equation_delta"])
    balanced_usd = bs_usd["is_balanced"]

    print(
        f"        USD Balance Sheet: Assets={assets_usd}, Delta={delta_usd}, Balanced={balanced_usd}"
    )

    if details is not None:
        details.update(
            {
                "currencies_consolidated": "SGD, USD, HKD",
                "total_assets_sgd": str(assets_sgd),
                "equation_delta_sgd": str(delta_sgd),
                "is_balanced_sgd": balanced_sgd,
                "total_assets_usd": str(assets_usd),
                "equation_delta_usd": str(delta_usd),
                "is_balanced_usd": balanced_usd,
                "equation_delta": str(delta_sgd),
                "is_balanced": balanced_sgd,
            }
        )

    _set_verdict(details, "total_assets_sgd", assets_sgd > Decimal("12800.00"))
    _set_verdict(
        details,
        "equation_delta_sgd",
        balanced_sgd is True and delta_sgd == Decimal("0.00"),
    )
    _set_verdict(
        details,
        "equation_delta_usd",
        assets_usd > Decimal("0.00")
        and balanced_usd is True
        and delta_usd == Decimal("0.00"),
    )

    assert assets_sgd > Decimal("12800.00"), (
        "Multi-currency assets must be consolidated into SGD"
    )
    assert balanced_sgd is True, (
        f"SGD balance sheet must be balanced under IAS 21 CTA: delta={delta_sgd}"
    )
    assert delta_sgd == Decimal("0.00"), (
        f"SGD equation delta must be exactly zero: {delta_sgd}"
    )
    try:
        assert_triple_accounting_articulation(bs_sgd)
    except AssertionError:
        _set_verdict(details, "equation_delta_sgd", False)
        raise

    assert assets_usd > Decimal("0.00"), "Consolidated USD assets must be positive"
    assert balanced_usd is True, (
        f"USD balance sheet must be balanced under IAS 21 CTA: delta={delta_usd}"
    )
    assert delta_usd == Decimal("0.00"), (
        f"USD equation delta must be exactly zero: {delta_usd}"
    )
    try:
        assert_triple_accounting_articulation(bs_usd)
    except AssertionError:
        _set_verdict(details, "equation_delta_usd", False)
        raise
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

    verdicts: dict[str, str] = {
        "sgd_closing_balance": "not_run",
        "usd_closing_balance": "not_run",
        "hkd_closing_balance": "not_run",
        "total_assets_sgd": "not_run",
        "equation_delta_sgd": "not_run",
        "equation_delta_usd": "not_run",
    }
    details: dict[str, Any] = {"assertion_verdicts": verdicts}

    try:
        client, user_email, _ = runner.create_ephemeral_client("case4")
        print(f"  [1/6] Registered test user: {user_email}")

        _upload_multicurrency_statements(runner, client, details=details)
        _verify_multicurrency_balance_sheets(runner, client, details=details)

        # Flow 17: Multi-Currency Transfer Realized FX Gain/Loss Decomposition (post-window 2025-05-05)
        fx_source_acc = runner.create_account(
            client, name="USD Wire Outflow Clearing", type="ASSET", currency="SGD"
        )
        fx_target_acc = runner.create_account(
            client, name="SGD Wire Receiving Account", type="ASSET", currency="SGD"
        )
        fx_gain_acc = runner.create_account(
            client, name="Realized FX Gain on Wire", type="INCOME", currency="SGD"
        )
        runner.post_manual_journal_entry(
            client,
            memo="Multi-Currency Wire Transfer with Realized FX Gain",
            entry_date="2025-05-05",
            lines=[
                {
                    "account_id": fx_target_acc["id"],
                    "direction": "DEBIT",
                    "amount": "1350.00",
                    "currency": "SGD",
                },
                {
                    "account_id": fx_source_acc["id"],
                    "direction": "CREDIT",
                    "amount": "1340.00",
                    "currency": "SGD",
                },
                {
                    "account_id": fx_gain_acc["id"],
                    "direction": "CREDIT",
                    "amount": "10.00",
                    "currency": "SGD",
                },
            ],
            rationale="OutflowValueInBase (1340.00) + RealizedGain (10.00) == InflowValueInBase (1350.00)",
        )
        bs_post_fx = runner.get_balance_sheet(
            client, as_of_date="2025-05-31", currency="SGD"
        )
        post_fx_ok = bs_post_fx["is_balanced"] is True and Decimal(
            str(bs_post_fx["equation_delta"])
        ) == Decimal("0.00")
        if not post_fx_ok:
            _set_verdict(details, "equation_delta_sgd", False)
        assert bs_post_fx["is_balanced"] is True, (
            f"Balance sheet unbalanced after Flow 17 FX entry: {bs_post_fx}"
        )
        assert Decimal(str(bs_post_fx["equation_delta"])) == Decimal("0.00")

        details.update(
            {
                "flow_17_realized_fx_gain_sgd": "10.00",
                "cta_variance_explained": (
                    "Translation variance between spot rate balance sheet items and period-average "
                    "net income is fully absorbed by the IAS 21 CTA equity reserve."
                ),
            }
        )

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_4",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details=details,
        )
    except Exception as exc:
        duration = time.time() - start_time
        print(f"❌ {case_name} FAILED in {duration:.2f}s: {exc}\n")
        return CaseResult(
            case_id="case_4",
            case_name=case_name,
            status="FAIL",
            duration_seconds=duration,
            details=details,
            error_message=str(exc),
        )
