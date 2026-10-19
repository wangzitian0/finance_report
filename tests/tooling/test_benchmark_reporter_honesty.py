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

import copy
import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import pytest

from common.testing.benchmarks import benchmark_html_reporter
from common.testing.benchmarks.benchmark_html_reporter import (
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
    # A deep copy: a test that changes its report never changes shared module data.
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


class _Dom(HTMLParser):
    """The tags, the attributes and the visible text of a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, tuple[str, ...]]] = []
        self.attributes: list[tuple[str, str, str | None]] = []
        self.text: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, tuple(name for name, _ in attrs)))
        self.attributes.extend((tag, name, value) for name, value in attrs)
        if tag in ("style", "script"):
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script") and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden and data.strip():
            self.text.append(" ".join(data.split()))


def _dom(page: str) -> _Dom:
    parser = _Dom()
    parser.feed(page)
    parser.close()
    return parser


def _card(page: str, case_id: str) -> str:
    """The HTML of the scenario card of one case."""
    tag = f'<span class="case-tag">{case_id.upper()}</span>'
    cards = [c for c in page.split('<div class="card scenario-card">')[1:] if tag in c]
    assert len(cards) == 1, f"expected one card for {case_id}, found {len(cards)}"
    return cards[0].split('<details class="raw-details">')[0]


class _Rows(HTMLParser):
    """The exact text of each cell of each table row.

    The text of a cell with a badge starts with the badge class, for example "[badge-pass] ".
    The parser keeps all white space, so a cell with an extra space does not match.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, ...]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "span" and self._cell is not None:
            classes = (dict(attrs).get("class") or "").split()
            self._cell.extend(f"[{name}] " for name in classes if name != "badge")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(tuple(self._row))
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _table_rows(fragment: str) -> list[tuple[str, ...]]:
    """The rows of the tables in an HTML fragment, header rows included."""
    parser = _Rows()
    parser.feed(fragment)
    parser.close()
    return parser.rows


def _case_rows(page: str, case_id: str) -> dict[str, tuple[str, str]]:
    """Map the label of each row of a case table to (value cell, verdict cell)."""
    rows = _table_rows(_card(page, case_id))[1:]
    assert len({label for label, _, _ in rows}) == len(rows), "two rows share a label"
    return {label: (value, verdict) for label, value, verdict in rows}


def _header_badge(page: str) -> tuple[str, str]:
    """The class and the text of the badge in the page header."""
    match = re.search(
        r'<span class="badge (badge-\w+)">([^<]*)</span>\s*</div>\s*</header>', page
    )
    assert match, "the page header has no badge"
    return match.group(1), match.group(2)


def _baseline_stat(page: str, label: str) -> tuple[str, str, str]:
    """The value, the note class and the note of one stat box of the baseline card."""
    match = re.search(
        rf'<span class="stat-label">{re.escape(label)}</span>\s*'
        r'<span class="stat-value">([^<]*) <small class="([^"]+)">\(([^)]*)\)</small>',
        page,
    )
    assert match, f"no baseline stat box labelled {label!r}"
    return match.group(1), match.group(2), match.group(3)


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


# The cases behind each invariant row.
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
    # One failed case fails each invariant that it backs. The other invariants pass.
    for failed in ("case_1", "case_2", "case_3", "case_4", "case_5", "case_6"):
        run = [
            _case(c["case_id"], "FAIL", **c["details"]) if c["case_id"] == failed else c
            for c in FULL_RUN
        ]
        assert _invariant_cells(generate_html_report(_report(run))) == {
            name: "FAIL" if failed in cases else "PASS"
            for name, cases in INVARIANT_CASES.items()
        }, failed
    # A case that is not in the run leaves each invariant that it backs NOT RUN.
    for absent in ("case_1", "case_3", "case_4", "case_6"):
        run = [c for c in FULL_RUN if c["case_id"] != absent]
        assert _invariant_cells(generate_html_report(_report(run))) == {
            name: "NOT RUN" if absent in cases else "PASS"
            for name, cases in INVARIANT_CASES.items()
        }, absent


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

    assert cells["Balance Sheet Identity"] == "FAIL"


@pytest.mark.parametrize("status", ["ERROR", "TIMEOUT", "fail", "UNKNOWN"])
def test_AC_testing_benchmarks_13_a_status_other_than_pass_or_skipped_fails_the_invariant(
    status: str,
) -> None:
    run = [_case("case_1", status, equation_delta="0.00"), *FULL_RUN[1:]]
    cells = _invariant_cells(generate_html_report(_report(run)))

    assert cells["Temporal Multi-Period Rollforward"] == "FAIL"
    assert cells["Balance Sheet Identity"] == "FAIL"


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


def test_AC_testing_benchmarks_13_a_summary_without_counts_takes_the_counts_from_the_results() -> (
    None
):
    run = _report(FULL_RUN)
    run["summary"]["passed"] = None
    run["summary"]["total"] = ""

    page = generate_html_report(run)
    summary = extract_summary_data(run)

    assert _stat_value(page, "Scenarios Passed") == "6 / 6"
    assert "ALL 6 SCENARIOS PASSED" in page
    assert "0 OF" not in page
    assert (summary["cases_total"], summary["cases_passed"]) == (6, 6)


def test_AC_testing_benchmarks_13_the_counts_of_the_summary_win_over_the_results() -> (
    None
):
    run = _report(FULL_RUN)
    run["summary"]["total"] = 9
    run["summary"]["passed"] = 5

    page = generate_html_report(run)

    assert _stat_value(page, "Scenarios Passed") == "5 / 9"
    assert extract_summary_data(run)["cases_total"] == 9


def test_AC_testing_benchmarks_13_the_invariants_table_shows_n_a_for_a_figure_that_is_markup() -> (
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
    rows = _invariant_rows(page)

    # A figure that is no number shows n/a. Its text never reaches the page.
    for markup in ("<i>1</i>", "<u>2</u>", "<b>3</b>"):
        assert markup not in table
        assert html.escape(markup) not in table
    assert (
        rows["Temporal Multi-Period Rollforward"][0]
        == "Closing balances of months 1 to 4: n/a, n/a, n/a, n/a"
    )
    assert rows["Retained Earnings Articulation"][0] == "Cumulative net income n/a"
    assert (
        rows["Credit Card Liability Clearance (No Double Counting)"][0]
        == "Card spend n/a, bank repayment n/a, net income n/a"
    )


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
    assert '<span class="badge badge-pass">Balanced (Δ not recorded)</span>' in page
    assert "SGD Balanced" not in page


def test_AC_testing_benchmarks_13_a_pass_badge_prints_only_a_number_as_the_delta() -> (
    None
):
    page = generate_html_report(_report([_case("case_2", equation_delta="<b>1</b>")]))
    card = _card(page, "case_2")

    assert "<b>1</b>" not in page
    assert "Balanced (Δ not recorded)" in card
    assert "SGD Balanced" not in card


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
    assert "ALL 7 SCENARIOS PASSED" not in page
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
    ["NaN", "Infinity", "-Infinity", "abc", "", None, [], {}, True, "1,5", "0x10"],
)
def test_AC_testing_benchmarks_13_a_delta_that_is_no_finite_number_is_not_recorded(
    raw: Any,
) -> None:
    run = [_case("case_2", equation_delta=raw)]

    page = generate_html_report(_report(run))

    assert _stat_value(page, "Largest Balance Delta") == "n/a"
    assert extract_summary_data(_report(run))["max_equation_delta"] == "n/a"


@pytest.mark.parametrize(
    ("raw", "box", "card"),
    [
        ("5E+12", "5.000E+12", "5.000E+12"),
        ("-5E+12", "5.000E+12", "-5.000E+12"),
        ("1e999999", "1.000E+999999", "1.000E+999999"),
        ("1E-1000000", "1.000E-1000000", "1.000E-1000000"),
        ("1E-7", "1.000E-7", "1.000E-7"),
        ("1E+11", "100000000000.00", "100000000000.00"),
        ("1" * 41, "1.111E+40", "1.111E+40"),
        ("0." + "1" * 40, "1.111E-1", "1.111E-1"),
    ],
)
def test_AC_testing_benchmarks_13_a_finite_delta_of_any_size_is_recorded_and_short(
    raw: str, box: str, card: str
) -> None:
    run = [_case("case_2", "FAIL", equation_delta=raw)]

    page = generate_html_report(_report(run))

    assert _stat_value(page, "Largest Balance Delta") == f"{box} SGD"
    assert _stat_note(page, "Largest Balance Delta") == "recorded by 1 of 1 case"
    assert f">{card} SGD Regression<" in _card(page, "case_2")
    assert extract_summary_data(_report(run))["max_equation_delta"] == box
    assert len(page) < 100_000


def test_AC_testing_benchmarks_13_a_case_table_keeps_the_sign_of_a_recorded_delta() -> (
    None
):
    page = generate_html_report(
        _report([_case("case_2", "FAIL", equation_delta="-0.37")])
    )

    assert "-0.37 SGD Regression" in _card(page, "case_2")
    assert _stat_value(page, "Largest Balance Delta") == "0.37 SGD"


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


@pytest.mark.parametrize(
    "value",
    ["abc", None, float("nan"), float("inf"), -3, "NaN", True, 10**400, 1e12, [], {}],
)
def test_AC_testing_benchmarks_13_a_duration_that_is_not_valid_shows_n_a(
    value: Any,
) -> None:
    case = _case("case_2", equation_delta="0.00")
    case["duration_seconds"] = value
    run = _report([case])

    page = generate_html_report(run)

    assert "⏱️ n/a" in page
    assert _stat_value(page, "Total Duration") == "n/a"
    # The summary records no duration. It does not claim a run time of 0 s.
    assert extract_summary_data(run)["duration_seconds"] is None


def test_AC_testing_benchmarks_13_the_durations_of_the_cases_add_up() -> None:
    first, second, broken = (_case("case_1"), _case("case_2"), _case("case_3"))
    first["duration_seconds"] = 1.5
    second["duration_seconds"] = "2.25"
    broken["duration_seconds"] = "abc"
    run = _report([first, second, broken])

    page = generate_html_report(run)

    assert _stat_value(page, "Total Duration") == "3.75s"
    assert "⏱️ 1.50s" in _card(page, "case_1")
    assert "⏱️ 2.25s" in _card(page, "case_2")
    assert "⏱️ n/a" in _card(page, "case_3")
    assert extract_summary_data(run)["duration_seconds"] == 3.75


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


@pytest.mark.parametrize("total", ["abc", None, True, -1, 10**400, float("inf"), 7.9])
def test_AC_testing_benchmarks_13_a_summary_count_that_is_no_count_gives_way_to_the_results(
    total: Any,
) -> None:
    run = _report([_case("case_1", equation_delta="0.00")])
    run["summary"]["total"] = total

    page = generate_html_report(run, baseline_data=_report(FULL_RUN))

    assert "1/1" in page
    assert "(100%)" in page


def test_AC_testing_benchmarks_13_a_recorded_total_of_zero_gives_no_pass_rate() -> None:
    run = _report([_case("case_1", equation_delta="0.00")])
    run["summary"]["total"] = 0

    page = generate_html_report(run, baseline_data=_report(FULL_RUN))

    assert "1/0" in page
    assert "(n/a)" in page
    assert "(100%)" not in page


def test_AC_testing_benchmarks_13_the_baseline_card_states_the_time_difference() -> (
    None
):
    def timed(seconds: float) -> dict[str, Any]:
        case = _case("case_2", equation_delta="0.00")
        case["duration_seconds"] = seconds
        return _report([case])

    slower = generate_html_report(timed(10.0), baseline_data=timed(3.0))
    assert '10.00s <small class="metric-diff-worse">(+7.00s)' in slower

    faster = generate_html_report(timed(3.0), baseline_data=timed(20.0))
    assert '3.00s <small class="metric-diff-better">(-17.00s)' in faster

    close = generate_html_report(timed(10.0), baseline_data=timed(7.0))
    assert '10.00s <small class="metric-diff-neutral">(+3.00s)' in close


@pytest.mark.parametrize("recorded", ["abc", None, float("nan"), -5, [], True])
def test_AC_testing_benchmarks_13_a_baseline_time_that_is_not_valid_falls_back_to_its_cases(
    recorded: Any,
) -> None:
    baseline = _report([_case("case_2", equation_delta="0.00")])
    baseline["summary"]["total_duration_seconds"] = recorded

    page = generate_html_report(
        _report([_case("case_2", equation_delta="0.00")]), baseline_data=baseline
    )

    assert "(0.00s)" in page
    assert not re.search(r"\bnans?\b", page, flags=re.IGNORECASE)


