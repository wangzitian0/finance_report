"""Unit tests for the financial scenario benchmark suite and staging smoke gate."""

from __future__ import annotations

import csv
import io
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from common.testing.matrix import STAGING_CORE_E2E_MARKER
from tools._lib.benchmarks.run_financial_scenario_benchmark import (
    generate_credit_card_repayment_bank_pdf,
    generate_household_wife_operations_csv,
    generate_standard_operations_csv,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "apps" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))


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


def test_generate_consecutive_months_replay_csv_identity() -> None:
    """Benchmark Case 1: Replay CSV generators maintain consecutive opening-closing chain reconciliation."""
    from tools._lib.benchmarks.statement_generators import (
        generate_consecutive_month1_csv,
        generate_consecutive_month2_csv,
        generate_consecutive_month3_csv,
        generate_consecutive_month4_csv,
    )

    # Month 1
    m1_opening = Decimal("15450.75")
    m1_bytes = generate_consecutive_month1_csv(opening_balance=m1_opening)
    m1_rows = list(csv.DictReader(io.StringIO(m1_bytes.decode("utf-8"))))
    assert len(m1_rows) == 2
    m1_delta = sum(Decimal(r["Amount"]) for r in m1_rows)
    m1_closing = m1_opening + m1_delta
    assert m1_closing == Decimal("15271.23")
    assert Decimal(m1_rows[0]["Statement Closing Balance"]) == m1_closing

    # Month 2
    m2_bytes = generate_consecutive_month2_csv(opening_balance=m1_closing)
    m2_rows = list(csv.DictReader(io.StringIO(m2_bytes.decode("utf-8"))))
    assert len(m2_rows) == 3
    m2_delta = sum(Decimal(r["Amount"]) for r in m2_rows)
    m2_closing = m1_closing + m2_delta
    assert m2_closing == Decimal("18250.00")
    assert Decimal(m2_rows[0]["Statement Closing Balance"]) == m2_closing

    # Month 3
    m3_bytes = generate_consecutive_month3_csv(opening_balance=m2_closing)
    m3_rows = list(csv.DictReader(io.StringIO(m3_bytes.decode("utf-8"))))
    assert len(m3_rows) == 2
    m3_delta = sum(Decimal(r["Amount"]) for r in m3_rows)
    m3_closing = m2_closing + m3_delta
    assert m3_closing == Decimal("21300.00")
    assert Decimal(m3_rows[0]["Statement Closing Balance"]) == m3_closing

    # Month 4
    m4_bytes = generate_consecutive_month4_csv(opening_balance=m3_closing)
    m4_rows = list(csv.DictReader(io.StringIO(m4_bytes.decode("utf-8"))))
    assert len(m4_rows) == 2
    m4_delta = sum(Decimal(r["Amount"]) for r in m4_rows)
    m4_closing = m3_closing + m4_delta
    assert m4_closing == Decimal("24200.00")
    assert Decimal(m4_rows[0]["Statement Closing Balance"]) == m4_closing


def test_benchmark_cli_cassette_option_parsing() -> None:
    """Benchmark CLI supports --cassette=replay and propagates to runner."""
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
        _parse_args,
    )

    parsed = _parse_args(["--cassette", "replay", "--app-url", "http://localhost:8000"])
    assert parsed.cassette == "replay"

    runner = ScenarioBenchmarkRunner(
        base_url="http://localhost:8000", cassette_mode=parsed.cassette
    )
    assert runner.cassette_mode == "replay"


