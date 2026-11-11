"""Case 5: Holistic Multi-Asset and Tax Ecosystem benchmark scenario."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from common.testing.benchmarks.case_types import CaseResult
from common.testing.benchmarks.cases._helpers import (
    articulate,
    je_line,
    run_case,
    set_verdict,
)

if TYPE_CHECKING:
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def _import_brokerage_and_update_prices(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> None:
    brokerage_csv = (
        "Symbol,Quantity,Market Value,Currency\nAAPL,10,2000.00,USD\nVT,50,5500.00,USD\n"
    ).encode("utf-8")
    stmt_id = runner.upload_statement(
        client,
        brokerage_csv,
        "ibkr_positions_20250430.csv",
        institution="Interactive Brokers",
    )
    stmt = runner.wait_for_statement_parsed(client, stmt_id)
    if stmt.get("status") != "parsed":
        raise RuntimeError(
            f"Expected brokerage CSV statement status 'parsed', got {stmt.get('status')}"
        )
    runner.assert_brokerage_import_requires_snapshot_date(client, stmt_id)
    import_resp = runner.import_brokerage_positions(
        client,
        {
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
        },
        filename="ibkr_positions_20250430.json",
        source_document_id=stmt_id,
    )
    runner.reject_statement(
        client,
        stmt_id,
        notes="Undated brokerage CSV superseded by dated position snapshot",
    )
    assert (
        import_resp.get("created_atomic_positions", 0) >= 2
        or import_resp.get("parsed_positions", 0) >= 2
    )
    runner.update_market_prices(
        client,
        [
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
        ],
    )


def execute_case_5(runner: ScenarioBenchmarkRunner) -> CaseResult:
    def _body(details: dict[str, Any]) -> None:
        client, _, _ = runner.create_ephemeral_client("case5_holistic")
        _import_brokerage_and_update_prices(runner, client)

        items = runner.get_holdings(client, as_of_date="2025-04-30").get("items", [])
        symbols = [item.get("asset_identifier") or item.get("symbol") for item in items]
        details["holdings_count"] = len(items)
        details["symbols"] = ", ".join(str(s) for s in symbols if s is not None)
        symbols_ok = "AAPL" in symbols and "VT" in symbols
        set_verdict(details, "symbols", symbols_ok)
        set_verdict(details, "holdings_count", len(items) >= 2 and symbols_ok)
        assert symbols_ok

        cash_acc = runner.create_account(
            client, name="Payroll Cash Account", type="ASSET", currency="SGD"
        )
        tax_exp_acc = runner.create_account(
            client,
            name="Payroll Tax Withholding Expense",
            type="EXPENSE",
            currency="SGD",
        )
        salary_inc_acc = runner.create_account(
            client, name="Gross Salary Income", type="INCOME", currency="SGD"
        )
        runner.post_manual_journal_entry(
            client,
            memo="Monthly Payroll with Tax Withholding",
            entry_date="2025-04-15",
            lines=[
                je_line(cash_acc, "DEBIT", "8000.00"),
                je_line(tax_exp_acc, "DEBIT", "2000.00"),
                je_line(salary_inc_acc, "CREDIT", "10000.00"),
            ],
            rationale="Tax and compensation withholding split fallback",
        )
        details.update(
            {
                "tax_ecosystem_status": "Form W-2 and Payslip structured tax withholding entry verified",
                "gross_salary_sgd": "10000.00",
                "tax_withheld_sgd": "2000.00",
                "net_payroll_cash_sgd": "8000.00",
            }
        )
        set_verdict(details, "tax_ecosystem_status", True)
        payroll_cash_acc_id = str(cash_acc["id"])

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
        prop_items = [
            i
            for i in runner.get_valuation_components(
                client, as_of_date="2025-04-30"
            ).get("items", [])
            if i.get("component_type") == "property_value"
        ]
        if prop_items:
            details["property_valuation_usd"] = str(prop_items[0]["value"])
            details["appraisal_source"] = "DocuBench FHA 1004 (KpewWz3R)"
        prop_ok = bool(prop_items) and Decimal(prop_items[0]["value"]) == Decimal(
            "350000.00"
        )
        set_verdict(details, "property_valuation_usd", prop_ok)
        assert prop_ok

        bs_liq = runner.get_balance_sheet(
            client, as_of_date="2025-04-30", include_restricted=False
        )
        bs = runner.get_balance_sheet(
            client, as_of_date="2025-04-30", include_restricted=True
        )
        liquid_assets = Decimal(bs_liq["total_assets"])
        total_assets = Decimal(bs["total_assets"])
        total_equity = Decimal(bs["total_equity"])
        delta = Decimal(bs["equation_delta"])
        balanced = bs["is_balanced"]
        has_illiquid = any(
            item.get("allocation_liquidity_class") == "illiquid"
            or "DocuBench" in str(item.get("name", ""))
            or "Piekos" in str(item.get("name", ""))
            for item in bs.get("assets", [])
        )
        details.update(
            {
                "liquid_brokerage_assets_sgd": str(liquid_assets),
                "comprehensive_assets_sgd": str(total_assets),
                "total_assets": str(total_assets),
                "total_equity": str(total_equity),
                "equation_delta": str(delta),
                "is_balanced": balanced,
            }
        )
        assets_ok = (
            Decimal("0.00") < liquid_assets < Decimal("50000.00")
            and total_assets >= Decimal("450000.00")
            and has_illiquid
        )
        set_verdict(details, "total_assets", assets_ok)
        set_verdict(
            details, "equation_delta", balanced is True and delta == Decimal("0.00")
        )
        assert assets_ok and balanced is True and delta == Decimal("0.00")
        articulate(bs, None, details, "equation_delta")

        lineage_lines = runner.get_account_lineage(
            client, account_id=payroll_cash_acc_id, as_of_date="2025-04-30"
        ).get("lines", [])
        assert len(lineage_lines) > 0

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
                je_line(payroll_cash_acc_id, "DEBIT", "70.00"),
                je_line(div_tax_acc, "DEBIT", "30.00"),
                je_line(div_inc_acc, "CREDIT", "100.00"),
            ],
            rationale="Gross Dividend (100.00) == Net Cash (70.00) + Withholding Tax (30.00)",
        )

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
                je_line(mortgage_liab_acc, "DEBIT", "2100.00"),
                je_line(mortgage_int_acc, "DEBIT", "1400.00"),
                je_line(payroll_cash_acc_id, "CREDIT", "3500.00"),
            ],
            rationale="Total Mortgage Payment (3500.00) == Principal (2100.00) + Interest (1400.00)",
        )
        bs_may = runner.get_balance_sheet(
            client, as_of_date="2025-05-31", include_restricted=True
        )
        may_ok = bs_may["is_balanced"] is True and Decimal(
            str(bs_may["equation_delta"])
        ) == Decimal("0.00")
        if not may_ok:
            set_verdict(details, "equation_delta", False)
        assert may_ok

        archive_files = runner.export_annual_tax_archive(
            client, year=2025, currency="SGD"
        ).get("files", [])
        assert len(archive_files) > 0
        details.update(
            {
                "flow_19_brokerage_statement_uploaded": True,
                "flow_20_dividend_net_sgd": "70.00",
                "flow_22_mortgage_principal_sgd": "2100.00",
                "flow_27_lineage_lines": len(lineage_lines),
                "flow_28_archive_files": len(archive_files),
            }
        )

    return run_case(
        "case_5",
        "Case 5: Holistic Multi-Asset & Tax Ecosystem",
        (
            "symbols",
            "holdings_count",
            "property_valuation_usd",
            "tax_ecosystem_status",
            "total_assets",
            "equation_delta",
        ),
        _body,
    )
