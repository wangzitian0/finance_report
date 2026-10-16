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

import html
import re
from typing import Any

import pytest

from tools._lib.benchmarks import benchmark_html_reporter
from tools._lib.benchmarks.benchmark_html_reporter import (
    IDENTITY_CASE_IDS,
    extract_summary_data,
    generate_html_report,
    generate_index_dashboard,
)

# ------------------------------------------------------------------- helpers


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


def _stat_note(page: str, label: str) -> str:
    match = re.search(
        rf'<span class="stat-label">{re.escape(label)}</span>\s*'
        r'<span class="stat-value">.*?</span>\s*'
        r'<span class="stat-note">(.*?)</span>',
        page,
        flags=re.DOTALL,
    )
    assert match, f"no note under the stat box labelled {label!r}"
    return match.group(1).strip()


def _baseline_class(page: str, label: str) -> str:
    """The CSS class of the note in one stat box of the baseline card."""
    match = re.search(
        rf'<span class="stat-label">{re.escape(label)}</span>\s*'
        r'<span class="stat-value">[^<]*<small class="([^"]+)">',
        page,
    )
    assert match, f"no baseline note under the stat box labelled {label!r}"
    return match.group(1)


def _card(page: str, case_id: str) -> str:
    """The HTML of the scenario card of one case."""
    tag = f'<span class="case-tag">{case_id.upper()}</span>'
    cards = [c for c in page.split('<div class="card scenario-card">')[1:] if tag in c]
    assert len(cards) == 1, f"expected one card for {case_id}, found {len(cards)}"
    return cards[0].split('<details class="raw-details">')[0]


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

# The run that Bench V2 published for staging v0.2.2: cases 1, 3, 4 and the UI case
# failed before they recorded a figure.
STAGING_V022 = [
    _case("case_1", "FAIL"),
    _case("case_2", equation_delta="0.00"),
    _case("case_3", "FAIL"),
    _case("case_4", "FAIL"),
    _case("case_5", equation_delta="0.00"),
    _case("case_6", equation_delta="0.00"),
    _case("case_ui", "FAIL"),
]

# --------------------------------------------------------------- invariants


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


def test_AC_testing_benchmarks_13_the_balance_sheet_identity_follows_the_cases_of_flow_23() -> (
    None
):
    assert IDENTITY_CASE_IDS == ("case_1", "case_4", "case_6")

    for case_id in IDENTITY_CASE_IDS:
        run = [
            _case(c["case_id"], "FAIL", **c["details"])
            if c["case_id"] == case_id
            else c
            for c in FULL_RUN
        ]
        cells = _invariant_cells(generate_html_report(_report(run)))
        assert cells["Balance Sheet Identity"] == "FAIL", case_id


def test_AC_testing_benchmarks_13_a_case_outside_flow_23_leaves_the_balance_sheet_identity() -> (
    None
):
    run = [
        _case(c["case_id"], "FAIL", **c["details"]) if c["case_id"] == "case_2" else c
        for c in FULL_RUN
    ]
    cells = _invariant_cells(generate_html_report(_report(run)))

    assert cells["Balance Sheet Identity"] == "PASS"


def test_AC_testing_benchmarks_13_a_failed_case_turns_its_invariants_to_fail_and_leaves_the_others() -> (
    None
):
    run = [_case("case_1", "FAIL", equation_delta="5.00"), *FULL_RUN[1:]]
    cells = _invariant_cells(generate_html_report(_report(run)))

    assert cells["Temporal Multi-Period Rollforward"] == "FAIL"
    assert cells["Retained Earnings Articulation"] == "FAIL"
    assert cells["Balance Sheet Identity"] == "FAIL"
    assert cells["Credit Card Liability Clearance (No Double Counting)"] == "PASS"


def test_AC_testing_benchmarks_13_a_failed_credit_card_case_fails_only_its_invariant() -> (
    None
):
    run = [*FULL_RUN[:2], _case("case_3", "FAIL"), *FULL_RUN[3:]]
    cells = _invariant_cells(generate_html_report(_report(run)))

    assert cells["Credit Card Liability Clearance (No Double Counting)"] == "FAIL"
    assert cells["Temporal Multi-Period Rollforward"] == "PASS"
    assert cells["Retained Earnings Articulation"] == "PASS"
    assert cells["Balance Sheet Identity"] == "PASS"


def test_AC_testing_benchmarks_13_a_case_that_did_not_run_leaves_its_invariants_not_run() -> (
    None
):
    cells = _invariant_cells(
        generate_html_report(_report([_case("case_2", equation_delta="0.00")]))
    )

    assert cells == {
        "Balance Sheet Identity": "NOT RUN",
        "Temporal Multi-Period Rollforward": "NOT RUN",
        "Credit Card Liability Clearance (No Double Counting)": "NOT RUN",
        "Retained Earnings Articulation": "NOT RUN",
    }


