"""AC-testing.benchmarks.13 and AC-testing.benchmarks.14: Bench V2 reports state only what a run recorded (#2484).

The per-run report and the index dashboard are public pages. Before this change they showed
text that no run produced:
- Fixed sample figures (for example 15,271.23 and 5,849.25) in place of a value that the run did not record.
- A "PASS" for each core invariant, and "0.00 SGD Balanced", for any run.
- "Zero Drift", "(100%)" and "All 3-Statement financial invariants reconciled" for a run that failed.
- The ten oldest runs in the trendline, and unescaped version labels and status text.
Each test below fails on that behavior or guards against fixing it too far.
"""

from __future__ import annotations

import re
from typing import Any

from tools._lib.benchmarks.benchmark_html_reporter import (
    extract_summary_data,
    generate_html_report,
    generate_index_dashboard,
)

# ------------------------------------------------------------------- reports


def _case(case_id: str, status: str = "PASS", **details: Any) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "case_name": case_id,
        "status": status,
        "duration_seconds": 1.0,
        "details": details,
    }


def _report(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(r["status"] == "PASS" for r in results)
    skipped = sum(r["status"] == "SKIPPED" for r in results)
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


def _invariant_cells(page: str) -> dict[str, str]:
    """Map the name of each invariant row to its adjudication badge text."""
    table = page.split('<table class="invariants-table">')[1].split("</table>")[0]
    rows = re.findall(
        r"<tr>\s*<td><strong>(.*?)</strong></td>.*?"
        r'<span class="badge badge-(?:pass|fail|skip)">(.*?)</span></td>\s*</tr>',
        table,
        flags=re.DOTALL,
    )
    return dict(rows)


def _stat_value(page: str, label: str) -> str:
    match = re.search(
        rf'<span class="stat-label">{re.escape(label)}</span>\s*'
        r'<span class="stat-value">(.*?)</span>',
        page,
        flags=re.DOTALL,
    )
    assert match, f"no stat box labelled {label!r}"
    return match.group(1).strip()


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
]


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


def test_AC_testing_benchmarks_13_a_failed_case_turns_its_invariants_to_fail_and_leaves_the_others() -> (
    None
):
    run = [_case("case_1", "FAIL", equation_delta="5.00"), *FULL_RUN[1:]]
    cells = _invariant_cells(generate_html_report(_report(run)))

    assert cells["Temporal Multi-Period Rollforward"] == "FAIL"
    assert cells["Retained Earnings Articulation"] == "FAIL"
    assert cells["Balance Sheet Identity"] == "FAIL"
    assert cells["Credit Card Liability Clearance (No Double Counting)"] == "PASS"


def test_AC_testing_benchmarks_13_a_case_that_did_not_run_leaves_its_invariants_not_run() -> (
    None
):
    cells = _invariant_cells(
        generate_html_report(_report([_case("case_2", equation_delta="0.00")]))
    )

    assert cells["Temporal Multi-Period Rollforward"] == "NOT RUN"
    assert cells["Credit Card Liability Clearance (No Double Counting)"] == "NOT RUN"
    assert cells["Retained Earnings Articulation"] == "NOT RUN"
    assert cells["Balance Sheet Identity"] == "PASS"


def test_AC_testing_benchmarks_13_a_skipped_case_is_not_run() -> None:
    run = [_case("case_1", "SKIPPED"), *FULL_RUN[1:]]
    cells = _invariant_cells(generate_html_report(_report(run)))

    assert cells["Temporal Multi-Period Rollforward"] == "NOT RUN"


def test_AC_testing_benchmarks_13_the_report_shows_no_figure_that_the_run_did_not_record() -> (
    None
):
    page = generate_html_report(_report([_case("case_2", "FAIL")]))

    for invented in (
        "15,450.75",
        "5,000 SGD",
        "0.00 SGD",
        "Zero P&amp;L contamination",
    ):
        assert invented not in page


def test_AC_testing_benchmarks_13_the_invariants_table_shows_the_values_the_run_recorded() -> (
    None
):
    page = generate_html_report(_report(FULL_RUN))

    assert "111.11" in page
    assert "22.22" in page
    assert "33.33" in page
    assert "44.44" in page


def test_AC_testing_benchmarks_13_a_pass_badge_states_the_recorded_delta() -> None:
    page = generate_html_report(_report([_case("case_2", equation_delta="0.01")]))

    assert "0.01 SGD Balanced" in page
    assert "0.00 SGD Balanced" not in page


def test_AC_testing_benchmarks_13_a_pass_badge_admits_a_delta_that_was_not_recorded() -> (
    None
):
    page = generate_html_report(_report([_case("case_2")]))

    assert "Balanced (Δ not recorded)" in page
    assert "SGD Balanced" not in page


def test_AC_testing_benchmarks_13_the_largest_delta_box_takes_the_largest_recorded_absolute_value() -> (
    None
):
    run = [
        _case("case_2", equation_delta="0.00"),
        _case("case_4", equation_delta_sgd="0.00", equation_delta_usd="-0.37"),
    ]
    page = generate_html_report(_report(run))

    assert _stat_value(page, "Largest Balance Delta") == "0.37 SGD"


def test_AC_testing_benchmarks_13_the_largest_delta_box_says_n_a_when_no_case_recorded_a_delta() -> (
    None
):
    page = generate_html_report(_report([_case("case_2")]))

    assert _stat_value(page, "Largest Balance Delta") == "n/a SGD"


