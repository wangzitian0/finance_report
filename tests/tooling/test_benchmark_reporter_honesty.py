"""AC-testing.benchmarks.13 and AC-testing.benchmarks.14: Bench V2 reports state only what a run recorded (#2484, #2519, #2540)."""

from __future__ import annotations

import argparse
import copy
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from common.testing.benchmarks import generate_benchmark_index
from common.testing.benchmarks.benchmark_html_reporter import (
    extract_summary_data,
    generate_html_report,
    generate_index_dashboard,
)
from common.testing.benchmarks.cases.case_6 import execute_case_6
from common.testing.benchmarks.run_financial_scenario_benchmark import _save_reports


def _case(case_id: str, status: str = "PASS", **details: Any) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "case_name": case_id,
        "status": status,
        "duration_seconds": 1.0,
        "details": details,
    }


def _report(results: list[dict[str, Any]]) -> dict[str, Any]:
    results = copy.deepcopy(list(results))
    passed = sum(r.get("status") == "PASS" for r in results)
    skipped = sum(r.get("status") == "SKIPPED" for r in results)
    failed = len(results) - passed - skipped
    return {
        "version_ref": "v-test",
        "run_at": "2026-10-10T00:00:00+00:00",
        "app_url": "https://staging.example.test",
        "summary": {
            "total": len(results),
            "passed": passed,
            "skipped": skipped,
            "failed": failed,
            "success": failed == 0 and skipped == 0,
        },
        "results": results,
    }


def _invariant_rows(page: str) -> dict[str, tuple[str, str]]:
    """Map the name of each invariant row to (observed text, adjudication badge text)."""
    table = page.split('<table class="invariants-table">')[1].split("</table>")[0]
    rows = re.findall(
        r"<tr>\s*<td><strong>(.*?)</strong></td>\s*<td><code>.*?</code></td>\s*"
        r"<td>(.*?)</td>\s*<td>"
        r'<span class="badge badge-(?:pass|fail|skip)">(.*?)</span></td>\s*</tr>',
        table,
        flags=re.DOTALL,
    )
    return {name: (observed, badge) for name, observed, badge in rows}


def _invariant_cells(page: str) -> dict[str, str]:
    """Map the name of each invariant row to its adjudication badge text."""
    return {name: badge for name, (_, badge) in _invariant_rows(page).items()}


def _stat_value(page: str, label: str) -> str:
    match = re.search(
        rf'<span class="stat-label">{re.escape(label)}</span>\s*'
        r'<span class="stat-value">(.*?)</span>',
        page,
        flags=re.DOTALL,
    )
    assert match, f"no stat box labelled {label!r}"
    return match.group(1).strip()


def _run(version: str, run_at: str, **overrides: Any) -> dict[str, Any]:
    return {
        "version": version,
        "run_at": run_at,
        "status": "PASS",
        "cases_total": 7,
        "cases_passed": 7,
        "duration_seconds": 10.0,
        "max_equation_delta": "0.00",
        **overrides,
    }


FULL_RUN = [
    _case(
        "case_1",
        m1_closing_balance="111.11",
        cumulative_net_income="22.22",
        equation_delta="0.00",
    ),
    _case("case_2", equation_delta="0.00"),
    _case(
        "case_3",
        card_spend_recorded="33.33",
        bank_repayment="44.44",
        net_income="-33.33",
        equation_delta="0.00",
    ),
    _case("case_4", equation_delta_sgd="0.00", equation_delta_usd="0.00"),
    _case("case_5", equation_delta="0.00"),
    _case("case_6", equation_delta="0.00"),
]

INVARIANT_CASES = {
    "Balance Sheet Identity": {"case_1", "case_4", "case_6"},
    "Temporal Multi-Period Rollforward": {"case_1"},
    "Credit Card Liability Clearance (No Double Counting)": {"case_3"},
    "Retained Earnings Articulation": {"case_1"},
}


