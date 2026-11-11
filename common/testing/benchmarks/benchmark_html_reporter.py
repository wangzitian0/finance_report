"""Benchmark HTML Reporter and Dashboard Generator."""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from common.testing.benchmarks._html_templates import (
    DASHBOARD_HTML_TEMPLATE,
    REPORT_HTML_TEMPLATE,
)
from common.testing.benchmarks.case_types import (
    FLOW_TO_CASES,
    FLOW_TO_DOMAIN,
    get_case_to_flows,
)

MISSING = "n/a"
UNKNOWN = "UNKNOWN"
PASS = "PASS"
FAIL = "FAIL"
NOT_RUN = "NOT RUN"
EQUATION_DELTA_KEYS = ("equation_delta", "equation_delta_sgd", "equation_delta_usd")
DELTA_CURRENCY = {
    "equation_delta": "SGD",
    "equation_delta_sgd": "SGD",
    "equation_delta_usd": "USD",
}
DELTA_FIXED_MIN = Decimal("1E-6")
DELTA_FIXED_MAX = Decimal("1E+12")
COUNT_LIMIT = DURATION_LIMIT = 10**9
IDENTITY_CASE_IDS = tuple(f"case_{case}" for case in FLOW_TO_CASES[23])
CASE_DELTA_KEYS = {
    "case_1": ("equation_delta",),
    "case_2": ("equation_delta",),
    "case_3": ("equation_delta",),
    "case_4": ("equation_delta_sgd", "equation_delta_usd"),
    "case_5": ("equation_delta",),
    "case_6": ("equation_delta",),
}
SUMMARY_FLAG_CASES = (
    ("zero_pnl_contamination", "case_3"),
    ("rollforward_balanced", "case_1"),
    ("multicurrency_consolidated", "case_4"),
    ("portfolio_holdings_verified", "case_5"),
    ("overdraft_articulation_verified", "case_6"),
)
TELEMETRY_DEPTH_LIMIT = 50
NO_FIGURES = "<p>No figures recorded. The case stopped before it recorded any.</p>"
NO_TABLE_FIGURES = "<p>No assertion table figures recorded. Inspect Raw Adjudication Telemetry below.</p>"
UNCONFIRMED = "❌ Unconfirmed"
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
_SURROGATE = re.compile(r"[\ud800-\udfff]")
_ISO_SUBSECOND = re.compile(r"(\d{2}:\d{2}:\d{2})\.\d+")
Row = tuple[str, str | None, str, str]


def _clean_surrogates(text: str) -> str:
    return _SURROGATE.sub("\ufffd", text)


def _safe_int_str(value: int) -> str:
    try:
        return str(value)
    except ValueError:
        return hex(value)


def sanitize_for_json(value: Any, _depth: int = 0) -> Any:
    if _depth > TELEMETRY_DEPTH_LIMIT:
        return "<depth-limit-exceeded>"
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        try:
            str(value)
            return value
        except ValueError:
            return _safe_int_str(value)
    if isinstance(value, float):
        return value if _number_text(value) is not None else str(value)
    if isinstance(value, (Decimal, str)):
        return _clean_surrogates(str(value))
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str):
                ks = _clean_surrogates(k)
            elif isinstance(k, int) and not isinstance(k, bool):
                ks = _safe_int_str(k)
            else:
                try:
                    ks = _clean_surrogates(str(k))
                except ValueError:
                    ks = repr(type(k).__name__)
            out[ks] = sanitize_for_json(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_for_json(item, _depth + 1) for item in value]
    try:
        return _clean_surrogates(str(value))
    except ValueError:
        return repr(type(value).__name__)