def test_AC_testing_benchmarks_13_a_baseline_time_that_is_recorded_wins_over_its_cases() -> (
    None
):
    baseline = _report([_case("case_2", equation_delta="0.00")])
    baseline["summary"]["total_duration_seconds"] = 0.5

    page = generate_html_report(
        _report([_case("case_2", equation_delta="0.00")]), baseline_data=baseline
    )

    assert "(+0.50s)" in page


# ------------------------------------------------------------- header text


def test_AC_testing_benchmarks_13_the_header_says_all_passed_only_when_every_case_passed() -> (
    None
):
    page = generate_html_report(_report(FULL_RUN))

    assert '<span class="badge badge-pass">ALL 6 SCENARIOS PASSED</span>' in page


def test_AC_testing_benchmarks_13_the_header_counts_the_passed_cases_of_a_failed_run() -> (
    None
):
    page = generate_html_report(_report([_case("case_1"), _case("case_2", "FAIL")]))

    assert '<span class="badge badge-fail">1 OF 2 SCENARIOS PASSED</span>' in page
    assert "ALL 2 SCENARIOS PASSED" not in page


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

    for n, key in enumerate(keys):
        assert f"<s{n}>" not in card
        # A figure prints a number or n/a. A text field and a case without a
        # table print their escaped text.
        assert (f"&lt;s{n}&gt;" in card) is (case_id == "other" or key in TEXT_KEYS)


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
    # The hero link and the two links of the table row read the same report_url.
    assert dashboard.count('href="#"') == 3
    assert "v1/report.html" not in dashboard


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


def _hero_badge(dashboard: str) -> tuple[str, str]:
    """The class and the text of the badge in the hero banner."""
    found = re.search(
        r'<div class="card hero-banner">\s*<div>\s*<span class="badge (\S+)">([^<]*)</span>',
        dashboard,
    )
    assert found, "the hero banner has no badge"
    return found.group(1), found.group(2)


@pytest.mark.parametrize(
    ("status", "expected"),
    [("PASS", ("badge-pass", "PASS")), ("FAIL", ("badge-fail", "FAIL"))],
)
def test_AC_testing_benchmarks_14_the_hero_badge_follows_the_status_of_the_latest_run(
    status: str, expected: tuple[str, str]
) -> None:
    older = _run(
        "v0", "2026-08-01T00:00:00", status="FAIL" if status == "PASS" else "PASS"
    )
    latest = _run("v1", "2026-09-01T00:00:00", status=status)

    assert _hero_badge(generate_index_dashboard([older, latest])) == expected


def test_AC_testing_benchmarks_14_a_count_beyond_the_integer_text_limit_is_n_a() -> (
    None
):
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", cases_total=10**5000)]
    )

    assert _stat_value(dashboard, "Latest Pass Rate") == "7/n/a (n/a)"


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

    assert "0.00s" not in dashboard
    assert dashboard.count("<td>n/a</td>") == 2
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
    assert "&lt;b&gt;X&lt;/b&gt;" in dashboard
    assert (
        "The status of the latest run is unknown. n/a of n/a cases passed" in dashboard
    )


def test_AC_testing_benchmarks_14_the_latest_run_is_the_newest_by_run_time() -> None:
    runs = [
        _run("v2", "2026-09-02T00:00:00", status="FAIL", cases_passed=1),
        _run("v1", "2026-09-01T00:00:00"),
    ]

    dashboard = generate_index_dashboard(runs)

    assert "Latest Deployed Release: v2" in dashboard
    assert _stat_value(dashboard, "Latest Pass Rate") == "1/7 (14%)"


# ---------------------------------------------------- placeholders and structure

HOSTILE = (
    '"><img src=x onerror=alert(1)><script>alert(2)</script>'
    "{{TABLE_ROWS}}{{SCENARIOS_HTML}}{{DIFF_HTML}}{{VERSION}}"
)
DELTA_KEYS = {"equation_delta", "equation_delta_sgd", "equation_delta_usd"}
# The detail keys that hold text. Every other key of a case table holds a figure.
TEXT_KEYS = {"symbols", "appraisal_source", "tax_ecosystem_status"}
# Every detail key that a case table reads. A test fills each key with the same text.
CASE_DETAIL_KEYS = {
    "case_1": [
        "m1_closing_balance",
        "m2_closing_balance",
        "m3_closing_balance",
        "m4_closing_balance",
        "q1_net_income",
        "cumulative_net_income",
        "equation_delta",
    ],
    "case_2": [
        "household_husband_cash",
        "household_wife_cash",
        "total_income",
        "total_expenses",
        "net_income",
        "ending_cash",
        "equation_delta",
    ],
    "case_3": [
        "card_spend_recorded",
        "bank_repayment",
        "ending_bank_cash",
        "credit_card_liability_cleared",
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
    "other": ["anything", "equation_delta"],
}


def _event_handlers(dom: _Dom) -> list[tuple[str, str]]:
    return [
        (tag, name) for tag, name, _ in dom.attributes if name.lower().startswith("on")
    ]


def _links(dom: _Dom) -> list[str]:
    return [value or "" for _, name, value in dom.attributes if name == "href"]


def _text_report(case_id: str, status: str, text: str) -> dict[str, Any]:
    """A report whose every string field holds `text`."""
    case = _case(
        case_id if case_id != "other" else text,
        status,
        **{key: text for key in CASE_DETAIL_KEYS[case_id]},
    )
    case["case_name"] = text
    case["error_message"] = text
    run = _report([case])
    run["version_ref"] = text
    run["app_url"] = text
    run["run_at"] = text
    return run


@pytest.mark.parametrize("status", ["PASS", "FAIL"])
@pytest.mark.parametrize("case_id", sorted(CASE_DETAIL_KEYS))
def test_AC_testing_benchmarks_13_text_from_a_run_never_adds_markup_to_the_report(
    case_id: str, status: str
) -> None:
    benign = _dom(
        generate_html_report(
            _text_report(case_id, status, "x"),
            baseline_data=_text_report(case_id, status, "x"),
        )
    )
    hostile = _dom(
        generate_html_report(
            _text_report(case_id, status, HOSTILE),
            baseline_data=_text_report(case_id, status, HOSTILE),
        )
    )

    assert hostile.tags == benign.tags
    assert _event_handlers(hostile) == []
    # The hostile text reaches the page as text, once for each text field that a
    # table prints. A figure that is no number prints n/a.
    printed_keys = [
        k
        for k in CASE_DETAIL_KEYS[case_id]
        if (k in TEXT_KEYS and (status == "PASS" or k != "appraisal_source"))
        or (case_id == "other" and k not in DELTA_KEYS)
    ]
    assert sum(HOSTILE in node for node in hostile.text) >= len(printed_keys) + 3


def test_AC_testing_benchmarks_13_run_text_with_a_placeholder_is_not_filled_again() -> (
    None
):
    run = _report([_case("case_2", equation_delta="0.00")])
    run["version_ref"] = "{{SCENARIOS_HTML}} onmouseover=alert(1) x"
    run["results"][0]["case_name"] = "{{DIFF_HTML}}"
    run["results"][0]["error_message"] = "{{INVARIANTS_ROWS}}"

    page = generate_html_report(run)
    dom = _dom(page)
    text = " ".join(dom.text)

    assert _event_handlers(dom) == []
    assert page.count('<table class="invariants-table">') == 1
    assert page.count('<div class="card scenario-card">') == 1
    assert "{{SCENARIOS_HTML}} onmouseover=alert(1) x" in text
    assert "{{DIFF_HTML}}" in text
    assert "{{INVARIANTS_ROWS}}" in text


def test_AC_testing_benchmarks_14_a_version_with_a_placeholder_adds_no_attribute_to_the_dashboard() -> (
    None
):
    version = "{{TABLE_ROWS}} onmouseover=alert(1) x"

    dashboard = generate_index_dashboard([_run(version, "2026-09-01T00:00:00")])
    dom = _dom(dashboard)

    assert _event_handlers(dom) == []
    assert _links(dom).count(f"{version}/report.html") == 3
    assert dashboard.count('class="btn-latest"') == 1
    assert dashboard.count('class="version-link"') == 1


def test_AC_testing_benchmarks_14_a_template_placeholder_is_filled_in_one_pass() -> (
    None
):
    fill = benchmark_html_reporter._fill

    assert fill("a {{X}} b {{Y}}", {"X": "{{Y}}", "Y": "no"}) == "a {{Y}} b no"
    with pytest.raises(KeyError):
        fill("a {{MISSING}}", {})


def _text_run(text: str, number: Any) -> dict[str, Any]:
    return {
        "version": text,
        "run_at": text,
        "status": text,
        "app_url": text,
        "report_url": text,
        "cases_total": number,
        "cases_passed": number,
        "duration_seconds": number,
        "max_equation_delta": number,
        "max_equation_delta_currency": text,
    }


@pytest.mark.parametrize(
    ("benign_number", "hostile_number"),
    [(7, 7), ("abc", HOSTILE)],
    ids=["valid-numbers", "hostile-numbers"],
)
def test_AC_testing_benchmarks_14_text_from_a_run_never_adds_markup_to_the_dashboard(
    benign_number: Any, hostile_number: Any
) -> None:
    # A number field with hostile text is no number. The benign run of that case
    # holds another value that is no number, so both runs draw no trend point.
    benign = _dom(generate_index_dashboard([_text_run("x", benign_number)]))
    hostile_page = generate_index_dashboard([_text_run(HOSTILE, hostile_number)])
    hostile = _dom(hostile_page)

    assert hostile.tags == benign.tags
    assert _event_handlers(hostile) == []
    assert {tag for tag, _ in hostile.tags} == {tag for tag, _ in benign.tags}
    for link in _links(hostile):
        assert urlsplit(link).scheme in ("", "http", "https")
    # The text reaches the page as text: the version, the status, the environment and the label.
    assert sum(HOSTILE in node for node in hostile.text) >= 4


@pytest.mark.parametrize(
    "page",
    [
        generate_html_report(_report(FULL_RUN), baseline_data=_report(FULL_RUN)),
        generate_html_report(_report([])),
        generate_index_dashboard([]),
        generate_index_dashboard([{"version": "v1", "status": "PASS"}]),
    ],
    ids=["full-report", "empty-report", "empty-dashboard", "one-run-dashboard"],
)
def test_AC_testing_benchmarks_14_a_page_keeps_no_unfilled_placeholder(
    page: str,
) -> None:
    assert re.findall(r"\{\{[A-Z_]+\}\}", page) == []


# ------------------------------------------------------------- bad numbers

BAD_NUMBERS = [
    float("inf"),
    float("-inf"),
    float("nan"),
    10**400,
    -1,
    7.9,
    "abc",
    "NaN",
    "Infinity",
    None,
    True,
    [],
    {},
    1e30,
]
PYTHON_WORDS = re.compile(r"\b(None|nan|inf|Infinity|NaN|True|False)\b")


def _without_telemetry(page: str) -> str:
    return re.sub(r'<pre class="raw-json">.*?</pre>', "", page, flags=re.DOTALL)


@pytest.mark.parametrize("bad", BAD_NUMBERS, ids=repr)
def test_AC_testing_benchmarks_13_a_value_that_is_no_number_never_crashes_the_report(
    bad: Any,
) -> None:
    run = _report(FULL_RUN)
    run["summary"].update(total=bad, passed=bad, skipped=bad, failed=bad)
    for case in run["results"]:
        case["duration_seconds"] = bad
        case["details"]["equation_delta"] = bad
    baseline = _report(FULL_RUN)
    baseline["summary"]["total_duration_seconds"] = bad

    page = generate_html_report(run, baseline_data=baseline)

    assert PYTHON_WORDS.findall(_without_telemetry(page)) == []
    assert extract_summary_data(run)["cases_total"] == 6


@pytest.mark.parametrize("bad", BAD_NUMBERS, ids=repr)
def test_AC_testing_benchmarks_14_a_value_that_is_no_number_never_crashes_the_dashboard(
    bad: Any,
) -> None:
    run = _run(
        "v1",
        "2026-09-01T00:00:00",
        cases_total=bad,
        cases_passed=bad,
        duration_seconds=bad,
        max_equation_delta=bad,
    )

    dashboard = generate_index_dashboard([run, _run("v0", "2026-08-01T00:00:00")])

    assert PYTHON_WORDS.findall(dashboard) == []


@pytest.mark.parametrize(
    ("passed", "total", "rate"),
    [
        (7.0, "7", "7/7 (100%)"),
        ("5", 7, "5/7 (71%)"),
        (1, 8, "1/8 (13%)"),
        (7.9, 8, "n/a/8 (n/a)"),
        (14, 7, "14/7 (n/a)"),
        (-2, 7, "n/a/7 (n/a)"),
        (3, 0, "3/0 (n/a)"),
        (10**9, 10**9, "1000000000/1000000000 (100%)"),
        (10**9 + 1, 10**9 + 1, "n/a/n/a (n/a)"),
    ],
)
def test_AC_testing_benchmarks_14_the_pass_rate_follows_counts_that_are_whole_numbers(
    passed: Any, total: Any, rate: str
) -> None:
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", cases_passed=passed, cases_total=total)]
    )

    assert _stat_value(dashboard, "Latest Pass Rate") == rate


