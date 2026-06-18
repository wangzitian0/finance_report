"""Tests for the staging AI/OCR replay contract tool."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from tools import staging_ai_ocr_gate_contract as contract

ROOT = Path(__file__).resolve().parents[2]


def test_AC8_13_49_gate_files_include_matrix_llm_proofs_and_supplementals(
    monkeypatch,
) -> None:
    """AC8.13.49: Gate file list is generated from one replay contract source."""
    monkeypatch.setattr(
        contract,
        "_load_matrix",
        lambda: {
            "proofs": [
                {
                    "file": "tests/e2e/test_statement_full_journey.py",
                    "ci_tier": "post_merge_environment",
                    "required_markers": ["llm"],
                },
                {
                    "file": "tests/e2e/test_not_llm.py",
                    "ci_tier": "post_merge_environment",
                    "required_markers": ["e2e"],
                },
                {
                    "file": "tests/e2e/test_wrong_tier.py",
                    "ci_tier": "pr",
                    "required_markers": ["llm"],
                },
            ]
        },
    )

    assert contract.gate_files() == [
        "tests/e2e/test_statement_full_journey.py",
        "tests/e2e/test_statement_upload_e2e.py",
    ]


def test_AC8_13_49_missing_replay_counter_fails_closed(monkeypatch) -> None:
    """AC8.13.49: Every gate file must have explicit expected replay counters."""
    monkeypatch.setattr(
        contract,
        "_load_matrix",
        lambda: {
            "proofs": [
                {
                    "file": "tests/e2e/test_missing_counter.py",
                    "ci_tier": "post_merge_environment",
                    "required_markers": ["llm"],
                },
            ]
        },
    )

    with pytest.raises(SystemExit, match="Missing staging AI/OCR replay counters"):
        contract.gate_files()


def test_AC8_13_49_totals_and_shell_output_are_deterministic(monkeypatch) -> None:
    """AC8.13.49: Replay count totals and shell assignments share one source."""
    monkeypatch.setattr(
        contract,
        "gate_files",
        lambda: [
            "tests/e2e/test_statement_full_journey.py",
            "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        ],
    )

    assert contract.totals(contract.gate_files()) == {
        "uploads": 3,
        "parse_completions": 3,
        "brokerage_imports": 2,
        "report_verifications": 0,
    }
    shell = contract.emit_shell()
    assert (
        "STAGING_AI_OCR_TESTS=(tests/e2e/test_statement_full_journey.py "
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py)"
    ) in shell
    assert "STAGING_AI_OCR_EXPECTED_UPLOADS=3" in shell
    assert "STAGING_AI_OCR_EXPECTED_PARSE_COMPLETIONS=3" in shell
    assert "STAGING_AI_OCR_EXPECTED_BROKERAGE_IMPORTS=2" in shell
    assert "STAGING_AI_OCR_EXPECTED_REPORT_VERIFICATIONS=0" in shell


def test_AC8_13_49_main_supports_shell_and_human_output(monkeypatch, capsys) -> None:
    """AC8.13.49: CLI output supports workflow shell eval and human inspection."""
    monkeypatch.setattr(
        contract,
        "gate_files",
        lambda: ["tests/e2e/test_statement_full_journey.py"],
    )

    monkeypatch.setattr(sys, "argv", ["staging_ai_ocr_gate_contract.py", "--shell"])
    assert contract.main() == 0
    assert "STAGING_AI_OCR_EXPECTED_UPLOADS=1" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["staging_ai_ocr_gate_contract.py"])
    assert contract.main() == 0
    output = capsys.readouterr().out
    assert "Staging AI/OCR gate files:" in output
    assert "- tests/e2e/test_statement_full_journey.py" in output
    assert "- uploads: 1" in output


def test_AC8_13_109_ai_ocr_gate_tests_use_isolated_users() -> None:
    """AC8.13.109: Post-merge AI/OCR gate tests must not share mutable users."""
    shared_user_fixtures = {"authenticated_page", "shared_auth_state"}

    offenders: list[str] = []
    for relative_path in contract.gate_files():
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            used_fixtures = {arg.arg for arg in node.args.args}
            shared = sorted(used_fixtures & shared_user_fixtures)
            if shared:
                offenders.append(
                    f"{relative_path}::{node.name} uses {', '.join(shared)}"
                )

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_tests_use_cookie_auth_for_api_calls() -> None:
    """AC8.13.109: Provider-backed E2E API calls must use HttpOnly cookie auth."""
    offenders: list[str] = []
    forbidden_snippets = [
        "localStorage.getItem('finance_access_token')",
        'localStorage.getItem("finance_access_token")',
        '"Authorization": f"Bearer {access_token}"',
        "'Authorization': f'Bearer {access_token}'",
    ]

    for relative_path in contract.gate_files():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in source:
                offenders.append(f"{relative_path} contains {snippet}")

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_tests_avoid_networkidle_waits() -> None:
    """AC8.13.109: Deployed browser gates wait on explicit UI, not networkidle."""
    offenders: list[str] = []

    for relative_path in contract.gate_files():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        if "networkidle" in source:
            offenders.append(f"{relative_path} waits for networkidle")

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_httpx_calls_use_absolute_api_urls() -> None:
    """AC8.13.109: Httpx-backed deployed E2E calls must not use relative URLs."""
    offenders: list[str] = []
    relative_prefixes = ("/api/", "/assets/")

    def relative_url_prefix(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr) and node.values:
            first_value = node.values[0]
            if isinstance(first_value, ast.Constant) and isinstance(
                first_value.value, str
            ):
                return first_value.value
        return None

    for relative_path in contract.gate_files():
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            url_prefix = relative_url_prefix(first_arg)
            if url_prefix and url_prefix.startswith(relative_prefixes):
                offenders.append(
                    f"{relative_path}:{node.lineno} uses relative API URL {url_prefix!r}"
                )

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_dashboard_analytics_locator_is_exact() -> None:
    """AC8.13.109: Dashboard checks must not also match loading status labels."""
    offenders: list[str] = []

    for relative_path in contract.gate_files():
        tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get_by_label":
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            exact_keyword = next(
                (kw for kw in node.keywords if kw.arg == "exact"),
                None,
            )
            is_dashboard_analytics = (
                isinstance(first_arg, ast.Constant)
                and first_arg.value == "Dashboard analytics"
            )
            is_exact = (
                exact_keyword is not None
                and isinstance(exact_keyword.value, ast.Constant)
                and exact_keyword.value.value is True
            )
            if is_dashboard_analytics and not is_exact:
                offenders.append(
                    f"{relative_path}:{node.lineno} uses inexact Dashboard analytics label"
                )

    assert offenders == []


def test_AC8_13_109_ai_ocr_gate_does_not_assert_hidden_statement_overlay_links() -> (
    None
):
    """AC8.13.109: Statement list checks use visible text/API state, not overlay links."""
    offenders: list[str] = []
    forbidden_snippets = [
        'locator("a").filter(has_text=',
        "locator('a').filter(has_text=",
        "locator(f'a[href=",
        'locator(f"a[href=',
    ]

    for relative_path in contract.gate_files():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in source:
                offenders.append(f"{relative_path} contains {snippet}")

    assert offenders == []


_JUNIT_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="staging-ai-ocr" tests="3" failures="1" errors="0" skipped="1">
    <testcase classname="tests.e2e.test_a" name="test_upload_ok"/>
    <testcase classname="tests.e2e.test_b" name="test_parse_cmb">
      <failure message="parse failed">Date is required</failure>
    </testcase>
    <testcase classname="tests.e2e.test_c" name="test_skipme"><skipped/></testcase>
  </testsuite>
</testsuites>
"""


