"""AC-testing.benchmarks.13 and AC-testing.benchmarks.14: Bench V2 reports state only what a run recorded (#2484)."""

from __future__ import annotations

import copy
import re
from typing import Any

from common.testing.benchmarks.benchmark_html_reporter import (
    generate_html_report,
    generate_index_dashboard,
)


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