@pytest.mark.parametrize(
    "results",
    [None, "x", 5, [None, 5, "x", []], {"case_1": 1}],
    ids=repr,
)
def test_AC_testing_benchmarks_13_results_that_are_no_list_of_cases_give_an_empty_report(
    results: Any,
) -> None:
    run = _report(FULL_RUN)
    run["results"] = results

    page = generate_html_report(run, baseline_data=run)

    assert set(_invariant_cells(page).values()) == {"NOT RUN"}
    assert extract_summary_data(run)["cases_total"] == 6


@pytest.mark.parametrize("summary", [None, "x", 5, []], ids=repr)
def test_AC_testing_benchmarks_13_a_summary_that_is_no_dict_gives_counts_of_the_results(
    summary: Any,
) -> None:
    run = _report(FULL_RUN)
    run["summary"] = summary

    page = generate_html_report(run, baseline_data=run)
    data = extract_summary_data(run)

    assert _stat_value(page, "Scenarios Passed") == "6 / 6"
    # Without a recorded summary the status is unknown. It is not FAIL.
    assert (data["cases_total"], data["cases_passed"], data["status"]) == (
        6,
        6,
        "UNKNOWN",
    )
    assert _header_badge(page) == ("badge-fail", "6 OF 6 SCENARIOS PASSED")
    dashboard = generate_index_dashboard([data])
    assert "The status of the latest run is unknown. 6 of 6 cases passed" in dashboard
    assert "did not pass" not in dashboard


@pytest.mark.parametrize("details", [None, "x", 5, ["a"]], ids=repr)
def test_AC_testing_benchmarks_13_details_that_are_no_dict_count_as_not_recorded(
    details: Any,
) -> None:
    case = _case("case_2")
    case["details"] = details

    page = generate_html_report(_report([case]))

    assert "Balanced (Δ not recorded)" in _card(page, "case_2")
    assert _stat_value(page, "Largest Balance Delta") == "n/a"


# ----------------------------------------------------------- missing values


def test_AC_testing_benchmarks_13_a_report_without_identity_fields_shows_n_a_and_not_a_default() -> (
    None
):
    run = _report(FULL_RUN)
    for key in ("version_ref", "app_url", "run_at"):
        del run[key]

    dom = _dom(generate_html_report(run))
    data = extract_summary_data(run)

    assert "Financial Scenario Benchmark: n/a" in dom.text
    assert dom.text[dom.text.index("Target:") + 1] == "n/a"
    assert dom.text[dom.text.index("• Executed:") + 1] == "n/a"
    assert "staging" not in " ".join(dom.text).lower()
    # The summary records no version and no report link. The dashboard links to "#".
    assert (data["version"], data["run_at"], data["app_url"]) == (None, "", "")
    assert data["report_url"] is None
    dashboard = _dom(generate_index_dashboard([data]))
    assert _links(dashboard) == ["#", "#", "#"]
    assert "Latest Deployed Release: n/a" in dashboard.text


def test_AC_testing_benchmarks_14_a_run_without_a_time_is_older_than_a_run_with_one() -> (
    None
):
    undated = _run("v-undated", "", status="FAIL", cases_passed=1)
    del undated["run_at"]

    dashboard = generate_index_dashboard(
        [undated, _run("v-dated", "2026-09-01T00:00:00")]
    )

    assert "Latest Deployed Release: v-dated" in dashboard
    assert [("v-undated" in row) for row in _history_rows(dashboard)] == [False, True]
    assert "<td>n/a</td>" in _history_rows(dashboard)[1]


def test_AC_testing_benchmarks_14_a_run_with_no_identity_or_counts_shows_n_a_in_every_cell() -> (
    None
):
    dashboard = generate_index_dashboard([{}])
    cells = re.findall(r"<td>(.*?)</td>", _history_rows(dashboard)[0], flags=re.DOTALL)
    text = [re.sub(r"<[^>]+>", "", cell).strip() for cell in cells]

    assert text == [
        "n/a",
        "UNKNOWN",
        "n/a",
        "n/a",
        "n/a / n/a",
        "n/a",
        "n/a",
        "View Report →",
    ]
    assert "Latest Deployed Release: n/a" in dashboard
    assert (
        "The status of the latest run is unknown. n/a of n/a cases passed" in dashboard
    )


@pytest.mark.parametrize("success", ["false", "no", "yes", 1, 0, None, "True"])
def test_AC_testing_benchmarks_13_only_a_true_success_flag_marks_a_run_as_passed(
    success: Any,
) -> None:
    run = _report(FULL_RUN)
    run["summary"]["success"] = success

    page = generate_html_report(run)

    assert extract_summary_data(run)["status"] == "FAIL"
    assert '<span class="badge badge-fail">' in page
    assert '<span class="badge badge-pass">ALL' not in page


# --------------------------------------------------------- badges and classes


def test_AC_testing_benchmarks_13_the_badge_classes_follow_the_status_of_the_run_and_the_cases() -> (
    None
):
    page = generate_html_report(
        _report(
            [
                _case("case_1", equation_delta="0.00"),
                _case("case_2", "FAIL"),
                _case("case_3", "SKIPPED"),
                {"case_id": "case_4", "case_name": "x", "details": {}},
            ]
        )
    )

    def badge(case_id: str) -> str:
        match = re.search(
            r'<span class="badge (badge-\w+)">([^<]*)</span>\s*</div>\s*</div>',
            _card(page, case_id) + "</div></div>",
        )
        assert match, case_id
        return f"{match.group(1)} {match.group(2)}"

    assert badge("case_1") == "badge-pass PASS"
    assert badge("case_2") == "badge-fail FAIL"
    assert badge("case_3") == "badge-fail SKIPPED"
    assert badge("case_4") == "badge-fail UNKNOWN"
    assert "No figures recorded" in _card(page, "case_4")


def test_AC_testing_benchmarks_14_the_badge_classes_follow_the_status_of_the_runs() -> (
    None
):
    runs = [
        _run("v3", "2026-09-03T00:00:00", status="FAIL"),
        _run("v2", "2026-09-02T00:00:00", status="PASS"),
        _run("v1", "2026-09-01T00:00:00", status="other"),
    ]

    dashboard = generate_index_dashboard(runs)

    badges = re.findall(r'<span class="badge (badge-\w+)">([^<]*)</span>', dashboard)
    assert badges == [
        ("badge-fail", "FAIL"),
        ("badge-fail", "FAIL"),
        ("badge-pass", "PASS"),
        ("badge-fail", "other"),
    ]


# ------------------------------------------------------------- trendline


def _trend_points(dashboard: str) -> list[tuple[float, float]]:
    raw = re.search(r'<polyline[^>]* points="([^"]*)"', _trend(dashboard))
    assert raw
    return [
        (float(x), float(y))
        for x, y in (pair.split(",") for pair in raw.group(1).split())
    ]


def test_AC_testing_benchmarks_14_a_longer_run_draws_a_higher_point() -> None:
    runs = [
        _run("v1", "2026-09-01T00:00:00", duration_seconds=10.0),
        _run("v2", "2026-09-02T00:00:00", duration_seconds=20.0),
    ]

    points = _trend_points(generate_index_dashboard(runs))

    assert points == [(40.0, 80.0), (660.0, 40.0)]


def test_AC_testing_benchmarks_14_one_run_draws_one_point_in_the_middle() -> None:
    points = _trend_points(
        generate_index_dashboard([_run("v1", "2026-09-01T00:00:00")])
    )

    assert points == [(350.0, 40.0)]


def test_AC_testing_benchmarks_14_a_run_without_a_valid_duration_is_labelled_n_a() -> (
    None
):
    runs = [
        _run("v1", "2026-09-01T00:00:00", duration_seconds="slow"),
        _run("v2", "2026-09-02T00:00:00", duration_seconds=4.0),
    ]

    trend = _trend(generate_index_dashboard(runs))

    assert ">n/a</text>" in trend
    assert ">4.0s</text>" in trend


# ----------------------------------------------------------- summary fields


def test_AC_testing_benchmarks_13_the_summary_names_the_report_of_its_version() -> None:
    data = extract_summary_data(_report(FULL_RUN))

    assert data["version"] == "v-test"
    assert data["report_url"] == "v-test/report.html"
    assert data["run_at"] == "2026-10-10T00:00:00+00:00"
    assert data["app_url"] == "https://staging.example.test"
    assert data["status"] == "PASS"


# --------------------------------------------------------- visible text

EMPTY_DASHBOARD_TEXT = [
    "Financial Reporting Benchmark Observatory",
    "📊 Financial Reporting Benchmark Observatory",
    "Continuous Accounting Invariant Tracking across Tagged Releases & Deployments",
    "UNKNOWN",
    "Latest Deployed Release: n/a",
    "The history holds no run yet",
    "Total Releases Tracked",
    "0",
    "Latest Pass Rate",
    "n/a (n/a)",
    "Latest Latency",
    "n/a",
    "Largest Balance Delta",
    "n/a",
    "📈 Historical Latency Trendline (Seconds)",
    "📜 Historical Benchmark Runs",
    "Version",
    "Status",
    "Execution Date",
    "Environment",
    "Pass Rate",
    "Duration",
    "Eq Delta",
    "Action",
    "Finance Report Benchmark Suite • Automated Continuous Quality Observatory",
]
ONE_RUN_DASHBOARD_TEXT = [
    "Financial Reporting Benchmark Observatory",
    "📊 Financial Reporting Benchmark Observatory",
    "Continuous Accounting Invariant Tracking across Tagged Releases & Deployments",
    "PASS",
    "Latest Deployed Release: v1",
    "7 of 7 cases passed",
    "View Latest Full Report →",
    "Total Releases Tracked",
    "1",
    "Latest Pass Rate",
    "7/7 (100%)",
    "Latest Latency",
    "10.00s",
    "Largest Balance Delta",
    "0.00 SGD",
    "📈 Historical Latency Trendline (Seconds)",
    "10.0s",
    "v1",
    "📜 Historical Benchmark Runs",
    "Version",
    "Status",
    "Execution Date",
    "Environment",
    "Pass Rate",
    "Duration",
    "Eq Delta",
    "Action",
    "v1",
    "PASS",
    "2026-09-01 00:00:00",
    "https://staging.example.test",
    "7 / 7",
    "10.00s",
    "0.00 SGD",
    "View Report →",
    "Finance Report Benchmark Suite • Automated Continuous Quality Observatory",
]
EMPTY_REPORT_TEXT = [
    "Financial Reporting Benchmark: n/a",
    "← All Benchmark Runs",
    "Financial Scenario Benchmark: n/a",
    "Target:",
    "n/a",
    "• Executed:",
    "n/a",
    "0 OF 0 SCENARIOS PASSED",
    "Scenarios Passed",
    "0 / 0",
    "Total Duration",
    "n/a",
    "Largest Balance Delta",
    "n/a",
    "recorded by 0 of 0 cases",
    "Cases Not Passed",
    "0",
    "🛡️ Core Financial Invariants (The Proof)",
    "Fundamental Financial Invariant",
    "Mathematical Formalism",
    "Observed Truth",
    "Adjudication",
    "Balance Sheet Identity",
    "Assets ≡ Liabilities + Equity + Net Income",
    "No delta recorded by any of the 3 cases",
    "NOT RUN",
    "Temporal Multi-Period Rollforward",
    "Month_{n+1} Opening Cash ≡ Month_n Closing Cash",
    "Closing balances of months 1 to 4: n/a, n/a, n/a, n/a",
    "NOT RUN",
    "Credit Card Liability Clearance (No Double Counting)",
    "Card spend recorded once; repayment moves cash and liability only",
    "Card spend n/a, bank repayment n/a, net income n/a",
    "NOT RUN",
    "Retained Earnings Articulation",
    "Closing Equity = Opening Equity + Net Income",
    "Cumulative net income n/a",
    "NOT RUN",
    "🧪 Evaluated Scenario Details",
    "Finance-Report System Benchmark Suite • Autonomous Zero-Raster-Image Report",
    "Generated from the results that the run recorded",
]


def test_AC_testing_benchmarks_14_the_empty_dashboard_holds_only_this_text() -> None:
    """A new fixed sentence in the template fails this test. Review it before you accept it."""
    assert _dom(generate_index_dashboard([])).text == EMPTY_DASHBOARD_TEXT