def test_benchmark_manifest_v2_fixtures_verified() -> None:
    """AC-testing.benchmarks.v2: manifest.yaml is version 2.1 and all registered fixtures have verified schema and sha256."""
    import hashlib
    import re
    import yaml

    manifest_path = REPO_ROOT / "common/testing/fixtures/benchmarks/manifest.yaml"
    assert manifest_path.exists()
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert data["version"] == "2.1"

    fixtures = data.get("fixtures", [])
    fixture_ids = {f["id"] for f in fixtures}
    expected_ids = {
        "bankstatemently_straits_capital",
        "docubench_w2_tax_statement",
        "docubench_payslip_statement",
    }
    assert expected_ids == fixture_ids, f"Manifest fixtures drifted: {fixture_ids}"

    required_fixture_keys = {
        "id",
        "doc_type",
        "currency",
        "download_url",
        "sha256",
        "local_path",
    }
    sha256_pattern = re.compile(r"^[a-f0-9]{64}$")
    for item in fixtures:
        assert required_fixture_keys.issubset(item.keys())
        assert item["download_url"].startswith("https://")
        assert sha256_pattern.match(item["sha256"]), f"Invalid sha256 for {item['id']}"
        rel_path = item["local_path"]
        f_path = REPO_ROOT / rel_path
        if f_path.exists():
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
            "total": 6,
            "passed": 6,
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
                    "tax_ecosystem_status": "Form W-2 and Payslip structured tax withholding entry verified",
                    "gross_salary_sgd": "10000.00",
                    "tax_withheld_sgd": "2000.00",
                    "net_payroll_cash_sgd": "8000.00",
                    "total_assets": "385,000.00",
                    "equation_delta": "0.00",
                    "is_balanced": True,
                },
            },
            {
                "case_id": "case_6",
                "case_name": "Case 6: Bank Overdraft & Capital Gain Disposal",
                "status": "PASS",
                "duration_seconds": 6.8,
                "details": {
                    "overdraft_cash": "-1,500.00",
                    "ending_cash": "11,000.00",
                    "capital_gain": "2,500.00",
                    "net_income": "0.00",
                    "total_assets": "11,000.00",
                    "total_equity": "11,000.00",
                    "equation_delta": "0.00",
                    "is_balanced": True,
                },
            },
        ],
    }

    summary = extract_summary_data(mock_report)
    assert summary["cases_total"] == 6
    assert summary["cases_passed"] == 6
    assert summary["cases_failed"] == 0
    assert summary["status"] == "PASS"
    assert summary["rollforward_balanced"] is True
    assert summary["zero_pnl_contamination"] is True
    assert summary["multicurrency_consolidated"] is True
    assert summary["portfolio_holdings_verified"] is True
    assert summary["overdraft_articulation_verified"] is True
    assert summary["max_equation_delta"] == "0.00"

    html_out = generate_html_report(mock_report)
    expected_snippets = [
        "ALL 6 SCENARIOS BALANCED",
        "CASE_1",
        "CASE_2",
        "CASE_3",
        "CASE_4",
        "CASE_5",
        "CASE_6",
        "Husband Account (DBS Bank) Ending Cash",
        "Wife Account (Standard Chartered) Ending Cash",
        "Credit Card Incurred Charges",
        "Real Estate Property Appraisal",
        "Overdraft Checkpoint Cash Balance",
    ]
    for snippet in expected_snippets:
        assert html_out.find(snippet) != -1, f"Missing {snippet} in html output"
    assert len(html_out) > 5000