def test_AC8_13_137_summarize_junit_reports_per_doc_failures(tmp_path: Path) -> None:
    """AC8.13.137: the gate summarizes JUnit results into real pass/fail counts and
    names the failing corpus docs, instead of a binary "Failures observed: 1+"."""
    xml = tmp_path / "gate.xml"
    xml.write_text(_JUNIT_XML, encoding="utf-8")

    summary = contract.summarize_junit([xml])

    assert summary["total"] == 3
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["failed_tests"] == ["tests.e2e.test_b::test_parse_cmb"]


def test_AC8_13_137_render_junit_summary_lists_failed_tests(tmp_path: Path) -> None:
    """AC8.13.137: the rendered markdown names the failed test so the red gate is
    actionable (which doc failed), not opaque."""
    xml = tmp_path / "gate.xml"
    xml.write_text(_JUNIT_XML, encoding="utf-8")

    rendered = contract.render_junit_summary(contract.summarize_junit([xml]))

    assert "passed: 1" in rendered
    assert "failed: 1" in rendered
    assert "tests.e2e.test_b::test_parse_cmb" in rendered


def test_AC8_13_137_summarize_junit_tolerates_missing_xml(tmp_path: Path) -> None:
    """AC8.13.137: a missing/unreadable XML yields an empty summary, never a crash,
    so the gate's reporting step can't itself fail the workflow."""
    summary = contract.summarize_junit([tmp_path / "does-not-exist.xml"])
    assert summary == {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "failed_tests": [],
    }