def write_utf8_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_bytes = _clean_surrogates(content).encode("utf-8", errors="replace")
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(clean_bytes)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _fill(template: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def _details_of(result: dict[str, Any]) -> dict[str, Any]:
    d = result.get("details")
    return d if isinstance(d, dict) else {}


def _case_id(result: dict[str, Any]) -> str | None:
    cid = result.get("case_id")
    return cid if isinstance(cid, str) and cid else None


def _recorded(details: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        val = details.get(key)
        if val is not None and val != "":
            return val
    return None


def _number_text(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        raw = str(value).strip()
        cleaned = raw.replace(",", "") if isinstance(value, str) else raw
        num = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    return _clean_surrogates(cleaned) if num.is_finite() else None


def _number(value: Any) -> Decimal | None:
    t = _number_text(value)
    return None if t is None else Decimal(t)


def _text_value(value: Any) -> str | None:
    if isinstance(value, str):
        c = _clean_surrogates(value)
        return c if c else None
    return _number_text(value)


def _show(value: Any) -> str:
    t = _text_value(value)
    return MISSING if t is None else html.escape(t)


def _figure(details: dict[str, Any], *keys: str) -> str | None:
    return _number_text(_recorded(details, *keys))


def _text(details: dict[str, Any], *keys: str) -> str | None:
    return _text_value(_recorded(details, *keys))


def _whole_number(value: Any) -> int | None:
    n = _number(value)
    if n is None or not 0 <= n <= COUNT_LIMIT or n != n.to_integral_value():
        return None
    return int(n)


def _count(value: Any) -> str:
    n = _whole_number(value)
    return MISSING if n is None else str(n)


def _percent(part: Any, whole: Any) -> str:
    num, den = _whole_number(part), _whole_number(whole)
    if num is None or not den or num > den:
        return MISSING
    share = (200 * num + den) // (2 * den)
    return f"{min(max(share, 1), 99) if 0 < num < den else share}%"


def _cases(count: int) -> str:
    return f"{count} case" if count == 1 else f"{count} cases"


def _seconds_or_none(value: Any) -> float | None:
    n = _number(value)
    return abs(float(n)) if n is not None and 0 <= n <= DURATION_LIMIT else None


def _duration_text(value: Any) -> str:
    s = _seconds_or_none(value)
    return MISSING if s is None else f"{s:.2f}s"


def _total_seconds(results: list[dict[str, Any]]) -> float | None:
    if not results:
        return None
    durs = [_seconds_or_none(r.get("duration_seconds")) for r in results]
    return (
        None if any(s is None for s in durs) else sum(s for s in durs if s is not None)
    )


def _href(url: str) -> str:
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        return "#"
    return html.escape(url) if scheme in ("", "http", "https") else "#"


def _format_number(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    size = value.copy_abs()
    if size == 0 or (
        DELTA_FIXED_MIN <= size < DELTA_FIXED_MAX and len(size.as_tuple().digits) <= 28
    ):
        rounded = size.quantize(Decimal("0.01"))
        return sign + (str(rounded) if rounded == size else format(size, "f"))
    return f"{sign}{size:.3E}"


def _formatted(value: Decimal | None) -> str | None:
    return None if value is None else _format_number(value)


def _money(text: str | None, *, signed: bool = False) -> str | None:
    if text is None:
        return None
    num = Decimal(text)
    digits = text.lstrip("+-")
    if num < 0:
        return f"-${digits}"
    return f"+${digits}" if signed and num > 0 else f"${digits}"


def _recorded_deltas(results: list[dict[str, Any]]) -> list[tuple[Decimal, str]]:
    return [
        (val.copy_abs(), DELTA_CURRENCY[k])
        for r in results
        for k in EQUATION_DELTA_KEYS
        if (val := _number(_details_of(r).get(k))) is not None
    ]


def _largest_delta(results: list[dict[str, Any]]) -> tuple[str, str]:
    found = _recorded_deltas(results)
    if not found:
        return MISSING, ""
    val, ccy = max(found, key=lambda item: item[0])
    return _format_number(val), ccy


def _delta_text(results: list[dict[str, Any]]) -> str:
    val, ccy = _largest_delta(results)
    return f"{val} {ccy}" if ccy else MISSING


def _recorded_delta_count(results: list[dict[str, Any]]) -> int:
    return sum(1 for r in results if _recorded_deltas([r]))


def _effective_case_status(result: dict[str, Any] | None) -> str | None:
    if not result:
        return None
    status = _text_value(result.get("status"))
    if status == PASS and any(sz != 0 for sz, _ in _recorded_deltas([result])):
        return FAIL
    return status


def _verdict(cases: list[dict[str, Any] | None]) -> str:
    statuses = [_effective_case_status(c) for c in cases]
    if not statuses:
        return NOT_RUN
    if any(s not in (None, "SKIPPED", PASS) for s in statuses):
        return FAIL
    return NOT_RUN if any(s in (None, "SKIPPED") for s in statuses) else PASS


def _cases_by_id(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        if (cid := _case_id(r)) is not None:
            groups.setdefault(cid, []).append(r)
    return {
        cid: next(rec for rec in grp if _verdict([rec]) == _verdict(grp))
        for cid, grp in groups.items()
    }


def _badge(kind: str, text: str) -> str:
    return f'<span class="badge badge-{kind}">{html.escape(text)}</span>'


def _status_badge_class(status_text: str) -> str:
    if status_text == PASS:
        return "badge-pass"
    return (
        "badge-skip" if status_text in ("SKIPPED", UNKNOWN, NOT_RUN) else "badge-fail"
    )


def _render_invariants_rows(by_id: dict[str, dict[str, Any]]) -> str:
    id_cases = [by_id.get(cid) for cid in IDENTITY_CASE_IDS]
    id_present = [by_id[cid] for cid in IDENTITY_CASE_IDS if cid in by_id]
    id_rec = _recorded_delta_count(id_present)
    needed = _cases(len(IDENTITY_CASE_IDS))
    id_obs = (
        f"Largest recorded |Δ| is {_delta_text(id_present)}, recorded by {id_rec} of {needed}"
        if id_rec
        else f"No delta recorded by any of the {needed}"
    )
    c1, c3 = by_id.get("case_1"), by_id.get("case_3")
    d1, d3 = _details_of(c1 or {}), _details_of(c3 or {})
    closings = ", ".join(
        _figure(d1, f"m{n}_closing_balance", f"month_{n}_ending_balance") or MISSING
        for n in (1, 2, 3, 4)
    )
    spend = _figure(d3, "card_spend_recorded") or MISSING
    repay = _figure(d3, "bank_repayment") or MISSING
    ni = _figure(d3, "net_income") or MISSING
    cum = _figure(d1, "cumulative_net_income") or MISSING
    rows = (
        (
            "Balance Sheet Identity",
            "Assets ≡ Liabilities + Equity + Net Income",
            id_obs,
            id_cases,
        ),
        (
            "Temporal Multi-Period Rollforward",
            "Month_{n+1} Opening Cash ≡ Month_n Closing Cash",
            f"Closing balances of months 1 to 4: {closings}",
            [c1],
        ),
        (
            "Credit Card Liability Clearance (No Double Counting)",
            "Card spend recorded once; repayment moves cash and liability only",
            f"Card spend {spend}, bank repayment {repay}, net income {ni}",
            [c3],
        ),
        (
            "Retained Earnings Articulation",
            "Closing Equity = Opening Equity + Net Income",
            f"Cumulative net income {cum}",
            [c1],
        ),
    )
    return "".join(
        f"<tr><td><strong>{html.escape(name)}</strong></td>"
        f"<td><code>{html.escape(formula)}</code></td>"
        f"<td>{html.escape(obs)}</td>"
        f"<td>{_badge({PASS: 'pass', FAIL: 'fail'}.get(v := _verdict(cs), 'skip'), v)}</td></tr>"
        for name, formula, obs, cs in rows
    )


def _summary_of(report_data: Any) -> dict[str, Any]:
    s = report_data.get("summary") if isinstance(report_data, dict) else None
    return s if isinstance(s, dict) else {}


def _results_of(report_data: Any) -> list[dict[str, Any]]:
    res = report_data.get("results") if isinstance(report_data, dict) else None
    return [r for r in res if isinstance(r, dict)] if isinstance(res, list) else []


def _derived_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    statuses = [_effective_case_status(r) for r in results]
    passed, skipped = statuses.count(PASS), statuses.count("SKIPPED")
    return {
        "total": len(results),
        "passed": passed,
        "skipped": skipped,
        "failed": len(results) - passed - skipped,
    }


def _summary_disagreement(
    report_data: Any, results: list[dict[str, Any]]
) -> str | None:
    if not isinstance(report_data, dict) or not isinstance(
        report_data.get("summary"), dict
    ):
        return None
    summary, derived = _summary_of(report_data), _derived_counts(results)
    mismatches = [
        f"summary.{k}={_text_value(summary.get(k)) or summary.get(k)!r} vs results.{k}={derived[k]}"
        for k in ("total", "passed", "skipped", "failed")
        if k in summary
        and summary.get(k) is not None
        and _whole_number(summary.get(k)) != derived[k]
    ]
    if summary.get("success") is True and (
        derived["total"] == 0 or derived["passed"] == 0 or derived["failed"] > 0
    ):
        mismatches.append(
            f"summary.success=True vs results(passed={derived['passed']}, failed={derived['failed']}, total={derived['total']})"
        )
    return "; ".join(mismatches) if mismatches else None


def _report_counts(report_data: Any) -> dict[str, int]:
    results = _results_of(report_data)
    derived = _derived_counts(results)
    if results or _summary_disagreement(report_data, results) is not None:
        return derived
    summary = _summary_of(report_data)
    return {
        k: fb if (rec := _whole_number(summary.get(k))) is None else rec
        for k, fb in derived.items()
    }


def _run_passed(
    report_data: Any, counts: dict[str, int], results: list[dict[str, Any]]
) -> bool:
    failed_res = sum(
        1 for r in results if _effective_case_status(r) not in (PASS, "SKIPPED")
    )
    return (
        _summary_of(report_data).get("success") is True
        and _summary_disagreement(report_data, results) is None
        and counts["total"] >= 1
        and counts["passed"] >= 1
        and counts["failed"] == 0
        and counts["passed"] + counts["skipped"] == counts["total"]
        and failed_res == 0
    )


def extract_summary_data(report_data: Any) -> dict[str, Any]:
    rd = report_data if isinstance(report_data, dict) else {}
    results = _results_of(rd)
    counts = _report_counts(rd)
    by_id = _cases_by_id(results)
    version = _text_value(rd.get("version_ref"))
    total_sec = _total_seconds(results)
    passed_ids = {cid for cid, c in by_id.items() if _verdict([c]) == PASS}
    c2f = get_case_to_flows()
    flows = {f for cid in passed_ids for f in c2f.get(cid, ())}
    domains = {FLOW_TO_DOMAIN[f] for f in flows if f in FLOW_TO_DOMAIN}
    status = (
        UNKNOWN
        if not isinstance(report_data, dict)
        or not isinstance(report_data.get("summary"), dict)
        else (PASS if _run_passed(rd, counts, results) else FAIL)
    )
    max_val, max_ccy = _largest_delta(results)
    return {
        "version": version,
        "run_at": _text_value(rd.get("run_at")) or "",
        "app_url": _text_value(rd.get("app_url")) or "",
        "status": status,
        "cases_total": counts["total"],
        "cases_passed": counts["passed"],
        "cases_skipped": counts["skipped"],
        "cases_failed": counts["failed"],
        "duration_seconds": None if total_sec is None else round(total_sec, 2),
        "max_equation_delta": max_val,
        "max_equation_delta_currency": max_ccy,
        **{
            flag: _verdict([by_id.get(cid)]) == PASS for flag, cid in SUMMARY_FLAG_CASES
        },
        "thirty_flows_coverage": f"{len(flows)}/30",
        "domains_covered": len(domains),
        "report_url": None if version is None else f"{version}/report.html",
    }


def _drift_note(
    results: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]
) -> tuple[str, str]:
    deltas = _recorded_deltas(results)
    if not deltas:
        return "not recorded", "metric-diff-neutral"
    drift = any(sz != 0 for sz, _ in deltas)
    id_rec = _recorded_delta_count(
        [by_id[cid] for cid in IDENTITY_CASE_IDS if cid in by_id]
    )
    if drift and id_rec == len(IDENTITY_CASE_IDS):
        return "Drift", "metric-diff-worse"
    bal_cases = [by_id.get(cid) for cid in CASE_DELTA_KEYS]
    complete = all(
        _number(_details_of(c or {}).get(k)) is not None
        for c, ks in zip(bal_cases, CASE_DELTA_KEYS.values())
        for k in ks
    )
    if drift or not complete:
        return "not recorded for every balance case", "metric-diff-neutral"
    if _verdict(bal_cases) != PASS:
        return "not every balance case passed", "metric-diff-neutral"
    return "Zero Drift", "metric-diff-better"


def _render_diff_section(
    baseline_data: Any,
    total_seconds: float | None,
    counts: dict[str, int],
    results: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> str:
    if not isinstance(baseline_data, dict) or not baseline_data:
        return ""
    b_sec = _seconds_or_none(
        _summary_of(baseline_data).get("total_duration_seconds")
    ) or _total_seconds(_results_of(baseline_data))
    if b_sec is None:
        b_sec = _seconds_or_none(
            _summary_of(baseline_data).get("total_duration_seconds")
        )
    dur_text = MISSING if total_seconds is None else f"{total_seconds:.2f}s"
    if total_seconds is None or b_sec is None:
        dur_diff_text, dur_cls = MISSING, "metric-diff-neutral"
    else:
        diff = total_seconds - b_sec
        r = round(diff, 2)
        dur_diff_text = f"{'+' if r > 0 else '-' if r < 0 else ''}{abs(r):.2f}s"
        dur_cls = (
            "metric-diff-worse"
            if diff > 5
            else ("metric-diff-better" if diff < -5 else "metric-diff-neutral")
        )
    tot, pas = counts["total"], counts["passed"]
    pass_cls = (
        "metric-diff-neutral"
        if not tot
        else ("metric-diff-better" if pas == tot else "metric-diff-worse")
    )
    d_note, d_cls = _drift_note(results, by_id)
    return (
        f'<div class="card baseline-card"><h3>⚖️ Baseline Comparison (vs {_show(baseline_data.get("version_ref"))})</h3>'
        f'<div class="grid grid-3">'
        f'<div class="stat-box"><span class="stat-label">Execution Time</span><span class="stat-value">{dur_text} <small class="{dur_cls}">({dur_diff_text})</small></span></div>'
        f'<div class="stat-box"><span class="stat-label">Pass Rate</span><span class="stat-value">{pas}/{tot} <small class="{pass_cls}">({_percent(pas, tot)})</small></span></div>'
        f'<div class="stat-box"><span class="stat-label">Max Equation Delta</span><span class="stat-value">{_delta_text(results)} <small class="{d_cls}">({d_note})</small></span></div>'
        f"</div></div>"
    )


def _row_verdict_state(
    details: dict[str, Any], passed: bool, value_present: bool, *keys: str
) -> str:
    verdicts = details.get("assertion_verdicts")
    if isinstance(verdicts, dict):
        for k in keys:
            raw = verdicts.get(k)
            if raw in ("passed", True):
                return "passed" if value_present else "not_run"
            if raw in ("failed", False):
                return "failed"
            if raw == "not_run":
                return "not_run"
        return "not_run"
    if not value_present:
        return "not_run"
    return "passed" if passed else "failed"


def _check_row(
    details: dict[str, Any], passed: bool, confirmed: str, value: Any, *keys: str
) -> str:
    st = _row_verdict_state(details, passed, value is not None, *keys)
    return (
        html.escape(f"✅ {confirmed}")
        if st == "passed"
        else (UNCONFIRMED if st == "failed" else MISSING)
    )


def _delta_badge(
    delta: Decimal | None,
    unit: str,
    passed: bool,
    broken: str | None = None,
    *,
    details: dict[str, Any] | None = None,
    keys: tuple[str, ...] = ("equation_delta",),
) -> str:
    if delta is not None and delta != 0:
        msg = (
            f"{_format_number(delta)} {unit} {broken}"
            if broken
            else f"❌ {_format_number(delta)} {unit} Regression"
        )
        return _badge("fail", msg)
    if delta is None:
        if (
            details is not None
            and _row_verdict_state(details, passed, False, *keys) == "failed"
        ):
            return _badge("fail", f"❌ {unit} Equation Broken")
        return (
            _badge("pass", f"Balanced ({unit} Δ not recorded)")
            if passed
            else _badge("skip", f"{unit} Δ not recorded")
        )
    if details is not None:
        st = _row_verdict_state(details, passed, True, *keys)
        if st == "passed":
            return _badge("pass", f"✅ {_format_number(delta)} {unit} Balanced")
        if st == "failed":
            msg = (
                f"{_format_number(delta)} {unit} {broken}"
                if broken
                else f"❌ {_format_number(delta)} {unit} Unconfirmed"
            )
            return _badge("fail", msg)
        return _badge("skip", f"{_format_number(delta)} {unit} No difference recorded")
    return (
        _badge("pass", f"✅ {_format_number(delta)} {unit} Balanced")
        if passed
        else _badge("skip", f"{_format_number(delta)} {unit} No difference recorded")
    )


def _has_recorded_telemetry(details: dict[str, Any]) -> bool:
    for k, val in details.items():
        if k == "assertion_verdicts":
            if isinstance(val, dict) and any(v != "not_run" for v in val.values()):
                return True
        elif val is not None and val != "":
            return True
    return False


def _table(
    headers: tuple[str, str, str],
    rows: list[Row],
    passed: bool,
    details: dict[str, Any] | None = None,
) -> str:
    if not passed and all(val is None for _, val, _, _ in rows):
        return (
            NO_TABLE_FIGURES
            if (details and _has_recorded_telemetry(details))
            else NO_FIGURES
        )
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        f"<tr><td>{html.escape(lbl)}</td>"
        f"<td>{MISSING if val is None else html.escape(f'{val} {u}' if u else val)}</td>"
        f"<td>{vrd}</td></tr>"
        for lbl, val, u, vrd in rows
    )
    return f'<table class="data-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _m_row(
    details: dict[str, Any],
    passed: bool,
    label: str,
    confirmed: str,
    *keys: str,
    unit: str = "",
    signed: bool = False,
    money: bool = True,
    text: bool = False,
) -> Row:
    raw = _text(details, *keys) if text else _figure(details, *keys)
    val = _money(raw, signed=signed) if (money and not text) else raw
    return (label, val, unit, _check_row(details, passed, confirmed, val, *keys))


def _d_row(
    details: dict[str, Any],
    passed: bool,
    label: str,
    unit: str,
    *keys: str,
    broken: str | None = None,
) -> Row:
    d = _number(details.get(keys[0]))
    return (
        label,
        _money(_formatted(d)),
        unit,
        _delta_badge(d, unit, passed, broken=broken, details=details, keys=keys),
    )


def _render_case_1_table(d: dict[str, Any], p: bool) -> str:
    return _table(
        ("Financial Assertion", "Value (SGD)", "Reconciliation Status"),
        [
            _m_row(
                d,
                p,
                "Month 1 (Jan 2025) Ending Balance",
                "Anchor Confirmed",
                "m1_closing_balance",
                "month_1_ending_balance",
            ),
            _m_row(
                d,
                p,
                "Month 2 (Feb 2025) Ending Balance",
                "Exact Continuity Rollforward",
                "m2_closing_balance",
                "month_2_ending_balance",
            ),
            _m_row(
                d,
                p,
                "Month 3 (Mar 2025 - Q1 Close) Ending Balance",
                "Q1 Continuity Confirmed",
                "m3_closing_balance",
                "month_3_ending_balance",
            ),
            _m_row(
                d,
                p,
                "Month 4 (Apr 2025 - Q2 Transition) Ending Balance",
                "4-Month Rollforward Intact",
                "m4_closing_balance",
                "month_4_ending_balance",
            ),
            _m_row(
                d,
                p,
                "Q1 Cumulative Net Income",
                "Articulated to Q1 Retained Earnings",
                "q1_net_income",
            ),
            _m_row(
                d,
                p,
                "4-Month Cumulative Net Income",
                "Articulated to Retained Earnings",
                "cumulative_net_income",
            ),
            _d_row(
                d,
                p,
                "Balance Sheet Equation Delta (A - L - E)",
                "SGD",
                "equation_delta",
            ),
        ],
        p,
        d,
    )


def _render_case_2_table(d: dict[str, Any], p: bool) -> str:
    return _table(
        ("Financial Assertion", "Value (SGD)", "Reconciliation Status"),
        [
            _m_row(
                d,
                p,
                "Husband Account (DBS Bank) Ending Cash",
                "Source Account Reconciled",
                "household_husband_cash",
            ),
            _m_row(
                d,
                p,
                "Wife Account (Standard Chartered) Ending Cash",
                "Multi-PII Account Reconciled",
                "household_wife_cash",
            ),
            _m_row(
                d,
                p,
                "Consolidated Operating Revenue",
                "Combined Inflow Reconciled",
                "total_income",
                signed=True,
            ),
            _m_row(
                d,
                p,
                "Consolidated Operating Expenses",
                "Family Expenses Categorized",
                "total_expenses",
                signed=True,
            ),
            _m_row(
                d,
                p,
                "Consolidated Net Operating Income",
                "P&L Sum Reconciled",
                "net_income",
                signed=True,
            ),
            _m_row(
                d,
                p,
                "Consolidated Total Liquid Cash",
                "Cash Flow Ending Cash Conserved",
                "ending_cash",
                "closing_balance",
            ),
            _d_row(d, p, "Balance Sheet Equation Delta", "SGD", "equation_delta"),
        ],
        p,
        d,
    )


def _render_case_3_table(d: dict[str, Any], p: bool) -> str:
    ni = _figure(d, "net_income")
    st = _row_verdict_state(d, p, ni is not None, "net_income")
    pnl_b = (
        _badge("pass", "✅ Zero Double-Counting (Pure Liability Clearance)")
        if st == "passed"
        else (_badge("fail", "❌ Unconfirmed") if st == "failed" else MISSING)
    )
    return _table(
        ("Financial Assertion", "Value (SGD)", "Reconciliation Status"),
        [
            _m_row(
                d,
                p,
                "Credit Card Incurred Charges (Liability Incurrence)",
                "Card Expense & Liability Tracked",
                "card_spend_recorded",
                signed=True,
            ),
            _m_row(
                d,
                p,
                "Bank Account Settlement Payment Outflow",
                "Bank Cash Outflow Tracked",
                "bank_repayment",
                signed=True,
            ),
            _m_row(
                d,
                p,
                "Credit Card Liability Ending Balance",
                "Liability Fully Cleared",
                "credit_card_liability_cleared",
            ),
            _m_row(
                d,
                p,
                "Ending Bank Liquid Cash Balance",
                "Cash Balance Conserved",
                "ending_bank_cash",
                "total_assets",
            ),
            ("P&L Double-Counting Prevention (Net Income)", _money(ni), "", pnl_b),
            _d_row(d, p, "Balance Sheet Equation Delta", "SGD", "equation_delta"),
        ],
        p,
        d,
    )


def _render_case_4_table(d: dict[str, Any], p: bool) -> str:
    return _table(
        ("Financial Assertion", "Amount", "Multi-Currency Status"),
        [
            _m_row(
                d,
                p,
                "Singapore Jurisdiction (SGD Account)",
                "Local Inflow Verified",
                "sgd_closing_balance",
                unit="SGD",
                money=False,
            ),
            _m_row(
                d,
                p,
                "United States Jurisdiction (USD Account)",
                "Foreign Currency Inflow Verified",
                "usd_closing_balance",
                unit="USD",
                money=False,
            ),
            _m_row(
                d,
                p,
                "Hong Kong Jurisdiction (HKD Account)",
                "Foreign Currency Inflow Verified",
                "hkd_closing_balance",
                unit="HKD",
                money=False,
            ),
            _m_row(
                d,
                p,
                "Consolidated Total Assets (SGD Base)",
                "Unified Multi-Currency Conversion",
                "total_assets_sgd",
                unit="SGD",
            ),
            _d_row(
                d,
                p,
                "SGD Balance Sheet Equation Delta",
                "SGD",
                "equation_delta_sgd",
                "equation_delta",
            ),
            _d_row(
                d, p, "USD Balance Sheet Equation Delta", "USD", "equation_delta_usd"
            ),
        ],
        p,
        d,
    )


def _render_case_5_table(d: dict[str, Any], p: bool) -> str:
    app = _text(d, "appraisal_source") or MISSING
    return _table(
        ("Financial Assertion", "Value", "Portfolio Status"),
        [
            _m_row(
                d,
                p,
                "Public Securities Tracked",
                "Position Snapshots Recognized",
                "symbols",
                text=True,
            ),
            _m_row(
                d,
                p,
                "Managed Holdings Count",
                "Atomic & Managed Reconciliation Intact",
                "holdings_count",
                unit="Assets",
                money=False,
            ),
            _m_row(
                d,
                p,
                "Real Estate Property Appraisal",
                app,
                "property_valuation_usd",
                unit="USD",
            ),
            _m_row(
                d,
                p,
                "Tax & Compensation Integration",
                "DocuBench Tax Fixtures Integrated",
                "tax_ecosystem_status",
                text=True,
            ),
            _m_row(
                d,
                p,
                "Consolidated Wealth Valuation",
                "Fair Market Valuation Reflected",
                "total_assets",
                unit="SGD",
            ),
            _d_row(d, p, "Balance Sheet Equation Delta", "SGD", "equation_delta"),
        ],
        p,
        d,
    )


def _render_case_6_table(d: dict[str, Any], p: bool) -> str:
    return _table(
        ("Accounting Invariant", "Reported Metric", "Integrity Check"),
        [
            _m_row(
                d,
                p,
                "Overdraft Checkpoint Cash Balance",
                "Negative Balance Equation Validated",
                "overdraft_cash",
                "ending_cash_balance",
                unit="SGD",
            ),
            _m_row(
                d,
                p,
                "Realized Capital Gain from Art Disposal",
                "Capital Gain Recognized in P&L",
                "capital_gain",
                unit="SGD",
                signed=True,
            ),
            _m_row(
                d,
                p,
                "Final Period Net Income",
                "Expense Offset by Capital Gain",
                "net_income",
                unit="SGD",
            ),
            _m_row(
                d,
                p,
                "Final Period Total Assets",
                "Ending Assets Reconciled",
                "total_assets",
                "ending_cash_balance",
                "ending_cash",
                unit="SGD",
            ),
            _m_row(
                d,
                p,
                "Final Period Total Equity",
                "Ending Equity Reconciled",
                "total_equity",
                unit="SGD",
            ),
            _d_row(
                d,
                p,
                "Balance Sheet Equation Delta",
                "SGD",
                "equation_delta",
                broken="❌ Equation Broken",
            ),
        ],
        p,
        d,
    )


CASE_TABLES = {
    "case_1": _render_case_1_table,
    "case_2": _render_case_2_table,
    "case_3": _render_case_3_table,
    "case_4": _render_case_4_table,
    "case_5": _render_case_5_table,
    "case_6": _render_case_6_table,
}


def _nests_deeper_than(value: Any, limit: int) -> bool:
    pending = [(value, 1)]
    while pending:
        item, lvl = pending.pop()
        if isinstance(item, (dict, list, tuple, set, frozenset)):
            if lvl > limit:
                return True
            children = item.values() if isinstance(item, dict) else item
            pending.extend((c, lvl + 1) for c in children)
    return False


def _telemetry(details: dict[str, Any]) -> str:
    if _nests_deeper_than(details, TELEMETRY_DEPTH_LIMIT):
        return (
            f"Not shown: the details nest deeper than {TELEMETRY_DEPTH_LIMIT} levels."
        )
    return html.escape(json.dumps(sanitize_for_json(details), indent=2))


def _render_case_details(cid: str | None, details: dict[str, Any], status: Any) -> str:
    if status == "SKIPPED":
        return "<p>Not run: the case did not run.</p>"
    passed = status == PASS and not any(
        sz != 0
        for k in EQUATION_DELTA_KEYS
        if (sz := _number(details.get(k))) is not None
    )
    if (render := CASE_TABLES.get(cid or "")) is not None:
        return render(details, passed)
    if not passed and not _has_recorded_telemetry(details):
        return NO_FIGURES
    return f"<pre class='raw-json'>{_telemetry(details)}</pre>"


def _render_scenario_cards(results: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for r in results:
        cid = _case_id(r)
        cid_tag = html.escape(cid.upper()) if cid else UNKNOWN
        eff = _effective_case_status(r)
        raw_st = _text_value(eff) or UNKNOWN
        cdetails = _details_of(r)
        err = _text_value(r.get("error_message"))
        err_html = (
            f"<div class='error-banner'><strong>Error:</strong> {html.escape(err)}</div>"
            if err
            else ""
        )
        cards.append(
            f'<div class="card scenario-card"><div class="scenario-header"><div>'
            f'<span class="case-tag">{cid_tag}</span><h3 class="scenario-title">{_show(r.get("case_name"))}</h3></div>'
            f'<div class="scenario-meta"><span class="duration-tag">⏱️ {_duration_text(r.get("duration_seconds"))}</span>'
            f'<span class="badge {_status_badge_class(raw_st)}">{html.escape(raw_st)}</span></div></div>'
            f"{err_html}{_render_case_details(cid, cdetails, eff)}"
            f'<details class="raw-details"><summary>Inspect Raw Adjudication Telemetry</summary>'
            f'<pre class="raw-json">{_telemetry(cdetails)}</pre></details></div>'
        )
    return "".join(cards)


def generate_html_report(report_data: Any, baseline_data: Any = None) -> str:
    rd = report_data if isinstance(report_data, dict) else {}
    results = _results_of(rd)
    counts = _report_counts(rd)
    by_id = _cases_by_id(results)
    not_passed = sum(1 for r in results if _effective_case_status(r) != PASS)
    run_passed = _run_passed(rd, counts, results)
    disagreement = _summary_disagreement(rd, results)
    all_passed = (
        run_passed
        and counts["passed"] == counts["total"]
        and counts["skipped"] == 0
        and not_passed == 0
    )
    if disagreement is not None:
        status_text = f"SUMMARY COUNT MISMATCH ({disagreement}) — {counts['passed']} OF {counts['total']} SCENARIOS PASSED"
        if counts["skipped"]:
            status_text += f", {counts['skipped']} SKIPPED"
    elif all_passed:
        status_text = f"ALL {counts['total']} SCENARIOS PASSED"
    else:
        status_text = f"{counts['passed']} OF {counts['total']} SCENARIOS PASSED"
        if counts["skipped"]:
            status_text += f", {counts['skipped']} SKIPPED"
    total_sec = _total_seconds(results)
    return _fill(
        REPORT_HTML_TEMPLATE,
        {
            "VERSION": _show(rd.get("version_ref")),
            "APP_URL": _show(rd.get("app_url")),
            "RUN_AT": _show(rd.get("run_at")),
            "STATUS_BADGE_CLASS": "badge-pass" if run_passed else "badge-fail",
            "STATUS_TEXT": html.escape(status_text),
            "PASSED_COUNT": str(counts["passed"]),
            "TOTAL_COUNT": str(counts["total"]),
            "TOTAL_DURATION_STR": MISSING if total_sec is None else f"{total_sec:.2f}s",
            "MAX_DELTA": _delta_text(results),
            "DELTA_COVERAGE": f"recorded by {_recorded_delta_count(results)} of {_cases(len(results))}",
            "NOT_PASSED_COUNT": str(not_passed),
            "INVARIANTS_ROWS": _render_invariants_rows(by_id),
            "DIFF_HTML": _render_diff_section(
                baseline_data, total_sec, counts, results, by_id
            ),
            "SCENARIOS_HTML": _render_scenario_cards(results),
        },
    )


def _run_time_key(run: dict[str, Any]) -> tuple[bool, Any]:
    text = _text_value(run.get("run_at")) or ""
    try:
        m = datetime.fromisoformat(text)
    except ValueError:
        return False, text
    return True, m if m.tzinfo is not None else m.replace(tzinfo=UTC)


def _delta_cell(run: dict[str, Any]) -> str:
    val = _number(run.get("max_equation_delta"))
    if val is None:
        return MISSING
    ccy = _text_value(run.get("max_equation_delta_currency")) or "SGD"
    return f"{_format_number(val)} {html.escape(ccy)}"


def _report_href(run: dict[str, Any]) -> str:
    url = _text_value(run.get("report_url"))
    if url is None:
        ver = _text_value(run.get("version"))
        if ver is None:
            return "#"
        url = f"{ver}/report.html"
    return _href(url)


def _format_run_date(value: Any) -> str:
    t = _text_value(value)
    return (
        MISSING
        if t is None
        else html.escape(_ISO_SUBSECOND.sub(r"\1", t.replace("T", " ")))
    )


def _render_dashboard_table_rows(sorted_runs: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for r in sorted_runs:
        v = html.escape(_text_value(r.get("version")) or MISSING)
        st_txt = _text_value(r.get("status")) or UNKNOWN
        url = _report_href(r)
        rows.append(
            f'<tr><td><a href="{url}" class="version-link"><strong>{v}</strong></a></td>'
            f'<td><span class="badge {_status_badge_class(st_txt)}">{html.escape(st_txt)}</span></td>'
            f"<td>{_format_run_date(r.get('run_at'))}</td>"
            f'<td><code class="env-code">{_show(r.get("app_url"))}</code></td>'
            f"<td>{_count(r.get('cases_passed'))} / {_count(r.get('cases_total'))}</td>"
            f"<td>{_duration_text(r.get('duration_seconds'))}</td>"
            f"<td>{_delta_cell(r)}</td>"
            f'<td><a href="{url}" class="btn-view">View Report →</a></td></tr>'
        )
    return "".join(rows)


def _render_dashboard_trend_svg(sorted_runs: list[dict[str, Any]]) -> str:
    if not sorted_runs:
        return ""
    chrono = list(reversed(sorted_runs[:10]))
    durs = [_seconds_or_none(r.get("duration_seconds")) for r in chrono]
    peak = max((d for d in durs if d is not None), default=None)
    w, h, pad = 700, 160, 40
    base = h - pad
    segments: list[list[str]] = [[]]
    dots: list[str] = []
    labels: list[str] = []
    for i, (run, sec) in enumerate(zip(chrono, durs)):
        x = pad + (i * (w - 2 * pad) / (len(chrono) - 1)) if len(chrono) > 1 else w / 2
        lbl = html.escape(_text_value(run.get("version")) or MISSING)
        labels.append(
            f'<text x="{x:.1f}" y="{h - 10}" font-size="11" fill="#cbd5e1" text-anchor="middle">{lbl}</text>'
        )
        if sec is None:
            segments.append([])
            dots.append(
                f'<text x="{x:.1f}" y="{base - 10:.1f}" font-size="11" fill="#94a3b8" text-anchor="middle">{MISSING}</text>'
            )
            continue
        y = base - (sec / peak * (h - 2 * pad) if peak else 0.0)
        segments[-1].append(f"{x:.1f},{y:.1f}")
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#3b82f6" stroke="#fff" stroke-width="2"/>'
            f'<text x="{x:.1f}" y="{y - 10:.1f}" font-size="11" fill="#94a3b8" text-anchor="middle">{sec:.1f}s</text>'
        )
    polys = "".join(
        f'<polyline fill="none" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="{" ".join(pts)}"/>'
        for pts in segments
        if pts
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" class="trend-svg">'
        f'<line x1="{pad}" y1="{base}" x2="{w - pad}" y2="{base}" stroke="#334155" stroke-width="1"/>'
        f"{polys}{''.join(dots)}{''.join(labels)}</svg>"
    )


def generate_index_dashboard(manifest_data: Any) -> str:
    runs = (
        [r for r in manifest_data if isinstance(r, dict)]
        if isinstance(manifest_data, (list, tuple))
        else []
    )
    sorted_runs = sorted(runs, key=_run_time_key, reverse=True)
    has_run = bool(sorted_runs)
    latest = sorted_runs[0] if has_run else {}
    ver_txt = _text_value(latest.get("version")) or MISSING
    st_txt = _text_value(latest.get("status")) or UNKNOWN
    passed = _count(latest.get("cases_passed"))
    total = _count(latest.get("cases_total"))
    skipped = _whole_number(latest.get("cases_skipped"))
    counts = f"{passed} of {total} cases passed" + (
        f" ({skipped} skipped)" if skipped else ""
    )
    if not has_run:
        summary = "The history holds no run yet"
    elif st_txt == PASS:
        summary = counts
    elif st_txt == FAIL:
        summary = f"The latest run did not pass: {counts}"
    else:
        summary = f"The status of the latest run is unknown. {counts}"
    link = (
        f'<a href="{_report_href(latest)}" class="btn-latest">View Latest Full Report →</a>'
        if has_run
        else ""
    )
    return _fill(
        DASHBOARD_HTML_TEMPLATE,
        {
            "LATEST_BADGE_CLASS": _status_badge_class(st_txt),
            "LATEST_STATUS": html.escape(st_txt),
            "LATEST_VER": html.escape(ver_txt),
            "LATEST_REPORT_LINK": link,
            "TOTAL_RUNS": str(len(runs)),
            "LATEST_PASS_RATE": f"{passed}/{total}" if has_run else MISSING,
            "LATEST_PASS_PERCENT": _percent(
                latest.get("cases_passed"), latest.get("cases_total")
            ),
            "LATEST_DURATION": _duration_text(latest.get("duration_seconds")),
            "LATEST_DELTA": _delta_cell(latest),
            "LATEST_SUMMARY": html.escape(summary),
            "CHART_SVG": _render_dashboard_trend_svg(sorted_runs),
            "TABLE_ROWS": _render_dashboard_table_rows(sorted_runs),
        },
    )
