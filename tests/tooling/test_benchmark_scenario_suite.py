"""Unit tests for the financial scenario benchmark suite and staging smoke gate."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from pathlib import Path

from common.testing.matrix import STAGING_CORE_E2E_MARKER
from tools._lib.benchmarks.run_financial_scenario_benchmark import (
    generate_credit_card_repayment_bank_pdf,
    generate_household_wife_operations_csv,
    generate_standard_operations_csv,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_staging_core_e2e_marker_contract() -> None:
    """AC-testing.deploy-gates.39: Staging deployment Phase 2 validation is scoped to fast fail-closed smoke."""
    assert STAGING_CORE_E2E_MARKER == "smoke and not llm"
    deploy_yml = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    expected_cmd = 'pytest tests/e2e -v -m "smoke and not llm" -n 4 --junit-xml=test-results/staging-core-e2e.xml'
    assert expected_cmd in deploy_yml


def test_generate_standard_operations_csv_identity() -> None:
    """Benchmark Case 2: standard operations CSV generation maintains strict 3-statement reconciliation."""
    opening = Decimal("10000.00")
    csv_bytes = generate_standard_operations_csv(opening_balance=opening)
    assert isinstance(csv_bytes, bytes)
    text = csv_bytes.decode("utf-8")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 4

    total_delta = Decimal("0.00")
    for row in rows:
        assert row["Statement Currency"] == "SGD"
        assert row["Statement Period Start"] == "2025-04-01"
        assert row["Statement Period End"] == "2025-04-30"
        assert Decimal(row["Statement Opening Balance"]) == opening
        assert Decimal(row["Statement Closing Balance"]) == opening + Decimal("2800.00")
        total_delta += Decimal(row["Amount"])

    assert total_delta == Decimal("2800.00")
    expected_closing = opening + total_delta
    assert expected_closing == Decimal("12800.00")


def test_generate_household_wife_operations_csv_identity() -> None:
    """Benchmark Case 2: wife's operating CSV generation maintains strict mathematical reconciliation."""
    opening = Decimal("5000.00")
    csv_bytes = generate_household_wife_operations_csv(opening_balance=opening)
    assert isinstance(csv_bytes, bytes)
    text = csv_bytes.decode("utf-8")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 3

    total_delta = Decimal("0.00")
    for row in rows:
        assert row["Statement Currency"] == "SGD"
        assert row["Statement Period Start"] == "2025-04-01"
        assert row["Statement Period End"] == "2025-04-30"
        assert Decimal(row["Statement Opening Balance"]) == opening
        assert Decimal(row["Statement Closing Balance"]) == opening + Decimal("3100.00")
        total_delta += Decimal(row["Amount"])

    assert total_delta == Decimal("3100.00")
    expected_closing = opening + total_delta
    assert expected_closing == Decimal("8100.00")


def test_generate_credit_card_repayment_bank_pdf(tmp_path: Path) -> None:
    """Benchmark Case 3: credit card debt clearance bank PDF generates valid ReportLab document."""
    pdf_path = tmp_path / "cc_repay.pdf"
    pdf_bytes = generate_credit_card_repayment_bank_pdf(
        pdf_path, opening_balance=Decimal("10000.00")
    )
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000
    assert pdf_path.exists()


def test_generate_consecutive_month3_and_month4_pdf(tmp_path: Path) -> None:
    """Benchmark Case 1: Month 3 (Q1 close) and Month 4 (Q2 transition) PDFs generate valid ReportLab documents."""
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        generate_consecutive_month3_pdf,
        generate_consecutive_month4_pdf,
    )

    p3 = tmp_path / "m3.pdf"
    b3 = generate_consecutive_month3_pdf(p3, opening_balance=Decimal("18250.00"))
    assert b3.startswith(b"%PDF")
    assert len(b3) > 1000
    assert p3.exists()

    p4 = tmp_path / "m4.pdf"
    b4 = generate_consecutive_month4_pdf(p4, opening_balance=Decimal("21300.00"))
    assert b4.startswith(b"%PDF")
    assert len(b4) > 1000
    assert p4.exists()


def test_generate_multicurrency_usd_and_hkd_csv() -> None:
    """Benchmark Case 4: multi-currency CSV generators maintain strict opening-closing mathematical reconciliation."""
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        generate_multicurrency_hkd_csv,
        generate_multicurrency_usd_csv,
    )

    # USD Statement
    usd_opening = Decimal("5000.00")
    usd_bytes = generate_multicurrency_usd_csv(opening_balance=usd_opening)
    usd_rows = list(csv.DictReader(io.StringIO(usd_bytes.decode("utf-8"))))
    assert len(usd_rows) == 2
    usd_delta = sum(Decimal(r["Amount"]) for r in usd_rows)
    assert usd_delta == Decimal("1800.00")
    assert Decimal(usd_rows[0]["Statement Closing Balance"]) == usd_opening + usd_delta

    # HKD Statement
    hkd_opening = Decimal("20000.00")
    hkd_bytes = generate_multicurrency_hkd_csv(opening_balance=hkd_opening)
    hkd_rows = list(csv.DictReader(io.StringIO(hkd_bytes.decode("utf-8"))))
    assert len(hkd_rows) == 2
    hkd_delta = sum(Decimal(r["Amount"]) for r in hkd_rows)
    assert hkd_delta == Decimal("4000.00")
    assert Decimal(hkd_rows[0]["Statement Closing Balance"]) == hkd_opening + hkd_delta