def test_benchmark_case_6_dispatch_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-testing.benchmarks.v2: Case 6 is exported and dispatchable via CLI and scenario runner."""
    from tools._lib.benchmarks import run_financial_scenario_benchmark
    from tools._lib.benchmarks.case_types import CaseResult
    from tools._lib.benchmarks.cases import execute_case_6

    assert callable(execute_case_6)

    # Prove case 6 is genuinely wired into scenario dispatch
    fake_result = CaseResult(
        case_id="case_6",
        case_name="Case 6 Test",
        status="PASS",
        duration_seconds=0.1,
        details={},
    )
    dispatched_cases: list[str] = []
    monkeypatch.setattr(
        run_financial_scenario_benchmark,
        "execute_case_6",
        lambda runner: (dispatched_cases.append("case_6"), fake_result)[1],
    )

    fake_runner = object()  # type: ignore[arg-type]
    results = run_financial_scenario_benchmark._dispatch_cases(fake_runner, "6")
    assert dispatched_cases == ["case_6"]
    assert len(results) == 1
    assert results[0].case_id == "case_6"


def test_benchmark_cli_case_selection_and_green_while_empty_guard() -> None:
    """AC-testing.benchmarks.v2: CLI fails closed on invalid case selection and supports case_1 format."""
    from tools._lib.benchmarks.run_financial_scenario_benchmark import main

    # Passing invalid case must fail-closed with code 2 (never GREEN-WHILE-EMPTY code 0)
    exit_code = main(
        ["--case", "invalid_case_99", "--app-url", "http://localhost:8000"]
    )
    assert exit_code == 2, (
        f"Expected exit code 2 on empty case selection, got {exit_code}"
    )


def test_benchmark_valuation_basis_contract_conformance() -> None:
    """AC-testing.benchmarks.v2: valuation_basis aligns with backend ManualValuationBasis schema."""
    import inspect
    from src.pricing.base.manual_valuation import ManualValuationBasis
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )

    # Invariant: "market_appraisal" is the legal enum value, "appraisal" is illegal
    valid_basis_values = {e.value for e in ManualValuationBasis}
    assert ManualValuationBasis.MARKET_APPRAISAL.value == "market_appraisal"
    assert not ({"appraisal"} & valid_basis_values)

    # Runner method signature must default to legal enum value
    sig = inspect.signature(ScenarioBenchmarkRunner.create_valuation_snapshot)
    assert sig.parameters["valuation_basis"].default == "market_appraisal"


def test_benchmark_statement_generators_zero_orphan_contract() -> None:
    """AC-testing.benchmarks.v2: All statement generators are mapped to active scenario cases."""
    import inspect
    from tools._lib.benchmarks import statement_generators

    all_generators = {
        name
        for name, fn in inspect.getmembers(statement_generators, inspect.isfunction)
        if name.startswith("generate_")
    }

    # Invariant: dead generator must be deleted
    assert "generate_bank_asset_transfer_pdf" not in all_generators

    expected_generators = {
        "generate_consecutive_month1_csv",
        "generate_consecutive_month2_csv",
        "generate_consecutive_month3_csv",
        "generate_consecutive_month4_csv",
        "generate_consecutive_month2_pdf",
        "generate_consecutive_month3_pdf",
        "generate_consecutive_month4_pdf",
        "generate_credit_card_repayment_bank_pdf",
        "generate_household_wife_operations_csv",
        "generate_multicurrency_hkd_csv",
        "generate_multicurrency_usd_csv",
        "generate_standard_operations_csv",
    }
    assert all_generators == expected_generators, (
        f"Generator set mismatch (orphaned or missing): {all_generators ^ expected_generators}"
    )


def test_sync_benchmark_fixtures_contract(tmp_path: Path) -> None:
    """AC-testing.benchmarks.v2: Fixture sync loads manifest v2.1 and verifies SHA-256 integrity."""
    from tools._lib.benchmarks import sync_benchmark_fixtures

    manifest_path = REPO_ROOT / "common/testing/fixtures/benchmarks/manifest.yaml"
    manifest = sync_benchmark_fixtures.load_manifest(manifest_path)
    assert manifest["version"] == "2.1"
    assert len(manifest["fixtures"]) == 3

    # Test SHA-256 computation
    sample_bytes = b"hello finance report benchmark"
    digest = sync_benchmark_fixtures.compute_sha256(sample_bytes)
    assert len(digest) == 64

    # Test missing fixture detection
    dummy_fixture = {
        "id": "dummy_test_doc",
        "local_path": "nonexistent/path/to/fixture.pdf",
    }
    is_ok, msg = sync_benchmark_fixtures.verify_fixture(dummy_fixture, tmp_path)
    assert not is_ok
    assert "Missing file" in msg


def test_benchmark_cli_domain_and_flow_option_parsing() -> None:
    """AC-testing.benchmarks.v2: CLI supports --domain 1..7 and --flow 1..30 mappings."""
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        DOMAIN_TO_CASES,
        FLOW_TO_CASES,
        _parse_args,
    )

    parsed = _parse_args(
        [
            "--app-url",
            "http://localhost:8000",
            "--domain",
            "1,4",
            "--flow",
            "14,23",
        ]
    )
    assert parsed.domain == "1,4"
    assert parsed.flow == "14,23"

    assert len(DOMAIN_TO_CASES) == 7
    assert len(FLOW_TO_CASES) == 30
    assert {"1"}.issubset(DOMAIN_TO_CASES[1])
    assert {"4"}.issubset(DOMAIN_TO_CASES[4])
    assert {"2"}.issubset(FLOW_TO_CASES[14])
    assert {"1"}.issubset(FLOW_TO_CASES[23])