def test_AC_testing_benchmarks_14_a_dashboard_of_one_run_holds_only_this_text() -> None:
    run = _run("v1", "2026-09-01T00:00:00", app_url="https://staging.example.test")

    assert _dom(generate_index_dashboard([run])).text == ONE_RUN_DASHBOARD_TEXT


def test_AC_testing_benchmarks_13_a_report_without_cases_holds_only_this_text() -> None:
    """A new fixed sentence in the template fails this test. Review it before you accept it."""
    page = generate_html_report({"summary": {}, "results": []})

    assert _dom(page).text == EMPTY_REPORT_TEXT


# ----------------------------------------------------- boundaries and cell maps


def test_AC_testing_benchmarks_13_the_largest_delta_can_be_the_sgd_delta_of_case_4() -> (
    None
):
    run = [_case("case_4", equation_delta_sgd="0.60", equation_delta_usd="0.30")]

    page = generate_html_report(_report(run))
    data = extract_summary_data(_report(run))

    assert _stat_value(page, "Largest Balance Delta") == "0.60 SGD"
    assert (data["max_equation_delta"], data["max_equation_delta_currency"]) == (
        "0.60",
        "SGD",
    )


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        ("1E-6", "0.000001"),
        ("9.99E-7", "9.990E-7"),
        ("999999999999.99", "999999999999.99"),
        ("1E+12", "1.000E+12"),
        ("0." + "1" * 28, "0." + "1" * 28),
        ("0." + "1" * 29, "1.111E-1"),
        ("-0", "0.00"),
        (" 0.25 ", "0.25"),
        ("0.1", "0.10"),
        ("12", "12.00"),
    ],
)
def test_AC_testing_benchmarks_13_a_delta_at_the_edge_of_a_range_prints_as_documented(
    raw: str, text: str
) -> None:
    page = generate_html_report(_report([_case("case_2", equation_delta=raw)]))

    assert _stat_value(page, "Largest Balance Delta") == f"{text} SGD"


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        (0, "0"),
        (0.0, "0"),
        ("0", "0"),
        ("1e9", "1000000000"),
        ("1000000000", "1000000000"),
        (1000000000.0, "1000000000"),
        ("1000000001", "n/a"),
        (1000000001.0, "n/a"),
        ("1E+10", "n/a"),
        ("1E+999999999", "n/a"),
    ],
)
def test_AC_testing_benchmarks_14_a_count_from_zero_to_the_limit_is_a_count(
    raw: Any, shown: str
) -> None:
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", cases_passed=raw, cases_total=raw)]
    )

    assert f"<td>{shown} / {shown}</td>" in _history_rows(dashboard)[0]


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [(0, "0.00s"), (0.004, "0.00s"), (1e9, "1000000000.00s"), (1e9 + 1000, "n/a")],
)
def test_AC_testing_benchmarks_13_a_duration_from_zero_to_the_limit_is_a_duration(
    seconds: float, shown: str
) -> None:
    case = _case("case_2", equation_delta="0.00")
    case["duration_seconds"] = seconds

    page = generate_html_report(_report([case]))

    assert f"⏱️ {shown}" in page
    assert _stat_value(page, "Total Duration") == shown


def test_AC_testing_benchmarks_13_the_rollforward_row_lists_the_four_closing_balances_in_order() -> (
    None
):
    recorded = {f"m{n}_closing_balance": f"{n}00.00" for n in (1, 2, 3, 4)}
    fallback = {f"month_{n}_ending_balance": f"{n}00.00" for n in (1, 2, 3, 4)}

    for details in (recorded, fallback):
        rows = _invariant_rows(
            generate_html_report(_report([_case("case_1", **details)]))
        )
        assert (
            rows["Temporal Multi-Period Rollforward"][0]
            == "Closing balances of months 1 to 4: 100.00, 200.00, 300.00, 400.00"
        )


def _distinct_details(case_id: str) -> dict[str, str]:
    return {
        key: "0.0" + str(n + 1) if key in DELTA_KEYS else f"{1000 + 111 * (n + 1)}.00"
        for n, key in enumerate(CASE_DETAIL_KEYS[case_id])
    }


@pytest.mark.parametrize("status", ["PASS", "FAIL"])
@pytest.mark.parametrize(
    "case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"]
)
def test_AC_testing_benchmarks_13_each_key_of_a_case_prints_in_its_own_table_cell(
    case_id: str, status: str
) -> None:
    details = _distinct_details(case_id)
    # Case 5 prints its appraisal source inside the verdict of a passed case only.
    shown = {
        key: value
        for key, value in details.items()
        if not (case_id == "case_5" and status == "FAIL" and key == "appraisal_source")
    }

    card = _card(
        generate_html_report(_report([_case(case_id, status, **details)])), case_id
    )
    cells = re.findall(r"<td>(.*?)</td>", card, flags=re.DOTALL)

    for key, value in shown.items():
        assert any(value in cell for cell in cells), (key, value)
    # No two keys share one cell: each table row prints its own key.
    for key, value in shown.items():
        holders = [cell for cell in cells if value in cell and "badge" not in cell]
        assert len(holders) == 1, (key, value, holders)


@pytest.mark.parametrize(
    ("case_id", "fallback", "primary"),
    [
        ("case_1", "month_1_ending_balance", "m1_closing_balance"),
        ("case_1", "month_2_ending_balance", "m2_closing_balance"),
        ("case_1", "month_3_ending_balance", "m3_closing_balance"),
        ("case_1", "month_4_ending_balance", "m4_closing_balance"),
        ("case_2", "closing_balance", "ending_cash"),
        ("case_3", "total_assets", "ending_bank_cash"),
    ],
)
def test_AC_testing_benchmarks_13_a_table_falls_back_to_the_older_key_of_a_figure(
    case_id: str, fallback: str, primary: str
) -> None:
    page = generate_html_report(_report([_case(case_id, **{fallback: "7777.00"})]))
    assert "7777.00" in _card(page, case_id)

    both = generate_html_report(
        _report([_case(case_id, **{fallback: "7777.00", primary: "8888.00"})])
    )
    assert "8888.00" in _card(both, case_id)
    assert "7777.00" not in _card(both, case_id)


def test_AC_testing_benchmarks_13_the_rollforward_row_falls_back_to_the_older_balance_keys() -> (
    None
):
    run = [
        _case(
            "case_1",
            month_1_ending_balance="101.00",
            month_2_ending_balance="102.00",
            month_3_ending_balance="103.00",
            month_4_ending_balance="104.00",
        )
    ]
    rows = _invariant_rows(generate_html_report(_report(run)))

    assert (
        rows["Temporal Multi-Period Rollforward"][0]
        == "Closing balances of months 1 to 4: 101.00, 102.00, 103.00, 104.00"
    )


def test_AC_testing_benchmarks_13_a_passed_case_without_a_flow_mapping_covers_no_flow() -> (
    None
):
    run = _report([_case("case_x", equation_delta="0.00")])

    summary = extract_summary_data(run)

    assert summary["thirty_flows_coverage"] == "0/30"
    assert summary["domains_covered"] == 0
    assert generate_html_report(run)


def test_AC_testing_benchmarks_13_the_summary_rounds_the_total_duration_to_two_decimals() -> (
    None
):
    run = _report([_case("case_1"), _case("case_2")])
    run["results"][0]["duration_seconds"] = 1.2345
    run["results"][1]["duration_seconds"] = 2.0

    assert extract_summary_data(run)["duration_seconds"] == 3.23


@pytest.mark.parametrize(
    ("case_id", "checks"),
    [
        ("case_1", 6),
        ("case_2", 6),
        ("case_3", 4),
        ("case_4", 4),
        ("case_5", 5),
        ("case_6", 5),
    ],
)
def test_AC_testing_benchmarks_13_a_passed_card_shows_only_check_marks_and_a_failed_card_only_crosses(
    case_id: str, checks: int
) -> None:
    details = _distinct_details(case_id)

    passed = _card(generate_html_report(_report([_case(case_id, **details)])), case_id)
    failed = _card(
        generate_html_report(_report([_case(case_id, "FAIL", **details)])), case_id
    )

    assert (passed.count("✅"), passed.count("❌")) == (checks, 0)
    # The failed card of case 6 adds one cross to its equation badge.
    assert (failed.count("✅"), failed.count("❌")) == (
        0,
        checks + (1 if case_id == "case_6" else 0),
    )


def test_AC_testing_benchmarks_13_the_badges_of_case_3_and_case_6_follow_the_status() -> (
    None
):
    passed = generate_html_report(
        _report(
            [
                _case("case_3", equation_delta="0.00"),
                _case("case_6", equation_delta="0.00"),
            ]
        )
    )
    failed = generate_html_report(
        _report(
            [
                _case("case_3", "FAIL", net_income="-1200.00", equation_delta="0.50"),
                _case("case_6", "FAIL", equation_delta="0.50"),
            ]
        )
    )
    # A recorded zero proves no fault. A failed case gets a neutral badge for it.
    failed_with_zero = generate_html_report(
        _report(
            [
                _case("case_3", "FAIL", equation_delta="0.00"),
                _case("case_6", "FAIL", equation_delta="0.00"),
            ]
        )
    )

    assert (
        '<span class="badge badge-pass">Zero Double-Counting (Pure Liability Clearance)</span>'
        in _card(passed, "case_3")
    )
    assert '<span class="badge badge-fail">Unconfirmed</span>' in _card(
        failed, "case_3"
    )
    assert '<span class="badge badge-pass">0.00 SGD Balanced</span>' in _card(
        passed, "case_6"
    )
    assert '<span class="badge badge-fail">❌ Equation Broken</span>' in _card(
        failed, "case_6"
    )
    assert _case_rows(failed_with_zero, "case_3") == {
        "Credit Card Incurred Charges (Liability Incurrence)": (
            "n/a",
            "❌ Unconfirmed",
        ),
        "Bank Account Settlement Payment Outflow": ("n/a", "❌ Unconfirmed"),
        "Credit Card Liability Ending Balance": ("n/a", "❌ Unconfirmed"),
        "Ending Bank Liquid Cash Balance": ("n/a", "❌ Unconfirmed"),
        "P&L Double-Counting Prevention (Net Income)": (
            "n/a",
            "[badge-skip] Not recorded",
        ),
        "Balance Sheet Equation Delta": (
            "$0.00",
            "[badge-skip] No difference recorded",
        ),
    }
    assert _case_rows(failed_with_zero, "case_6")["Balance Sheet Equation Delta"] == (
        "$0.00",
        "[badge-skip] No difference recorded",
    )
    for page in (failed, failed_with_zero):
        assert "Contamination" not in page
    assert "Equation Broken" not in failed_with_zero


def test_AC_testing_benchmarks_13_the_header_shows_the_target_and_the_time_of_the_run() -> (
    None
):
    dom = _dom(generate_html_report(_report(FULL_RUN)))

    assert dom.text[dom.text.index("Target:") + 1] == "https://staging.example.test"
    assert dom.text[dom.text.index("• Executed:") + 1] == "2026-10-10T00:00:00+00:00"
    assert "Financial Scenario Benchmark: v-test" in dom.text


def test_AC_testing_benchmarks_13_the_summary_names_the_cases_that_passed_and_the_flows_they_cover() -> (
    None
):
    full = extract_summary_data(_report(FULL_RUN))
    assert (full["thirty_flows_coverage"], full["domains_covered"]) == ("30/30", 7)
    assert full["cases_failed"] == 0
    assert [
        full[key]
        for key in (
            "zero_pnl_contamination",
            "rollforward_balanced",
            "multicurrency_consolidated",
            "portfolio_holdings_verified",
            "overdraft_articulation_verified",
        )
    ] == [True] * 5

    partial = extract_summary_data(
        _report(
            [
                _case("case_2", equation_delta="0.00"),
                _case("case_3", "FAIL"),
                _case("case_4", "SKIPPED"),
            ]
        )
    )
    assert (partial["thirty_flows_coverage"], partial["domains_covered"]) == ("8/30", 4)
    assert (
        partial["cases_total"],
        partial["cases_passed"],
        partial["cases_failed"],
    ) == (
        3,
        1,
        1,
    )
    assert [
        partial[key]
        for key in (
            "zero_pnl_contamination",
            "rollforward_balanced",
            "multicurrency_consolidated",
            "portfolio_holdings_verified",
            "overdraft_articulation_verified",
        )
    ] == [False] * 5