def test_benchmark_manifest_v2_fixtures_verified() -> None:
    """AC-testing.benchmarks.v2: manifest.yaml is version 2.0 and all registered fixtures exist with valid SHA-256."""
    import hashlib
    import yaml

    manifest_path = REPO_ROOT / "common/testing/fixtures/benchmarks/manifest.yaml"
    assert manifest_path.exists()
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert data["version"] == "2.0"

    fixtures = data.get("fixtures", [])
    fixture_ids = {f["id"] for f in fixtures}
    expected_ids = {
        "bankstatemently_straits_capital",
        "bankstatemently_liberty_national",
        "bankstatemently_silk_road",
        "docubench_carson_bank",
        "docubench_fidelity_brokerage",
        "docubench_fha_appraisal",
        "docubench_w2_tax_statement",
        "docubench_payslip_statement",
    }
    assert expected_ids.issubset(fixture_ids)

    for item in fixtures:
        rel_path = item["local_path"]
        f_path = REPO_ROOT / rel_path
        assert f_path.exists(), f"Missing fixture file: {rel_path}"
        if "slice_pages" in item:
            assert len(f_path.read_bytes()) < 10 * 1024 * 1024
        elif "sha256" in item:
            actual_sha = hashlib.sha256(f_path.read_bytes()).hexdigest()
            assert actual_sha == item["sha256"], f"SHA256 mismatch for {rel_path}"


def test_benchmark_reporter_summary_extraction_v2() -> None:
    """AC-testing.benchmarks.v2: reporter generates comprehensive summary and standalone HTML for all 5 scenarios."""
    from tools._lib.benchmarks.benchmark_html_reporter import (
        extract_summary_data,
        generate_html_report,
    )

    mock_report = {
        "suite": "financial_reporting_temporal_scenarios",
        "version_ref": "v2.0.0-test",
        "app_url": "https://report-staging.zitian.party",
        "run_at": "2026-09-24T12:00:00",
        "summary": {
            "total": 5,
            "passed": 5,
            "failed": 0,
            "success": True,
        },
        "results": [
            {
                "case_id": "case_1",
                "case_name": "Case 1: Consecutive 4-Month Rollforward",
                "status": "PASS",
                "duration_seconds": 15.2,
                "details": {
                    "m1_closing_balance": "15,271.23",
                    "m2_closing_balance": "18,250.00",
                    "m3_closing_balance": "21,300.00",
                    "m4_closing_balance": "24,200.00",
                    "q1_net_income": "5,849.25",
                    "cumulative_net_income": "8,749.25",
                    "equation_delta": "0.00",
                    "is_balanced": True,
                },
            },
            {
                "case_id": "case_2",
                "case_name": "Case 2: Multi-PII Household Operations",
                "status": "PASS",
                "duration_seconds": 5.1,
                "details": {
                    "household_husband_cash": "12,800.00",
                    "household_wife_cash": "8,100.00",
                    "total_income": "8,500.00",
                    "total_expenses": "2,600.00",
                    "net_income": "5,900.00",
                    "ending_cash": "20,900.00",
                    "equation_delta": "0.00",
                    "is_balanced": True,
                },
            },
            {
                "case_id": "case_3",
                "case_name": "Case 3: Credit Card Liability & Non-P&L Repayment Clearance",
                "status": "PASS",
                "duration_seconds": 8.0,
                "details": {
                    "card_spend_recorded": "1,200.00",
                    "bank_repayment": "1,200.00",
                    "ending_bank_cash": "8,800.00",
                    "credit_card_liability_cleared": "0.00",
                    "net_income": "-1,200.00",
                    "total_assets": "8,800.00",
                    "equation_delta": "0.00",
                    "is_balanced": True,
                },
            },
            {
                "case_id": "case_4",
                "case_name": "Case 4: Multi-Currency Consolidated Balance Sheet",
                "status": "PASS",
                "duration_seconds": 12.3,
                "details": {
                    "sgd_closing_balance": "12,800.00",
                    "usd_closing_balance": "6,800.00",
                    "hkd_closing_balance": "24,000.00",
                    "total_assets_sgd": "45,000.00",
                    "equation_delta_sgd": "0.00",
                    "equation_delta_usd": "0.00",
                    "is_balanced": True,
                },
            },
            {
                "case_id": "case_5",
                "case_name": "Case 5: Holistic Multi-Asset & Tax Ecosystem",
                "status": "PASS",
                "duration_seconds": 9.4,
                "details": {
                    "symbols": "AAPL, VT",
                    "holdings_count": 2,
                    "property_valuation_usd": "350,000.00",
                    "appraisal_source": "DocuBench FHA 1004 (KpewWz3R)",
                    "tax_ecosystem_status": "Form W-2 and Payslip fixtures verified",
                    "total_assets": "385,000.00",
                    "equation_delta": "0.00",
                    "is_balanced": True,
                },
            },
        ],
    }

    summary = extract_summary_data(mock_report)
    assert summary["cases_total"] == 5
    assert summary["cases_passed"] == 5
    assert summary["cases_failed"] == 0
    assert summary["status"] == "PASS"
    assert summary["rollforward_balanced"] is True
    assert summary["zero_pnl_contamination"] is True
    assert summary["multicurrency_consolidated"] is True
    assert summary["portfolio_holdings_verified"] is True
    assert summary["max_equation_delta"] == "0.00"

    html_out = generate_html_report(mock_report)
    assert "ALL 5 SCENARIOS BALANCED" in html_out
    assert "CASE_1" in html_out
    assert "CASE_2" in html_out
    assert "CASE_3" in html_out
    assert "CASE_4" in html_out
    assert "CASE_5" in html_out
    assert "Husband Account (DBS Bank) Ending Cash" in html_out
    assert "Wife Account (Standard Chartered) Ending Cash" in html_out
    assert "Credit Card Incurred Charges" in html_out
    assert "Real Estate Property Appraisal" in html_out
    assert "Singapore Jurisdiction (SGD Account)" in html_out
    assert len(html_out) > 5000