def test_AC_testing_benchmarks_13_a_report_without_results_proves_no_invariant() -> (
    None
):
    cells = _invariant_cells(generate_html_report(_report([])))

    assert set(cells.values()) == {"NOT RUN"}


def test_AC_testing_benchmarks_13_an_invariant_with_no_backing_case_is_not_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(benchmark_html_reporter, "IDENTITY_CASE_IDS", ())

    cells = _invariant_cells(generate_html_report(_report(FULL_RUN)))

    assert cells["Balance Sheet Identity"] == "NOT RUN"
    assert cells["Temporal Multi-Period Rollforward"] == "PASS"


def test_AC_testing_benchmarks_13_a_balance_case_that_did_not_run_leaves_the_identity_not_run() -> (
    None
):
    run = [c for c in FULL_RUN if c["case_id"] != "case_6"]
    cells = _invariant_cells(generate_html_report(_report(run)))

    assert cells["Balance Sheet Identity"] == "NOT RUN"
    assert cells["Temporal Multi-Period Rollforward"] == "PASS"


def test_AC_testing_benchmarks_13_a_skipped_case_is_not_run() -> None:
    run = [_case("case_1", "SKIPPED"), *FULL_RUN[1:]]
    cells = _invariant_cells(generate_html_report(_report(run)))

    assert cells["Temporal Multi-Period Rollforward"] == "NOT RUN"
    assert cells["Retained Earnings Articulation"] == "NOT RUN"
    assert cells["Balance Sheet Identity"] == "NOT RUN"


def test_AC_testing_benchmarks_13_a_failed_balance_case_wins_over_a_skipped_one() -> (
    None
):
    run = [
        _case("case_1", "SKIPPED"),
        _case("case_4", "FAIL"),
        _case("case_6", equation_delta="0.00"),
    ]
    cells = _invariant_cells(generate_html_report(_report(run)))

    assert cells["Balance Sheet Identity"] == "NOT RUN"


def test_AC_testing_benchmarks_13_the_invariants_table_shows_the_values_the_run_recorded() -> (
    None
):
    rows = _invariant_rows(generate_html_report(_report(FULL_RUN)))

    assert "111.11" in rows["Temporal Multi-Period Rollforward"][0]
    assert "22.22" in rows["Retained Earnings Articulation"][0]
    credit_card = rows["Credit Card Liability Clearance (No Double Counting)"][0]
    assert "33.33" in credit_card
    assert "44.44" in credit_card
    assert "-33.33" in credit_card


def test_AC_testing_benchmarks_13_the_balance_sheet_identity_row_states_the_recorded_deltas() -> (
    None
):
    run = [
        _case("case_1", equation_delta="0.00"),
        _case("case_4", equation_delta_sgd="0.00", equation_delta_usd="-0.37"),
        _case("case_6"),
    ]
    rows = _invariant_rows(generate_html_report(_report(run)))

    assert (
        rows["Balance Sheet Identity"][0]
        == "Largest recorded |Δ| is 0.37 USD, recorded by 2 of 3 cases"
    )


def test_AC_testing_benchmarks_13_the_balance_sheet_identity_row_says_when_no_case_recorded_a_delta() -> (
    None
):
    run = [_case("case_1"), _case("case_4"), _case("case_6")]
    rows = _invariant_rows(generate_html_report(_report(run)))

    assert (
        rows["Balance Sheet Identity"][0] == "No delta recorded by any of the 3 cases"
    )


def test_AC_testing_benchmarks_13_the_balance_sheet_identity_row_ignores_deltas_of_other_cases() -> (
    None
):
    run = [
        _case("case_1"),
        _case("case_2", equation_delta="9.99"),
        _case("case_4"),
        _case("case_6"),
    ]
    rows = _invariant_rows(generate_html_report(_report(run)))

    assert (
        rows["Balance Sheet Identity"][0] == "No delta recorded by any of the 3 cases"
    )


def test_AC_testing_benchmarks_13_an_invariant_without_recorded_values_shows_n_a() -> (
    None
):
    run = [_case("case_1", "FAIL"), _case("case_3", "FAIL")]
    rows = _invariant_rows(generate_html_report(_report(run)))

    assert (
        rows["Temporal Multi-Period Rollforward"][0]
        == "Closing balances of months 1 to 4: n/a, n/a, n/a, n/a"
    )
    assert rows["Retained Earnings Articulation"][0] == "Cumulative net income n/a"
    assert (
        rows["Credit Card Liability Clearance (No Double Counting)"][0]
        == "Card spend n/a, bank repayment n/a, net income n/a"
    )