def test_AC_testing_benchmarks_13_the_counts_come_from_the_results_without_a_summary() -> (
    None
):
    run = _report(
        [_case("case_1"), _case("case_2", "FAIL"), _case("case_3", "SKIPPED")]
    )
    del run["summary"]

    data = extract_summary_data(run)

    assert (data["cases_total"], data["cases_passed"], data["cases_failed"]) == (
        3,
        1,
        1,
    )
    assert "1 OF 3 SCENARIOS PASSED, 1 SKIPPED" in generate_html_report(run)


@pytest.mark.parametrize(
    ("current", "baseline", "css", "sign"),
    [
        (8.0, 3.0, "metric-diff-neutral", "+5.00s"),
        (8.01, 3.0, "metric-diff-worse", "+5.01s"),
        (3.0, 8.0, "metric-diff-neutral", "-5.00s"),
        (2.99, 8.0, "metric-diff-better", "-5.01s"),
        (3.0, 3.0, "metric-diff-neutral", "0.00s"),
    ],
)
def test_AC_testing_benchmarks_13_the_time_difference_changes_color_beyond_five_seconds(
    current: float, baseline: float, css: str, sign: str
) -> None:
    def timed(seconds: float) -> dict[str, Any]:
        case = _case("case_2", equation_delta="0.00")
        case["duration_seconds"] = seconds
        return _report([case])

    page = generate_html_report(timed(current), baseline_data=timed(baseline))

    assert f'<small class="{css}">({sign})</small>' in page


def test_AC_testing_benchmarks_13_the_baseline_card_marks_an_unrecorded_delta_as_neutral() -> (
    None
):
    page = generate_html_report(
        _report([_case("case_2")]), baseline_data=_report(FULL_RUN)
    )

    assert _baseline_class(page, "Max Equation Delta") == "metric-diff-neutral"
    assert "(not recorded)" in page
    assert _baseline_stat(page, "Max Equation Delta") == (
        "n/a",
        "metric-diff-neutral",
        "not recorded",
    )


# ------------------------------------------------------------ dashboard edges


def test_AC_testing_benchmarks_14_the_execution_date_shows_the_first_19_characters_of_the_time() -> (
    None
):
    dashboard = generate_index_dashboard([_run("v1", "2026-09-01T12:34:56.789+00:00")])

    assert "<td>2026-09-01 12:34:56</td>" in _history_rows(dashboard)[0]


def test_AC_testing_benchmarks_14_the_empty_dashboard_draws_no_trendline() -> None:
    assert "<svg" not in generate_index_dashboard([])


def test_AC_testing_benchmarks_14_the_trendline_scales_to_the_longest_run() -> None:
    short = _trend_points(
        generate_index_dashboard(
            [_run("v1", "2026-09-01T00:00:00", duration_seconds=0.5)]
        )
    )
    none = _trend_points(
        generate_index_dashboard(
            [_run("v1", "2026-09-01T00:00:00", duration_seconds=0)]
        )
    )

    assert short == [(350.0, 40.0)]
    assert none == [(350.0, 120.0)]


def test_AC_testing_benchmarks_14_the_trendline_spaces_its_points_evenly() -> None:
    runs = [
        _run("v1", "2026-09-01T00:00:00", duration_seconds=10.0),
        _run("v2", "2026-09-02T00:00:00", duration_seconds=20.0),
        _run("v3", "2026-09-03T00:00:00", duration_seconds=30.0),
    ]

    points = _trend_points(generate_index_dashboard(runs))

    assert points == [(40.0, 93.3), (350.0, 66.7), (660.0, 40.0)]


def test_AC_testing_benchmarks_14_the_trendline_puts_its_labels_above_and_below_the_points() -> (
    None
):
    trend = _trend(generate_index_dashboard([_run("v1", "2026-09-01T00:00:00")]))

    assert '<line x1="40" y1="120" x2="660" y2="120"' in trend
    assert '<text x="350.0" y="30.0"' in trend
    assert ">10.0s</text>" in trend
    assert '<text x="350.0" y="150"' in trend
    assert ">v1</text>" in trend


def test_AC_testing_benchmarks_14_the_hero_badge_of_a_passed_latest_run_is_green() -> (
    None
):
    runs = [
        _run("v2", "2026-09-02T00:00:00", status="PASS"),
        _run("v1", "2026-09-01T00:00:00", status="FAIL"),
    ]

    badges = re.findall(
        r'<span class="badge (badge-\w+)">([^<]*)</span>',
        generate_index_dashboard(runs),
    )

    assert badges[0] == ("badge-pass", "PASS")


# ------------------------------------------------- header claims (third audit)


def test_AC_testing_benchmarks_13_the_header_claims_all_passed_for_a_run_of_one_passed_case() -> (
    None
):
    run = _report([_case("case_2", equation_delta="0.00")])

    assert _header_badge(generate_html_report(run)) == (
        "badge-pass",
        "ALL 1 SCENARIOS PASSED",
    )
    assert extract_summary_data(run)["status"] == "PASS"


@pytest.mark.parametrize(
    ("summary", "statuses", "header"),
    [
        ({"success": True}, [], "0 OF 0 SCENARIOS PASSED"),
        (
            {"success": True, "total": 9, "passed": 5, "failed": 0, "skipped": 0},
            ["PASS"] * 6,
            "5 OF 9 SCENARIOS PASSED",
        ),
        (
            {"success": True, "total": 6, "passed": 6, "failed": 1, "skipped": 0},
            ["PASS"] * 6,
            "6 OF 6 SCENARIOS PASSED",
        ),
        (
            {"success": True, "total": 6, "passed": 6, "failed": 0, "skipped": 1},
            ["PASS"] * 6,
            "6 OF 6 SCENARIOS PASSED, 1 SKIPPED",
        ),
        (
            {"success": True, "total": 6, "passed": 6, "failed": 0, "skipped": 0},
            ["PASS"] * 5 + ["SKIPPED"],
            "6 OF 6 SCENARIOS PASSED",
        ),
        (
            {"success": True, "total": 2, "passed": 2, "failed": 0, "skipped": 0},
            ["PASS", "FAIL"],
            "2 OF 2 SCENARIOS PASSED",
        ),
    ],
    ids=[
        "no-case",
        "passed-below-total",
        "failed-count",
        "skipped-count",
        "skipped-record",
        "failed-record",
    ],
)
def test_AC_testing_benchmarks_13_the_header_claims_all_passed_only_when_every_shown_count_agrees(
    summary: dict[str, Any], statuses: list[str], header: str
) -> None:
    run = {
        "version_ref": "v-test",
        "summary": summary,
        "results": [
            _case(f"case_{n}", status) for n, status in enumerate(statuses, start=1)
        ],
    }

    assert _header_badge(generate_html_report(run)) == ("badge-fail", header)
    assert extract_summary_data(run)["status"] == "FAIL"


# ----------------------------------------------- repeated case ids (third audit)


@pytest.mark.parametrize(
    "records",
    [
        [
            _case("case_1", "FAIL", equation_delta="5.00"),
            _case("case_1", m1_closing_balance="111.11", equation_delta="0.00"),
        ],
        [
            _case("case_1", m1_closing_balance="111.11", equation_delta="0.00"),
            _case("case_1", "FAIL", equation_delta="5.00"),
        ],
    ],
    ids=["fail-first", "fail-last"],
)
def test_AC_testing_benchmarks_13_a_repeated_case_id_counts_as_its_worst_record(
    records: list[dict[str, Any]],
) -> None:
    run = _report([*records, *FULL_RUN[1:]])

    page = generate_html_report(run)
    data = extract_summary_data(run)
    rows = _invariant_rows(page)

    assert _invariant_cells(page) == {
        "Balance Sheet Identity": "FAIL",
        "Temporal Multi-Period Rollforward": "FAIL",
        "Credit Card Liability Clearance (No Double Counting)": "PASS",
        "Retained Earnings Articulation": "FAIL",
    }
    # The invariant rows show the figures of the record that failed.
    assert (
        rows["Temporal Multi-Period Rollforward"][0]
        == "Closing balances of months 1 to 4: n/a, n/a, n/a, n/a"
    )
    assert data["rollforward_balanced"] is False
    assert (data["thirty_flows_coverage"], data["domains_covered"]) == ("23/30", 7)


@pytest.mark.parametrize(
    ("statuses", "verdict"),
    [
        (("SKIPPED", "PASS"), "NOT RUN"),
        (("PASS", "SKIPPED"), "NOT RUN"),
        (("FAIL", "SKIPPED"), "FAIL"),
        (("SKIPPED", "FAIL"), "FAIL"),
        (("PASS", "PASS"), "PASS"),
    ],
)
def test_AC_testing_benchmarks_13_a_repeated_case_id_keeps_the_order_fail_not_run_pass(
    statuses: tuple[str, str], verdict: str
) -> None:
    run = _report(
        [_case("case_3", status, card_spend_recorded="1.00") for status in statuses]
    )

    cells = _invariant_cells(generate_html_report(run))

    assert cells["Credit Card Liability Clearance (No Double Counting)"] == verdict
    assert extract_summary_data(run)["zero_pnl_contamination"] is (verdict == "PASS")


def test_AC_testing_benchmarks_13_a_repeated_case_id_shows_its_first_worst_record() -> (
    None
):
    run = _report(
        [
            _case("case_3", card_spend_recorded="1.00"),
            _case("case_3", "FAIL", card_spend_recorded="9.00"),
            _case("case_3", "FAIL", card_spend_recorded="8.00"),
        ]
    )

    rows = _invariant_rows(generate_html_report(run))

    assert rows["Credit Card Liability Clearance (No Double Counting)"] == (
        "Card spend 9.00, bank repayment n/a, net income n/a",
        "FAIL",
    )


# ---------------------------------------------- baseline card (third audit)


def _timed_report(*seconds: Any) -> dict[str, Any]:
    """A report with one passed case for each duration."""
    cases = []
    for n, value in enumerate(seconds, start=1):
        case = _case(f"case_{n}", equation_delta="0.00")
        case["duration_seconds"] = value
        cases.append(case)
    return _report(cases)


@pytest.mark.parametrize(
    ("current", "baseline", "expected"),
    [
        (_timed_report("abc"), _timed_report(20.0), "n/a"),
        (_timed_report(None, "slow"), _timed_report(20.0), "n/a"),
        (_timed_report(12.0), {"version_ref": "v0"}, "12.00s"),
        (_timed_report(12.0), _timed_report(None), "12.00s"),
    ],
    ids=[
        "current-invalid",
        "current-missing",
        "baseline-without-summary",
        "baseline-cases-without-time",
    ],
)
def test_AC_testing_benchmarks_13_the_baseline_card_states_no_time_difference_without_two_times(
    current: dict[str, Any], baseline: dict[str, Any], expected: str
) -> None:
    page = generate_html_report(current, baseline_data=baseline)

    assert _baseline_stat(page, "Execution Time") == (
        expected,
        "metric-diff-neutral",
        "n/a",
    )


@pytest.mark.parametrize(
    ("current", "baseline"), [(3.0, 3.001), (3.001, 3.0), (3.0, 3.004)]
)
def test_AC_testing_benchmarks_13_a_time_difference_that_rounds_to_zero_shows_no_sign(
    current: float, baseline: float
) -> None:
    page = generate_html_report(
        _timed_report(current), baseline_data=_timed_report(baseline)
    )

    assert _baseline_stat(page, "Execution Time")[1:] == (
        "metric-diff-neutral",
        "0.00s",
    )


def test_AC_testing_benchmarks_13_the_baseline_pass_rate_of_a_run_without_cases_is_neutral() -> (
    None
):
    page = generate_html_report(_report([]), baseline_data=_report(FULL_RUN))

    assert _baseline_stat(page, "Pass Rate") == ("0/0", "metric-diff-neutral", "n/a")


# ---------------------------------------------------- zero drift (third audit)

BALANCE_DELTA_ROWS = [
    ("case_1", "equation_delta"),
    ("case_2", "equation_delta"),
    ("case_3", "equation_delta"),
    ("case_4", "equation_delta_sgd"),
    ("case_4", "equation_delta_usd"),
    ("case_5", "equation_delta"),
    ("case_6", "equation_delta"),
]


def _full_run_with(case_id: str, key: str, value: Any) -> dict[str, Any]:
    """The report of FULL_RUN with one recorded detail of one case replaced."""
    run = _report(FULL_RUN)
    [case] = [c for c in run["results"] if c["case_id"] == case_id]
    case["details"][key] = value
    return run


def test_AC_testing_benchmarks_13_zero_drift_holds_for_a_full_run_of_recorded_zeros() -> (
    None
):
    page = generate_html_report(_report(FULL_RUN), baseline_data=_report(FULL_RUN))

    assert _baseline_stat(page, "Max Equation Delta") == (
        "0.00 SGD",
        "metric-diff-better",
        "Zero Drift",
    )


