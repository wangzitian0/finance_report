"""
Benchmark HTML Reporter and Dashboard Generator.

Produces standalone, lightweight single-file HTML reports (<100KB) and
an aggregated multi-version index dashboard (<50KB) following the
Zero-Raster-Image policy (pure SVG/CSS, zero external CDN dependencies).
"""

from __future__ import annotations

import html
import json
import math
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from tools._lib.benchmarks._html_templates import (
    DASHBOARD_HTML_TEMPLATE,
    REPORT_HTML_TEMPLATE,
)
from tools._lib.benchmarks.case_types import (
    FLOW_TO_CASES,
    FLOW_TO_DOMAIN,
    get_case_to_flows,
)


MISSING = "n/a"
EQUATION_DELTA_KEYS = ("equation_delta", "equation_delta_sgd", "equation_delta_usd")
# The currency of each delta key.
DELTA_CURRENCY = {
    "equation_delta": "SGD",
    "equation_delta_sgd": "SGD",
    "equation_delta_usd": "USD",
}
# A value at or above this limit is no balance delta. The page never prints it.
DELTA_LIMIT = Decimal("1E+12")
# The cases of flow 23 prove the balance sheet identity (common/meta/flows).
IDENTITY_CASE_IDS = tuple(f"case_{case}" for case in FLOW_TO_CASES[23])


def _details_of(result: dict[str, Any]) -> dict[str, Any]:
    """The recorded details of a case result, or an empty dict."""
    details = result.get("details")
    return details if isinstance(details, dict) else {}


def _detail(details: dict[str, Any], *keys: str) -> Any:
    """First recorded value among `keys`, or "n/a" when the run recorded none.

    A report must never show an expected figure for a value the run did not produce.
    """
    for key in keys:
        value = details.get(key)
        if value not in (None, ""):
            return value
    return MISSING


def _show(value: Any) -> str:
    """Escaped text of a value for the page, or "n/a" when there is none."""
    return MISSING if value in (None, "") else html.escape(str(value))


def _whole_number(value: Any) -> int | None:
    """The value as a whole number, or None when it is not one."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _percent(part: Any, whole: Any) -> str:
    """Share of `part` in `whole` as a percent, or "n/a" when a count is not a number."""
    numerator, denominator = _whole_number(part), _whole_number(whole)
    if numerator is None or not denominator:
        return MISSING
    return f"{round(100 * numerator / denominator)}%"


def _cases(count: int) -> str:
    return f"{count} case" if count == 1 else f"{count} cases"


def _seconds(value: Any) -> float:
    """A duration in seconds, or 0.0 when the value is not a finite number."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    return seconds if math.isfinite(seconds) else 0.0


def _href(url: Any) -> str:
    """Escaped link target. A target with a scheme other than http or https becomes "#".

    `urlsplit` lowercases the scheme. It also removes tabs, new lines and leading control
    characters, as a browser does.
    """
    text = str(url)
    try:
        scheme = urlsplit(text).scheme
    except ValueError:
        return "#"
    return html.escape(text) if scheme in ("", "http", "https") else "#"


def _balanced_badge(delta: Any, unit: str) -> str:
    """Pass badge that states the recorded delta, or says that none was recorded."""
    if delta == MISSING:
        return '<span class="badge badge-pass">Balanced (Δ not recorded)</span>'
    return f'<span class="badge badge-pass">{html.escape(str(delta))} {unit} Balanced</span>'


def _format_delta(value: Decimal) -> str:
    """Two decimals when they are exact. The exact digits when the delta has more."""
    rounded = value.quantize(Decimal("0.01"))
    return str(rounded) if rounded == value else format(value, "f")


def _recorded_deltas(results: list[dict[str, Any]]) -> list[tuple[Decimal, str]]:
    """Each finite, plausible delta that the results recorded, as (absolute value, currency)."""
    found: list[tuple[Decimal, str]] = []
    for result in results:
        details = _details_of(result)
        for key in EQUATION_DELTA_KEYS:
            raw = details.get(key)
            if raw in (None, ""):
                continue
            try:
                value = abs(Decimal(str(raw)))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if value.is_finite() and value < DELTA_LIMIT:
                found.append((value, DELTA_CURRENCY[key]))
    return found


def _largest_delta(results: list[dict[str, Any]]) -> tuple[str, str]:
    """The largest recorded delta as (value, currency), or ("n/a", "") when none."""
    found = _recorded_deltas(results)
    if not found:
        return MISSING, ""
    value, currency = max(found, key=lambda item: item[0])
    return _format_delta(value), currency


def _max_equation_delta(results: list[dict[str, Any]]) -> str:
    """The value of the largest recorded delta, or "n/a" when none."""
    return _largest_delta(results)[0]


def _delta_text(results: list[dict[str, Any]]) -> str:
    """The largest recorded delta with its currency, or "n/a" when none."""
    value, currency = _largest_delta(results)
    return f"{value} {currency}" if currency else MISSING