def test_AC_testing_benchmarks_13_a_recorded_detail_that_is_an_empty_string_is_not_recorded() -> (
    None
):
    run = [_case("case_1", m1_closing_balance="", cumulative_net_income="")]
    rows = _invariant_rows(generate_html_report(_report(run)))

    assert (
        rows["Temporal Multi-Period Rollforward"][0]
        == "Closing balances of months 1 to 4: n/a, n/a, n/a, n/a"
    )
    assert rows["Retained Earnings Articulation"][0] == "Cumulative net income n/a"


def test_AC_testing_benchmarks_13_a_summary_without_counts_shows_n_a() -> None:
    run = _report(FULL_RUN)
    run["summary"]["passed"] = None
    run["summary"]["total"] = ""

    page = generate_html_report(run)

    assert _stat_value(page, "Scenarios Evaluated") == "n/a / n/a"


def test_AC_testing_benchmarks_13_the_invariants_table_escapes_recorded_values() -> (
    None
):
    run = [
        _case(
            "case_1",
            m1_closing_balance="<i>1</i>",
            cumulative_net_income="<u>2</u>",
        ),
        _case("case_3", card_spend_recorded="<b>3</b>"),
    ]
    page = generate_html_report(_report(run))
    table = page.split('<table class="invariants-table">')[1].split("</table>")[0]

    for markup in ("<i>1</i>", "<u>2</u>", "<b>3</b>"):
        assert markup not in table
    assert "&lt;i&gt;1&lt;/i&gt;" in table
    assert "&lt;u&gt;2&lt;/u&gt;" in table
    assert "&lt;b&gt;3&lt;/b&gt;" in table


# --------------------------------------------------------- no invented figures


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


@pytest.mark.parametrize("case_id", ["case_1", "case_2", "case_3", "case_5", "case_6"])
def test_AC_testing_benchmarks_13_a_passed_case_without_figures_shows_n_a_in_its_table(
    case_id: str,
) -> None:
    page = generate_html_report(_report([_case(case_id)]))
    card = _card(page, case_id)

    assert "n/a" in card
    assert "Balanced (Δ not recorded)" in card
    for sample in ("15,", "5,849", "12,800", "1,000.00", "0.00"):
        assert sample not in card


def test_AC_testing_benchmarks_13_a_passed_case_4_without_figures_shows_n_a_in_its_table() -> (
    None
):
    card = _card(generate_html_report(_report([_case("case_4")])), "case_4")

    assert card.count("Balanced (Δ not recorded)") == 2
    assert "n/a SGD" in card
    assert "n/a USD" in card
    assert "0.00" not in card


@pytest.mark.parametrize(
    ("case_id", "key", "currency"),
    [
        ("case_1", "equation_delta", "SGD"),
        ("case_2", "equation_delta", "SGD"),
        ("case_3", "equation_delta", "SGD"),
        ("case_4", "equation_delta_sgd", "SGD"),
        ("case_4", "equation_delta_usd", "USD"),
        ("case_5", "equation_delta", "SGD"),
        ("case_6", "equation_delta", "SGD"),
    ],
)
def test_AC_testing_benchmarks_13_a_pass_badge_states_the_recorded_delta_and_currency(
    case_id: str, key: str, currency: str
) -> None:
    card = _card(
        generate_html_report(_report([_case(case_id, **{key: "0.01"})])), case_id
    )

    assert f'<span class="badge badge-pass">0.01 {currency} Balanced</span>' in card
    assert "0.00" not in card


def test_AC_testing_benchmarks_13_a_pass_badge_admits_a_delta_that_was_not_recorded() -> (
    None
):
    page = generate_html_report(_report([_case("case_2")]))

    assert "Balanced (Δ not recorded)" in page
    assert "SGD Balanced" not in page


def test_AC_testing_benchmarks_13_a_pass_badge_escapes_the_recorded_delta() -> None:
    page = generate_html_report(_report([_case("case_2", equation_delta="<b>1</b>")]))

    assert "<b>1</b>" not in page
    assert "&lt;b&gt;1&lt;/b&gt; SGD Balanced" in page


@pytest.mark.parametrize(
    ("case_id", "details", "regression"),
    [
        ("case_1", {"equation_delta": "5.00"}, "5.00 SGD Regression"),
        ("case_2", {"equation_delta": "5.00"}, "5.00 SGD Regression"),
        ("case_3", {"equation_delta": "5.00"}, "5.00 SGD Regression"),
        ("case_4", {"equation_delta_sgd": "5.00"}, "5.00 SGD Regression"),
        ("case_4", {"equation_delta_usd": "6.00"}, "6.00 USD Regression"),
        ("case_5", {"equation_delta": "5.00"}, "5.00 SGD Regression"),
        ("case_6", {"equation_delta": "5.00"}, "Equation Broken"),
    ],
)
def test_AC_testing_benchmarks_13_a_failed_case_card_shows_its_regression(
    case_id: str, details: dict[str, str], regression: str
) -> None:
    page = generate_html_report(_report([_case(case_id, "FAIL", **details)]))

    assert regression in _card(page, case_id)
    assert "Balanced" not in _card(page, case_id)