def test_AC_testing_benchmarks_13_the_not_passed_box_counts_failed_and_skipped_cases() -> (
    None
):
    run = [_case("case_1"), _case("case_2", "FAIL"), _case("case_3", "SKIPPED")]
    page = generate_html_report(_report(run))

    assert _stat_value(page, "Cases Not Passed") == "2"


def test_AC_testing_benchmarks_13_the_summary_delta_is_n_a_when_no_case_recorded_one() -> (
    None
):
    assert (
        extract_summary_data(_report([_case("case_2")]))["max_equation_delta"] == "n/a"
    )
    assert (
        extract_summary_data(_report([_case("case_4", equation_delta_usd="-0.37")]))[
            "max_equation_delta"
        ]
        == "0.37"
    )


def test_AC_testing_benchmarks_13_the_baseline_card_computes_the_pass_rate_and_the_delta() -> (
    None
):
    run = [
        _case("case_1", equation_delta="0.00"),
        _case("case_2", "FAIL", equation_delta="1.50"),
        _case("case_3", equation_delta="0.00"),
    ]
    page = generate_html_report(_report(run), baseline_data=_report(FULL_RUN))

    assert "2/3" in page
    assert "(67%)" in page
    assert "(100%)" not in page
    assert "1.50 SGD" in page
    assert "Zero Drift" not in page


def test_AC_testing_benchmarks_13_the_baseline_card_reports_zero_drift_only_for_a_recorded_zero() -> (
    None
):
    page = generate_html_report(_report(FULL_RUN), baseline_data=_report(FULL_RUN))
    assert "(Zero Drift)" in page
    assert "(100%)" in page

    unrecorded = generate_html_report(
        _report([_case("case_2")]), baseline_data=_report(FULL_RUN)
    )
    assert "(Zero Drift)" not in unrecorded
    assert "(not recorded)" in unrecorded


def test_AC_testing_benchmarks_13_a_case_status_cannot_inject_markup() -> None:
    page = generate_html_report(_report([_case("case_2", "<i>PASS</i>")]))

    assert "<i>PASS</i>" not in page
    assert "&lt;i&gt;PASS&lt;/i&gt;" in page


def test_AC_testing_benchmarks_13_a_skipped_case_card_claims_no_regression() -> None:
    page = generate_html_report(_report([_case("case_2", "SKIPPED")]))

    assert "Regression" not in page
    assert "Not run: the case was skipped" in page


def test_AC_testing_benchmarks_13_a_failed_case_card_still_shows_its_regression() -> (
    None
):
    page = generate_html_report(
        _report([_case("case_2", "FAIL", equation_delta="5.00")])
    )

    assert "5.00 SGD Regression" in page


# ----------------------------------------------------------------- dashboard


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


def _trend(dashboard: str) -> str:
    return dashboard.split('<svg viewBox="0 0 700 160" class="trend-svg">')[1].split(
        "</svg>"
    )[0]


def test_AC_testing_benchmarks_14_the_trendline_shows_the_ten_newest_runs() -> None:
    runs = [_run(f"v0.1.{n:02d}", f"2026-09-{n:02d}T00:00:00") for n in range(1, 13)]

    trend = _trend(generate_index_dashboard(runs))

    for n in range(3, 13):
        assert f">v0.1.{n:02d}<" in trend
    assert ">v0.1.01<" not in trend
    assert ">v0.1.02<" not in trend
    assert trend.index(">v0.1.03<") < trend.index(">v0.1.12<")


def test_AC_testing_benchmarks_14_a_version_label_cannot_inject_markup_into_the_trendline() -> (
    None
):
    runs = [_run("<script>alert(1)</script>", "2026-09-01T00:00:00")]

    dashboard = generate_index_dashboard(runs)

    assert "<script>alert(1)</script>" not in dashboard
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in _trend(dashboard)


def test_AC_testing_benchmarks_14_a_run_without_a_status_is_unknown_and_not_pass() -> (
    None
):
    run = _run("v1", "2026-09-01T00:00:00")
    del run["status"]

    dashboard = generate_index_dashboard([run])

    assert '<span class="badge badge-fail">UNKNOWN</span>' in dashboard
    assert '<span class="badge badge-pass">' not in dashboard


def test_AC_testing_benchmarks_14_a_run_without_a_delta_shows_n_a_and_not_zero() -> (
    None
):
    run = _run("v1", "2026-09-01T00:00:00")
    del run["max_equation_delta"]

    dashboard = generate_index_dashboard([run])

    assert "<td>n/a</td>" in dashboard
    assert _stat_value(dashboard, "Largest Balance Delta") == "n/a SGD"
    assert "0.00 SGD" not in dashboard


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


def test_AC_testing_benchmarks_14_a_passing_latest_run_reports_its_case_counts() -> (
    None
):
    dashboard = generate_index_dashboard([_run("v1", "2026-09-01T00:00:00")])

    assert _stat_value(dashboard, "Latest Pass Rate") == "7/7 (100%)"
    assert "7 of 7 cases passed" in dashboard
    assert _stat_value(dashboard, "Largest Balance Delta") == "0.00 SGD"


def test_AC_testing_benchmarks_14_an_empty_dashboard_claims_nothing() -> None:
    dashboard = generate_index_dashboard([])

    assert _stat_value(dashboard, "Latest Pass Rate") == "N/A (N/A)"
    assert "No run is recorded yet" in dashboard
    assert "(100%)" not in dashboard


def test_AC_testing_benchmarks_14_the_latest_status_is_escaped() -> None:
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", status="<b>PASS</b>")]
    )

    assert "<b>PASS</b>" not in dashboard
    assert "&lt;b&gt;PASS&lt;/b&gt;" in dashboard
