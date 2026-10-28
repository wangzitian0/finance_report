"""Unit tests for the financial scenario benchmark suite and staging smoke gate."""

from __future__ import annotations

import csv
import io
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from common.testing.matrix import STAGING_CORE_E2E_MARKER
from common.testing.benchmarks.statement_generators import (
    generate_credit_card_repayment_bank_pdf,
    generate_household_wife_operations_csv,
    generate_standard_operations_csv,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "apps" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))


def test_staging_core_e2e_marker_contract() -> None:
    """Staging deployment Phase 2 validation is scoped to staging_core_e2e selection."""
    assert STAGING_CORE_E2E_MARKER == "(smoke or e2e) and not llm"
    deploy_yml = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    assert (
        "tools/test_selection.py --stage staging_core_e2e --shell" in deploy_yml
        and 'pytest "${STAGING_CORE_E2E_TESTS[@]}"' in deploy_yml
    )


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
    from common.testing.benchmarks.statement_generators import (
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
    from common.testing.benchmarks.statement_generators import (
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
    from common.testing.benchmarks.statement_generators import (
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


def test_benchmark_manifest_v2_fixtures_verified() -> None:
    """AC-testing.benchmarks.7: manifest.yaml is version 2.1 and all registered fixtures have verified schema and sha256."""
    import hashlib
    import re
    import yaml

    manifest_path = REPO_ROOT / "common/testing/fixtures/benchmarks/manifest.yaml"
    assert manifest_path.exists()
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert data["version"] == "2.1"
    assert "domains" not in data, "domains live only in thirty_flows_ssot.json"

    fixtures = data.get("fixtures", [])
    fixture_ids = {f["id"] for f in fixtures}
    expected_ids = {
        "bankstatemently_straits_capital",
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

    cases_dir = REPO_ROOT / "common/testing/benchmarks/cases"
    case_files_content = "\n".join(
        p.read_text(encoding="utf-8") for p in cases_dir.glob("case_*.py")
    )
    for item in fixtures:
        fixture_filename = Path(item["local_path"]).name
        assert fixture_filename in case_files_content, (
            f"Fixture {fixture_filename} in manifest.yaml is orphaned (not referenced in any case_*.py)"
        )


def test_benchmark_reporter_summary_extraction_v2() -> None:
    """AC-testing.benchmarks.8: reporter generates comprehensive summary and standalone HTML for all 5 scenarios."""
    from common.testing.benchmarks.benchmark_html_reporter import (
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
        "ALL 6 SCENARIOS PASSED",
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


def test_benchmark_valuation_basis_contract_conformance() -> None:
    """AC-testing.benchmarks.7: valuation_basis aligns with backend ManualValuationBasis schema."""
    import inspect
    from src.pricing.base.manual_valuation import ManualValuationBasis
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
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
    """AC-testing.benchmarks.7: All statement generators are mapped to active scenario cases."""
    import inspect
    from common.testing.benchmarks import statement_generators

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
    """AC-testing.benchmarks.7: Fixture sync loads manifest v2.1 and verifies SHA-256 integrity."""
    from common.testing.benchmarks import sync_benchmark_fixtures

    manifest_path = REPO_ROOT / "common/testing/fixtures/benchmarks/manifest.yaml"
    manifest = sync_benchmark_fixtures.load_manifest(manifest_path)
    assert manifest["version"] == "2.1"
    assert len(manifest["fixtures"]) == 1

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


def test_benchmark_oracle_triple_accounting_articulation_pass_and_fail() -> None:
    """AC-testing.benchmarks.6: Validate Pillar 4 Triple Accounting Articulation Invariant."""
    from common.testing.benchmarks.oracles import assert_triple_accounting_articulation

    # 1. Balanced case with matching income statement
    valid_bs = {
        "total_assets": "24200.00",
        "total_liabilities": "0.00",
        "total_equity": "15450.75",
        "net_income": "8749.25",
        "unrealized_fx_gain_loss": "0.00",
        "cta_adjustment": "0.00",
        "net_worth_adjustment_gain_loss": "0.00",
        "equation_delta": "0.00",
        "is_balanced": True,
    }
    valid_is = {
        "net_income": "8749.25",
    }
    # Must pass without exception
    assert_triple_accounting_articulation(valid_bs, valid_is)

    # 2. Failure: is_balanced is False
    unbalanced_bs = dict(valid_bs, is_balanced=False)
    with pytest.raises(AssertionError, match="Balance Sheet not balanced"):
        assert_triple_accounting_articulation(unbalanced_bs, valid_is)

    # 3. Failure: non-zero equation_delta
    delta_bs = dict(valid_bs, equation_delta="10.00")
    with pytest.raises(AssertionError, match="Equation delta 10.00 exceeds tolerance"):
        assert_triple_accounting_articulation(delta_bs, valid_is)

    # 4. Failure: net worth mismatch (assets - liabilities != ending equity)
    mismatch_nw_bs = dict(valid_bs, total_assets="25000.00")
    with pytest.raises(AssertionError, match="Net Worth .* != Ending Total Equity"):
        assert_triple_accounting_articulation(mismatch_nw_bs, valid_is)

    # 5. Failure: income statement net income mismatch
    mismatch_is = {"net_income": "5000.00"}
    with pytest.raises(
        AssertionError, match="does not match Income Statement Net Income"
    ):
        assert_triple_accounting_articulation(valid_bs, mismatch_is)


def test_benchmark_oracle_dom_hygiene_scanner() -> None:
    """AC-testing.benchmarks.3: Validate Pillar 3 DOM Hygiene Scanner."""
    from common.testing.benchmarks.oracles import (
        FORBIDDEN_DOM_JARGON,
        scan_dom_hygiene,
    )

    clean_dom = (
        "Welcome Alex. Here is your financial overview and balance sheet summary."
    )
    assert scan_dom_hygiene(clean_dom) == []

    dirty_dom = (
        "Dashboard overview: Loading upload-to-report workflow... Report none generated. "
        "Review details with source_result_digest and advisor_brief."
    )
    violations = scan_dom_hygiene(dirty_dom)
    assert len(violations) == len(FORBIDDEN_DOM_JARGON)


def test_wait_for_statement_parsed_retries_on_rate_limit_error() -> None:
    """AC-testing.benchmarks.1: wait_for_statement_parsed retries via POST /api/statements/{id}/retry on transient RateLimitError."""
    from unittest.mock import MagicMock

    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )

    runner = ScenarioBenchmarkRunner(base_url="http://localhost:8000")
    mock_client = MagicMock()

    resp_rejected = MagicMock()
    resp_rejected.status_code = 200
    resp_rejected.json.return_value = {
        "id": "stmt-rl-1",
        "status": "rejected",
        "validation_error": "Model test-vision-model failed: LLM provider call failed (RateLimitError)",
    }

    resp_parsed = MagicMock()
    resp_parsed.status_code = 200
    resp_parsed.json.return_value = {
        "id": "stmt-rl-1",
        "status": "parsed",
        "opening_balance": "100.00",
        "closing_balance": "200.00",
    }

    mock_client.get.side_effect = [resp_rejected, resp_parsed]

    resp_retry = MagicMock()
    resp_retry.status_code = 200
    mock_client.post.return_value = resp_retry

    result = runner.wait_for_statement_parsed(
        mock_client,
        "stmt-rl-1",
        max_wait_seconds=10,
        poll_interval=0,
        max_rate_limit_retries=2,
        retry_backoff_seconds=0.0,
    )

    assert result["status"] == "parsed"
    mock_client.post.assert_called_once_with("/api/statements/stmt-rl-1/retry")
    assert mock_client.get.call_count == 2


def test_runner_nominal_gap_helpers_and_case_execution_wiring(tmp_path: Path) -> None:
    """AC-testing.benchmarks.4: ScenarioBenchmarkRunner methods for all 30 flows are wired into Cases 1-6."""
    import json
    import zipfile
    from unittest.mock import MagicMock

    from common.testing.benchmarks.cases import (
        case_1,
        case_2,
        case_3,
        case_4,
        case_5,
        case_6,
    )
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )

    runner = ScenarioBenchmarkRunner(
        base_url="http://localhost:8000", replay_mode="replay"
    )
    mock_client = MagicMock()

    def _ok(payload: object, content: bytes = b"") -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = payload
        resp.text = "ok"
        resp.content = content
        return resp

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "package_id": "pkg-1",
                    "files": [{"filename": "balance_sheet.csv", "sha256": "abc"}],
                }
            ),
        )

    mock_client.post.side_effect = [
        _ok({"id": "stmt-bad", "status": "rejected"}),
        _ok({"items": [], "total": 0}),
        _ok({"approved_count": 2, "journal_entries_created": 2}),
        _ok(
            {
                "matches_created": 1,
                "auto_accepted": 0,
                "pending_review": 1,
                "unmatched": 0,
            }
        ),
        _ok({"id": "m-1", "status": "accepted"}),
        _ok(
            {
                "account_id": "acc-1",
                "bank_balance": "0.02",
                "book_balance": "0.00",
                "difference": "0.02",
                "is_gain": True,
                "journal_entry_id": "je-1",
            }
        ),
        _ok({}, content=zip_buf.getvalue()),
    ]
    mock_client.get.side_effect = [
        _ok({"items": [{"id": "m-1"}], "total": 1}),
        _ok([]),
        _ok(
            {
                "as_of_date": "2025-04-30",
                "coverage_start": "2025-01-01",
                "limiting_accounts": [],
            }
        ),
        _ok({"is_balanced": True, "equation_delta": "0.00"}),
        _ok({"account_id": "acc-1", "lines": [{"entry_id": "je-1"}]}),
    ]

    rejected = runner.reject_statement(mock_client, "stmt-bad", notes="triage")
    assert rejected["status"] == "rejected"
    checks = runner.run_stage2_consistency_checks(mock_client, "stmt-1")
    assert checks == {"items": [], "total": 0}
    batch_res = runner.batch_approve_matches(mock_client, ["m-1", "m-2"])
    assert batch_res["approved_count"] == 2
    recon_res = runner.run_reconciliation(mock_client, statement_id="stmt-1")
    assert recon_res["matches_created"] == 1
    accepted_cnt = runner.accept_reconciliation_matches(mock_client)
    assert accepted_cnt == 1
    anomalies = runner.list_transaction_anomalies(mock_client, "txn-1")
    assert anomalies == []
    adj = runner.post_reconciliation_adjustment(
        mock_client,
        account_id="acc-1",
        bank_balance="0.02",
        book_balance="0.00",
    )
    assert adj["difference"] == "0.02"
    cov = runner.get_report_coverage(mock_client, as_of_date="2025-04-30")
    assert cov["coverage_start"] == "2025-01-01"
    diag = runner.get_balance_sheet_diagnostics(
        mock_client, as_of_date="2025-04-30", currency="SGD"
    )
    assert diag["is_balanced"] is True
    lineage = runner.get_account_lineage(
        mock_client, account_id="acc-1", as_of_date="2025-04-30", currency="SGD"
    )
    assert len(lineage["lines"]) == 1
    manifest = runner.export_annual_tax_archive(mock_client, year=2025, currency="SGD")
    assert len(manifest["files"]) == 1

    # Verify Case 1 records coverage_start, Flow 7 mismatch block, Flow 24 diagnostics, and Flow 27 lineage
    c1_runner = MagicMock(unsafe=True)
    c1_runner.replay_mode = "replay"
    c1_client = MagicMock()
    c1_client.get.return_value.json.return_value = {
        "account_id": "acc-1",
        "institution": "Standard Chartered Bank",
    }
    c1_runner.create_ephemeral_client.return_value = (c1_client, "c1@test.example", {})
    c1_runner.upload_statement.side_effect = ["m1", "m2", "m3", "m4", "bad-m4"]
    c1_runner.wait_for_statement_parsed.side_effect = [
        {
            "opening_balance": "15450.75",
            "closing_balance": "15271.23",
            "balance_validated": True,
            "transactions": [],
        },
        {
            "opening_balance": "15271.23",
            "closing_balance": "18250.00",
            "balance_validated": True,
            "transactions": [],
        },
        {
            "opening_balance": "18250.00",
            "closing_balance": "21300.00",
            "balance_validated": True,
            "transactions": [],
        },
        {
            "opening_balance": "21300.00",
            "closing_balance": "24200.00",
            "balance_validated": True,
            "transactions": [],
        },
        {
            "id": "bad-m4",
            "status": "parsed",
            "balance_validated": False,
            "transactions": [],
        },
    ]
    c1_runner.approve_statement.return_value = {"status": "approved"}
    c1_runner.assert_approval_blocked_by_balance_mismatch.return_value = {
        "status_code": 400,
        "detail": "Balance mismatch",
    }
    c1_runner.get_data_quality_health.return_value = {
        "action_items": [{"id": "review_pending_statements"}]
    }
    c1_runner.reject_statement.return_value = {"id": "bad-m4", "status": "rejected"}
    c1_runner.get_balance_sheet.side_effect = [
        {
            "total_assets": "21300.00",
            "total_liabilities": "0.00",
            "total_equity": "15450.75",
            "net_income": "5849.25",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
        {
            "total_assets": "24200.00",
            "total_liabilities": "0.00",
            "total_equity": "15450.75",
            "net_income": "8749.25",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
    ]
    c1_runner.get_income_statement.side_effect = [
        {"net_income": "5849.25"},
        {"net_income": "8749.25"},
    ]
    c1_runner.get_cash_flow.side_effect = [
        {
            "summary": {
                "beginning_cash": "15450.75",
                "net_cash_flow": "5849.25",
                "ending_cash": "21300.00",
            }
        },
        {
            "summary": {
                "beginning_cash": "15450.75",
                "net_cash_flow": "8749.25",
                "ending_cash": "24200.00",
            }
        },
    ]
    c1_runner.get_report_coverage.return_value = {
        "as_of_date": "2025-04-30",
        "coverage_start": "2025-01-01",
        "limiting_accounts": [],
    }
    c1_runner.get_balance_sheet_diagnostics.return_value = {
        "is_balanced": True,
        "primary_category": "balanced",
    }
    c1_runner.get_account_lineage.return_value = {"lines": [{"entry_id": "je-1"}]}
    c1_runner.query_ai_advisor.return_value = "Your net worth is 24,200.00 SGD."
    c1_res = case_1.execute_case_1(c1_runner)
    assert c1_res.status == "PASS", c1_res.error_message
    assert c1_res.details["coverage_start"] == "2025-01-01"
    assert c1_res.details["flow_7_mismatch_blocked"] is True
    assert c1_res.details["flow_24_pending_triage_verified"] is True
    assert c1_res.details["flow_24_diagnostics_balanced"] is True
    assert c1_res.details["flow_27_lineage_lines"] == 1

    # Verify Case 2 exercises Flows 8, 9, 12, and 29
    c2_runner = MagicMock()
    c2_client = MagicMock()
    c2_runner.create_ephemeral_client.return_value = (c2_client, "c2@test.example", {})
    c2_runner.upload_statement.side_effect = ["h-stmt", "w-stmt", "bad-stmt"]
    c2_runner.wait_for_statement_parsed.side_effect = [
        {
            "opening_balance": "10000.00",
            "closing_balance": "12800.00",
            "transactions": [{"id": "txn-h1"}],
        },
        {
            "opening_balance": "5000.00",
            "closing_balance": "8100.00",
            "transactions": [{"id": "txn-w1"}],
        },
        {
            "opening_balance": "999.00",
            "closing_balance": "999.00",
            "transactions": [],
        },
    ]
    c2_runner.run_stage2_consistency_checks.return_value = {"items": [], "total": 0}
    c2_runner.batch_approve_matches.return_value = {"approved_count": 0}
    c2_runner.list_transaction_anomalies.return_value = []
    c2_runner.reject_statement.return_value = {"id": "bad-stmt", "status": "rejected"}
    c2_runner.get_balance_sheet.return_value = {
        "total_assets": "20900.00",
        "total_liabilities": "0.00",
        "total_equity": "15000.00",
        "net_income": "5900.00",
        "equation_delta": "0.00",
        "is_balanced": True,
    }
    c2_runner.get_income_statement.return_value = {
        "total_income": "8500.00",
        "total_expenses": "2600.00",
        "net_income": "5900.00",
    }
    c2_runner.get_cash_flow.return_value = {
        "summary": {
            "beginning_cash": "15000.00",
            "net_cash_flow": "5900.00",
            "ending_cash": "20900.00",
        }
    }
    c2_res = case_2.execute_case_2(c2_runner)
    assert c2_res.status == "PASS", c2_res.error_message
    assert c2_res.details["flow_8_checks_ran"] is True
    assert c2_res.details["flow_9_rejected_status"] == "rejected"
    assert c2_res.details["flow_12_batch_approved_count"] == 0
    assert c2_res.details["flow_29_anomalies_checked"] is True

    # Verify Case 3 exercises Flows 15, 16, and 18
    c3_runner = MagicMock()
    c3_client = MagicMock()
    c3_runner.create_ephemeral_client.return_value = (c3_client, "c3@test.example", {})
    c3_runner.create_account.side_effect = [
        {"id": "cc-1", "name": "Card"},
        {"id": "exp-1", "name": "Exp"},
        {"id": "rnd-1", "name": "Rounding Bank"},
    ]
    c3_runner.upload_statement.return_value = "stmt-cc"
    c3_runner.wait_for_statement_parsed.return_value = {
        "opening_balance": "10000.00",
        "closing_balance": "8800.00",
    }
    c3_runner.get_balance_sheet.side_effect = [
        {
            "total_assets": "8800.00",
            "total_liabilities": "0.00",
            "total_equity": "10000.00",
            "net_income": "-1200.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
        {
            "total_assets": "8800.02",
            "total_liabilities": "0.00",
            "total_equity": "10000.00",
            "net_income": "-1199.98",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
    ]
    c3_runner.get_income_statement.return_value = {
        "total_income": "0.00",
        "total_expenses": "1200.00",
        "net_income": "-1200.00",
    }
    c3_runner.run_reconciliation.return_value = {"matches_created": 1}
    c3_runner.accept_reconciliation_matches.return_value = 1
    c3_runner.post_reconciliation_adjustment.return_value = {
        "difference": "0.02",
        "journal_entry_id": "je-adj-1",
    }
    c3_res = case_3.execute_case_3(c3_runner)
    assert c3_res.status == "PASS", c3_res.error_message
    assert c3_res.details["flow_15_matches_created"] == 1
    assert c3_res.details["flow_16_matches_accepted"] == 1
    assert c3_res.details["flow_18_adjustment_difference"] == "0.02"

    # Verify Case 4 exercises Flow 17
    c4_runner = MagicMock()
    c4_client = MagicMock()
    c4_runner.create_ephemeral_client.return_value = (c4_client, "c4@test.example", {})
    c4_runner.upload_statement.side_effect = ["sgd-1", "usd-1", "hkd-1"]
    c4_runner.wait_for_statement_parsed.side_effect = [
        {"closing_balance": "12800.00", "balance_validated": True},
        {"closing_balance": "6800.00", "balance_validated": True},
        {"closing_balance": "24000.00", "balance_validated": True},
    ]
    c4_runner.create_account.side_effect = [
        {"id": "fx-src", "name": "USD Wire"},
        {"id": "fx-tgt", "name": "SGD Wire"},
        {"id": "fx-gain", "name": "FX Gain"},
    ]
    c4_runner.get_balance_sheet.side_effect = [
        {
            "total_assets": "25000.00",
            "total_liabilities": "0.00",
            "total_equity": "20000.00",
            "net_income": "5000.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
        {
            "total_assets": "18500.00",
            "total_liabilities": "0.00",
            "total_equity": "14800.00",
            "net_income": "3700.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
        {
            "total_assets": "25010.00",
            "total_liabilities": "0.00",
            "total_equity": "20000.00",
            "net_income": "5010.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
    ]
    c4_res = case_4.execute_case_4(c4_runner)
    assert c4_res.status == "PASS", c4_res.error_message
    assert c4_res.details["flow_17_realized_fx_gain_sgd"] == "10.00"

    # Verify Case 5 exercises Flows 19, 20, 22, 27, 28, and 30
    c5_runner = MagicMock(unsafe=True)
    c5_client = MagicMock()
    c5_runner.create_ephemeral_client.return_value = (c5_client, "c5@test.example", {})
    c5_runner.upload_statement.return_value = "brk-stmt-1"
    c5_runner.wait_for_statement_parsed.return_value = {
        "id": "brk-stmt-1",
        "status": "parsed",
    }
    c5_runner.assert_brokerage_import_requires_snapshot_date.return_value = {
        "error_id": "brokerage_snapshot_date_missing"
    }
    c5_runner.reject_statement.return_value = {
        "id": "brk-stmt-1",
        "status": "rejected",
    }
    c5_runner.import_brokerage_positions.return_value = {"created_atomic_positions": 2}
    c5_runner.get_holdings.return_value = {
        "items": [{"symbol": "AAPL"}, {"symbol": "VT"}]
    }
    c5_runner.create_account.side_effect = [
        {"id": "cash-1"},
        {"id": "tax-1"},
        {"id": "sal-1"},
        {"id": "div-inc"},
        {"id": "div-tax"},
        {"id": "mtg-liab"},
        {"id": "mtg-int"},
    ]
    c5_runner.get_valuation_components.return_value = {
        "items": [{"component_type": "property_value", "value": "350000.00"}]
    }
    c5_runner.get_balance_sheet.side_effect = [
        {
            "total_assets": "18000.00",
            "total_liabilities": "0.00",
            "total_equity": "10000.00",
            "net_income": "8000.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
        {
            "total_assets": "500000.00",
            "total_liabilities": "0.00",
            "total_equity": "492000.00",
            "net_income": "8000.00",
            "equation_delta": "0.00",
            "is_balanced": True,
            "assets": [{"allocation_liquidity_class": "illiquid", "name": "DocuBench"}],
        },
        {
            "total_assets": "498670.00",
            "total_liabilities": "-2100.00",
            "total_equity": "492000.00",
            "net_income": "8770.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
    ]
    c5_runner.get_account_lineage.return_value = {"lines": [{"entry_id": "je-pay"}]}
    c5_runner.export_annual_tax_archive.return_value = {
        "files": [{"filename": "balance_sheet.csv", "sha256": "abc"}]
    }
    c5_runner.query_ai_advisor.return_value = "Portfolio holdings AAPL and VT verified."
    c5_res = case_5.execute_case_5(c5_runner)
    assert c5_res.status == "PASS", c5_res.error_message
    assert c5_res.details["flow_19_brokerage_statement_uploaded"] is True
    assert c5_res.details["flow_20_dividend_net_sgd"] == "70.00"
    assert c5_res.details["flow_22_mortgage_principal_sgd"] == "2100.00"
    assert c5_res.details["flow_27_lineage_lines"] == 1
    assert c5_res.details["flow_28_archive_files"] == 1

    # Verify Case 6 exercises Flow 24
    c6_runner = MagicMock()
    c6_client = MagicMock()
    c6_runner.create_ephemeral_client.return_value = (c6_client, "c6@test.example", {})
    c6_runner.create_account.side_effect = [
        {"id": "chk-1"},
        {"id": "emg-1"},
        {"id": "eq-1"},
        {"id": "art-1"},
        {"id": "cg-1"},
    ]
    c6_runner.get_balance_sheet.side_effect = [
        {
            "total_assets": "-1500.00",
            "total_liabilities": "0.00",
            "total_equity": "1000.00",
            "net_income": "-2500.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
        {
            "total_assets": "11000.00",
            "total_liabilities": "0.00",
            "total_equity": "11000.00",
            "net_income": "0.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
    ]
    c6_runner.get_balance_sheet_diagnostics.return_value = {"is_balanced": True}
    c6_res = case_6.execute_case_6(c6_runner)
    assert c6_res.status == "PASS", c6_res.error_message
    assert c6_res.details["flow_24_diagnostics_balanced"] is True


def test_runner_flow_7_19_24_hardening_helpers_and_failure_branches() -> None:
    """AC-testing.benchmarks.4: Flow 7, 19, and 24 helpers enforce falsifiable pass and error paths."""
    from unittest.mock import MagicMock

    from common.testing.benchmarks.cases import case_1, case_5
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )

    runner = ScenarioBenchmarkRunner(
        base_url="http://localhost:8000", replay_mode="replay"
    )
    mock_client = MagicMock()

    def _resp(status_code: int, payload: object, text: str = "err") -> MagicMock:
        r = MagicMock()
        r.status_code = status_code
        r.json.return_value = payload
        r.text = text
        return r

    # 1. assert_approval_blocked_by_balance_mismatch pass and fail
    mock_client.post.return_value = _resp(
        400, {"detail": "Balance mismatch"}, "Balance mismatch"
    )
    blocked = runner.assert_approval_blocked_by_balance_mismatch(mock_client, "stmt-7")
    assert blocked == {"status_code": 400, "detail": "Balance mismatch"}

    mock_client.post.return_value = _resp(200, {"status": "approved"}, "ok")
    with pytest.raises(RuntimeError, match="Expected balance mismatch approval block"):
        runner.assert_approval_blocked_by_balance_mismatch(mock_client, "stmt-7")

    # 2. assert_brokerage_import_requires_snapshot_date pass and fail
    mock_client.post.return_value = _resp(
        422, {"error_id": "brokerage_snapshot_date_missing"}, "missing snapshot date"
    )
    brk_err = runner.assert_brokerage_import_requires_snapshot_date(
        mock_client, "stmt-19"
    )
    assert brk_err["error_id"] == "brokerage_snapshot_date_missing"

    mock_client.post.return_value = _resp(200, {"created_atomic_positions": 1}, "ok")
    with pytest.raises(
        RuntimeError, match="Expected undated brokerage CSV import to fail with 422"
    ):
        runner.assert_brokerage_import_requires_snapshot_date(mock_client, "stmt-19")

    mock_client.post.return_value = _resp(422, {"detail": "unrelated error"}, "bad")
    with pytest.raises(
        RuntimeError, match="Expected brokerage_snapshot_date_missing error"
    ):
        runner.assert_brokerage_import_requires_snapshot_date(mock_client, "stmt-19")

    # 3. get_data_quality_health pass and fail
    mock_client.get.return_value = _resp(
        200, {"action_items": [{"id": "review_pending_statements"}]}, "ok"
    )
    dq = runner.get_data_quality_health(
        mock_client, as_of_date="2025-04-30", currency="SGD"
    )
    assert dq["action_items"][0]["id"] == "review_pending_statements"
    mock_client.get.assert_called_with(
        "/api/reports/data-quality",
        params={"as_of_date": "2025-04-30", "currency": "SGD"},
    )

    mock_client.get.return_value = _resp(500, {}, "server error")
    with pytest.raises(RuntimeError, match="Get data quality health failed: 500"):
        runner.get_data_quality_health(mock_client)

    # 4. import_brokerage_positions with source_document_id pass and fail
    mock_client.post.return_value = _resp(200, {"created_atomic_positions": 2}, "ok")
    imp_res = runner.import_brokerage_positions(
        mock_client,
        {"positions": []},
        filename="ibkr.json",
        source_document_id="stmt-19",
    )
    assert imp_res["created_atomic_positions"] == 2
    mock_client.post.assert_called_with(
        "/api/portfolio/brokerage/import",
        json={
            "filename": "ibkr.json",
            "payload": {"positions": []},
            "source_document_id": "stmt-19",
        },
    )

    mock_client.post.return_value = _resp(400, {}, "bad import")
    with pytest.raises(RuntimeError, match="Brokerage import request failed: 400"):
        runner.import_brokerage_positions(mock_client, {"positions": []})

    # 5. Case 1 and Case 5 negative guard branches
    bad_c1_runner = MagicMock(unsafe=True)
    bad_c1_runner.upload_statement.return_value = "bad-1"
    bad_c1_runner.wait_for_statement_parsed.return_value = {"balance_validated": True}
    with pytest.raises(RuntimeError, match="Expected balance_validated=False"):
        case_1._verify_flow_7_and_24_mismatch_and_diagnostics(
            bad_c1_runner, mock_client
        )

    bad_c1_runner.wait_for_statement_parsed.return_value = {"balance_validated": False}
    bad_c1_runner.get_data_quality_health.return_value = {"action_items": []}
    with pytest.raises(RuntimeError, match="Expected review_pending_statements"):
        case_1._verify_flow_7_and_24_mismatch_and_diagnostics(
            bad_c1_runner, mock_client
        )

    bad_c5_runner = MagicMock(unsafe=True)
    bad_c5_runner.upload_statement.return_value = "brk-1"
    bad_c5_runner.wait_for_statement_parsed.return_value = {"status": "approved"}
    with pytest.raises(
        RuntimeError, match="Expected brokerage CSV statement status 'parsed'"
    ):
        case_5._import_brokerage_and_update_prices(bad_c5_runner, mock_client)


def test_ssot_benchmark_and_storage_doc_convergence() -> None:
    """Guard against duplicate benchmark README and stale storage/extraction doc drift."""
    assert not (REPO_ROOT / "common/testing/fixtures/benchmarks/README.md").exists()
    assert "**MinIO** (Prod)" not in (
        REPO_ROOT / "common/runtime/environments.md"
    ).read_text(encoding="utf-8")
    assert "before routing to `uploaded`" not in (
        REPO_ROOT / "common/extraction/readme.md"
    ).read_text(encoding="utf-8")