def test_AC_testing_benchmarks_13_a_failed_case_without_figures_says_so_and_claims_no_assertion() -> (
    None
):
    page = generate_html_report(_report([_case("case_1", "FAIL")]))
    card = _card(page, "case_1")

    assert "No figures recorded. The case stopped before it recorded any." in card
    assert "❌" not in card
    assert "Unconfirmed" not in card
    assert "Discontinuous" not in card


def test_AC_testing_benchmarks_13_a_failed_case_with_figures_keeps_its_table() -> None:
    page = generate_html_report(
        _report([_case("case_1", "FAIL", m1_closing_balance="111.11")])
    )
    card = _card(page, "case_1")

    assert "111.11" in card
    assert "No figures recorded" not in card
    assert "❌ Unconfirmed" in card


def test_AC_testing_benchmarks_13_a_skipped_case_card_claims_no_regression() -> None:
    page = generate_html_report(_report([_case("case_2", "SKIPPED")]))
    card = _card(page, "case_2")

    assert "Regression" not in page
    assert "Not run: the case did not run." in card
    assert "❌" not in card


def test_AC_testing_benchmarks_13_the_published_staging_run_shows_no_false_pass() -> (
    None
):
    page = generate_html_report(_report(STAGING_V022), baseline_data=_report(FULL_RUN))

    assert _invariant_cells(page) == {
        "Balance Sheet Identity": "FAIL",
        "Temporal Multi-Period Rollforward": "FAIL",
        "Credit Card Liability Clearance (No Double Counting)": "FAIL",
        "Retained Earnings Articulation": "FAIL",
    }
    assert "3 OF 7 SCENARIOS PASSED" in page
    assert "SCENARIOS BALANCED" not in page
    assert "Zero Drift" not in page
    assert _stat_value(page, "Cases Not Passed") == "4"
    assert "Closing balances of months 1 to 4: n/a, n/a, n/a, n/a" in page
    assert (
        page.count("No figures recorded. The case stopped before it recorded any.") == 4
    )


# ----------------------------------------------------------- summary boxes


def test_AC_testing_benchmarks_13_the_largest_delta_box_takes_the_largest_recorded_absolute_value() -> (
    None
):
    run = [
        _case("case_2", equation_delta="0.00"),
        _case("case_4", equation_delta_sgd="0.00", equation_delta_usd="-0.37"),
    ]
    page = generate_html_report(_report(run))

    assert _stat_value(page, "Largest Balance Delta") == "0.37 USD"


def test_AC_testing_benchmarks_13_the_largest_delta_box_compares_numbers_and_not_text() -> (
    None
):
    run = [
        _case("case_1", equation_delta="9.00"),
        _case("case_2", equation_delta="10.00"),
        _case("case_3", equation_delta="-8.50"),
    ]
    page = generate_html_report(_report(run))

    assert _stat_value(page, "Largest Balance Delta") == "10.00 SGD"


def test_AC_testing_benchmarks_13_the_largest_delta_box_keeps_the_currency_of_the_largest_delta() -> (
    None
):
    run = [
        _case("case_2", equation_delta="0.50"),
        _case("case_4", equation_delta_sgd="0.10", equation_delta_usd="0.30"),
    ]
    page = generate_html_report(_report(run))

    assert _stat_value(page, "Largest Balance Delta") == "0.50 SGD"


def test_AC_testing_benchmarks_13_the_largest_delta_box_shows_a_small_delta_exactly() -> (
    None
):
    page = generate_html_report(_report([_case("case_2", equation_delta="0.004")]))

    assert _stat_value(page, "Largest Balance Delta") == "0.004 SGD"
    assert "0.00 SGD" not in page


def test_AC_testing_benchmarks_13_the_largest_delta_box_says_n_a_when_no_case_recorded_a_delta() -> (
    None
):
    page = generate_html_report(_report([_case("case_2")]))

    assert _stat_value(page, "Largest Balance Delta") == "n/a"
    assert _stat_note(page, "Largest Balance Delta") == "recorded by 0 of 1 case"


@pytest.mark.parametrize(
    "raw",
    ["NaN", "Infinity", "-Infinity", "1e999999", "1E+12", "abc", "", None, [], {}],
)
def test_AC_testing_benchmarks_13_a_delta_that_is_no_finite_number_is_not_recorded(
    raw: Any,
) -> None:
    run = [_case("case_2", equation_delta=raw)]

    page = generate_html_report(_report(run))

    assert _stat_value(page, "Largest Balance Delta") == "n/a"
    assert extract_summary_data(_report(run))["max_equation_delta"] == "n/a"