def _recorded_delta_count(results: list[dict[str, Any]]) -> int:
    """How many results recorded at least one delta."""
    return sum(1 for result in results if _recorded_deltas([result]))


def _identity_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The results of the cases that prove the balance sheet identity."""
    by_id = {r.get("case_id"): r for r in results}
    return [by_id[case_id] for case_id in IDENTITY_CASE_IDS if case_id in by_id]


def _adjudication(cases: list[dict[str, Any] | None]) -> str:
    """PASS only when every backing case ran and passed.

    A case that did not run, or was skipped, leaves the invariant unproven.
    """
    statuses = [case.get("status") if case else None for case in cases]
    if not statuses or any(status in (None, "SKIPPED") for status in statuses):
        return '<span class="badge badge-skip">NOT RUN</span>'
    if all(status == "PASS" for status in statuses):
        return '<span class="badge badge-pass">PASS</span>'
    return '<span class="badge badge-fail">FAIL</span>'


def _render_invariants_rows(results: list[dict[str, Any]]) -> str:
    """Rows of the "Core Financial Invariants" table, from the recorded case results."""
    by_id = {r.get("case_id"): r for r in results}
    identity_cases = [by_id.get(case_id) for case_id in IDENTITY_CASE_IDS]
    identity_present = _identity_results(results)
    identity_recorded = _recorded_delta_count(identity_present)
    if identity_recorded:
        identity_observed = (
            f"Largest recorded |Δ| is {_delta_text(identity_present)}, recorded by "
            f"{identity_recorded} of {_cases(len(IDENTITY_CASE_IDS))}"
        )
    else:
        identity_observed = (
            f"No delta recorded by any of the {_cases(len(IDENTITY_CASE_IDS))}"
        )
    case_1 = by_id.get("case_1")
    case_3 = by_id.get("case_3")
    d1 = _details_of(case_1 or {})
    d3 = _details_of(case_3 or {})
    closings = ", ".join(
        str(_detail(d1, f"m{n}_closing_balance", f"month_{n}_ending_balance"))
        for n in (1, 2, 3, 4)
    )
    rows = [
        (
            "Balance Sheet Identity",
            "Assets ≡ Liabilities + Equity + Net Income",
            identity_observed,
            identity_cases,
        ),
        (
            "Temporal Multi-Period Rollforward",
            "Month_{n+1} Opening Cash ≡ Month_n Closing Cash",
            f"Closing balances of months 1 to 4: {closings}",
            [case_1],
        ),
        (
            "Credit Card Liability Clearance (No Double Counting)",
            "Card spend recorded once; repayment moves cash and liability only",
            f"Card spend {_detail(d3, 'card_spend_recorded')}, "
            f"bank repayment {_detail(d3, 'bank_repayment')}, "
            f"net income {_detail(d3, 'net_income')}",
            [case_3],
        ),
        (
            "Retained Earnings Articulation",
            "Closing Equity = Opening Equity + Net Income",
            f"Cumulative net income {_detail(d1, 'cumulative_net_income')}",
            [case_1],
        ),
    ]
    out = ""
    for name, formula, observed, cases in rows:
        out += f"""
                    <tr>
                        <td><strong>{html.escape(name)}</strong></td>
                        <td><code>{html.escape(formula)}</code></td>
                        <td>{html.escape(observed)}</td>
                        <td>{_adjudication(cases)}</td>
                    </tr>"""
    return out


def extract_summary_data(report_data: dict[str, Any]) -> dict[str, Any]:
    """Extract machine-readable summary metrics from full benchmark report data."""
    summary = report_data.get("summary", {})
    results = report_data.get("results", [])
    version_ref = report_data.get("version_ref", "dev")

    total_duration = sum(_seconds(r.get("duration_seconds")) for r in results)

    passed_case_ids = {
        r.get("case_id")
        for r in results
        if r.get("status") == "PASS" and r.get("case_id")
    }
    case_to_flows = get_case_to_flows()
    covered_flows: set[int] = set()
    for cid in passed_case_ids:
        if cid in case_to_flows:
            covered_flows.update(case_to_flows[cid])
    covered_domains = {FLOW_TO_DOMAIN[f] for f in covered_flows if f in FLOW_TO_DOMAIN}

    return {
        "version": version_ref,
        "run_at": report_data.get("run_at", datetime.now(UTC).isoformat()),
        "app_url": report_data.get("app_url", ""),
        "status": "PASS" if summary.get("success", False) else "FAIL",
        "cases_total": summary.get("total", len(results)),
        "cases_passed": summary.get(
            "passed", sum(1 for r in results if r.get("status") == "PASS")
        ),
        "cases_failed": summary.get(
            "failed", sum(1 for r in results if r.get("status") != "PASS")
        ),
        "duration_seconds": round(total_duration, 2),
        "max_equation_delta": _max_equation_delta(results),
        "max_equation_delta_currency": _largest_delta(results)[1],
        "zero_pnl_contamination": any(
            r.get("case_id") == "case_3" and r.get("status") == "PASS" for r in results
        ),
        "rollforward_balanced": any(
            r.get("case_id") == "case_1" and r.get("status") == "PASS" for r in results
        ),
        "multicurrency_consolidated": any(
            r.get("case_id") == "case_4" and r.get("status") == "PASS" for r in results
        ),
        "portfolio_holdings_verified": any(
            r.get("case_id") == "case_5" and r.get("status") == "PASS" for r in results
        ),
        "overdraft_articulation_verified": any(
            r.get("case_id") == "case_6" and r.get("status") == "PASS" for r in results
        ),
        "thirty_flows_coverage": f"{len(covered_flows)}/30",
        "domains_covered": len(covered_domains),
        "report_url": f"{version_ref}/report.html",
    }


def _render_diff_section(
    baseline_data: dict[str, Any] | None,
    total_dur: float,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
) -> str:
    """Render the baseline comparison card if baseline data is provided."""
    if not baseline_data:
        return ""
    b_summary = baseline_data.get("summary", {})
    b_dur = b_summary.get(
        "total_duration_seconds",
        sum(
            _seconds(r.get("duration_seconds"))
            for r in baseline_data.get("results", [])
        ),
    )
    dur_diff = total_dur - b_dur
    dur_diff_sign = f"+{dur_diff:.2f}s" if dur_diff > 0 else f"{dur_diff:.2f}s"
    dur_class = (
        "metric-diff-worse"
        if dur_diff > 5
        else ("metric-diff-better" if dur_diff < -5 else "metric-diff-neutral")
    )
    b_version = html.escape(str(baseline_data.get("version_ref", "baseline")))
    total_cases = summary.get("total", 0)
    passed_cases = summary.get("passed", 0)
    pass_pct = _percent(passed_cases, total_cases)
    total_number = _whole_number(total_cases)
    pass_class = (
        "metric-diff-better"
        if total_number and _whole_number(passed_cases) == total_number
        else "metric-diff-worse"
    )
    max_delta_text = _delta_text(results)
    identity_recorded = _recorded_delta_count(_identity_results(results))
    if max_delta_text == MISSING:
        delta_note, delta_class = "not recorded", "metric-diff-neutral"
    elif identity_recorded < len(IDENTITY_CASE_IDS):
        delta_note, delta_class = (
            "not recorded for every balance case",
            "metric-diff-neutral",
        )
    elif Decimal(_max_equation_delta(results)) == 0:
        delta_note, delta_class = "Zero Drift", "metric-diff-better"
    else:
        delta_note, delta_class = "Drift", "metric-diff-worse"
    return f"""
    <div class="card baseline-card">
        <h3 style="font-size: 1.1rem; margin-bottom: 12px;">⚖️ Baseline Comparison (vs {b_version})</h3>
        <div class="grid grid-3">
            <div class="stat-box">
                <span class="stat-label">Execution Time</span>
                <span class="stat-value">{total_dur:.2f}s <small class="{dur_class}">({dur_diff_sign})</small></span>
            </div>
            <div class="stat-box">
                <span class="stat-label">Pass Rate</span>
                <span class="stat-value">{_show(passed_cases)}/{_show(total_cases)} <small class="{pass_class}">({pass_pct})</small></span>
            </div>
            <div class="stat-box">
                <span class="stat-label">Max Equation Delta</span>
                <span class="stat-value">{max_delta_text} <small class="{delta_class}">({delta_note})</small></span>
            </div>
        </div>
    </div>
    """


def _render_case_1_table(cdetails: dict[str, Any], case_passed: bool) -> str:
    eq_badge = (
        _balanced_badge(_detail(cdetails, "equation_delta"), "SGD")
        if case_passed
        else f'<span class="badge badge-fail">{html.escape(str(_detail(cdetails, "equation_delta")))} SGD Regression</span>'
    )
    m1_close = _detail(cdetails, "m1_closing_balance", "month_1_ending_balance")
    m2_close = _detail(cdetails, "m2_closing_balance", "month_2_ending_balance")
    m3_close = _detail(cdetails, "m3_closing_balance", "month_3_ending_balance")
    m4_close = _detail(cdetails, "m4_closing_balance", "month_4_ending_balance")
    q1_ni = _detail(cdetails, "q1_net_income")
    cum_ni = _detail(cdetails, "cumulative_net_income")
    eq_delta = _detail(cdetails, "equation_delta")
    return f"""
    <table class="data-table">
        <thead><tr><th>Financial Assertion</th><th>Value (SGD)</th><th>Reconciliation Status</th></tr></thead>
        <tbody>
            <tr><td>Month 1 (Jan 2025) Ending Balance</td><td>${html.escape(str(m1_close))}</td><td>{"✅ Anchor Confirmed" if case_passed else "❌ Unconfirmed"}</td></tr>
            <tr><td>Month 2 (Feb 2025) Ending Balance</td><td>${html.escape(str(m2_close))}</td><td>{"✅ Exact Continuity Rollforward" if case_passed else "❌ Discontinuous"}</td></tr>
            <tr><td>Month 3 (Mar 2025 - Q1 Close) Ending Balance</td><td>${html.escape(str(m3_close))}</td><td>{"✅ Q1 Continuity Confirmed" if case_passed else "❌ Discontinuous"}</td></tr>
            <tr><td>Month 4 (Apr 2025 - Q2 Transition) Ending Balance</td><td>${html.escape(str(m4_close))}</td><td>{"✅ 4-Month Rollforward Intact" if case_passed else "❌ Discontinuous"}</td></tr>
            <tr><td>Q1 Cumulative Net Income</td><td>${html.escape(str(q1_ni))}</td><td>{"✅ Articulated to Q1 Retained Earnings" if case_passed else "❌ Mismatched"}</td></tr>
            <tr><td>4-Month Cumulative Net Income</td><td>${html.escape(str(cum_ni))}</td><td>{"✅ Articulated to Retained Earnings" if case_passed else "❌ Mismatched"}</td></tr>
            <tr><td>Balance Sheet Equation Delta (A - L - E)</td><td>${html.escape(str(eq_delta))}</td><td>{eq_badge}</td></tr>
        </tbody>
    </table>
    """


def _render_case_2_table(cdetails: dict[str, Any], case_passed: bool) -> str:
    eq_badge = (
        _balanced_badge(_detail(cdetails, "equation_delta"), "SGD")
        if case_passed
        else f'<span class="badge badge-fail">{html.escape(str(_detail(cdetails, "equation_delta")))} SGD Regression</span>'
    )
    h_cash = _detail(cdetails, "household_husband_cash")
    w_cash = _detail(cdetails, "household_wife_cash")
    rev = _detail(cdetails, "total_income")
    exp = _detail(cdetails, "total_expenses")
    ni = _detail(cdetails, "net_income")
    cash = _detail(cdetails, "ending_cash", "closing_balance")
    eq_delta = _detail(cdetails, "equation_delta")
    return f"""
    <table class="data-table">
        <thead><tr><th>Financial Assertion</th><th>Value (SGD)</th><th>Reconciliation Status</th></tr></thead>
        <tbody>
            <tr><td>Husband Account (DBS Bank) Ending Cash</td><td>${html.escape(str(h_cash))}</td><td>{"✅ Source Account Reconciled" if case_passed else "❌ Untracked"}</td></tr>
            <tr><td>Wife Account (Standard Chartered) Ending Cash</td><td>${html.escape(str(w_cash))}</td><td>{"✅ Multi-PII Account Reconciled" if case_passed else "❌ Untracked"}</td></tr>
            <tr><td>Consolidated Operating Revenue</td><td>+${html.escape(str(rev))}</td><td>{"✅ Combined Inflow Reconciled" if case_passed else "❌ Untracked"}</td></tr>
            <tr><td>Consolidated Operating Expenses</td><td>-${html.escape(str(exp))}</td><td>{"✅ Family Expenses Categorized" if case_passed else "❌ Untracked"}</td></tr>
            <tr><td>Consolidated Net Operating Income</td><td>+${html.escape(str(ni))}</td><td>{"✅ P&amp;L Sum Reconciled" if case_passed else "❌ Mismatched"}</td></tr>
            <tr><td>Consolidated Total Liquid Cash</td><td>${html.escape(str(cash))}</td><td>{"✅ Cash Flow Ending Cash Conserved" if case_passed else "❌ Mismatched"}</td></tr>
            <tr><td>Balance Sheet Equation Delta</td><td>${html.escape(str(eq_delta))}</td><td>{eq_badge}</td></tr>
        </tbody>
    </table>
    """


def _render_case_3_table(cdetails: dict[str, Any], case_passed: bool) -> str:
    pnl_badge = (
        '<span class="badge badge-pass">Zero Double-Counting (Pure Liability Clearance)</span>'
        if case_passed
        else '<span class="badge badge-fail">P&amp;L Contamination Detected</span>'
    )
    eq_badge = (
        _balanced_badge(_detail(cdetails, "equation_delta"), "SGD")
        if case_passed
        else f'<span class="badge badge-fail">{html.escape(str(_detail(cdetails, "equation_delta")))} SGD Regression</span>'
    )
    card_spend = _detail(cdetails, "card_spend_recorded")
    bank_repay = _detail(cdetails, "bank_repayment")
    ending_cash = _detail(cdetails, "ending_bank_cash", "total_assets")
    liab_cleared = _detail(cdetails, "credit_card_liability_cleared")
    net_income_val = _detail(cdetails, "net_income")
    eq_delta = _detail(cdetails, "equation_delta")
    return f"""
    <table class="data-table">
        <thead><tr><th>Financial Assertion</th><th>Value (SGD)</th><th>Reconciliation Status</th></tr></thead>
        <tbody>
            <tr><td>Credit Card Incurred Charges (Liability Incurrence)</td><td>-${html.escape(str(card_spend))}</td><td>{"✅ Card Expense &amp; Liability Tracked" if case_passed else "❌ Untracked"}</td></tr>
            <tr><td>Bank Account Settlement Payment Outflow</td><td>-${html.escape(str(bank_repay))}</td><td>{"✅ Bank Cash Outflow Tracked" if case_passed else "❌ Untracked"}</td></tr>
            <tr><td>Credit Card Liability Ending Balance</td><td>${html.escape(str(liab_cleared))}</td><td>{"✅ Liability Fully Cleared" if case_passed else "❌ Outstanding Liability"}</td></tr>
            <tr><td>Ending Bank Liquid Cash Balance</td><td>${html.escape(str(ending_cash))}</td><td>{"✅ Cash Balance Conserved" if case_passed else "❌ Mismatched"}</td></tr>
            <tr><td>P&amp;L Double-Counting Prevention (Net Income)</td><td>${html.escape(str(net_income_val))}</td><td>{pnl_badge}</td></tr>
            <tr><td>Balance Sheet Equation Delta</td><td>${html.escape(str(eq_delta))}</td><td>{eq_badge}</td></tr>
        </tbody>
    </table>
    """


def _render_case_4_table(cdetails: dict[str, Any], case_passed: bool) -> str:
    eq_badge_sgd = (
        _balanced_badge(_detail(cdetails, "equation_delta_sgd"), "SGD")
        if case_passed
        else f'<span class="badge badge-fail">{html.escape(str(_detail(cdetails, "equation_delta_sgd")))} SGD Regression</span>'
    )
    eq_badge_usd = (
        _balanced_badge(_detail(cdetails, "equation_delta_usd"), "USD")
        if case_passed
        else f'<span class="badge badge-fail">{html.escape(str(_detail(cdetails, "equation_delta_usd")))} USD Regression</span>'
    )
    sgd_bal = _detail(cdetails, "sgd_closing_balance")
    usd_bal = _detail(cdetails, "usd_closing_balance")
    hkd_bal = _detail(cdetails, "hkd_closing_balance")
    total_sgd = _detail(cdetails, "total_assets_sgd")
    return f"""
    <table class="data-table">
        <thead><tr><th>Financial Assertion</th><th>Amount</th><th>Multi-Currency Status</th></tr></thead>
        <tbody>
            <tr><td>Singapore Jurisdiction (SGD Account)</td><td>{html.escape(str(sgd_bal))} SGD</td><td>{"✅ Local Inflow Verified" if case_passed else "❌ Unverified"}</td></tr>
            <tr><td>United States Jurisdiction (USD Account)</td><td>{html.escape(str(usd_bal))} USD</td><td>{"✅ Foreign Currency Inflow Verified" if case_passed else "❌ Unverified"}</td></tr>
            <tr><td>Hong Kong Jurisdiction (HKD Account)</td><td>{html.escape(str(hkd_bal))} HKD</td><td>{"✅ Foreign Currency Inflow Verified" if case_passed else "❌ Unverified"}</td></tr>
            <tr><td>Consolidated Total Assets (SGD Base)</td><td>${html.escape(str(total_sgd))} SGD</td><td>{"✅ Unified Multi-Currency Conversion" if case_passed else "❌ Imbalanced"}</td></tr>
            <tr><td>SGD Balance Sheet Equation Delta</td><td>${html.escape(str(_detail(cdetails, "equation_delta_sgd")))}</td><td>{eq_badge_sgd}</td></tr>
            <tr><td>USD Balance Sheet Equation Delta</td><td>${html.escape(str(_detail(cdetails, "equation_delta_usd")))}</td><td>{eq_badge_usd}</td></tr>
        </tbody>
    </table>
    """


def _render_case_5_table(cdetails: dict[str, Any], case_passed: bool) -> str:
    eq_badge = (
        _balanced_badge(_detail(cdetails, "equation_delta"), "SGD")
        if case_passed
        else f'<span class="badge badge-fail">{html.escape(str(_detail(cdetails, "equation_delta")))} SGD Regression</span>'
    )
    holdings_cnt = _detail(cdetails, "holdings_count")
    symbols = _detail(cdetails, "symbols")
    prop_val = _detail(cdetails, "property_valuation_usd")
    appraisal_src = _detail(cdetails, "appraisal_source")
    tax_status = _detail(cdetails, "tax_ecosystem_status")
    assets_val = _detail(cdetails, "total_assets")
    eq_delta = _detail(cdetails, "equation_delta")
    return f"""
    <table class="data-table">
        <thead><tr><th>Financial Assertion</th><th>Value</th><th>Portfolio Status</th></tr></thead>
        <tbody>
            <tr><td>Public Securities Tracked</td><td>{html.escape(str(symbols))}</td><td>{"✅ Position Snapshots Recognized" if case_passed else "❌ Missing"}</td></tr>
            <tr><td>Managed Holdings Count</td><td>{html.escape(str(holdings_cnt))} Assets</td><td>{"✅ Atomic &amp; Managed Reconciliation Intact" if case_passed else "❌ Unreconciled"}</td></tr>
            <tr><td>Real Estate Property Appraisal</td><td>${html.escape(str(prop_val))} USD</td><td>{"✅ " + html.escape(str(appraisal_src)) if case_passed else "❌ Excluded"}</td></tr>
            <tr><td>Tax &amp; Compensation Integration</td><td>{html.escape(str(tax_status))}</td><td>{"✅ DocuBench Tax Fixtures Integrated" if case_passed else "❌ Incomplete"}</td></tr>
            <tr><td>Consolidated Wealth Valuation</td><td>${html.escape(str(assets_val))} SGD</td><td>{"✅ Fair Market Valuation Reflected" if case_passed else "❌ Excluded"}</td></tr>
            <tr><td>Balance Sheet Equation Delta</td><td>${html.escape(str(eq_delta))}</td><td>{eq_badge}</td></tr>
        </tbody>
    </table>
    """


def _render_case_6_table(cdetails: dict[str, Any], case_passed: bool) -> str:
    overdraft_cash = _detail(cdetails, "overdraft_cash")
    capital_gain = _detail(cdetails, "capital_gain")
    net_income = _detail(cdetails, "net_income")
    total_assets = _detail(cdetails, "total_assets")
    total_equity = _detail(cdetails, "total_equity")
    eq_delta = _detail(cdetails, "equation_delta")

    eq_badge = (
        _balanced_badge(eq_delta, "SGD")
        if case_passed
        else '<span class="badge badge-fail">❌ Equation Broken</span>'
    )

    return f"""
    <table class="details-table">
        <thead>
            <tr><th>Accounting Invariant</th><th>Reported Metric</th><th>Integrity Check</th></tr>
        </thead>
        <tbody>
            <tr><td>Overdraft Checkpoint Cash Balance</td><td>${html.escape(str(overdraft_cash))} SGD</td><td>{"✅ Negative Balance Equation Validated" if case_passed else "❌ Equation Broken"}</td></tr>
            <tr><td>Realized Capital Gain from Art Disposal</td><td>+${html.escape(str(capital_gain))} SGD</td><td>{"✅ Capital Gain Recognized in P&amp;L" if case_passed else "❌ Untracked"}</td></tr>
            <tr><td>Final Period Net Income</td><td>${html.escape(str(net_income))} SGD</td><td>{"✅ Expense Offset by Capital Gain" if case_passed else "❌ Mismatched"}</td></tr>
            <tr><td>Final Period Total Assets</td><td>${html.escape(str(total_assets))} SGD</td><td>{"✅ Ending Assets Reconciled" if case_passed else "❌ Mismatched"}</td></tr>
            <tr><td>Final Period Total Equity</td><td>${html.escape(str(total_equity))} SGD</td><td>{"✅ Ending Equity Reconciled" if case_passed else "❌ Mismatched"}</td></tr>
            <tr><td>Balance Sheet Equation Delta</td><td>${html.escape(str(eq_delta))}</td><td>{eq_badge}</td></tr>
        </tbody>
    </table>
    """


def _render_case_details_table(
    cid: str, cdetails: dict[str, Any], case_passed: bool
) -> str:
    """Dispatch case detail table rendering according to scenario ID."""
    if cid == "case_1":
        return _render_case_1_table(cdetails, case_passed)
    if cid == "case_2":
        return _render_case_2_table(cdetails, case_passed)
    if cid == "case_3":
        return _render_case_3_table(cdetails, case_passed)
    if cid == "case_4":
        return _render_case_4_table(cdetails, case_passed)
    if cid == "case_5":
        return _render_case_5_table(cdetails, case_passed)
    if cid == "case_6":
        return _render_case_6_table(cdetails, case_passed)
    return f"<pre class='raw-json'>{html.escape(json.dumps(cdetails, indent=2))}</pre>"


def _render_scenario_cards(results: list[dict[str, Any]]) -> str:
    """Render the list of scenario execution cards."""
    cards: list[str] = []
    for r in results:
        cid = str(r.get("case_id", ""))
        cid_tag = html.escape(cid.upper())
        cname = html.escape(str(r.get("case_name", "")))
        status = r.get("status", "FAIL")
        cstatus = html.escape(str(status))
        cdur = _seconds(r.get("duration_seconds"))
        cbadge = "badge-pass" if status == "PASS" else "badge-fail"
        cdetails = _details_of(r)
        err = r.get("error_message")
        case_passed = status == "PASS"

        # A case that did not run, or that stopped before it recorded a figure, has no
        # figures. A table of failed assertions would claim facts that the run did not observe.
        if status == "SKIPPED":
            details_table = "<p>Not run: the case did not run.</p>"
        elif not case_passed and not cdetails:
            details_table = (
                "<p>No figures recorded. The case stopped before it recorded any.</p>"
            )
        else:
            details_table = _render_case_details_table(cid, cdetails, case_passed)
        err_html = (
            f"<div class='error-banner'><strong>Error:</strong> {html.escape(str(err))}</div>"
            if err
            else ""
        )
        cards.append(
            f"""
        <div class="card scenario-card">
            <div class="scenario-header">
                <div>
                    <span class="case-tag">{cid_tag}</span>
                    <h3 class="scenario-title">{cname}</h3>
                </div>
                <div class="scenario-meta">
                    <span class="duration-tag">⏱️ {cdur:.2f}s</span>
                    <span class="badge {cbadge}">{cstatus}</span>
                </div>
            </div>
            {err_html}
            {details_table}
            <details class="raw-details">
                <summary>Inspect Raw Adjudication Telemetry</summary>
                <pre class="raw-json">{html.escape(json.dumps(cdetails, indent=2))}</pre>
            </details>
        </div>
        """
        )
    return "".join(cards)


def generate_html_report(
    report_data: dict[str, Any], baseline_data: dict[str, Any] | None = None
) -> str:
    """Generate standalone single-file HTML report for a specific release run."""
    version = html.escape(str(report_data.get("version_ref", "dev")))
    app_url = html.escape(
        str(report_data.get("app_url", "https://report-staging.zitian.party"))
    )
    run_at = html.escape(str(report_data.get("run_at", datetime.now(UTC).isoformat())))
    summary = report_data.get("summary", {})
    results = report_data.get("results", [])
    all_passed = summary.get("success", False)

    total_cases = summary.get("total", len(results))
    skipped_cases = _whole_number(summary.get("skipped", 0)) or 0
    status_badge_class = "badge-pass" if all_passed else "badge-fail"
    if all_passed and not skipped_cases:
        status_text = f"ALL {_show(total_cases)} SCENARIOS BALANCED"
    else:
        status_text = f"{_show(summary.get('passed', 0))} OF {_show(total_cases)} SCENARIOS PASSED"
        if skipped_cases:
            status_text += f", {skipped_cases} SKIPPED"
    total_dur = sum(_seconds(r.get("duration_seconds")) for r in results)

    diff_html = _render_diff_section(baseline_data, total_dur, summary, results)
    scenarios_html = _render_scenario_cards(results)

    rendered = REPORT_HTML_TEMPLATE
    rendered = rendered.replace("{{VERSION}}", version)
    rendered = rendered.replace("{{APP_URL}}", app_url)
    rendered = rendered.replace("{{RUN_AT}}", run_at)
    rendered = rendered.replace("{{STATUS_BADGE_CLASS}}", status_badge_class)
    rendered = rendered.replace("{{STATUS_TEXT}}", status_text)
    rendered = rendered.replace("{{PASSED_COUNT}}", _show(summary.get("passed", 0)))
    rendered = rendered.replace("{{TOTAL_COUNT}}", _show(summary.get("total", 0)))
    rendered = rendered.replace("{{TOTAL_DURATION_STR}}", f"{total_dur:.2f}s")
    rendered = rendered.replace("{{MAX_DELTA}}", _delta_text(results))
    rendered = rendered.replace(
        "{{DELTA_COVERAGE}}",
        f"recorded by {_recorded_delta_count(results)} of {_cases(len(results))}",
    )
    rendered = rendered.replace(
        "{{NOT_PASSED_COUNT}}",
        str(sum(1 for r in results if r.get("status") != "PASS")),
    )
    rendered = rendered.replace("{{INVARIANTS_ROWS}}", _render_invariants_rows(results))
    rendered = rendered.replace("{{DIFF_HTML}}", diff_html)
    rendered = rendered.replace("{{SCENARIOS_HTML}}", scenarios_html)
    return rendered


def _delta_cell(run: dict[str, Any]) -> str:
    """Delta of one run for the history table. Older entries hold SGD without a currency."""
    delta = run.get("max_equation_delta")
    if delta in (None, "", MISSING):
        return MISSING
    currency = run.get("max_equation_delta_currency") or "SGD"
    return f"{html.escape(str(delta))} {html.escape(str(currency))}"


def _render_dashboard_table_rows(sorted_runs: list[dict[str, Any]]) -> str:
    """Render historical table rows for the multi-version dashboard."""
    table_rows = ""
    for r in sorted_runs:
        version_text = str(r.get("version", "unknown"))
        v = html.escape(version_text)
        status = html.escape(str(r.get("status", "UNKNOWN")))
        badge_cls = "badge-pass" if status == "PASS" else "badge-fail"
        run_date = html.escape(str(r.get("run_at", ""))[:19].replace("T", " "))
        env = html.escape(str(r.get("app_url", "")))
        cases_str = (
            f"{_show(r.get('cases_passed', 0))} / {_show(r.get('cases_total', 0))}"
        )
        dur_str = f"{_seconds(r.get('duration_seconds')):.2f}s"
        delta_cell = _delta_cell(r)
        rep_url = _href(r.get("report_url") or f"{version_text}/report.html")

        table_rows += f"""
        <tr>
            <td><a href="{rep_url}" class="version-link"><strong>{v}</strong></a></td>
            <td><span class="badge {badge_cls}">{status}</span></td>
            <td>{run_date}</td>
            <td><code class="env-code">{env}</code></td>
            <td>{cases_str}</td>
            <td>{dur_str}</td>
            <td>{delta_cell}</td>
            <td><a href="{rep_url}" class="btn-view">View Report →</a></td>
        </tr>
        """
    return table_rows


def _render_dashboard_trend_svg(sorted_runs: list[dict[str, Any]]) -> str:
    """Render historical latency SVG trendline."""
    if not sorted_runs:
        return ""
    # `sorted_runs` is newest first: take the ten newest, then show them oldest to newest.
    chrono_runs = list(reversed(sorted_runs[:10]))
    durations = [_seconds(r.get("duration_seconds")) for r in chrono_runs]
    max_d = max(durations) if durations and max(durations) > 0 else 100.0
    width, height = 700, 160
    padding = 40

    pts: list[tuple[float, float]] = []
    for i, d in enumerate(durations):
        x = (
            padding + (i * (width - 2 * padding) / (len(durations) - 1))
            if len(durations) > 1
            else width / 2
        )
        y = height - padding - ((d / max_d) * (height - 2 * padding))
        pts.append((x, y))

    polyline_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    dots_svg = ""
    labels_svg = ""
    for i, (x, y) in enumerate(pts):
        ver_label = html.escape(str(chrono_runs[i].get("version", "")))
        dur_val = _seconds(chrono_runs[i].get("duration_seconds"))
        dots_svg += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#3b82f6" stroke="#fff" stroke-width="2"/>'
        dots_svg += f'<text x="{x:.1f}" y="{y - 10:.1f}" font-size="11" fill="#94a3b8" text-anchor="middle">{dur_val:.1f}s</text>'
        labels_svg += f'<text x="{x:.1f}" y="{height - 10}" font-size="11" fill="#cbd5e1" text-anchor="middle">{ver_label}</text>'

    return f"""
    <svg viewBox="0 0 {width} {height}" class="trend-svg">
        <line x1="{padding}" y1="{height - padding}" x2="{width - padding}" y2="{height - padding}" stroke="#334155" stroke-width="1"/>
        <polyline fill="none" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="{polyline_pts}"/>
        {dots_svg}
        {labels_svg}
    </svg>
    """


def generate_index_dashboard(manifest_data: list[dict[str, Any]]) -> str:
    """Generate the root /benchmarks/index.html multi-version dashboard."""
    sorted_runs = sorted(
        manifest_data, key=lambda x: str(x.get("run_at", "")), reverse=True
    )

    total_runs = len(sorted_runs)
    latest_run = sorted_runs[0] if sorted_runs else {}
    latest_ver_text = str(latest_run.get("version", MISSING))
    latest_ver = html.escape(latest_ver_text)
    latest_status_text = str(latest_run.get("status", "UNKNOWN"))
    latest_status = html.escape(latest_status_text)
    passed = latest_run.get("cases_passed", 0)
    total = latest_run.get("cases_total", 0)
    latest_pass_rate = f"{_show(passed)}/{_show(total)}" if latest_run else MISSING
    latest_pass_percent = _percent(passed, total) if latest_run else MISSING
    if latest_run:
        latest_delta = _delta_cell(latest_run)
        latest_duration = f"{_seconds(latest_run.get('duration_seconds')):.2f}s"
    else:
        latest_delta = MISSING
        latest_duration = MISSING
    counts = f"{passed} of {total} cases passed"
    if not latest_run:
        latest_summary = "The history holds no run yet"
    elif latest_status_text == "PASS":
        latest_summary = counts
    elif latest_status_text == "FAIL":
        latest_summary = f"The latest run did not pass: {counts}"
    else:
        latest_summary = f"The status of the latest run is unknown. {counts}"
    latest_badge_class = "badge-pass" if latest_status_text == "PASS" else "badge-fail"
    latest_report_link = (
        f'<a href="{_href(f"{latest_ver_text}/report.html")}" class="btn-latest">View Latest Full Report →</a>'
        if latest_run
        else ""
    )

    table_rows = _render_dashboard_table_rows(sorted_runs)
    chart_svg = _render_dashboard_trend_svg(sorted_runs)

    rendered = DASHBOARD_HTML_TEMPLATE
    rendered = rendered.replace("{{LATEST_BADGE_CLASS}}", latest_badge_class)
    rendered = rendered.replace("{{LATEST_STATUS}}", latest_status)
    rendered = rendered.replace("{{LATEST_VER}}", latest_ver)
    rendered = rendered.replace("{{LATEST_REPORT_LINK}}", latest_report_link)
    rendered = rendered.replace("{{TOTAL_RUNS}}", str(total_runs))
    rendered = rendered.replace("{{LATEST_PASS_RATE}}", latest_pass_rate)
    rendered = rendered.replace("{{LATEST_PASS_PERCENT}}", latest_pass_percent)
    rendered = rendered.replace("{{LATEST_DURATION}}", latest_duration)
    rendered = rendered.replace("{{LATEST_DELTA}}", latest_delta)
    rendered = rendered.replace("{{LATEST_SUMMARY}}", html.escape(latest_summary))
    rendered = rendered.replace("{{CHART_SVG}}", chart_svg)
    rendered = rendered.replace("{{TABLE_ROWS}}", table_rows)
    return rendered