def test_AC_testing_benchmarks_13_the_invariants_table_passes_only_for_cases_that_passed() -> (
    None
):
    page = generate_html_report(_report(FULL_RUN))

    assert _invariant_cells(page) == {
        "Balance Sheet Identity": "PASS",
        "Temporal Multi-Period Rollforward": "PASS",
        "Credit Card Liability Clearance (No Double Counting)": "PASS",
        "Retained Earnings Articulation": "PASS",
    }
    for failed in ("case_1", "case_2", "case_3", "case_4", "case_5", "case_6"):
        run = [
            _case(c["case_id"], "FAIL", **c["details"]) if c["case_id"] == failed else c
            for c in FULL_RUN
        ]
        assert _invariant_cells(generate_html_report(_report(run))) == {
            name: "FAIL" if failed in cases else "PASS"
            for name, cases in INVARIANT_CASES.items()
        }, failed
    for absent in ("case_1", "case_3", "case_4", "case_6"):
        run = [c for c in FULL_RUN if c["case_id"] != absent]
        assert _invariant_cells(generate_html_report(_report(run))) == {
            name: "NOT RUN" if absent in cases else "PASS"
            for name, cases in INVARIANT_CASES.items()
        }, absent


def test_AC_testing_benchmarks_14_the_latest_pass_rate_is_computed_from_the_latest_run() -> (
    None
):
    runs = [
        _run("v1", "2026-09-01T00:00:00"),
        _run("v2", "2026-09-02T00:00:00", status="FAIL", cases_passed=5),
    ]

    dashboard = generate_index_dashboard(runs)

    assert _stat_value(dashboard, "Latest Pass Rate") == "5/7 (71%)"
    assert "The latest run did not pass: 5 of 7 cases passed" in dashboard
    assert "reconciled" not in dashboard
    assert '<span class="badge badge-fail">FAIL</span>' in dashboard
    assert "Latest Deployed Release: v2" in dashboard


def _case_card(page: str, case_id: str) -> str:
    tag = f'<span class="case-tag">{case_id.upper()}</span>'
    assert tag in page, f"no card for {case_id}"
    return page.split(tag, 1)[1].split('<div class="card scenario-card">', 1)[0]


def _case_rows(page: str, case_id: str) -> dict[str, tuple[str, str]]:
    card = _case_card(page, case_id)
    body = card.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    rows = re.findall(
        r"<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td></tr>",
        body,
        flags=re.DOTALL,
    )
    return {label: (value, verdict) for label, value, verdict in rows}