def test_AC_testing_benchmarks_13_a_delta_that_is_no_number_does_not_hide_a_recorded_one() -> (
    None
):
    run = [
        _case("case_1", equation_delta="NaN"),
        _case("case_2", equation_delta="0.25"),
    ]
    page = generate_html_report(_report(run))

    assert _stat_value(page, "Largest Balance Delta") == "0.25 SGD"
    assert _stat_note(page, "Largest Balance Delta") == "recorded by 1 of 2 cases"


def test_AC_testing_benchmarks_13_the_delta_note_counts_the_cases_that_recorded_a_delta() -> (
    None
):
    page = generate_html_report(_report(FULL_RUN))

    assert _stat_note(page, "Largest Balance Delta") == "recorded by 6 of 6 cases"

    partial = generate_html_report(
        _report([_case("case_1", equation_delta="0.00"), _case("case_2")])
    )
    assert _stat_note(partial, "Largest Balance Delta") == "recorded by 1 of 2 cases"

    single = generate_html_report(_report([_case("case_1", equation_delta="0.00")]))
    assert _stat_note(single, "Largest Balance Delta") == "recorded by 1 of 1 case"


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
        extract_summary_data(_report([_case("case_2")]))["max_equation_delta_currency"]
        == ""
    )


def test_AC_testing_benchmarks_13_the_summary_delta_names_its_currency() -> None:
    summary = extract_summary_data(
        _report([_case("case_4", equation_delta_usd="-0.37")])
    )

    assert summary["max_equation_delta"] == "0.37"
    assert summary["max_equation_delta_currency"] == "USD"


@pytest.mark.parametrize("value", ["abc", None, float("nan"), float("inf"), -3, "NaN"])
def test_AC_testing_benchmarks_13_a_duration_that_is_no_finite_number_counts_as_zero(
    value: Any,
) -> None:
    case = _case("case_2", equation_delta="0.00")
    case["duration_seconds"] = value
    run = _report([case])

    page = generate_html_report(run)
    summary = extract_summary_data(run)

    assert "⏱️ 0.00s" in page or value == -3
    assert summary["duration_seconds"] in (0.0, -3.0)


# ----------------------------------------------------------------- baseline


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


def test_AC_testing_benchmarks_13_the_baseline_card_needs_a_delta_from_every_balance_case_for_zero_drift() -> (
    None
):
    run = [
        _case("case_1", equation_delta="0.00"),
        _case("case_2", equation_delta="0.00"),
        _case("case_4"),
        _case("case_6"),
    ]
    page = generate_html_report(_report(run), baseline_data=_report(FULL_RUN))

    assert "(Zero Drift)" not in page
    assert "(not recorded for every balance case)" in page


def test_AC_testing_benchmarks_13_the_baseline_card_names_a_recorded_drift() -> None:
    run = [
        _case("case_1", equation_delta="0.00"),
        _case("case_4", equation_delta_sgd="0.00", equation_delta_usd="0.02"),
        _case("case_6", equation_delta="0.00"),
    ]
    page = generate_html_report(_report(run), baseline_data=_report(FULL_RUN))

    assert "0.02 USD" in page
    assert "(Drift)" in page
    assert "Zero Drift" not in page


def test_AC_testing_benchmarks_13_the_baseline_card_colors_a_failed_run_as_worse_and_a_clean_run_as_better() -> (
    None
):
    clean = generate_html_report(_report(FULL_RUN), baseline_data=_report(FULL_RUN))
    assert _baseline_class(clean, "Pass Rate") == "metric-diff-better"
    assert _baseline_class(clean, "Max Equation Delta") == "metric-diff-better"

    failed = generate_html_report(
        _report([_case("case_1", equation_delta="0.00"), _case("case_2", "FAIL")]),
        baseline_data=_report(FULL_RUN),
    )
    assert _baseline_class(failed, "Pass Rate") == "metric-diff-worse"
    assert _baseline_class(failed, "Max Equation Delta") == "metric-diff-neutral"

    drift = generate_html_report(
        _report([_case("case_2", equation_delta="0.02")]),
        baseline_data=_report(FULL_RUN),
    )
    assert _baseline_class(drift, "Max Equation Delta") == "metric-diff-neutral"

    all_balance_cases = [
        _case("case_1", equation_delta="0.00"),
        _case("case_4", equation_delta_sgd="0.00", equation_delta_usd="0.02"),
        _case("case_6", equation_delta="0.00"),
    ]
    drifted = generate_html_report(
        _report(all_balance_cases), baseline_data=_report(FULL_RUN)
    )
    assert _baseline_class(drifted, "Max Equation Delta") == "metric-diff-worse"


def test_AC_testing_benchmarks_13_the_baseline_card_cannot_inject_markup() -> None:
    baseline = _report(FULL_RUN)
    baseline["version_ref"] = "<script>alert(1)</script>"

    page = generate_html_report(_report(FULL_RUN), baseline_data=baseline)

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


