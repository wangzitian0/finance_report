"""Core smoke contract tests for financial scenario benchmarks (referenced by user_cases_ssot)."""

from __future__ import annotations

import csv
import io
import json
import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import httpx
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
    assert "common.testing.test_selection --stage staging_core_e2e --run" in hook_text(manifest.slots["staging_gate"])
    assert "tests.benchmarks.run_financial_scenario_benchmark" in hook_text(manifest.slots["scheduled_audit"])
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
    runner.get_income_statement.return_value = {
        "total_income": "0.00",
        "total_expenses": "1200.00",
        "net_income": "-1200.00",
    }
    runner.run_reconciliation.return_value = {"matches_created": 1}
    runner.accept_reconciliation_matches.return_value = 1
    runner.post_reconciliation_adjustment.return_value = {"difference": "0.02", "journal_entry_id": "je-adj-1"}

    res = case_3.execute_case_3(runner)
    assert res.status == "PASS"
    summary = extract_summary_data(
        {
            "summary": {"total": 1, "passed": 1, "failed": 0, "success": True},
            "results": [{"case_id": "case_3", "status": "PASS", "details": res.details}],
        }
    )
    assert summary["cases_passed"] == 1


def test_brokerage_pdf_fixtures_contain_holdings_table() -> None:
    import fitz

    generated_dir = REPO_ROOT / "tests/fixtures/pdf/generated"
    for stem in ("futu_statement_fixture", "moomoo_statement_fixture"):
        pdf_path = generated_dir / f"{stem}.pdf"
        expected_path = generated_dir / f"{stem}_expected.json"
        with fitz.open(pdf_path) as doc:
            full_text = "\n".join(page.get_text("text") for page in doc)
        assert "Holdings / Positions" in full_text, f"{pdf_path.name} missing Holdings / Positions table"
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        assert expected.get("positions"), f"{expected_path.name} missing non-empty positions"


def test_bench_sdk_version_mismatch_and_unknown_tag_diagnostics(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.benchmarks.run_financial_scenario_benchmark import _check_sdk_version
    from tests.e2e.deployment_pin import assert_pinned_deployment

    monkeypatch.setattr(
        "tests.benchmarks.run_financial_scenario_benchmark.read_sdk_pin",
        lambda _r: ("https://x/infra2_sdk-3.32.0-py3-none-any.whl", "0" * 64, "infra2_sdk-3.32.0-py3-none-any.whl"),
    )
    monkeypatch.setattr("importlib.metadata.version", lambda _pkg: "3.8.0")
    warning = _check_sdk_version()
    assert warning is not None and "3.32.0" in warning and "3.8.0" in warning and "3.32.0" in capsys.readouterr().err

    with pytest.raises(AssertionError, match=r"unknown to local git.*COMMIT_REF"):
        assert_pinned_deployment({"version": "024cc16", "git_sha": "024cc16"}, "v0.2.50", None)


def _approval_api(digest: str | None, approvals: list[dict], *, approve_status: int = 200) -> httpx.Client:
    """Return a client for a fake API that records each approval body (#3025)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/review"):
            return httpx.Response(200, json={"source_result_digest": digest})
        if request.url.path.endswith("/approvals"):
            approvals.append(json.loads(request.content))
            return httpx.Response(approve_status, json={"status": "approved", "detail": "balance mismatch"})
        return httpx.Response(200, json={"status": "parsed"})

    return httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handler))


def test_benchmark_approvals_name_the_reviewed_extraction_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.benchmarks import run_financial_scenario_benchmark as runner_module

    monkeypatch.setattr(runner_module, "wait_for_statement_runs_sync", lambda *_args: None)
    runner = runner_module.ScenarioBenchmarkRunner("http://api.test")
    digest = "a" * 64
    sent: list[dict] = []
    runner.approve_statement(_approval_api(digest, sent), "stmt-1")
    runner.assert_approval_blocked_by_balance_mismatch(_approval_api(digest, sent, approve_status=400), "stmt-2")
    assert sent == [
        {"create_account_if_missing": True, "expected_source_result_digest": digest},
        {"expected_source_result_digest": digest},
    ]

    sent_without_result: list[dict] = []
    runner.approve_statement(_approval_api(None, sent_without_result), "stmt-3")
    assert sent_without_result == [{"create_account_if_missing": True}]


def test_benchmark_block_check_rejects_a_missing_digest_refusal() -> None:
    """A 422 that asks for the digest is not a balance block (#3025)."""
    from tests.benchmarks.run_financial_scenario_benchmark import ScenarioBenchmarkRunner

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/review"):
            return httpx.Response(200, json={"source_result_digest": None})
        return httpx.Response(422, json={"detail": "Send expected_source_result_digest."})

    client = httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="Expected balance mismatch approval block"):
        ScenarioBenchmarkRunner("http://api.test").assert_approval_blocked_by_balance_mismatch(client, "stmt-1")