def _mock_case6_runner(final_delta: str = "12.50") -> MagicMock:
    runner = MagicMock()
    runner.create_ephemeral_client.return_value = (MagicMock(), "c6@test.local", {})
    runner.create_account.side_effect = [
        {"id": "acc-chk", "name": "Checking"},
        {"id": "acc-exp", "name": "Expense"},
        {"id": "acc-eq", "name": "Equity"},
        {"id": "acc-art", "name": "Art"},
        {"id": "acc-cg", "name": "CapGain"},
    ]
    runner.get_balance_sheet.side_effect = [
        {
            "total_assets": "-1500.00",
            "total_liabilities": "0.00",
            "total_equity": "1000.00",
            "net_income": "-2500.00",
            "unrealized_fx_gain_loss": "0.00",
            "cta_adjustment": "0.00",
            "net_worth_adjustment_gain_loss": "0.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        },
        {
            "total_assets": "11000.00",
            "total_liabilities": "0.00",
            "total_equity": "11000.00",
            "net_income": "0.00",
            "unrealized_fx_gain_loss": "0.00",
            "cta_adjustment": "0.00",
            "net_worth_adjustment_gain_loss": "0.00",
            "equation_delta": final_delta,
            "is_balanced": final_delta == "0.00",
        },
    ]
    runner.get_balance_sheet_diagnostics.return_value = {
        "is_balanced": final_delta == "0.00"
    }
    return runner


def test_AC_testing_benchmarks_13_case_6_partial_failure_marks_only_failed_assertion_row() -> (
    None
):
    """Slice A (#2519): case_6 with wrong equation_delta marks passing rows ✅, failed delta ❌, and unverified row n/a."""
    runner = _mock_case6_runner(final_delta="12.50")
    case_res = execute_case_6(runner)

    assert case_res.status == "FAIL"
    verdicts = case_res.details["assertion_verdicts"]
    assert verdicts["overdraft_cash"] == "passed"
    assert verdicts["ending_cash_balance"] == "passed"
    assert verdicts["capital_gain"] == "passed"
    assert verdicts["net_income"] == "passed"
    assert verdicts["total_assets"] == "passed"
    assert verdicts["total_equity"] == "passed"
    assert verdicts["equation_delta"] == "failed"

    # Also verify that if a row has no verdict / was not run, the table renders "n/a" (not a mark).
    partial_details = copy.deepcopy(case_res.details)
    partial_details.pop("total_equity", None)
    partial_details["assertion_verdicts"]["total_equity"] = "not_run"

    report = _report(
        [
            {
                "case_id": "case_6",
                "case_name": case_res.case_name,
                "status": "FAIL",
                "duration_seconds": 1.2,
                "details": partial_details,
                "error_message": case_res.error_message,
            }
        ]
    )
    page = generate_html_report(report)
    rows = _case_rows(page, "case_6")

    assert rows["Overdraft Checkpoint Cash Balance"] == (
        "-$1500.00 SGD",
        "✅ Negative Balance Equation Validated",
    )
    assert rows["Realized Capital Gain from Art Disposal"] == (
        "+$2500.00 SGD",
        "✅ Capital Gain Recognized in P&amp;L",
    )
    assert rows["Final Period Net Income"] == (
        "$0.00 SGD",
        "✅ Expense Offset by Capital Gain",
    )
    assert rows["Final Period Total Assets"] == (
        "$11000.00 SGD",
        "✅ Ending Assets Reconciled",
    )
    assert rows["Final Period Total Equity"] == ("n/a", "n/a")
    delta_val, delta_verdict = rows["Balance Sheet Equation Delta"]
    assert delta_val == "$12.50 SGD"
    assert "❌" in delta_verdict and "12.50 SGD" in delta_verdict


def test_AC_testing_benchmarks_13_allow_skip_run_status_and_dashboard_agree() -> None:
    """Finding 2 (#2540): a run with --allow-skip that recorded success=True and failed=0 reports PASS consistently."""
    report = {
        "version_ref": "v-skip-ok",
        "run_at": "2026-10-20T08:00:00+00:00",
        "app_url": "https://staging.example.test",
        "summary": {
            "total": 2,
            "passed": 1,
            "skipped": 1,
            "failed": 0,
            "success": True,
        },
        "results": [
            _case("case_1", "PASS", equation_delta="0.00"),
            _case("case_2", "SKIPPED"),
        ],
    }

    summary = extract_summary_data(report)
    assert summary["status"] == "PASS"
    assert summary["cases_skipped"] == 1

    page = generate_html_report(report)
    assert (
        '<span class="badge badge-pass">1 OF 2 SCENARIOS PASSED, 1 SKIPPED</span>'
        in page
    )

    dashboard = generate_index_dashboard([summary])
    assert "The latest run did not pass" not in dashboard
    assert "1 of 2 cases passed (1 skipped)" in dashboard
    assert '<span class="badge badge-pass">PASS</span>' in dashboard


def test_AC_testing_benchmarks_13_summary_count_disagreement_is_surfaced_and_fails_run() -> (
    None
):
    """Finding 3 (#2540): summary counts that disagree with result records derive from results and surface the mismatch."""
    dishonest_report = {
        "version_ref": "v-dishonest",
        "run_at": "2026-10-20T08:00:00+00:00",
        "app_url": "https://staging.example.test",
        "summary": {
            "total": 6,
            "passed": 6,
            "skipped": 0,
            "failed": 0,
            "success": True,
        },
        "results": [
            _case("case_1", "PASS", equation_delta="0.00"),
            _case("case_2", "FAIL", equation_delta="5.00"),
        ],
    }

    summary = extract_summary_data(dishonest_report)
    assert summary["status"] == "FAIL"
    assert summary["cases_total"] == 2
    assert summary["cases_passed"] == 1
    assert summary["cases_failed"] == 1

    page = generate_html_report(dishonest_report)
    assert "ALL 6 SCENARIOS PASSED" not in page
    assert "SUMMARY COUNT MISMATCH" in page
    assert _stat_value(page, "Scenarios Passed") == "1 / 2"


def test_AC_testing_benchmarks_13_passed_case_with_nonzero_delta_is_treated_as_failed() -> (
    None
):
    """Finding 4 (#2540): a case with status PASS and non-zero delta is never shown as Balanced or green PASS."""
    report = _report([_case("case_1", "PASS", equation_delta="12.50")])
    summary = extract_summary_data(report)
    assert summary["status"] == "FAIL"
    assert summary["cases_passed"] == 0
    assert summary["cases_failed"] == 1
    assert summary["rollforward_balanced"] is False

    page = generate_html_report(report)
    assert "Balanced" not in page
    assert "ALL 1 SCENARIOS PASSED" not in page
    rows = _case_rows(page, "case_1")
    delta_cell, delta_badge = rows["Balance Sheet Equation Delta (A - L - E)"]
    assert delta_cell == "$12.50 SGD"
    assert "badge-fail" in delta_badge and "12.50 SGD" in delta_badge


def test_AC_testing_benchmarks_13_failed_card_with_telemetry_does_not_claim_no_figures_recorded() -> (
    None
):
    """Finding 5 (#2540): when details has telemetry keys, the card never claims the case stopped before recording any."""
    report = _report([_case("case_1", "FAIL", total_assets="24200.00")])
    page = generate_html_report(report)
    card = _case_card(page, "case_1")
    assert "No figures recorded. The case stopped before it recorded any." not in card
    assert (
        "No assertion table figures recorded. Inspect Raw Adjudication Telemetry below."
        in card
    )


def test_AC_testing_benchmarks_13_total_duration_requires_all_cases_to_have_valid_durations() -> (
    None
):
    """Finding 6 (#2540): total duration is n/a / None when any case duration is missing or invalid."""
    c1 = _case("case_1", "PASS", equation_delta="0.00")
    c2 = _case("case_2", "PASS", equation_delta="0.00")
    c2["duration_seconds"] = None
    report = _report([c1, c2])

    summary = extract_summary_data(report)
    assert summary["duration_seconds"] is None

    page = generate_html_report(report)
    assert _stat_value(page, "Total Duration") == "n/a"


def test_AC_testing_benchmarks_13_lone_surrogates_are_sanitized_without_truncating_files(
    tmp_path: Path,
) -> None:
    """Finding 7 (#2540): lone UTF-16 surrogates in report/summary strings never raise UnicodeEncodeError or truncate files."""
    report = _report(
        [
            _case(
                "case_1",
                "FAIL",
                m1_closing_balance="100.00",
                note="bad surrogate \ud800 tail",
            )
        ]
    )
    report["results"][0]["error_message"] = "boom \ud800 end"
    args = argparse.Namespace(
        json_report=tmp_path / "report.json",
        baseline=None,
        output_html=tmp_path / "v-surrogate" / "report.html",
        output_summary=tmp_path / "v-surrogate" / "summary.json",
    )

    _save_reports(args, report)

    html_text = args.output_html.read_text(encoding="utf-8")
    assert "</html>" in html_text
    summary_obj = json.loads(args.output_summary.read_text(encoding="utf-8"))
    assert summary_obj["status"] == "FAIL"

    # Also verify generate_benchmark_index handles lone surrogates in summary.json
    (tmp_path / "v-surrogate" / "summary.json").write_text(
        '{"version": "v-surrogate\\ud800", "run_at": "2026-10-20T00:00:00+00:00", "status": "FAIL"}',
        encoding="utf-8",
    )
    rc = generate_benchmark_index.main(["--benchmarks-dir", str(tmp_path)])
    assert rc == 0
    index_text = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "</html>" in index_text


def test_AC_testing_benchmarks_13_failed_delta_rows_include_currency_code() -> None:
    """Finding 8 (#2540): failed delta rows include SGD/USD currency code in the value cell and badge."""
    report = _report(
        [
            _case(
                "case_4",
                "FAIL",
                sgd_closing_balance="100.00",
                equation_delta_sgd="12.50",
                equation_delta_usd="0.00",
            ),
            _case(
                "case_6",
                "FAIL",
                overdraft_cash="-1500.00",
                equation_delta="12.50",
            ),
        ]
    )
    page = generate_html_report(report)

    c4_rows = _case_rows(page, "case_4")
    assert c4_rows["SGD Balance Sheet Equation Delta"][0] == "$12.50 SGD"
    assert "12.50 SGD" in c4_rows["SGD Balance Sheet Equation Delta"][1]
    assert c4_rows["USD Balance Sheet Equation Delta"][0] == "$0.00 USD"
    assert "0.00 USD" in c4_rows["USD Balance Sheet Equation Delta"][1]

    c6_rows = _case_rows(page, "case_6")
    assert c6_rows["Balance Sheet Equation Delta"][0] == "$12.50 SGD"
    assert "12.50 SGD" in c6_rows["Balance Sheet Equation Delta"][1]


def test_AC_testing_benchmarks_13_edge_case_in_process_inputs_do_not_crash() -> None:
    """Finding 9 (#2540): non-dict report_data, None manifest, Decimal/tuple keys, and >4300-digit ints do not crash."""
    huge_int = 10**5000
    assert "</html>" in generate_html_report(None)  # type: ignore[arg-type]
    assert "</html>" in generate_html_report(["not-a-dict"])  # type: ignore[arg-type]
    assert extract_summary_data(None)["status"] == "UNKNOWN"  # type: ignore[arg-type]
    assert "</html>" in generate_index_dashboard(None)  # type: ignore[arg-type]

    weird_case = {
        "case_id": "case_1",
        "case_name": "Weird Telemetry",
        "status": "FAIL",
        "duration_seconds": huge_int,
        "details": {
            Decimal("1.23"): "decimal-key",
            ("tuple", "key"): huge_int,
            "m1_closing_balance": huge_int,
        },
    }
    page = generate_html_report(
        {"summary": {"success": False}, "results": [weird_case]}
    )
    assert "</html>" in page
    assert "decimal-key" in page


def test_AC_testing_benchmarks_14_skipped_and_unknown_badges_and_timezone_offset() -> (
    None
):
    """Finding 10 (#2540): SKIPPED and UNKNOWN use badge-skip, and history table preserves timezone offset."""
    report = _report([_case("case_1", "SKIPPED")])
    page = generate_html_report(report)
    card = _case_card(page, "case_1")
    assert '<span class="badge badge-skip">SKIPPED</span>' in card

    empty_dashboard = generate_index_dashboard([])
    assert '<span class="badge badge-skip">UNKNOWN</span>' in empty_dashboard
    assert '<span class="badge badge-fail">UNKNOWN</span>' not in empty_dashboard

    tz_dashboard = generate_index_dashboard(
        [_run("v-tz", "2026-10-19T09:12:00+08:00", status="UNKNOWN")]
    )
    assert "2026-10-19 09:12:00+08:00" in tz_dashboard
    assert '<span class="badge badge-skip">UNKNOWN</span>' in tz_dashboard