@pytest.mark.parametrize("total", ["abc", None, 0, True])
def test_AC_testing_benchmarks_13_a_baseline_without_a_usable_case_count_shows_n_a(
    total: Any,
) -> None:
    run = _report([_case("case_1", equation_delta="0.00")])
    run["summary"]["total"] = total

    page = generate_html_report(run, baseline_data=_report(FULL_RUN))

    assert "(n/a)" in page
    assert "(100%)" not in page


# ------------------------------------------------------------- header text


def test_AC_testing_benchmarks_13_the_header_says_balanced_only_when_every_case_passed() -> (
    None
):
    page = generate_html_report(_report(FULL_RUN))

    assert "ALL 6 SCENARIOS BALANCED" in page


def test_AC_testing_benchmarks_13_the_header_counts_the_passed_cases_of_a_failed_run() -> (
    None
):
    page = generate_html_report(_report([_case("case_1"), _case("case_2", "FAIL")]))

    assert "1 OF 2 SCENARIOS PASSED" in page
    assert "BALANCED" not in page


def test_AC_testing_benchmarks_13_the_header_counts_the_skipped_cases() -> None:
    page = generate_html_report(
        _report([_case("case_1"), _case("case_2", "SKIPPED"), _case("case_3", "FAIL")])
    )

    assert "1 OF 3 SCENARIOS PASSED, 1 SKIPPED" in page


def test_AC_testing_benchmarks_13_a_run_that_succeeded_with_a_skipped_case_is_not_balanced() -> (
    None
):
    run = _report([_case("case_1"), _case("case_2", "SKIPPED")])
    run["summary"]["success"] = True

    page = generate_html_report(run)

    assert "BALANCED" not in page
    assert "1 OF 2 SCENARIOS PASSED, 1 SKIPPED" in page


# ----------------------------------------------------------------- escaping


def test_AC_testing_benchmarks_13_a_case_status_cannot_inject_markup() -> None:
    page = generate_html_report(_report([_case("case_2", "<i>PASS</i>")]))

    assert "<i>PASS</i>" not in page
    assert "&lt;i&gt;PASS&lt;/i&gt;" in page


def test_AC_testing_benchmarks_13_the_case_identity_and_error_cannot_inject_markup() -> (
    None
):
    case = _case("CASE_<S>X</S>", "FAIL")
    case["case_name"] = "<u>name</u>"
    case["error_message"] = "<script>boom()</script>"

    page = generate_html_report(_report([case]))

    for markup in ("<S>X</S>", "<u>name</u>", "<script>boom()</script>"):
        assert markup not in page
    assert "&lt;S&gt;X&lt;/S&gt;" in page
    assert "&lt;u&gt;name&lt;/u&gt;" in page
    assert "&lt;script&gt;boom()&lt;/script&gt;" in page


def test_AC_testing_benchmarks_13_the_version_and_run_text_cannot_inject_markup() -> (
    None
):
    run = _report(FULL_RUN)
    run["version_ref"] = "<b>v</b>"
    run["app_url"] = "<i>url</i>"
    run["run_at"] = "<u>time</u>"

    page = generate_html_report(run)

    for markup in ("<b>v</b>", "<i>url</i>", "<u>time</u>"):
        assert markup not in page


@pytest.mark.parametrize(
    "case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6", "other"]
)
def test_AC_testing_benchmarks_13_recorded_values_cannot_inject_markup_into_a_case_table(
    case_id: str,
) -> None:
    keys = {
        "case_1": [
            "m1_closing_balance",
            "q1_net_income",
            "cumulative_net_income",
            "equation_delta",
        ],
        "case_2": [
            "household_husband_cash",
            "total_income",
            "ending_cash",
            "equation_delta",
        ],
        "case_3": [
            "card_spend_recorded",
            "bank_repayment",
            "ending_bank_cash",
            "net_income",
            "equation_delta",
        ],
        "case_4": [
            "sgd_closing_balance",
            "usd_closing_balance",
            "hkd_closing_balance",
            "total_assets_sgd",
            "equation_delta_sgd",
            "equation_delta_usd",
        ],
        "case_5": [
            "holdings_count",
            "symbols",
            "property_valuation_usd",
            "appraisal_source",
            "tax_ecosystem_status",
            "total_assets",
            "equation_delta",
        ],
        "case_6": [
            "overdraft_cash",
            "capital_gain",
            "net_income",
            "total_assets",
            "total_equity",
            "equation_delta",
        ],
        "other": ["anything"],
    }[case_id]
    details = {key: f"<s{n}>x</s{n}>" for n, key in enumerate(keys)}

    page = generate_html_report(_report([_case(case_id, **details)]))
    card = _card(page, case_id)

    for n, _ in enumerate(keys):
        assert f"<s{n}>" not in card
        assert f"&lt;s{n}&gt;" in card


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


def _history_rows(dashboard: str) -> list[str]:
    body = dashboard.split("<tbody")[1].split("</tbody>")[0]
    return re.findall(r"<tr>.*?</tr>", body, flags=re.DOTALL)


