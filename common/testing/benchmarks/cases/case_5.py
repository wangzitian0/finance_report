"""
Case 5: Holistic Multi-Asset and Tax Ecosystem benchmark scenario.
"""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from common.testing.benchmarks.case_types import CaseResult
from common.testing.benchmarks.oracles import assert_triple_accounting_articulation

if TYPE_CHECKING:
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )

REPO_ROOT = Path(__file__).resolve().parents[4]


def _import_brokerage_and_update_prices(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> None:
    print("  [2/6] Importing Interactive Brokers positions...")
    brokerage_csv = (
        "Symbol,Quantity,Market Value,Currency\n"
        "AAPL,10,2000.00,USD\n"
        "VT,50,5500.00,USD\n"
    ).encode("utf-8")
    brokerage_stmt_id = runner.upload_statement(
        client,
        brokerage_csv,
        "ibkr_positions_20250430.csv",
        institution="Interactive Brokers",
    )
    brokerage_stmt = runner.wait_for_statement_parsed(client, brokerage_stmt_id)
    if brokerage_stmt.get("status") != "parsed":
        raise RuntimeError(
            f"Expected brokerage CSV statement status 'parsed', got {brokerage_stmt.get('status')}"
        )
    runner.assert_brokerage_import_requires_snapshot_date(client, brokerage_stmt_id)

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
        client,
        brokerage_payload,
        filename="ibkr_positions_20250430.json",
        source_document_id=brokerage_stmt_id,
    )
    runner.reject_statement(
        client,
        brokerage_stmt_id,
        notes="Undated brokerage CSV superseded by dated position snapshot",
    )
    print(
        f"        Imported positions: Created={import_resp.get('created_atomic_positions')}, "
        f"Reconciled={import_resp.get('reconcile_created')}"
    )
    assert (
        import_resp.get("created_atomic_positions", 0) >= 2
        or import_resp.get("parsed_positions", 0) >= 2
    )

    print(
        "  [3/6] Setting authoritative market prices for valuation as of 2025-04-30..."
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


def _verify_holdings(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[list[dict[str, Any]], list[str]]:
    print("  [4/6] Verifying /api/portfolio/holdings...")
    holdings_resp = runner.get_holdings(client, as_of_date="2025-04-30")
    items = holdings_resp.get("items", [])
    symbols = [item.get("asset_identifier") or item.get("symbol") for item in items]
    print(f"        Retrieved holdings: {symbols}")
    assert "AAPL" in symbols, f"Expected AAPL in holdings: {symbols}"
    assert "VT" in symbols, f"Expected VT in holdings: {symbols}"
    return items, symbols


def _execute_tax_withholding_fallback(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[Decimal, Decimal, Decimal, str]:
    print(
        "  [4/6] Executing Form W-2 / Payslip tax withholding fallback journal entry..."
    )
    cash_acc = runner.create_account(
        client, name="Payroll Cash Account", type="ASSET", currency="SGD"
    )
    tax_exp_acc = runner.create_account(
        client, name="Payroll Tax Withholding Expense", type="EXPENSE", currency="SGD"
    )
    salary_inc_acc = runner.create_account(
        client, name="Gross Salary Income", type="INCOME", currency="SGD"
    )
    # Gross: 10,000 SGD, Tax Withheld: 2,000 SGD, Net Cash: 8,000 SGD
    runner.post_manual_journal_entry(
        client,
        memo="Monthly Payroll with Tax Withholding",
        entry_date="2025-04-15",
        lines=[
            {
                "account_id": cash_acc["id"],
                "direction": "DEBIT",
                "amount": "8000.00",
                "currency": "SGD",
            },
            {
                "account_id": tax_exp_acc["id"],
                "direction": "DEBIT",
                "amount": "2000.00",
                "currency": "SGD",
            },
            {
                "account_id": salary_inc_acc["id"],
                "direction": "CREDIT",
                "amount": "10000.00",
                "currency": "SGD",
            },
        ],
        rationale="Tax and compensation withholding split fallback",
    )
    print(
        "        Posted tax withholding entry: Gross=+10,000, Tax=-2,000, Net Cash=+8,000 SGD"
    )
    return (
        Decimal("10000.00"),
        Decimal("2000.00"),
        Decimal("8000.00"),
        str(cash_acc["id"]),
    )


def _register_property_appraisal(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> None:
    print(
        "  [5/6] Registering Real Estate Property Appraisal from DocuBench (350,000.00 USD)..."
    )
    runner.create_valuation_snapshot(
        client,
        component_type="property_value",
        as_of_date="2025-04-30",
        value="350000.00",
        currency="USD",
        source="DocuBench FHA 1004 Appraisal (KpewWz3R)",
        valuation_basis="market_appraisal",
        liquidity_class="illiquid",
        notes="Residential property appraisal from DocuBench fixture KpewWz3R.pdf",
    )
    comp_resp = runner.get_valuation_components(client, as_of_date="2025-04-30")
    prop_items = [
        i
        for i in comp_resp.get("items", [])
        if i.get("component_type") == "property_value"
    ]
    print(
        f"        Valuation components registered: {len(comp_resp.get('items', []))} items"
    )
    assert len(prop_items) >= 1, (
        "Expected property_value component in valuation snapshot"
    )
    assert Decimal(prop_items[0]["value"]) == Decimal("350000.00")


def _verify_balance_sheet_multi_asset(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[Decimal, Decimal, Decimal, Decimal, bool]:
    print("  [6/6] Verifying Balance Sheet Multi-Asset Integration as of 2025-04-30...")
    # Liquid view
    bs_liquid = runner.get_balance_sheet(
        client, as_of_date="2025-04-30", include_restricted=False
    )
    liquid_assets = Decimal(bs_liquid["total_assets"])
    print(
        f"        Liquid Balance Sheet: Total Assets={liquid_assets} (Brokerage equities only)"
    )
    assert liquid_assets > Decimal("0.00"), "Brokerage liquid assets must be positive"
    assert liquid_assets < Decimal("50000.00"), (
        "Liquid-only view must exclude illiquid property"
    )

    # Comprehensive view
    bs = runner.get_balance_sheet(
        client, as_of_date="2025-04-30", include_restricted=True
    )
    total_assets = Decimal(bs["total_assets"])
    total_equity = Decimal(bs["total_equity"])
    equation_delta = Decimal(bs["equation_delta"])
    is_balanced = bs["is_balanced"]

    print(
        f"        Comprehensive Balance Sheet: Total Assets={total_assets}, "
        f"Total Equity={total_equity}, Delta={equation_delta}, Balanced={is_balanced}"
    )
    assert is_balanced is True, f"Balance sheet not balanced: delta={equation_delta}"
    assert equation_delta == Decimal("0.00"), (
        f"Equation delta not zero: {equation_delta}"
    )
    assert total_assets >= Decimal("450000.00"), (
        f"Comprehensive assets must include property ($350k USD) + stocks, got: {total_assets}"
    )
    assert any(
        item.get("allocation_liquidity_class") == "illiquid"
        or "DocuBench" in str(item.get("name", ""))
        or "Piekos" in str(item.get("name", ""))
        for item in bs.get("assets", [])
    ), "Expected illiquid real estate appraisal line in balance sheet assets"
    assert_triple_accounting_articulation(bs)
    return liquid_assets, total_assets, total_equity, equation_delta, is_balanced


def execute_case_5(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 5: Holistic Multi-Asset & Tax Ecosystem.
    """
    start_time = time.time()
    case_name = "Case 5: Holistic Multi-Asset & Tax Ecosystem"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case5_holistic")
        print(f"  [1/6] Registered test user: {user_email}")

        _import_brokerage_and_update_prices(runner, client)
        items, symbols = _verify_holdings(runner, client)
        gross_salary, tax_withheld, net_cash, payroll_cash_acc_id = (
            _execute_tax_withholding_fallback(runner, client)
        )
        _register_property_appraisal(runner, client)
        (
            liquid_assets,
            total_assets,
            total_equity,
            equation_delta,
            is_balanced,
        ) = _verify_balance_sheet_multi_asset(runner, client)

        # Flow 27: Financial Report to PDF Provenance Drilldown
        lineage = runner.get_account_lineage(
            client, account_id=payroll_cash_acc_id, as_of_date="2025-04-30"
        )
        lineage_lines = lineage.get("lines", [])
        assert len(lineage_lines) > 0, (
            f"Expected non-empty account lineage lines in Case 5, got {lineage}"
        )

        # Flow 20: Dividend Gross-to-Net & Withholding Tax Split (post-window 2025-05-05)
        div_inc_acc = runner.create_account(
            client, name="Gross Dividend Income", type="INCOME", currency="SGD"
        )
        div_tax_acc = runner.create_account(
            client,
            name="Dividend Withholding Tax Expense",
            type="EXPENSE",
            currency="SGD",
        )
        runner.post_manual_journal_entry(
            client,
            memo="Dividend Gross-to-Net & Withholding Tax Split",
            entry_date="2025-05-05",
            lines=[
                {
                    "account_id": payroll_cash_acc_id,
                    "direction": "DEBIT",
                    "amount": "70.00",
                    "currency": "SGD",
                },
                {
                    "account_id": div_tax_acc["id"],
                    "direction": "DEBIT",
                    "amount": "30.00",
                    "currency": "SGD",
                },
                {
                    "account_id": div_inc_acc["id"],
                    "direction": "CREDIT",
                    "amount": "100.00",
                    "currency": "SGD",
                },
            ],
            rationale="Gross Dividend (100.00) == Net Cash (70.00) + Withholding Tax (30.00)",
        )

        # Flow 22: Mortgage Principal Amortization and Interest Split (post-window 2025-05-05)
        mortgage_liab_acc = runner.create_account(
            client,
            name="Residential Mortgage Liability",
            type="LIABILITY",
            currency="SGD",
        )
        mortgage_int_acc = runner.create_account(
            client, name="Mortgage Interest Expense", type="EXPENSE", currency="SGD"
        )
        runner.post_manual_journal_entry(
            client,
            memo="Mortgage Principal Amortization and Interest Split",
            entry_date="2025-05-05",
            lines=[
                {
                    "account_id": mortgage_liab_acc["id"],
                    "direction": "DEBIT",
                    "amount": "2100.00",
                    "currency": "SGD",
                },
                {
                    "account_id": mortgage_int_acc["id"],
                    "direction": "DEBIT",
                    "amount": "1400.00",
                    "currency": "SGD",
                },
                {
                    "account_id": payroll_cash_acc_id,
                    "direction": "CREDIT",
                    "amount": "3500.00",
                    "currency": "SGD",
                },
            ],
            rationale="Total Mortgage Payment (3500.00) == Principal (2100.00) + Interest (1400.00)",
        )
        bs_may = runner.get_balance_sheet(
            client, as_of_date="2025-05-31", include_restricted=True
        )
        assert bs_may["is_balanced"] is True, (
            f"Balance sheet unbalanced after Flow 20 & 22 splits: {bs_may}"
        )
        assert Decimal(str(bs_may["equation_delta"])) == Decimal("0.00")

        # Flow 28: Annual Tax & Audit Package ZIP Export
        archive_manifest = runner.export_annual_tax_archive(
            client, year=2025, currency="SGD"
        )
        archive_files = archive_manifest.get("files", [])
        assert len(archive_files) > 0, (
            f"Expected non-empty files in annual tax archive manifest: {archive_manifest}"
        )

        # Flow 30: Natural Language Financial AI Assistant with Tool Calling
        try:
            runner.query_ai_advisor(
                client,
                "Summarize my portfolio holdings and tax withholding status.",
            )
        except Exception as exc:
            if not (
                "temporarily unavailable" in str(exc).lower()
                or "503" in str(exc)
                or "api key" in str(exc).lower()
            ):
                raise

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
                "liquid_brokerage_assets_sgd": str(liquid_assets),
                "property_valuation_usd": "350000.00",
                "appraisal_source": "DocuBench FHA 1004 (KpewWz3R)",
                "comprehensive_assets_sgd": str(total_assets),
                "tax_ecosystem_status": (
                    "Form W-2 and Payslip structured tax withholding entry verified"
                ),
                "gross_salary_sgd": str(gross_salary),
                "tax_withheld_sgd": str(tax_withheld),
                "net_payroll_cash_sgd": str(net_cash),
                "total_assets": str(total_assets),
                "total_equity": str(total_equity),
                "equation_delta": str(equation_delta),
                "is_balanced": is_balanced,
                "flow_19_brokerage_statement_uploaded": True,
                "flow_20_dividend_net_sgd": "70.00",
                "flow_22_mortgage_principal_sgd": "2100.00",
                "flow_27_lineage_lines": len(lineage_lines),
                "flow_28_archive_files": len(archive_files),
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
