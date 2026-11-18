"""Core smoke contract tests for financial scenario benchmarks (referenced by thirty_flows_ssot)."""

from __future__ import annotations

import csv
import io
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from infra2_sdk.manifests import load_hooks_manifest

from common.testing.matrix import STAGING_CORE_E2E_MARKER
from tests.benchmarks.benchmark_summary import extract_summary_data
from tests.benchmarks.cases import case_3
from tests.benchmarks.oracles import assert_triple_accounting_articulation
from tests.benchmarks.statement_generators import generate_credit_card_repayment_bank_csv
from tests.tooling.hook_text import hook_text

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "apps" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))


def test_staging_core_e2e_marker_and_benchmark_manifest() -> None:
    assert STAGING_CORE_E2E_MARKER == "(smoke or e2e) and not llm"
    manifest = load_hooks_manifest(REPO_ROOT / "runtime-hooks.manifest.json")
    assert "common.testing.test_selection --stage staging_core_e2e --run" in hook_text(
        manifest.slots["staging_gate"]
    )
    bench_manifest = yaml.safe_load((REPO_ROOT / "tests/fixtures/benchmarks/manifest.yaml").read_text())
    assert bench_manifest["version"] == "2.2"
    assert len(bench_manifest["fixtures"]) == 20


def test_benchmark_generators_oracle_and_case_3_smoke() -> None:
    csv_bytes = generate_credit_card_repayment_bank_csv(opening_balance=Decimal("10000.00"))
    rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))
    assert len(rows) == 1 and Decimal(rows[0]["Statement Closing Balance"]) == Decimal("8800.00")

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
    assert_triple_accounting_articulation(valid_bs, {"net_income": "8749.25"})
    with pytest.raises(AssertionError, match="Balance Sheet not balanced"):
        assert_triple_accounting_articulation({**valid_bs, "is_balanced": False}, {"net_income": "8749.25"})

    runner = MagicMock()
    runner.create_ephemeral_client.return_value = (MagicMock(), "c3@test.example", {})
    runner.create_account.side_effect = [{"id": "cc-1"}, {"id": "exp-1"}, {"id": "rnd-1"}]
    runner.upload_statement.return_value = "stmt-cc"
    runner.wait_for_statement_parsed.return_value = {"opening_balance": "10000.00", "closing_balance": "8800.00"}
    runner.get_balance_sheet.side_effect = [
        {"total_assets": "8800.00", "total_liabilities": "0.00", "total_equity": "10000.00", "net_income": "-1200.00", "equation_delta": "0.00", "is_balanced": True},
        {"total_assets": "8800.02", "total_liabilities": "0.00", "total_equity": "10000.00", "net_income": "-1199.98", "equation_delta": "0.00", "is_balanced": True},
    ]
    runner.get_income_statement.return_value = {"total_income": "0.00", "total_expenses": "1200.00", "net_income": "-1200.00"}
    runner.run_reconciliation.return_value = {"matches_created": 1}
    runner.accept_reconciliation_matches.return_value = 1
    runner.post_reconciliation_adjustment.return_value = {"difference": "0.02", "journal_entry_id": "je-adj-1"}

    res = case_3.execute_case_3(runner)
    assert res.status == "PASS"
    summary = extract_summary_data(
        {"summary": {"total": 1, "passed": 1, "failed": 0, "success": True}, "results": [{"case_id": "case_3", "status": "PASS", "details": res.details}]}
    )
    assert summary["cases_passed"] == 1