def test_AC_testing_benchmarks_14_the_trendline_shows_the_ten_newest_runs() -> None:
    runs = [_run(f"v0.1.{n:02d}", f"2026-09-{n:02d}T00:00:00") for n in range(1, 13)]

    trend = _trend(generate_index_dashboard(runs))

    for n in range(3, 13):
        assert f">v0.1.{n:02d}<" in trend
    assert ">v0.1.01<" not in trend
    assert ">v0.1.02<" not in trend
    assert trend.index(">v0.1.03<") < trend.index(">v0.1.12<")


def test_AC_testing_benchmarks_14_the_trendline_shows_a_single_run() -> None:
    trend = _trend(generate_index_dashboard([_run("v1", "2026-09-01T00:00:00")]))

    assert ">v1<" in trend
    assert "10.0s" in trend


def test_AC_testing_benchmarks_14_a_version_label_cannot_inject_markup_into_the_trendline() -> (
    None
):
    runs = [_run("<script>alert(1)</script>", "2026-09-01T00:00:00")]

    dashboard = generate_index_dashboard(runs)

    assert "<script>alert(1)</script>" not in dashboard
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in _trend(dashboard)


def test_AC_testing_benchmarks_14_the_history_table_escapes_every_run_field() -> None:
    run = _run(
        "<b>v</b>",
        "<d>date</d>2026-09-01T00:00:00",
        status="<i>PASS</i>",
        app_url="<u>url</u>",
        max_equation_delta="<s>9</s>",
        max_equation_delta_currency="<em>XX</em>",
        cases_passed="<p>1</p>",
        cases_total="<q>2</q>",
        report_url='"><script>x()</script>',
    )

    dashboard = generate_index_dashboard([run])

    for markup in (
        "<b>v</b>",
        "<d>date</d>",
        "<i>PASS</i>",
        "<u>url</u>",
        "<s>9</s>",
        "<em>XX</em>",
        "<p>1</p>",
        "<q>2</q>",
        "<script>x()</script>",
    ):
        assert markup not in dashboard, markup


@pytest.mark.parametrize(
    "target",
    [
        "javascript:alert(1)",
        " JavaScript:alert(1)",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "\x01javascript:alert(1)",
        "data:text/html,x",
        "vbscript:x",
        "mailto:a@b.test",
        "http://[::1",
    ],
)
def test_AC_testing_benchmarks_14_a_report_link_with_another_scheme_than_http_or_https_becomes_a_hash(
    target: str,
) -> None:
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", report_url=target)]
    )

    assert html.escape(target) not in dashboard
    assert dashboard.count('href="#"') == 2
    assert "v1/report.html" not in dashboard.split("<tbody")[1]


def test_AC_testing_benchmarks_14_a_version_label_cannot_make_a_link_run_code() -> None:
    dashboard = generate_index_dashboard(
        [_run("javascript:alert(1)//", "2026-09-01T00:00:00")]
    )

    assert 'href="javascript:' not in dashboard
    assert 'href="#"' in dashboard


def test_AC_testing_benchmarks_14_a_report_link_keeps_a_normal_target() -> None:
    dashboard = generate_index_dashboard([_run("v1", "2026-09-01T00:00:00")])

    assert 'href="v1/report.html"' in dashboard
    assert dashboard.count('href="v1/report.html"') == 3
    assert 'href="v1/report.html" class="btn-latest"' in dashboard


@pytest.mark.parametrize(
    "target",
    [
        "https://example.test/v1/report.html?a=1&b=2",
        "HTTP://example.test/report.html",
        "//example.test/report.html",
        "../v1/report.html",
    ],
)
def test_AC_testing_benchmarks_14_a_report_link_keeps_an_http_https_or_relative_target(
    target: str,
) -> None:
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", report_url=target)]
    )

    assert f'href="{html.escape(target)}"' in dashboard
    assert 'href="#"' not in dashboard


def test_AC_testing_benchmarks_14_a_run_without_a_status_is_unknown_and_not_pass() -> (
    None
):
    run = _run("v1", "2026-09-01T00:00:00")
    del run["status"]

    dashboard = generate_index_dashboard([run])

    assert '<span class="badge badge-fail">UNKNOWN</span>' in dashboard
    assert '<span class="badge badge-pass">' not in dashboard
    assert "The status of the latest run is unknown. 7 of 7 cases passed" in dashboard


def test_AC_testing_benchmarks_14_a_run_without_a_delta_shows_n_a_and_not_zero() -> (
    None
):
    run = _run("v1", "2026-09-01T00:00:00")
    del run["max_equation_delta"]

    dashboard = generate_index_dashboard([run])

    assert "<td>n/a</td>" in dashboard
    assert _stat_value(dashboard, "Largest Balance Delta") == "n/a"
    assert "0.00 SGD" not in dashboard