@pytest.mark.parametrize("value", [None, "NaN", "abc", []], ids=repr)
@pytest.mark.parametrize(("case_id", "key"), BALANCE_DELTA_ROWS)
def test_AC_testing_benchmarks_13_zero_drift_needs_a_recorded_zero_in_every_delta_row(
    case_id: str, key: str, value: Any
) -> None:
    run = _full_run_with(case_id, key, value)

    page = generate_html_report(run, baseline_data=_report(FULL_RUN))

    assert _baseline_stat(page, "Max Equation Delta") == (
        "0.00 SGD",
        "metric-diff-neutral",
        "not recorded for every balance case",
    )


@pytest.mark.parametrize("status", ["FAIL", "SKIPPED"])
@pytest.mark.parametrize(
    "case_id", ["case_1", "case_2", "case_3", "case_4", "case_5", "case_6"]
)
def test_AC_testing_benchmarks_13_zero_drift_needs_every_balance_case_to_pass(
    case_id: str, status: str
) -> None:
    run = _report(
        [
            _case(c["case_id"], status, **c["details"])
            if c["case_id"] == case_id
            else c
            for c in FULL_RUN
        ]
    )

    page = generate_html_report(run, baseline_data=_report(FULL_RUN))

    assert _baseline_stat(page, "Max Equation Delta") == (
        "0.00 SGD",
        "metric-diff-neutral",
        "not every balance case passed",
    )


def test_AC_testing_benchmarks_13_zero_drift_never_stands_beside_a_delta_that_is_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A future identity case outside the balance cases must not open a gap.
    monkeypatch.setattr(
        benchmark_html_reporter,
        "IDENTITY_CASE_IDS",
        ("case_1", "case_4", "case_6", "case_7"),
    )
    run = _full_run_with("case_2", "equation_delta", "0.02")

    page = generate_html_report(run, baseline_data=_report(FULL_RUN))

    assert _baseline_stat(page, "Max Equation Delta") == (
        "0.02 SGD",
        "metric-diff-neutral",
        "not recorded for every balance case",
    )


# ------------------------------------------- failed case cards (third audit)

NO_FIGURES_TEXT = "No figures recorded. The case stopped before it recorded any."


def _money_text(raw: str) -> str:
    """The value cell that a recorded money figure prints: the sign before the dollar."""
    return f"-${raw[1:]}" if raw.startswith("-") else f"${raw}"


# The delta rows of the case tables: case, delta key, row label.
DELTA_ROWS = [
    ("case_1", "equation_delta", "Balance Sheet Equation Delta (A - L - E)"),
    ("case_2", "equation_delta", "Balance Sheet Equation Delta"),
    ("case_3", "equation_delta", "Balance Sheet Equation Delta"),
    ("case_4", "equation_delta_sgd", "SGD Balance Sheet Equation Delta"),
    ("case_4", "equation_delta_usd", "USD Balance Sheet Equation Delta"),
    ("case_5", "equation_delta", "Balance Sheet Equation Delta"),
    ("case_6", "equation_delta", "Balance Sheet Equation Delta"),
]
# One figure of each case table that is no delta.
OTHER_FIGURE = {
    "case_1": "m1_closing_balance",
    "case_2": "household_husband_cash",
    "case_3": "card_spend_recorded",
    "case_4": "sgd_closing_balance",
    "case_5": "total_assets",
    "case_6": "overdraft_cash",
}


@pytest.mark.parametrize("zero", ["0.00", "0", "-0.00", 0])
@pytest.mark.parametrize(("case_id", "key", "label"), DELTA_ROWS)
def test_AC_testing_benchmarks_13_a_failed_case_claims_no_fault_for_a_recorded_zero_delta(
    case_id: str, key: str, label: str, zero: Any
) -> None:
    page = generate_html_report(_report([_case(case_id, "FAIL", **{key: zero})]))
    card = _card(page, case_id)

    assert _case_rows(page, case_id)[label] == (
        "$0.00",
        "[badge-skip] No difference recorded",
    )
    assert "Regression" not in card
    assert "Equation Broken" not in card


@pytest.mark.parametrize(("case_id", "key", "label"), DELTA_ROWS)
def test_AC_testing_benchmarks_13_a_failed_case_claims_no_fault_for_a_delta_it_did_not_record(
    case_id: str, key: str, label: str
) -> None:
    page = generate_html_report(
        _report([_case(case_id, "FAIL", **{OTHER_FIGURE[case_id]: "1.00"})])
    )
    card = _card(page, case_id)

    assert _case_rows(page, case_id)[label] == ("n/a", "[badge-skip] Δ not recorded")
    assert "Regression" not in card
    assert "Equation Broken" not in card


def test_AC_testing_benchmarks_13_a_failed_credit_card_case_names_no_cause_for_its_net_income() -> (
    None
):
    label = "P&L Double-Counting Prevention (Net Income)"
    for net_income in ("0.00", "-1200.00", "-2400.00"):
        page = generate_html_report(
            _report([_case("case_3", "FAIL", net_income=net_income)])
        )
        assert _case_rows(page, "case_3")[label] == (
            _money_text(net_income),
            "[badge-fail] Unconfirmed",
        )
        assert "Contamination" not in page

    missing = generate_html_report(
        _report([_case("case_3", "FAIL", card_spend_recorded="1.00")])
    )
    assert _case_rows(missing, "case_3")[label] == ("n/a", "[badge-skip] Not recorded")


@pytest.mark.parametrize("case_id", sorted(OTHER_FIGURE))
def test_AC_testing_benchmarks_13_a_failed_case_without_a_recorded_figure_shows_no_table(
    case_id: str,
) -> None:
    figure_keys = [key for key in CASE_DETAIL_KEYS[case_id] if key not in TEXT_KEYS]
    for details in (
        {"is_balanced": False},
        {"is_balanced": False, "unknown_key": "1.00"},
        {key: "abc" for key in figure_keys},
    ):
        card = _card(
            generate_html_report(_report([_case(case_id, "FAIL", **details)])), case_id
        )
        assert NO_FIGURES_TEXT in card, details
        assert "<table" not in card, details
        assert "❌" not in card, details


# ----------------------------------------------- golden case tables (third audit)

UNCONFIRMED = "❌ Unconfirmed"
CASE_TABLE_HEADERS = {
    "case_1": ("Financial Assertion", "Value (SGD)", "Reconciliation Status"),
    "case_2": ("Financial Assertion", "Value (SGD)", "Reconciliation Status"),
    "case_3": ("Financial Assertion", "Value (SGD)", "Reconciliation Status"),
    "case_4": ("Financial Assertion", "Amount", "Multi-Currency Status"),
    "case_5": ("Financial Assertion", "Value", "Portfolio Status"),
    "case_6": ("Accounting Invariant", "Reported Metric", "Integrity Check"),
}
# Each row of each case table for the details of `_distinct_details`:
# label, detail keys, unit, value cell, verdict of a passed case, verdict of a failed case.
CASE_TABLE_ROWS: dict[str, list[tuple[str, tuple[str, ...], str, str, str, str]]] = {
    "case_1": [
        (
            "Month 1 (Jan 2025) Ending Balance",
            ("m1_closing_balance", "month_1_ending_balance"),
            "",
            "$1111.00",
            "✅ Anchor Confirmed",
            UNCONFIRMED,
        ),
        (
            "Month 2 (Feb 2025) Ending Balance",
            ("m2_closing_balance", "month_2_ending_balance"),
            "",
            "$1222.00",
            "✅ Exact Continuity Rollforward",
            UNCONFIRMED,
        ),
        (
            "Month 3 (Mar 2025 - Q1 Close) Ending Balance",
            ("m3_closing_balance", "month_3_ending_balance"),
            "",
            "$1333.00",
            "✅ Q1 Continuity Confirmed",
            UNCONFIRMED,
        ),
        (
            "Month 4 (Apr 2025 - Q2 Transition) Ending Balance",
            ("m4_closing_balance", "month_4_ending_balance"),
            "",
            "$1444.00",
            "✅ 4-Month Rollforward Intact",
            UNCONFIRMED,
        ),
        (
            "Q1 Cumulative Net Income",
            ("q1_net_income",),
            "",
            "$1555.00",
            "✅ Articulated to Q1 Retained Earnings",
            UNCONFIRMED,
        ),
        (
            "4-Month Cumulative Net Income",
            ("cumulative_net_income",),
            "",
            "$1666.00",
            "✅ Articulated to Retained Earnings",
            UNCONFIRMED,
        ),
        (
            "Balance Sheet Equation Delta (A - L - E)",
            ("equation_delta",),
            "",
            "$0.07",
            "[badge-pass] 0.07 SGD Balanced",
            "[badge-fail] 0.07 SGD Regression",
        ),
    ],
    "case_2": [
        (
            "Husband Account (DBS Bank) Ending Cash",
            ("household_husband_cash",),
            "",
            "$1111.00",
            "✅ Source Account Reconciled",
            UNCONFIRMED,
        ),
        (
            "Wife Account (Standard Chartered) Ending Cash",
            ("household_wife_cash",),
            "",
            "$1222.00",
            "✅ Multi-PII Account Reconciled",
            UNCONFIRMED,
        ),
        (
            "Consolidated Operating Revenue",
            ("total_income",),
            "",
            "+$1333.00",
            "✅ Combined Inflow Reconciled",
            UNCONFIRMED,
        ),
        (
            "Consolidated Operating Expenses",
            ("total_expenses",),
            "",
            "+$1444.00",
            "✅ Family Expenses Categorized",
            UNCONFIRMED,
        ),
        (
            "Consolidated Net Operating Income",
            ("net_income",),
            "",
            "+$1555.00",
            "✅ P&L Sum Reconciled",
            UNCONFIRMED,
        ),
        (
            "Consolidated Total Liquid Cash",
            ("ending_cash", "closing_balance"),
            "",
            "$1666.00",
            "✅ Cash Flow Ending Cash Conserved",
            UNCONFIRMED,
        ),
        (
            "Balance Sheet Equation Delta",
            ("equation_delta",),
            "",
            "$0.07",
            "[badge-pass] 0.07 SGD Balanced",
            "[badge-fail] 0.07 SGD Regression",
        ),
    ],
    "case_3": [
        (
            "Credit Card Incurred Charges (Liability Incurrence)",
            ("card_spend_recorded",),
            "",
            "+$1111.00",
            "✅ Card Expense & Liability Tracked",
            UNCONFIRMED,
        ),
        (
            "Bank Account Settlement Payment Outflow",
            ("bank_repayment",),
            "",
            "+$1222.00",
            "✅ Bank Cash Outflow Tracked",
            UNCONFIRMED,
        ),
        (
            "Credit Card Liability Ending Balance",
            ("credit_card_liability_cleared",),
            "",
            "$1444.00",
            "✅ Liability Fully Cleared",
            UNCONFIRMED,
        ),
        (
            "Ending Bank Liquid Cash Balance",
            ("ending_bank_cash", "total_assets"),
            "",
            "$1333.00",
            "✅ Cash Balance Conserved",
            UNCONFIRMED,
        ),
        (
            "P&L Double-Counting Prevention (Net Income)",
            ("net_income",),
            "",
            "$1555.00",
            "[badge-pass] Zero Double-Counting (Pure Liability Clearance)",
            "[badge-fail] Unconfirmed",
        ),
        (
            "Balance Sheet Equation Delta",
            ("equation_delta",),
            "",
            "$0.06",
            "[badge-pass] 0.06 SGD Balanced",
            "[badge-fail] 0.06 SGD Regression",
        ),
    ],
    "case_4": [
        (
            "Singapore Jurisdiction (SGD Account)",
            ("sgd_closing_balance",),
            "SGD",
            "1111.00 SGD",
            "✅ Local Inflow Verified",
            UNCONFIRMED,
        ),
        (
            "United States Jurisdiction (USD Account)",
            ("usd_closing_balance",),
            "USD",
            "1222.00 USD",
            "✅ Foreign Currency Inflow Verified",
            UNCONFIRMED,
        ),
        (
            "Hong Kong Jurisdiction (HKD Account)",
            ("hkd_closing_balance",),
            "HKD",
            "1333.00 HKD",
            "✅ Foreign Currency Inflow Verified",
            UNCONFIRMED,
        ),
        (
            "Consolidated Total Assets (SGD Base)",
            ("total_assets_sgd",),
            "SGD",
            "$1444.00 SGD",
            "✅ Unified Multi-Currency Conversion",
            UNCONFIRMED,
        ),
        (
            "SGD Balance Sheet Equation Delta",
            ("equation_delta_sgd",),
            "",
            "$0.05",
            "[badge-pass] 0.05 SGD Balanced",
            "[badge-fail] 0.05 SGD Regression",
        ),
        (
            "USD Balance Sheet Equation Delta",
            ("equation_delta_usd",),
            "",
            "$0.06",
            "[badge-pass] 0.06 USD Balanced",
            "[badge-fail] 0.06 USD Regression",
        ),
    ],
    "case_5": [
        (
            "Public Securities Tracked",
            ("symbols",),
            "",
            "1222.00",
            "✅ Position Snapshots Recognized",
            UNCONFIRMED,
        ),
        (
            "Managed Holdings Count",
            ("holdings_count",),
            "Assets",
            "1111.00 Assets",
            "✅ Atomic & Managed Reconciliation Intact",
            UNCONFIRMED,
        ),
        (
            "Real Estate Property Appraisal",
            ("property_valuation_usd",),
            "USD",
            "$1333.00 USD",
            "✅ 1444.00",
            UNCONFIRMED,
        ),
        (
            "Tax & Compensation Integration",
            ("tax_ecosystem_status",),
            "",
            "1555.00",
            "✅ DocuBench Tax Fixtures Integrated",
            UNCONFIRMED,
        ),
        (
            "Consolidated Wealth Valuation",
            ("total_assets",),
            "SGD",
            "$1666.00 SGD",
            "✅ Fair Market Valuation Reflected",
            UNCONFIRMED,
        ),
        (
            "Balance Sheet Equation Delta",
            ("equation_delta",),
            "",
            "$0.07",
            "[badge-pass] 0.07 SGD Balanced",
            "[badge-fail] 0.07 SGD Regression",
        ),
    ],
    "case_6": [
        (
            "Overdraft Checkpoint Cash Balance",
            ("overdraft_cash",),
            "SGD",
            "$1111.00 SGD",
            "✅ Negative Balance Equation Validated",
            UNCONFIRMED,
        ),
        (
            "Realized Capital Gain from Art Disposal",
            ("capital_gain",),
            "SGD",
            "+$1222.00 SGD",
            "✅ Capital Gain Recognized in P&L",
            UNCONFIRMED,
        ),
        (
            "Final Period Net Income",
            ("net_income",),
            "SGD",
            "$1333.00 SGD",
            "✅ Expense Offset by Capital Gain",
            UNCONFIRMED,
        ),
        (
            "Final Period Total Assets",
            ("total_assets",),
            "SGD",
            "$1444.00 SGD",
            "✅ Ending Assets Reconciled",
            UNCONFIRMED,
        ),
        (
            "Final Period Total Equity",
            ("total_equity",),
            "SGD",
            "$1555.00 SGD",
            "✅ Ending Equity Reconciled",
            UNCONFIRMED,
        ),
        (
            "Balance Sheet Equation Delta",
            ("equation_delta",),
            "",
            "$0.06",
            "[badge-pass] 0.06 SGD Balanced",
            "[badge-fail] ❌ Equation Broken",
        ),
    ],
}