def test_AC_testing_benchmarks_14_an_n_a_delta_in_the_manifest_stays_n_a() -> None:
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", max_equation_delta="n/a")]
    )

    assert _stat_value(dashboard, "Largest Balance Delta") == "n/a"
    assert "n/a SGD" not in dashboard


def test_AC_testing_benchmarks_14_an_older_manifest_entry_holds_sgd_and_a_newer_one_names_its_currency() -> (
    None
):
    older = _run("v1", "2026-09-01T00:00:00", max_equation_delta="0.00")
    newer = _run(
        "v2",
        "2026-09-02T00:00:00",
        max_equation_delta="0.37",
        max_equation_delta_currency="USD",
    )

    rows = _history_rows(generate_index_dashboard([older, newer]))

    assert "<td>0.37 USD</td>" in rows[0]
    assert "<td>0.00 SGD</td>" in rows[1]
    assert (
        _stat_value(generate_index_dashboard([older, newer]), "Largest Balance Delta")
        == "0.37 USD"
    )
    assert (
        _stat_value(generate_index_dashboard([older]), "Largest Balance Delta")
        == "0.00 SGD"
    )


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


def test_AC_testing_benchmarks_14_a_passing_latest_run_reports_its_case_counts() -> (
    None
):
    dashboard = generate_index_dashboard([_run("v1", "2026-09-01T00:00:00")])

    assert _stat_value(dashboard, "Latest Pass Rate") == "7/7 (100%)"
    assert "7 of 7 cases passed" in dashboard
    assert "did not pass" not in dashboard
    assert _stat_value(dashboard, "Largest Balance Delta") == "0.00 SGD"
    assert '<span class="badge badge-pass">PASS</span>' in dashboard


@pytest.mark.parametrize(
    "counts",
    [
        {"cases_passed": "abc", "cases_total": "xyz"},
        {"cases_passed": None, "cases_total": None},
        {"cases_passed": 3, "cases_total": 0},
        {"cases_passed": 3, "cases_total": True},
    ],
)
def test_AC_testing_benchmarks_14_a_run_without_usable_counts_shows_n_a_and_does_not_crash(
    counts: dict[str, Any],
) -> None:
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", status="FAIL", **counts)]
    )

    assert "(n/a)" in dashboard
    assert "(100%)" not in dashboard


def test_AC_testing_benchmarks_14_a_duration_that_is_no_number_does_not_crash() -> None:
    dashboard = generate_index_dashboard(
        [
            _run("v1", "2026-09-01T00:00:00", duration_seconds="slow"),
            _run("v2", "2026-09-02T00:00:00", duration_seconds=float("nan")),
        ]
    )

    assert "0.00s" in dashboard
    assert not re.search(r"\bnan\b", dashboard, flags=re.IGNORECASE)


def test_AC_testing_benchmarks_14_an_empty_dashboard_claims_nothing() -> None:
    dashboard = generate_index_dashboard([])

    assert _stat_value(dashboard, "Latest Pass Rate") == "n/a (n/a)"
    assert "The history holds no run yet" in dashboard
    assert "(100%)" not in dashboard
    assert "N/A" not in dashboard
    assert "View Latest Full Report" not in dashboard
    assert _stat_value(dashboard, "Largest Balance Delta") == "n/a"
    assert _stat_value(dashboard, "Latest Latency") == "n/a"
    assert "Latest Deployed Release: n/a" in dashboard
    assert "None" not in dashboard


def test_AC_testing_benchmarks_14_the_latest_status_is_escaped() -> None:
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", status="<b>PASS</b>")]
    )

    assert "<b>PASS</b>" not in dashboard
    assert "&lt;b&gt;PASS&lt;/b&gt;" in dashboard


def test_AC_testing_benchmarks_14_the_latest_summary_is_escaped() -> None:
    dashboard = generate_index_dashboard(
        [
            _run(
                "v1",
                "2026-09-01T00:00:00",
                status="<b>X</b>",
                cases_passed="<i>1</i>",
                cases_total="<u>2</u>",
            )
        ]
    )

    for markup in ("<b>X</b>", "<i>1</i>", "<u>2</u>"):
        assert markup not in dashboard
    assert "&lt;i&gt;1&lt;/i&gt; of &lt;u&gt;2&lt;/u&gt; cases passed" in dashboard


def test_AC_testing_benchmarks_14_the_latest_run_is_the_newest_by_run_time() -> None:
    runs = [
        _run("v2", "2026-09-02T00:00:00", status="FAIL", cases_passed=1),
        _run("v1", "2026-09-01T00:00:00"),
    ]

    dashboard = generate_index_dashboard(runs)

    assert "Latest Deployed Release: v2" in dashboard
    assert _stat_value(dashboard, "Latest Pass Rate") == "1/7 (14%)"