@pytest.mark.parametrize("status", ["PASS", "FAIL"])
@pytest.mark.parametrize("case_id", sorted(CASE_TABLE_ROWS))
def test_AC_testing_benchmarks_13_each_value_of_a_case_table_stays_in_the_row_of_its_label(
    case_id: str, status: str
) -> None:
    page = generate_html_report(
        _report([_case(case_id, status, **_distinct_details(case_id))])
    )

    assert _table_rows(_card(page, case_id)) == [
        CASE_TABLE_HEADERS[case_id],
        *[
            (label, value, passed if status == "PASS" else failed)
            for label, _, _, value, passed, failed in CASE_TABLE_ROWS[case_id]
        ],
    ]


@pytest.mark.parametrize(
    ("case_id", "key"),
    [
        (case_id, key)
        for case_id, rows in sorted(CASE_TABLE_ROWS.items())
        for _, keys, *_ in rows
        for key in keys
    ],
)
def test_AC_testing_benchmarks_13_a_failed_case_with_one_recorded_value_shows_its_table(
    case_id: str, key: str
) -> None:
    card = _card(
        generate_html_report(_report([_case(case_id, "FAIL", **{key: "1.00"})])),
        case_id,
    )

    assert "<table" in card
    assert NO_FIGURES_TEXT not in card


# --------------------------------------------- figures and text (third audit)

BAD_FIGURES = [
    float("nan"),
    float("inf"),
    float("-inf"),
    "NaN",
    "Infinity",
    "-Infinity",
    "abc",
    "1,5",
    True,
    False,
    [],
    {},
    ["1.00"],
    {"value": "1.00"},
]


@pytest.mark.parametrize("bad", BAD_FIGURES, ids=repr)
@pytest.mark.parametrize("case_id", sorted(CASE_TABLE_ROWS))
def test_AC_testing_benchmarks_13_a_figure_that_is_no_finite_number_shows_n_a(
    case_id: str, bad: Any
) -> None:
    figure_keys = [key for key in CASE_DETAIL_KEYS[case_id] if key not in TEXT_KEYS]
    page = generate_html_report(
        _report([_case(case_id, **{key: bad for key in figure_keys})])
    )
    card = _card(page, case_id)

    assert [value for value, _ in _case_rows(page, case_id).values()] == [
        f"n/a {unit}" if unit else "n/a" for _, _, unit, *_ in CASE_TABLE_ROWS[case_id]
    ]
    assert PYTHON_WORDS.findall(card) == []
    assert "[]" not in card
    assert "{}" not in card


@pytest.mark.parametrize("bad", BAD_FIGURES, ids=repr)
def test_AC_testing_benchmarks_13_an_invariant_figure_that_is_no_finite_number_shows_n_a(
    bad: Any,
) -> None:
    run = [
        _case(
            "case_1",
            cumulative_net_income=bad,
            **{f"m{n}_closing_balance": bad for n in (1, 2, 3, 4)},
        ),
        _case("case_3", card_spend_recorded=bad, bank_repayment=bad, net_income=bad),
    ]

    rows = _invariant_rows(generate_html_report(_report(run)))

    assert rows["Temporal Multi-Period Rollforward"][0] == (
        "Closing balances of months 1 to 4: n/a, n/a, n/a, n/a"
    )
    assert rows["Retained Earnings Articulation"][0] == "Cumulative net income n/a"
    assert rows["Credit Card Liability Clearance (No Double Counting)"][0] == (
        "Card spend n/a, bank repayment n/a, net income n/a"
    )


@pytest.mark.parametrize(
    "value",
    [["AAPL"], {"symbol": "AAPL"}, True, False, None, "", float("nan")],
    ids=repr,
)
def test_AC_testing_benchmarks_13_a_text_field_that_is_no_text_shows_n_a(
    value: Any,
) -> None:
    page = generate_html_report(
        _report(
            [
                _case(
                    "case_5",
                    symbols=value,
                    appraisal_source=value,
                    tax_ecosystem_status=value,
                )
            ]
        )
    )
    rows = _case_rows(page, "case_5")

    assert rows["Public Securities Tracked"] == (
        "n/a",
        "✅ Position Snapshots Recognized",
    )
    assert rows["Real Estate Property Appraisal"] == ("n/a USD", "✅ n/a")
    assert rows["Tax & Compensation Integration"] == (
        "n/a",
        "✅ DocuBench Tax Fixtures Integrated",
    )
    assert PYTHON_WORDS.findall(_card(page, "case_5")) == []


def test_AC_testing_benchmarks_13_a_text_field_keeps_its_recorded_text() -> None:
    page = generate_html_report(
        _report(
            [
                _case(
                    "case_5",
                    symbols="AAPL, VT",
                    appraisal_source="FHA 1004",
                    tax_ecosystem_status=7,
                )
            ]
        )
    )
    rows = _case_rows(page, "case_5")

    assert rows["Public Securities Tracked"][0] == "AAPL, VT"
    assert rows["Real Estate Property Appraisal"][1] == "✅ FHA 1004"
    assert rows["Tax & Compensation Integration"][0] == "7"


# ----------------------------------------------------------- signs (third audit)


@pytest.mark.parametrize(
    ("raw", "signed_text", "plain_text"),
    [
        ("-100.00", "-$100.00", "-$100.00"),
        ("100.00", "+$100.00", "$100.00"),
        ("+100.00", "+$100.00", "$100.00"),
        ("0.00", "$0.00", "$0.00"),
        ("-0.00", "$0.00", "$0.00"),
        ("0.50", "+$0.50", "$0.50"),
        (-7.5, "-$7.5", "-$7.5"),
    ],
)
@pytest.mark.parametrize(
    ("case_id", "key", "label", "unit", "signed"),
    [
        ("case_2", "total_income", "Consolidated Operating Revenue", "", True),
        ("case_2", "total_expenses", "Consolidated Operating Expenses", "", True),
        ("case_2", "net_income", "Consolidated Net Operating Income", "", True),
        (
            "case_2",
            "household_husband_cash",
            "Husband Account (DBS Bank) Ending Cash",
            "",
            False,
        ),
        (
            "case_3",
            "card_spend_recorded",
            "Credit Card Incurred Charges (Liability Incurrence)",
            "",
            True,
        ),
        (
            "case_3",
            "bank_repayment",
            "Bank Account Settlement Payment Outflow",
            "",
            True,
        ),
        (
            "case_6",
            "capital_gain",
            "Realized Capital Gain from Art Disposal",
            " SGD",
            True,
        ),
        (
            "case_6",
            "overdraft_cash",
            "Overdraft Checkpoint Cash Balance",
            " SGD",
            False,
        ),
    ],
)
def test_AC_testing_benchmarks_13_a_sign_comes_from_the_recorded_value(
    case_id: str,
    key: str,
    label: str,
    unit: str,
    signed: bool,
    raw: Any,
    signed_text: str,
    plain_text: str,
) -> None:
    page = generate_html_report(_report([_case(case_id, **{key: raw})]))

    assert (
        _case_rows(page, case_id)[label][0]
        == (signed_text if signed else plain_text) + unit
    )
    assert "$-" not in _card(page, case_id)


# --------------------------------------------------- odd JSON (third audit)


def _nested(depth: int) -> list[Any]:
    """Lists that nest `depth` levels deep."""
    value: list[Any] = []
    for _ in range(depth - 1):
        value = [value]
    return value


@pytest.mark.parametrize(
    "case_id", [["case_1"], {"id": "case_1"}, 1, True, None, ""], ids=repr
)
def test_AC_testing_benchmarks_13_a_case_id_that_is_no_string_is_an_unknown_case(
    case_id: Any,
) -> None:
    case = _case("case_1", m1_closing_balance="111.11", equation_delta="0.00")
    case["case_id"] = case_id
    run = _report([case])

    page = generate_html_report(run, baseline_data=run)
    data = extract_summary_data(run)

    assert page.count('<span class="case-tag">UNKNOWN</span>') == 1
    assert set(_invariant_cells(page).values()) == {"NOT RUN"}
    assert (data["thirty_flows_coverage"], data["rollforward_balanced"]) == (
        "0/30",
        False,
    )


@pytest.mark.parametrize(
    "baseline", [[{"version_ref": "v1"}], "baseline", 5, True, [], {}], ids=repr
)
def test_AC_testing_benchmarks_13_a_baseline_that_is_no_dict_gives_no_baseline_card(
    baseline: Any,
) -> None:
    page = generate_html_report(_report(FULL_RUN), baseline_data=baseline)

    assert '<div class="card baseline-card">' not in page
    assert _header_badge(page) == ("badge-pass", "ALL 6 SCENARIOS PASSED")


@pytest.mark.parametrize("depth", [1000, 5000])
def test_AC_testing_benchmarks_13_deep_nesting_never_stops_the_report_or_the_dashboard(
    depth: int,
) -> None:
    deep = _nested(depth)
    run = _report([_case("case_1", m1_closing_balance="111.11"), _case("case_9")])
    run["version_ref"] = deep
    run["summary"].update(total=deep, total_duration_seconds=deep)
    run["results"][0].update(case_name=deep, error_message=deep, status=deep)
    run["results"][0]["details"]["m2_closing_balance"] = deep
    run["results"][1]["details"]["x"] = deep

    page = generate_html_report(run, baseline_data=run)
    data = extract_summary_data(run)
    dashboard = generate_index_dashboard([{**data, "status": deep, "app_url": deep}])
    rows = _case_rows(page, "case_1")

    # The telemetry of case_1, and the table and the telemetry of case_9.
    assert page.count("Not shown: the details nest deeper than 50 levels.") == 3
    assert rows["Month 1 (Jan 2025) Ending Balance"] == ("$111.11", "❌ Unconfirmed")
    assert rows["Month 2 (Feb 2025) Ending Balance"] == ("n/a", "❌ Unconfirmed")
    assert "Financial Scenario Benchmark: n/a" in _dom(page).text
    assert (data["version"], data["status"], data["cases_total"]) == (None, "FAIL", 2)
    assert "Latest Deployed Release: n/a" in dashboard
    assert '<span class="badge badge-fail">UNKNOWN</span>' in dashboard


@pytest.mark.parametrize(("depth", "shown"), [(49, True), (50, False)])
def test_AC_testing_benchmarks_13_the_telemetry_shows_details_that_nest_up_to_50_levels(
    depth: int, shown: bool
) -> None:
    page = generate_html_report(_report([_case("case_9", x=_nested(depth))]))

    assert ("&quot;x&quot;: [" in page) is shown
    assert ("Not shown: the details nest deeper than 50 levels." in page) is not shown


# ----------------------------------------------- invariant rows (third audit)


def test_AC_testing_benchmarks_13_each_invariant_value_stays_in_the_row_of_its_label() -> (
    None
):
    run = [
        _case(
            "case_1",
            m1_closing_balance="101.00",
            m2_closing_balance="202.00",
            m3_closing_balance="303.00",
            m4_closing_balance="404.00",
            cumulative_net_income="505.00",
            equation_delta="0.01",
        ),
        _case(
            "case_3",
            card_spend_recorded="606.00",
            bank_repayment="707.00",
            net_income="-808.00",
        ),
        _case("case_4", equation_delta_sgd="0.02", equation_delta_usd="0.03"),
        _case("case_6", equation_delta="0.04"),
    ]
    page = generate_html_report(_report(run))
    table = page.split('<table class="invariants-table">')[1].split("</table>")[0]

    assert _table_rows(table) == [
        (
            "Fundamental Financial Invariant",
            "Mathematical Formalism",
            "Observed Truth",
            "Adjudication",
        ),
        (
            "Balance Sheet Identity",
            "Assets ≡ Liabilities + Equity + Net Income",
            "Largest recorded |Δ| is 0.04 SGD, recorded by 3 of 3 cases",
            "[badge-pass] PASS",
        ),
        (
            "Temporal Multi-Period Rollforward",
            "Month_{n+1} Opening Cash ≡ Month_n Closing Cash",
            "Closing balances of months 1 to 4: 101.00, 202.00, 303.00, 404.00",
            "[badge-pass] PASS",
        ),
        (
            "Credit Card Liability Clearance (No Double Counting)",
            "Card spend recorded once; repayment moves cash and liability only",
            "Card spend 606.00, bank repayment 707.00, net income -808.00",
            "[badge-pass] PASS",
        ),
        (
            "Retained Earnings Articulation",
            "Closing Equity = Opening Equity + Net Income",
            "Cumulative net income 505.00",
            "[badge-pass] PASS",
        ),
    ]


def test_AC_testing_benchmarks_13_the_identity_row_counts_against_the_three_cases_it_needs() -> (
    None
):
    run = [
        _case("case_1", equation_delta="0.00"),
        _case("case_4", equation_delta_sgd="0.00", equation_delta_usd="-0.37"),
    ]

    rows = _invariant_rows(generate_html_report(_report(run)))

    assert rows["Balance Sheet Identity"] == (
        "Largest recorded |Δ| is 0.37 USD, recorded by 2 of 3 cases",
        "NOT RUN",
    )


SUMMARY_FLAGS = {
    "zero_pnl_contamination": "case_3",
    "rollforward_balanced": "case_1",
    "multicurrency_consolidated": "case_4",
    "portfolio_holdings_verified": "case_5",
    "overdraft_articulation_verified": "case_6",
}


@pytest.mark.parametrize(("flag", "case_id"), sorted(SUMMARY_FLAGS.items()))
def test_AC_testing_benchmarks_13_each_summary_flag_reads_only_its_own_case(
    flag: str, case_id: str
) -> None:
    run = _report(
        [
            _case(c["case_id"], "PASS" if c["case_id"] == case_id else "FAIL")
            for c in FULL_RUN
        ]
    )

    data = extract_summary_data(run)

    assert {name: data[name] for name in SUMMARY_FLAGS} == {
        name: name == flag for name in SUMMARY_FLAGS
    }


@pytest.mark.parametrize("value", [-0.0, "-0.0", "-0"], ids=repr)
def test_AC_testing_benchmarks_13_a_duration_of_negative_zero_shows_no_sign(
    value: Any,
) -> None:
    case = _case("case_2", equation_delta="0.00")
    case["duration_seconds"] = value

    page = generate_html_report(_report([case]))
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", duration_seconds=value)]
    )

    assert "⏱️ 0.00s" in page
    assert _stat_value(page, "Total Duration") == "0.00s"
    assert "-0.0" not in page
    assert _stat_value(dashboard, "Latest Latency") == "0.00s"
    assert "-0.0" not in dashboard


# ------------------------------------------------------ dashboard (third audit)


def _polylines(dashboard: str) -> list[list[tuple[float, float]]]:
    """The points of each polyline of the trendline."""
    return [
        [(float(x), float(y)) for x, y in (pair.split(",") for pair in raw.split())]
        for raw in re.findall(r'<polyline[^>]* points="([^"]*)"', _trend(dashboard))
    ]


def test_AC_testing_benchmarks_14_a_run_without_a_valid_duration_gets_no_point_and_breaks_the_line() -> (
    None
):
    runs = [
        _run("v1", "2026-09-01T00:00:00", duration_seconds=10.0),
        _run("v2", "2026-09-02T00:00:00", duration_seconds="slow"),
        _run("v3", "2026-09-03T00:00:00", duration_seconds=20.0),
    ]

    dashboard = generate_index_dashboard(runs)
    trend = _trend(dashboard)

    assert _polylines(dashboard) == [[(40.0, 80.0)], [(660.0, 40.0)]]
    assert trend.count("<circle") == 2
    assert (
        '<text x="350.0" y="110.0" font-size="11" fill="#94a3b8" '
        'text-anchor="middle">n/a</text>'
    ) in trend
    assert (
        '<text x="350.0" y="150" font-size="11" fill="#cbd5e1" '
        'text-anchor="middle">v2</text>'
    ) in trend


def test_AC_testing_benchmarks_14_a_run_summary_without_a_valid_duration_shows_n_a_on_the_dashboard() -> (
    None
):
    run = _timed_report(None, "slow")

    data = extract_summary_data(run)
    dashboard = generate_index_dashboard([data])

    assert data["duration_seconds"] is None
    assert _stat_value(dashboard, "Latest Latency") == "n/a"
    assert _polylines(dashboard) == []
    assert "<circle" not in _trend(dashboard)
    assert "0.00s" not in dashboard


def test_AC_testing_benchmarks_14_the_hero_link_follows_the_recorded_report_url() -> (
    None
):
    target = "https://pages.test/runs/42/report.html"

    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", report_url=target)]
    )

    assert _links(_dom(dashboard)) == [target, target, target]


def test_AC_testing_benchmarks_14_the_latest_run_is_the_newest_by_parsed_time() -> None:
    # 20:00 UTC is later than 01:00 at UTC+8 on the next day, which is 17:00 UTC.
    runs = [
        _run("v-new", "2026-09-01T20:00:00+00:00"),
        _run("v-old", "2026-09-02T01:00:00+08:00", status="FAIL"),
    ]

    dashboard = generate_index_dashboard(runs)

    assert "Latest Deployed Release: v-new" in dashboard
    assert [("v-new" in row) for row in _history_rows(dashboard)] == [True, False]


def test_AC_testing_benchmarks_14_a_run_time_without_an_offset_is_utc() -> None:
    # 20:00 at UTC+1 is 19:00 UTC. The naive time 19:30 is UTC, so it is newer.
    runs = [
        _run("v-aware", "2026-09-01T20:00:00+01:00"),
        _run("v-naive", "2026-09-01T19:30:00"),
    ]

    dashboard = generate_index_dashboard(runs)

    assert "Latest Deployed Release: v-naive" in dashboard


def test_AC_testing_benchmarks_14_a_run_time_that_does_not_parse_is_older_than_a_parsed_one() -> (
    None
):
    dashboard = generate_index_dashboard(
        [_run("v-text", "zzz"), _run("v-dated", "2026-09-01T00:00:00")]
    )
    two_texts = generate_index_dashboard([_run("v-a", "x-1"), _run("v-b", "x-2")])

    assert "Latest Deployed Release: v-dated" in dashboard
    assert "Latest Deployed Release: v-b" in two_texts


def test_AC_testing_benchmarks_14_the_dashboard_skips_manifest_entries_that_are_no_dict() -> (
    None
):
    manifest = [
        None,
        5,
        "x",
        [],
        _run("v1", "2026-09-01T00:00:00"),
        {"version": "v0", "run_at": "2026-08-01T00:00:00"},
    ]

    dashboard = generate_index_dashboard(manifest)

    assert _stat_value(dashboard, "Total Releases Tracked") == "2"
    assert len(_history_rows(dashboard)) == 2
    assert "Latest Deployed Release: v1" in dashboard


@pytest.mark.parametrize(
    ("passed", "total", "rate"),
    [
        (199, 200, "199/200 (99%)"),
        (999, 1000, "999/1000 (99%)"),
        (1, 201, "1/201 (1%)"),
        (1, 1000, "1/1000 (1%)"),
        (0, 7, "0/7 (0%)"),
        (7, 7, "7/7 (100%)"),
        (200, 200, "200/200 (100%)"),
    ],
)
def test_AC_testing_benchmarks_14_a_rounded_pass_rate_shows_0_or_100_percent_only_for_exact_counts(
    passed: int, total: int, rate: str
) -> None:
    dashboard = generate_index_dashboard(
        [_run("v1", "2026-09-01T00:00:00", cases_passed=passed, cases_total=total)]
    )

    assert _stat_value(dashboard, "Latest Pass Rate") == rate


class _NoTextList(list[Any]):
    """A list that fails the test when the reporter turns it into text."""

    def __repr__(self) -> str:
        raise AssertionError("the reporter called str() on a list")

    __str__ = __repr__


class _NoTextDict(dict[str, Any]):
    """A dict that fails the test when the reporter turns it into text."""

    def __repr__(self) -> str:
        raise AssertionError("the reporter called str() on a dict")

    __str__ = __repr__


@pytest.mark.parametrize(
    "make", [lambda: _NoTextList(["1.00"]), lambda: _NoTextDict(value="1.00")]
)
def test_AC_testing_benchmarks_13_the_report_never_turns_a_container_into_text(
    make: Any,
) -> None:
    # str() of a container that nests deep enough raises RecursionError.
    run = _report(FULL_RUN)
    for key in ("version_ref", "app_url", "run_at"):
        run[key] = make()
    run["summary"].update(total=make(), passed=make(), total_duration_seconds=make())
    for case in run["results"]:
        case.update(
            case_name=make(),
            error_message=make(),
            duration_seconds=make(),
        )
        case["details"].update(
            {key: make() for key in CASE_DETAIL_KEYS[case["case_id"]]}
        )

    page = generate_html_report(run, baseline_data=run)
    data = extract_summary_data(run)
    dashboard = generate_index_dashboard(
        [
            {
                **data,
                **{
                    key: make()
                    for key in (
                        "version",
                        "status",
                        "run_at",
                        "app_url",
                        "report_url",
                        "cases_total",
                        "cases_passed",
                        "duration_seconds",
                        "max_equation_delta",
                        "max_equation_delta_currency",
                    )
                },
            }
        ]
    )

    assert _case_rows(page, "case_1")["Month 1 (Jan 2025) Ending Balance"] == (
        "n/a",
        "✅ Anchor Confirmed",
    )
    assert _case_rows(page, "case_5")["Public Securities Tracked"][0] == "n/a"
    assert "Financial Scenario Benchmark: n/a" in _dom(page).text
    assert (data["version"], data["run_at"], data["duration_seconds"]) == (
        None,
        "",
        None,
    )
    assert _links(_dom(dashboard)) == ["#", "#", "#"]


def test_AC_testing_benchmarks_13_a_case_without_a_table_shows_its_recorded_details() -> (
    None
):
    failed = _card(
        generate_html_report(_report([_case("case_9", "FAIL", note="x")])), "case_9"
    )
    passed_empty = _card(generate_html_report(_report([_case("case_9")])), "case_9")
    failed_empty = _card(
        generate_html_report(_report([_case("case_9", "FAIL")])), "case_9"
    )

    # The details print as JSON with an indent of two spaces.
    assert (
        "<pre class='raw-json'>{\n  &quot;note&quot;: &quot;x&quot;\n}</pre>" in failed
    )
    assert NO_FIGURES_TEXT not in failed
    assert "<pre class='raw-json'>{}</pre>" in passed_empty
    assert NO_FIGURES_TEXT not in passed_empty
    assert NO_FIGURES_TEXT in failed_empty
    assert "raw-json" not in failed_empty
