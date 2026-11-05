"""
Benchmark HTML Reporter and Dashboard Generator.

Produces standalone, lightweight single-file HTML reports (<100KB) and
an aggregated multi-version index dashboard (<50KB) following the
Zero-Raster-Image policy (pure SVG/CSS, zero external CDN dependencies).
"""

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
# The currency of each delta key.
DELTA_CURRENCY = {
    "equation_delta": "SGD",
    "equation_delta_sgd": "SGD",
    "equation_delta_usd": "USD",
}
# A delta outside this range prints in scientific form. This keeps the page short.
DELTA_FIXED_MIN = Decimal("1E-6")
DELTA_FIXED_MAX = Decimal("1E+12")
# A count above this limit is no count. A duration above this limit is no run time.
COUNT_LIMIT = 10**9
DURATION_LIMIT = 10**9
# The cases of flow 23 prove the balance sheet identity (common/meta/flows).
IDENTITY_CASE_IDS = tuple(f"case_{case}" for case in FLOW_TO_CASES[23])
# The delta rows of each case table. "Zero Drift" needs a recorded zero in each row.
CASE_DELTA_KEYS = {
    "case_1": ("equation_delta",),
    "case_2": ("equation_delta",),
    "case_3": ("equation_delta",),
    "case_4": ("equation_delta_sgd", "equation_delta_usd"),
    "case_5": ("equation_delta",),
    "case_6": ("equation_delta",),
}
# Each flag of the run summary and the case that it reads.
SUMMARY_FLAG_CASES = (
    ("zero_pnl_contamination", "case_3"),
    ("rollforward_balanced", "case_1"),
    ("multicurrency_consolidated", "case_4"),
    ("portfolio_holdings_verified", "case_5"),
    ("overdraft_articulation_verified", "case_6"),
)
# The page does not show telemetry that nests deeper than this limit.
# json.dumps with an indent raises RecursionError near 1000 levels.
TELEMETRY_DEPTH_LIMIT = 50
NO_FIGURES = "<p>No figures recorded. The case stopped before it recorded any.</p>"
NO_TABLE_FIGURES = "<p>No assertion table figures recorded. Inspect Raw Adjudication Telemetry below.</p>"
# A failed case does not show which check failed, so each row of its table says this.
UNCONFIRMED = "❌ Unconfirmed"
_PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")
_SURROGATE = re.compile(r"[\ud800-\udfff]")
_ISO_SUBSECOND = re.compile(r"(\d{2}:\d{2}:\d{2})\.\d+")
# One row of a case table: label, recorded value or None, unit, verdict HTML.
Row = tuple[str, str | None, str, str]


def _clean_surrogates(text: str) -> str:
    """Replace lone UTF-16 surrogates with the replacement character U+FFFD."""
    return _SURROGATE.sub("\ufffd", text)


def _safe_int_str(value: int) -> str:
    """Convert an int to text without crashing on Python's 4300-digit str() limit."""
    try:
        return str(value)
    except ValueError:
        return hex(value)


def sanitize_for_json(value: Any, _depth: int = 0) -> Any:
    """Convert arbitrary in-process values into UTF-8 and JSON-safe primitives."""
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
        text = _number_text(value)
        return value if text is not None else str(value)
    if isinstance(value, Decimal):
        return _clean_surrogates(str(value))
    if isinstance(value, str):
        return _clean_surrogates(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str):
                key_str = _clean_surrogates(k)
            elif isinstance(k, int) and not isinstance(k, bool):
                key_str = _safe_int_str(k)
            else:
                try:
                    key_str = _clean_surrogates(str(k))
                except ValueError:
                    key_str = repr(type(k).__name__)
            out[key_str] = sanitize_for_json(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_for_json(item, _depth + 1) for item in value]
    try:
        return _clean_surrogates(str(value))
    except ValueError:
        return repr(type(value).__name__)


def write_utf8_atomic(path: Path, content: str) -> None:
    """Encode UTF-8 in memory (replacing any lone surrogates) and atomically replace `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_bytes = _clean_surrogates(content).encode("utf-8", errors="replace")
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
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
    """Fill each {{NAME}} of a template in one pass.

    The pass never reads a value for placeholders again. Text from a run cannot add markup.
    """
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def _details_of(result: dict[str, Any]) -> dict[str, Any]:
    """The recorded details of a case result, or an empty dict."""
    details = result.get("details")
    return details if isinstance(details, dict) else {}


def _case_id(result: dict[str, Any]) -> str | None:
    """The case id of a result, or None when the id is no string or is empty."""
    case_id = result.get("case_id")
    return case_id if isinstance(case_id, str) and case_id else None


def _recorded(details: dict[str, Any], *keys: str) -> Any:
    """The first value among `keys` that the run recorded, or None.

    None and the empty string are not recorded values.
    A report must never show an expected figure for a value that the run did not produce.
    """
    for key in keys:
        value = details.get(key)
        if value is not None and value != "":
            return value
    return None


def _number_text(value: Any) -> str | None:
    """The recorded text of a finite number, or None when the value is no finite number.

    A number, or a string in decimal syntax, is a number. A bool, a container and None are not.
    The text of a bool is no decimal syntax. The function never calls str() on a container,
    so a deep container cannot raise RecursionError.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        raw = str(value).strip()
        cleaned = raw.replace(",", "") if isinstance(value, str) else raw
        number = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        # str() raises ValueError for an int with more digits than Python prints.
        return None
    return _clean_surrogates(cleaned) if number.is_finite() else None


def _number(value: Any) -> Decimal | None:
    """A recorded value as a finite number, or None when the value is no finite number."""
    text = _number_text(value)
    return None if text is None else Decimal(text)


def _text_value(value: Any) -> str | None:
    """The text of a recorded scalar, or None when the run recorded no text.

    A string that is not empty is text. A finite number shows its recorded digits.
    A bool, a container and None have no text.
    """
    if isinstance(value, str):
        cleaned = _clean_surrogates(value)
        return cleaned if cleaned else None
    return _number_text(value)


def _show(value: Any) -> str:
    """Escaped text of a value for the page, or "n/a" when there is none."""
    text = _text_value(value)
    return MISSING if text is None else html.escape(text)


def _figure(details: dict[str, Any], *keys: str) -> str | None:
    """The recorded text of a figure, or None when the first recorded value is no number."""
    return _number_text(_recorded(details, *keys))


def _text(details: dict[str, Any], *keys: str) -> str | None:
    """The recorded text of a text field, or None when the first recorded value is no text."""
    return _text_value(_recorded(details, *keys))


def _whole_number(value: Any) -> int | None:
    """The value as a whole number from 0 to COUNT_LIMIT, or None when it is not one."""
    number = _number(value)
    if (
        number is None
        or not 0 <= number <= COUNT_LIMIT
        or number != number.to_integral_value()
    ):
        return None
    return int(number)


def _count(value: Any) -> str:
    """A count for the page, or "n/a" when the value is no count."""
    number = _whole_number(value)
    return MISSING if number is None else str(number)


def _percent(part: Any, whole: Any) -> str:
    """Share of `part` in `whole` as a percent, or "n/a" when a count is no count.

    The rounded share shows 0% only when no case passed, and 100% only when all passed.
    """
    numerator, denominator = _whole_number(part), _whole_number(whole)
    if numerator is None or not denominator or numerator > denominator:
        return MISSING
    share = (200 * numerator + denominator) // (2 * denominator)
    if 0 < numerator < denominator:
        share = min(max(share, 1), 99)
    return f"{share}%"


def _cases(count: int) -> str:
    return f"{count} case" if count == 1 else f"{count} cases"


def _seconds_or_none(value: Any) -> float | None:
    """A duration in seconds from 0 to DURATION_LIMIT, or None when the value is not one.

    A negative zero becomes zero. The page never shows "-0.00s".
    """
    number = _number(value)
    if number is None or not 0 <= number <= DURATION_LIMIT:
        return None
    return abs(float(number))


def _duration_text(value: Any) -> str:
    """A duration for the page, or "n/a" when the value is not a valid duration."""
    seconds = _seconds_or_none(value)
    return MISSING if seconds is None else f"{seconds:.2f}s"


def _total_seconds(results: list[dict[str, Any]]) -> float | None:
    """The sum of the case durations when every case recorded a valid duration, else None."""
    if not results:
        return None
    durations = [_seconds_or_none(r.get("duration_seconds")) for r in results]
    if any(seconds is None for seconds in durations):
        return None
    return sum(seconds for seconds in durations if seconds is not None)


def _href(url: str) -> str:
    """Escaped link target. A target with a scheme other than http or https becomes "#".

    `urlsplit` lowercases the scheme. It also removes tabs, new lines and leading control
    characters, as a browser does.
    """
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        return "#"
    return html.escape(url) if scheme in ("", "http", "https") else "#"


def _format_number(value: Decimal) -> str:
    """A number as text.

    Two decimals when they are exact, else the exact digits. A very small or very large
    number, and a number with many digits, print in scientific form.
    """
    sign = "-" if value < 0 else ""
    size = value.copy_abs()
    digits = len(size.as_tuple().digits)
    if size == 0 or (DELTA_FIXED_MIN <= size < DELTA_FIXED_MAX and digits <= 28):
        rounded = size.quantize(Decimal("0.01"))
        return sign + (str(rounded) if rounded == size else format(size, "f"))
    return f"{sign}{size:.3E}"


def _formatted(value: Decimal | None) -> str | None:
    """A delta as text, or None when the run recorded none."""
    return None if value is None else _format_number(value)


def _money(text: str | None, *, signed: bool = False) -> str | None:
    """A number text after a dollar sign, or None when there is no number.

    The sign comes from the number: "-$100.00". With `signed`, a number above zero shows
    a plus sign: "+$100.00". Zero shows no sign.
    """
    if text is None:
        return None
    number = Decimal(text)
    digits = text.lstrip("+-")
    if number < 0:
        return f"-${digits}"
    return f"+${digits}" if signed and number > 0 else f"${digits}"


def _recorded_deltas(results: list[dict[str, Any]]) -> list[tuple[Decimal, str]]:
    """Each finite delta that the results recorded, as (absolute value, currency)."""
    found: list[tuple[Decimal, str]] = []
    for result in results:
        details = _details_of(result)
        for key in EQUATION_DELTA_KEYS:
            value = _number(details.get(key))
            if value is not None:
                found.append((value.copy_abs(), DELTA_CURRENCY[key]))
    return found


def _largest_delta(results: list[dict[str, Any]]) -> tuple[str, str]:
    """The largest recorded delta as (value, currency), or ("n/a", "") when none."""
    found = _recorded_deltas(results)
    if not found:
        return MISSING, ""
    value, currency = max(found, key=lambda item: item[0])
    return _format_number(value), currency


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


def _has_nonzero_delta(result: dict[str, Any]) -> bool:
    """True when the case result recorded any non-zero equation delta."""
    return any(size != 0 for size, _ in _recorded_deltas([result]))


def _effective_case_status(result: dict[str, Any] | None) -> str | None:
    """The effective status of a case record.

    A record with status PASS that recorded a non-zero equation delta is FAIL.
    """
    if not result:
        return None
    status = _text_value(result.get("status"))
    if status == PASS and _has_nonzero_delta(result):
        return FAIL
    return status


def _verdict(cases: list[dict[str, Any] | None]) -> str:
    """The verdict of the case records behind a check: FAIL, NOT RUN or PASS.

    FAIL when a record failed (or recorded a non-zero delta). NOT RUN when no record
    failed and a record is missing, has no status or was skipped. PASS only when every
    record ran and passed. No record gives NOT RUN.
    """
    statuses = [_effective_case_status(case) for case in cases]
    if not statuses:
        return NOT_RUN
    if any(status not in (None, "SKIPPED", PASS) for status in statuses):
        return FAIL
    if any(status in (None, "SKIPPED") for status in statuses):
        return NOT_RUN
    return PASS


def _cases_by_id(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One record for each case id of the results.

    A case id with more than one record keeps its first record with the worst verdict.
    FAIL wins over NOT RUN, and NOT RUN wins over PASS. A result without an id is left out.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        case_id = _case_id(result)
        if case_id is not None:
            groups.setdefault(case_id, []).append(result)
    return {
        case_id: next(
            record for record in group if _verdict([record]) == _verdict(group)
        )
        for case_id, group in groups.items()
    }


def _identity_results(by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The results of the cases that prove the balance sheet identity."""
    return [by_id[case_id] for case_id in IDENTITY_CASE_IDS if case_id in by_id]


def _badge(kind: str, text: str) -> str:
    """A badge of the kind "pass", "fail" or "skip" with escaped text."""
    return f'<span class="badge badge-{kind}">{html.escape(text)}</span>'


def _adjudication(cases: list[dict[str, Any] | None]) -> str:
    """The badge of an invariant from the verdict of the cases behind it."""
    verdict = _verdict(cases)
    kind = {PASS: "pass", FAIL: "fail"}.get(verdict, "skip")
    return _badge(kind, verdict)


def _render_invariants_rows(by_id: dict[str, dict[str, Any]]) -> str:
    """Rows of the "Core Financial Invariants" table, from the recorded case results."""
    identity_cases = [by_id.get(case_id) for case_id in IDENTITY_CASE_IDS]
    identity_present = _identity_results(by_id)
    identity_recorded = _recorded_delta_count(identity_present)
    needed = _cases(len(IDENTITY_CASE_IDS))
    if identity_recorded:
        identity_observed = (
            f"Largest recorded |Δ| is {_delta_text(identity_present)}, recorded by "
            f"{identity_recorded} of {needed}"
        )
    else:
        identity_observed = f"No delta recorded by any of the {needed}"
    case_1 = by_id.get("case_1")
    case_3 = by_id.get("case_3")
    d1 = _details_of(case_1 or {})
    d3 = _details_of(case_3 or {})
    closings = ", ".join(
        _figure(d1, f"m{n}_closing_balance", f"month_{n}_ending_balance") or MISSING
        for n in (1, 2, 3, 4)
    )
    card_spend = _figure(d3, "card_spend_recorded") or MISSING
    repayment = _figure(d3, "bank_repayment") or MISSING
    net_income = _figure(d3, "net_income") or MISSING
    cumulative = _figure(d1, "cumulative_net_income") or MISSING
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
            f"Card spend {card_spend}, bank repayment {repayment}, "
            f"net income {net_income}",
            [case_3],
        ),
        (
            "Retained Earnings Articulation",
            "Closing Equity = Opening Equity + Net Income",
            f"Cumulative net income {cumulative}",
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


def _summary_of(report_data: Any) -> dict[str, Any]:
    """The summary of a report, or an empty dict."""
    if not isinstance(report_data, dict):
        return {}
    summary = report_data.get("summary")
    return summary if isinstance(summary, dict) else {}


def _results_of(report_data: Any) -> list[dict[str, Any]]:
    """The case results of a report. An entry that is no dict is dropped."""
    if not isinstance(report_data, dict):
        return []
    results = report_data.get("results")
    if not isinstance(results, list):
        return []
    return [result for result in results if isinstance(result, dict)]


def _derived_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    """Case counts derived directly from the verified case result records."""
    statuses = [_effective_case_status(result) for result in results]
    passed = statuses.count(PASS)
    skipped = statuses.count("SKIPPED")
    return {
        "total": len(results),
        "passed": passed,
        "skipped": skipped,
        "failed": len(results) - passed - skipped,
    }


def _summary_disagreement(
    report_data: Any, results: list[dict[str, Any]]
) -> str | None:
    """Describe any disagreement between summary counts/flags and verified result records."""
    if not isinstance(report_data, dict) or not isinstance(
        report_data.get("summary"), dict
    ):
        return None
    summary = _summary_of(report_data)
    derived = _derived_counts(results)
    mismatches: list[str] = []
    for key in ("total", "passed", "skipped", "failed"):
        if key in summary and summary.get(key) is not None:
            recorded = _whole_number(summary.get(key))
            if recorded is None or recorded != derived[key]:
                mismatches.append(
                    f"summary.{key}={_text_value(summary.get(key)) or summary.get(key)!r} vs results.{key}={derived[key]}"
                )
    if summary.get("success") is True and (
        derived["total"] == 0 or derived["passed"] == 0 or derived["failed"] > 0
    ):
        mismatches.append(
            f"summary.success=True vs results(passed={derived['passed']}, failed={derived['failed']}, total={derived['total']})"
        )
    if not mismatches:
        return None
    return "; ".join(mismatches)


def _report_counts(report_data: Any) -> dict[str, int]:
    """Case counts of a report.

    When result records are present, derived counts from verified results are authoritative.
    When results are empty and summary counts agree with zero, summary counts are used.
    """
    results = _results_of(report_data)
    derived = _derived_counts(results)
    if results or _summary_disagreement(report_data, results) is not None:
        return derived
    summary = _summary_of(report_data)
    counts: dict[str, int] = {}
    for key, fallback in derived.items():
        recorded = _whole_number(summary.get(key))
        counts[key] = fallback if recorded is None else recorded
    return counts


def _not_passed_count(results: list[dict[str, Any]]) -> int:
    """How many case records did not pass."""
    return sum(1 for result in results if _effective_case_status(result) != PASS)


def _failed_count(results: list[dict[str, Any]]) -> int:
    """How many case records failed (excluding PASS and SKIPPED)."""
    return sum(
        1
        for result in results
        if _effective_case_status(result) not in (PASS, "SKIPPED")
    )


def _all_passed(
    report_data: Any,
    counts: dict[str, int],
    results: list[dict[str, Any]],
) -> bool:
    """True only when the run recorded success and every case passed with zero skips."""
    return (
        _summary_of(report_data).get("success") is True
        and _summary_disagreement(report_data, results) is None
        and counts["total"] >= 1
        and counts["passed"] == counts["total"]
        and counts["failed"] == 0
        and counts["skipped"] == 0
        and _not_passed_count(results) == 0
    )


def _run_passed(
    report_data: Any,
    counts: dict[str, int],
    results: list[dict[str, Any]],
) -> bool:
    """True when the run recorded success, counts agree with results, at least one case passed, and none failed."""
    return (
        _summary_of(report_data).get("success") is True
        and _summary_disagreement(report_data, results) is None
        and counts["total"] >= 1
        and counts["passed"] >= 1
        and counts["failed"] == 0
        and counts["passed"] + counts["skipped"] == counts["total"]
        and _failed_count(results) == 0
    )


def _run_status(
    report_data: Any,
    counts: dict[str, int],
    results: list[dict[str, Any]],
) -> str:
    """PASS or FAIL as the page header decides, or UNKNOWN for a report without a summary."""
    if not isinstance(report_data, dict) or not isinstance(
        report_data.get("summary"), dict
    ):
        return UNKNOWN
    return PASS if _run_passed(report_data, counts, results) else FAIL


def extract_summary_data(report_data: Any) -> dict[str, Any]:
    """Extract machine-readable summary metrics from full benchmark report data.

    A value that the run did not record is None. The exceptions are run_at and app_url:
    they are "" then, because the index generator sorts the summaries by run_at text.
    """
    report_dict = report_data if isinstance(report_data, dict) else {}
    results = _results_of(report_dict)
    counts = _report_counts(report_dict)
    by_id = _cases_by_id(results)
    version = _text_value(report_dict.get("version_ref"))
    total_seconds = _total_seconds(results)

    passed_case_ids = {
        case_id for case_id, case in by_id.items() if _verdict([case]) == PASS
    }
    case_to_flows = get_case_to_flows()
    covered_flows: set[int] = set()
    for cid in passed_case_ids:
        covered_flows.update(case_to_flows.get(cid, ()))
    covered_domains = {FLOW_TO_DOMAIN[f] for f in covered_flows if f in FLOW_TO_DOMAIN}

    return {
        "version": version,
        "run_at": _text_value(report_dict.get("run_at")) or "",
        "app_url": _text_value(report_dict.get("app_url")) or "",
        "status": _run_status(report_dict, counts, results),
        "cases_total": counts["total"],
        "cases_passed": counts["passed"],
        "cases_skipped": counts["skipped"],
        "cases_failed": counts["failed"],
        "duration_seconds": (
            None if total_seconds is None else round(total_seconds, 2)
        ),
        "max_equation_delta": _max_equation_delta(results),
        "max_equation_delta_currency": _largest_delta(results)[1],
        **{
            flag: _verdict([by_id.get(case_id)]) == PASS
            for flag, case_id in SUMMARY_FLAG_CASES
        },
        "thirty_flows_coverage": f"{len(covered_flows)}/30",
        "domains_covered": len(covered_domains),
        "report_url": None if version is None else f"{version}/report.html",
    }


def _signed_seconds(seconds: float) -> str:
    """A time difference with its sign. A difference that rounds to zero shows no sign."""
    rounded = round(seconds, 2)
    sign = "+" if rounded > 0 else "-" if rounded < 0 else ""
    return f"{sign}{abs(rounded):.2f}s"


def _drift_note(
    results: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]
) -> tuple[str, str]:
    """The note and the CSS class of the largest delta on the baseline card.

    "Drift" needs a recorded delta that is not zero and a delta from each identity case.
    "Zero Drift" needs a recorded zero in each delta row of every balance case. Each of
    those cases must pass. Every recorded delta must be zero.
    """
    deltas = _recorded_deltas(results)
    if not deltas:
        return "not recorded", "metric-diff-neutral"
    drift = any(size != 0 for size, _ in deltas)
    identity_recorded = _recorded_delta_count(_identity_results(by_id))
    if drift and identity_recorded == len(IDENTITY_CASE_IDS):
        return "Drift", "metric-diff-worse"
    balance_cases = [by_id.get(case_id) for case_id in CASE_DELTA_KEYS]
    complete = all(
        _number(_details_of(case or {}).get(key)) is not None
        for case, keys in zip(balance_cases, CASE_DELTA_KEYS.values())
        for key in keys
    )
    if drift or not complete:
        return "not recorded for every balance case", "metric-diff-neutral"
    if _verdict(balance_cases) != PASS:
        return "not every balance case passed", "metric-diff-neutral"
    return "Zero Drift", "metric-diff-better"


def _render_diff_section(
    baseline_data: Any,
    total_seconds: float | None,
    counts: dict[str, int],
    results: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> str:
    """Render the baseline comparison card when a baseline dict is given.

    A baseline that is no dict, or an empty dict, gives no card.
    """
    if not isinstance(baseline_data, dict) or not baseline_data:
        return ""
    baseline_seconds = _seconds_or_none(
        _summary_of(baseline_data).get("total_duration_seconds")
    )
    if baseline_seconds is None:
        baseline_seconds = _total_seconds(_results_of(baseline_data))
    dur_text = MISSING if total_seconds is None else f"{total_seconds:.2f}s"
    if total_seconds is None or baseline_seconds is None:
        # A time difference needs a recorded time on both sides.
        dur_diff_text, dur_class = MISSING, "metric-diff-neutral"
    else:
        dur_diff = total_seconds - baseline_seconds
        dur_diff_text = _signed_seconds(dur_diff)
        dur_class = (
            "metric-diff-worse"
            if dur_diff > 5
            else ("metric-diff-better" if dur_diff < -5 else "metric-diff-neutral")
        )
    b_version = _show(baseline_data.get("version_ref"))
    total_cases = counts["total"]
    passed_cases = counts["passed"]
    pass_pct = _percent(passed_cases, total_cases)
    if not total_cases:
        pass_class = "metric-diff-neutral"
    elif passed_cases == total_cases:
        pass_class = "metric-diff-better"
    else:
        pass_class = "metric-diff-worse"
    max_delta_text = _delta_text(results)
    delta_note, delta_class = _drift_note(results, by_id)
    return f"""
    <div class="card baseline-card">
        <h3 style="font-size: 1.1rem; margin-bottom: 12px;">⚖️ Baseline Comparison (vs {b_version})</h3>
        <div class="grid grid-3">
            <div class="stat-box">
                <span class="stat-label">Execution Time</span>
                <span class="stat-value">{dur_text} <small class="{dur_class}">({dur_diff_text})</small></span>
            </div>
            <div class="stat-box">
                <span class="stat-label">Pass Rate</span>
                <span class="stat-value">{passed_cases}/{total_cases} <small class="{pass_class}">({pass_pct})</small></span>
            </div>
            <div class="stat-box">
                <span class="stat-label">Max Equation Delta</span>
                <span class="stat-value">{max_delta_text} <small class="{delta_class}">({delta_note})</small></span>
            </div>
        </div>
    </div>
    """


def _row_verdict_state(
    details: dict[str, Any],
    passed: bool,
    value_present: bool,
    *keys: str,
) -> str:
    """Resolve the per-assertion verdict of a table row: 'passed', 'failed' or 'not_run'."""
    verdicts = details.get("assertion_verdicts")
    if isinstance(verdicts, dict):
        for key in keys:
            raw = verdicts.get(key)
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
    details: dict[str, Any],
    passed: bool,
    confirmed: str,
    value: Any,
    *keys: str,
) -> str:
    """The verdict cell of a row, reading per-assertion verdicts when present."""
    state = _row_verdict_state(details, passed, value is not None, *keys)
    if state == "passed":
        return html.escape(f"✅ {confirmed}")
    if state == "failed":
        return UNCONFIRMED
    return MISSING


def _check(passed: bool, confirmed: str) -> str:
    """The verdict cell of a row: the confirmed text for a passed case, else UNCONFIRMED."""
    return html.escape(f"✅ {confirmed}") if passed else UNCONFIRMED


def _delta_badge(
    delta: Decimal | None,
    unit: str,
    passed: bool,
    broken: str | None = None,
    *,
    details: dict[str, Any] | None = None,
    keys: tuple[str, ...] = ("equation_delta",),
) -> str:
    """The badge of a delta row.

    A non-zero delta is always a failed check. A zero delta on a passed row is Balanced.
    """
    if delta is not None and delta != 0:
        msg = (
            f"{_format_number(delta)} {unit} {broken}"
            if broken
            else f"❌ {_format_number(delta)} {unit} Regression"
        )
        return _badge("fail", msg)
    if delta is None:
        if details is not None:
            state = _row_verdict_state(details, passed, False, *keys)
            if state == "failed":
                return _badge("fail", f"❌ {unit} Equation Broken")
        if passed:
            return _badge("pass", f"Balanced ({unit} Δ not recorded)")
        return _badge("skip", f"{unit} Δ not recorded")
    # delta == 0
    if details is not None:
        state = _row_verdict_state(details, passed, True, *keys)
        if state == "passed":
            return _badge("pass", f"✅ {_format_number(delta)} {unit} Balanced")
        if state == "failed":
            msg = (
                f"{_format_number(delta)} {unit} {broken}"
                if broken
                else f"❌ {_format_number(delta)} {unit} Unconfirmed"
            )
            return _badge("fail", msg)
        return _badge("skip", f"{_format_number(delta)} {unit} No difference recorded")
    if passed:
        return _badge("pass", f"✅ {_format_number(delta)} {unit} Balanced")
    return _badge("skip", f"{_format_number(delta)} {unit} No difference recorded")


def _deltas(details: dict[str, Any], case_id: str) -> list[Decimal | None]:
    """The recorded deltas of the delta rows of a case table, in row order."""
    return [_number(details.get(key)) for key in CASE_DELTA_KEYS[case_id]]


def _cell(value: str | None, unit: str) -> str:
    """The escaped value cell of a row. A missing value shows "n/a"."""
    if value is None:
        return MISSING
    return html.escape(f"{value} {unit}" if unit else value)


def _has_recorded_telemetry(details: dict[str, Any]) -> bool:
    """True when `details` holds any recorded telemetry beyond `not_run` verdicts."""
    for key, val in details.items():
        if key == "assertion_verdicts":
            if isinstance(val, dict) and any(v != "not_run" for v in val.values()):
                return True
            continue
        if val is not None and val != "":
            return True
    return False


def _table(
    headers: tuple[str, str, str],
    rows: list[Row],
    passed: bool,
    details: dict[str, Any] | None = None,
) -> str:
    """A case table, or a note for a failed case that recorded no value in any row.

    A table of a case that stopped early would claim checks that the run never made.
    """
    if not passed and all(value is None for _, value, _, _ in rows):
        if details and _has_recorded_telemetry(details):
            return NO_TABLE_FIGURES
        return NO_FIGURES
    head = "".join(f"<th>{html.escape(name)}</th>" for name in headers)
    body = "".join(
        f"\n            <tr><td>{html.escape(label)}</td>"
        f"<td>{_cell(value, unit)}</td><td>{verdict}</td></tr>"
        for label, value, unit, verdict in rows
    )
    return f"""
    <table class="data-table">
        <thead><tr>{head}</tr></thead>
        <tbody>{body}
        </tbody>
    </table>
    """


def _render_case_1_table(details: dict[str, Any], passed: bool) -> str:
    (delta,) = _deltas(details, "case_1")
    m1 = _money(_figure(details, "m1_closing_balance", "month_1_ending_balance"))
    m2 = _money(_figure(details, "m2_closing_balance", "month_2_ending_balance"))
    m3 = _money(_figure(details, "m3_closing_balance", "month_3_ending_balance"))
    m4 = _money(_figure(details, "m4_closing_balance", "month_4_ending_balance"))
    q1 = _money(_figure(details, "q1_net_income"))
    cum = _money(_figure(details, "cumulative_net_income"))
    return _table(
        ("Financial Assertion", "Value (SGD)", "Reconciliation Status"),
        [
            (
                "Month 1 (Jan 2025) Ending Balance",
                m1,
                "",
                _check_row(
                    details,
                    passed,
                    "Anchor Confirmed",
                    m1,
                    "m1_closing_balance",
                    "month_1_ending_balance",
                ),
            ),
            (
                "Month 2 (Feb 2025) Ending Balance",
                m2,
                "",
                _check_row(
                    details,
                    passed,
                    "Exact Continuity Rollforward",
                    m2,
                    "m2_closing_balance",
                    "month_2_ending_balance",
                ),
            ),
            (
                "Month 3 (Mar 2025 - Q1 Close) Ending Balance",
                m3,
                "",
                _check_row(
                    details,
                    passed,
                    "Q1 Continuity Confirmed",
                    m3,
                    "m3_closing_balance",
                    "month_3_ending_balance",
                ),
            ),
            (
                "Month 4 (Apr 2025 - Q2 Transition) Ending Balance",
                m4,
                "",
                _check_row(
                    details,
                    passed,
                    "4-Month Rollforward Intact",
                    m4,
                    "m4_closing_balance",
                    "month_4_ending_balance",
                ),
            ),
            (
                "Q1 Cumulative Net Income",
                q1,
                "",
                _check_row(
                    details,
                    passed,
                    "Articulated to Q1 Retained Earnings",
                    q1,
                    "q1_net_income",
                ),
            ),
            (
                "4-Month Cumulative Net Income",
                cum,
                "",
                _check_row(
                    details,
                    passed,
                    "Articulated to Retained Earnings",
                    cum,
                    "cumulative_net_income",
                ),
            ),
            (
                "Balance Sheet Equation Delta (A - L - E)",
                _money(_formatted(delta)),
                "SGD",
                _delta_badge(
                    delta,
                    "SGD",
                    passed,
                    details=details,
                    keys=("equation_delta",),
                ),
            ),
        ],
        passed,
        details,
    )


def _render_case_2_table(details: dict[str, Any], passed: bool) -> str:
    (delta,) = _deltas(details, "case_2")
    h_cash = _money(_figure(details, "household_husband_cash"))
    w_cash = _money(_figure(details, "household_wife_cash"))
    inc = _money(_figure(details, "total_income"), signed=True)
    exp = _money(_figure(details, "total_expenses"), signed=True)
    net = _money(_figure(details, "net_income"), signed=True)
    end_cash = _money(_figure(details, "ending_cash", "closing_balance"))
    return _table(
        ("Financial Assertion", "Value (SGD)", "Reconciliation Status"),
        [
            (
                "Husband Account (DBS Bank) Ending Cash",
                h_cash,
                "",
                _check_row(
                    details,
                    passed,
                    "Source Account Reconciled",
                    h_cash,
                    "household_husband_cash",
                ),
            ),
            (
                "Wife Account (Standard Chartered) Ending Cash",
                w_cash,
                "",
                _check_row(
                    details,
                    passed,
                    "Multi-PII Account Reconciled",
                    w_cash,
                    "household_wife_cash",
                ),
            ),
            (
                "Consolidated Operating Revenue",
                inc,
                "",
                _check_row(
                    details,
                    passed,
                    "Combined Inflow Reconciled",
                    inc,
                    "total_income",
                ),
            ),
            (
                "Consolidated Operating Expenses",
                exp,
                "",
                _check_row(
                    details,
                    passed,
                    "Family Expenses Categorized",
                    exp,
                    "total_expenses",
                ),
            ),
            (
                "Consolidated Net Operating Income",
                net,
                "",
                _check_row(
                    details,
                    passed,
                    "P&L Sum Reconciled",
                    net,
                    "net_income",
                ),
            ),
            (
                "Consolidated Total Liquid Cash",
                end_cash,
                "",
                _check_row(
                    details,
                    passed,
                    "Cash Flow Ending Cash Conserved",
                    end_cash,
                    "ending_cash",
                    "closing_balance",
                ),
            ),
            (
                "Balance Sheet Equation Delta",
                _money(_formatted(delta)),
                "SGD",
                _delta_badge(
                    delta,
                    "SGD",
                    passed,
                    details=details,
                    keys=("equation_delta",),
                ),
            ),
        ],
        passed,
        details,
    )


def _render_case_3_table(details: dict[str, Any], passed: bool) -> str:
    (delta,) = _deltas(details, "case_3")
    spend = _money(_figure(details, "card_spend_recorded"), signed=True)
    repay = _money(_figure(details, "bank_repayment"), signed=True)
    cleared = _money(_figure(details, "credit_card_liability_cleared"))
    cash = _money(_figure(details, "ending_bank_cash", "total_assets"))
    net_income = _figure(details, "net_income")
    pnl_state = _row_verdict_state(
        details, passed, net_income is not None, "net_income"
    )
    if pnl_state == "passed":
        pnl_badge = _badge("pass", "✅ Zero Double-Counting (Pure Liability Clearance)")
    elif pnl_state == "failed":
        pnl_badge = _badge("fail", "❌ Unconfirmed")
    else:
        pnl_badge = MISSING
    return _table(
        ("Financial Assertion", "Value (SGD)", "Reconciliation Status"),
        [
            (
                "Credit Card Incurred Charges (Liability Incurrence)",
                spend,
                "",
                _check_row(
                    details,
                    passed,
                    "Card Expense & Liability Tracked",
                    spend,
                    "card_spend_recorded",
                ),
            ),
            (
                "Bank Account Settlement Payment Outflow",
                repay,
                "",
                _check_row(
                    details,
                    passed,
                    "Bank Cash Outflow Tracked",
                    repay,
                    "bank_repayment",
                ),
            ),
            (
                "Credit Card Liability Ending Balance",
                cleared,
                "",
                _check_row(
                    details,
                    passed,
                    "Liability Fully Cleared",
                    cleared,
                    "credit_card_liability_cleared",
                ),
            ),
            (
                "Ending Bank Liquid Cash Balance",
                cash,
                "",
                _check_row(
                    details,
                    passed,
                    "Cash Balance Conserved",
                    cash,
                    "ending_bank_cash",
                    "total_assets",
                ),
            ),
            (
                "P&L Double-Counting Prevention (Net Income)",
                _money(net_income),
                "",
                pnl_badge,
            ),
            (
                "Balance Sheet Equation Delta",
                _money(_formatted(delta)),
                "SGD",
                _delta_badge(
                    delta,
                    "SGD",
                    passed,
                    details=details,
                    keys=("equation_delta",),
                ),
            ),
        ],
        passed,
        details,
    )


def _render_case_4_table(details: dict[str, Any], passed: bool) -> str:
    sgd_delta, usd_delta = _deltas(details, "case_4")
    sgd_bal = _figure(details, "sgd_closing_balance")
    usd_bal = _figure(details, "usd_closing_balance")
    hkd_bal = _figure(details, "hkd_closing_balance")
    tot_sgd = _money(_figure(details, "total_assets_sgd"))
    return _table(
        ("Financial Assertion", "Amount", "Multi-Currency Status"),
        [
            (
                "Singapore Jurisdiction (SGD Account)",
                sgd_bal,
                "SGD",
                _check_row(
                    details,
                    passed,
                    "Local Inflow Verified",
                    sgd_bal,
                    "sgd_closing_balance",
                ),
            ),
            (
                "United States Jurisdiction (USD Account)",
                usd_bal,
                "USD",
                _check_row(
                    details,
                    passed,
                    "Foreign Currency Inflow Verified",
                    usd_bal,
                    "usd_closing_balance",
                ),
            ),
            (
                "Hong Kong Jurisdiction (HKD Account)",
                hkd_bal,
                "HKD",
                _check_row(
                    details,
                    passed,
                    "Foreign Currency Inflow Verified",
                    hkd_bal,
                    "hkd_closing_balance",
                ),
            ),
            (
                "Consolidated Total Assets (SGD Base)",
                tot_sgd,
                "SGD",
                _check_row(
                    details,
                    passed,
                    "Unified Multi-Currency Conversion",
                    tot_sgd,
                    "total_assets_sgd",
                ),
            ),
            (
                "SGD Balance Sheet Equation Delta",
                _money(_formatted(sgd_delta)),
                "SGD",
                _delta_badge(
                    sgd_delta,
                    "SGD",
                    passed,
                    details=details,
                    keys=("equation_delta_sgd", "equation_delta"),
                ),
            ),
            (
                "USD Balance Sheet Equation Delta",
                _money(_formatted(usd_delta)),
                "USD",
                _delta_badge(
                    usd_delta,
                    "USD",
                    passed,
                    details=details,
                    keys=("equation_delta_usd",),
                ),
            ),
        ],
        passed,
        details,
    )


def _render_case_5_table(details: dict[str, Any], passed: bool) -> str:
    (delta,) = _deltas(details, "case_5")
    appraisal = _text(details, "appraisal_source") or MISSING
    symbols = _text(details, "symbols")
    holdings = _figure(details, "holdings_count")
    prop_val = _money(_figure(details, "property_valuation_usd"))
    tax_status = _text(details, "tax_ecosystem_status")
    tot_assets = _money(_figure(details, "total_assets"))
    return _table(
        ("Financial Assertion", "Value", "Portfolio Status"),
        [
            (
                "Public Securities Tracked",
                symbols,
                "",
                _check_row(
                    details,
                    passed,
                    "Position Snapshots Recognized",
                    symbols,
                    "symbols",
                ),
            ),
            (
                "Managed Holdings Count",
                holdings,
                "Assets",
                _check_row(
                    details,
                    passed,
                    "Atomic & Managed Reconciliation Intact",
                    holdings,
                    "holdings_count",
                ),
            ),
            (
                "Real Estate Property Appraisal",
                prop_val,
                "USD",
                _check_row(
                    details,
                    passed,
                    appraisal,
                    prop_val,
                    "property_valuation_usd",
                ),
            ),
            (
                "Tax & Compensation Integration",
                tax_status,
                "",
                _check_row(
                    details,
                    passed,
                    "DocuBench Tax Fixtures Integrated",
                    tax_status,
                    "tax_ecosystem_status",
                ),
            ),
            (
                "Consolidated Wealth Valuation",
                tot_assets,
                "SGD",
                _check_row(
                    details,
                    passed,
                    "Fair Market Valuation Reflected",
                    tot_assets,
                    "total_assets",
                ),
            ),
            (
                "Balance Sheet Equation Delta",
                _money(_formatted(delta)),
                "SGD",
                _delta_badge(
                    delta,
                    "SGD",
                    passed,
                    details=details,
                    keys=("equation_delta",),
                ),
            ),
        ],
        passed,
        details,
    )


def _render_case_6_table(details: dict[str, Any], passed: bool) -> str:
    (delta,) = _deltas(details, "case_6")
    od_cash = _money(_figure(details, "overdraft_cash", "ending_cash_balance"))
    cap_gain = _money(_figure(details, "capital_gain"), signed=True)
    net_inc = _money(_figure(details, "net_income"))
    tot_assets = _money(
        _figure(details, "total_assets", "ending_cash", "ending_cash_balance")
    )
    tot_equity = _money(_figure(details, "total_equity"))
    return _table(
        ("Accounting Invariant", "Reported Metric", "Integrity Check"),
        [
            (
                "Overdraft Checkpoint Cash Balance",
                od_cash,
                "SGD",
                _check_row(
                    details,
                    passed,
                    "Negative Balance Equation Validated",
                    od_cash,
                    "overdraft_cash",
                    "ending_cash_balance",
                ),
            ),
            (
                "Realized Capital Gain from Art Disposal",
                cap_gain,
                "SGD",
                _check_row(
                    details,
                    passed,
                    "Capital Gain Recognized in P&L",
                    cap_gain,
                    "capital_gain",
                ),
            ),
            (
                "Final Period Net Income",
                net_inc,
                "SGD",
                _check_row(
                    details,
                    passed,
                    "Expense Offset by Capital Gain",
                    net_inc,
                    "net_income",
                ),
            ),
            (
                "Final Period Total Assets",
                tot_assets,
                "SGD",
                _check_row(
                    details,
                    passed,
                    "Ending Assets Reconciled",
                    tot_assets,
                    "total_assets",
                    "ending_cash_balance",
                    "ending_cash",
                ),
            ),
            (
                "Final Period Total Equity",
                tot_equity,
                "SGD",
                _check_row(
                    details,
                    passed,
                    "Ending Equity Reconciled",
                    tot_equity,
                    "total_equity",
                ),
            ),
            (
                "Balance Sheet Equation Delta",
                _money(_formatted(delta)),
                "SGD",
                _delta_badge(
                    delta,
                    "SGD",
                    passed,
                    broken="❌ Equation Broken",
                    details=details,
                    keys=("equation_delta",),
                ),
            ),
        ],
        passed,
        details,
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
    """True when the containers in `value` nest more than `limit` levels deep.

    The walk uses a stack and no recursion. The value itself is level 1.
    """
    pending = [(value, 1)]
    while pending:
        item, level = pending.pop()
        if isinstance(item, (dict, list, tuple, set, frozenset)):
            if level > limit:
                return True
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, level + 1) for child in children)
    return False


def _telemetry(details: dict[str, Any]) -> str:
    """The recorded details as escaped JSON, or a note when they nest too deep."""
    if _nests_deeper_than(details, TELEMETRY_DEPTH_LIMIT):
        return (
            f"Not shown: the details nest deeper than {TELEMETRY_DEPTH_LIMIT} levels."
        )
    safe_details = sanitize_for_json(details)
    return html.escape(json.dumps(safe_details, indent=2))


def _render_case_details(cid: str | None, details: dict[str, Any], status: Any) -> str:
    """The table of a case, or a note when the case has no figures to show.

    A case that did not run, or that stopped before it recorded a figure, has no figures.
    A table of failed assertions would claim facts that the run did not observe.
    """
    if status == "SKIPPED":
        return "<p>Not run: the case did not run.</p>"
    passed = status == PASS and not any(
        size != 0
        for key in EQUATION_DELTA_KEYS
        if (size := _number(details.get(key))) is not None
    )
    render = CASE_TABLES.get(cid or "")
    if render is not None:
        return render(details, passed)
    if not passed and not _has_recorded_telemetry(details):
        return NO_FIGURES
    return f"<pre class='raw-json'>{_telemetry(details)}</pre>"


def _status_badge_class(status_text: str) -> str:
    """Badge CSS class for a case or run status."""
    if status_text == PASS:
        return "badge-pass"
    if status_text in ("SKIPPED", UNKNOWN, NOT_RUN):
        return "badge-skip"
    return "badge-fail"


def _render_scenario_cards(results: list[dict[str, Any]]) -> str:
    """Render the list of scenario execution cards."""
    cards: list[str] = []
    for r in results:
        cid = _case_id(r)
        cid_tag = html.escape(cid.upper()) if cid else UNKNOWN
        eff_status = _effective_case_status(r)
        raw_status = _text_value(eff_status) or UNKNOWN
        cstatus = html.escape(raw_status)
        cbadge = _status_badge_class(raw_status)
        cdetails = _details_of(r)
        error = _text_value(r.get("error_message"))
        err_html = (
            f"<div class='error-banner'><strong>Error:</strong> {html.escape(error)}</div>"
            if error
            else ""
        )
        cards.append(
            f"""
        <div class="card scenario-card">
            <div class="scenario-header">
                <div>
                    <span class="case-tag">{cid_tag}</span>
                    <h3 class="scenario-title">{_show(r.get("case_name"))}</h3>
                </div>
                <div class="scenario-meta">
                    <span class="duration-tag">⏱️ {_duration_text(r.get("duration_seconds"))}</span>
                    <span class="badge {cbadge}">{cstatus}</span>
                </div>
            </div>
            {err_html}
            {_render_case_details(cid, cdetails, eff_status)}
            <details class="raw-details">
                <summary>Inspect Raw Adjudication Telemetry</summary>
                <pre class="raw-json">{_telemetry(cdetails)}</pre>
            </details>
        </div>
        """
        )
    return "".join(cards)


def generate_html_report(report_data: Any, baseline_data: Any = None) -> str:
    """Generate standalone single-file HTML report for a specific release run."""
    report_dict = report_data if isinstance(report_data, dict) else {}
    results = _results_of(report_dict)
    counts = _report_counts(report_dict)
    by_id = _cases_by_id(results)
    all_passed = _all_passed(report_dict, counts, results)
    run_passed = _run_passed(report_dict, counts, results)
    disagreement = _summary_disagreement(report_dict, results)

    if disagreement is not None:
        status_text = (
            f"SUMMARY COUNT MISMATCH ({disagreement}) — "
            f"{counts['passed']} OF {counts['total']} SCENARIOS PASSED"
        )
        if counts["skipped"]:
            status_text += f", {counts['skipped']} SKIPPED"
    elif all_passed:
        status_text = f"ALL {counts['total']} SCENARIOS PASSED"
    else:
        status_text = f"{counts['passed']} OF {counts['total']} SCENARIOS PASSED"
        if counts["skipped"]:
            status_text += f", {counts['skipped']} SKIPPED"
    total_seconds = _total_seconds(results)

    return _fill(
        REPORT_HTML_TEMPLATE,
        {
            "VERSION": _show(report_dict.get("version_ref")),
            "APP_URL": _show(report_dict.get("app_url")),
            "RUN_AT": _show(report_dict.get("run_at")),
            "STATUS_BADGE_CLASS": "badge-pass" if run_passed else "badge-fail",
            "STATUS_TEXT": html.escape(status_text),
            "PASSED_COUNT": str(counts["passed"]),
            "TOTAL_COUNT": str(counts["total"]),
            "TOTAL_DURATION_STR": (
                MISSING if total_seconds is None else f"{total_seconds:.2f}s"
            ),
            "MAX_DELTA": _delta_text(results),
            "DELTA_COVERAGE": (
                f"recorded by {_recorded_delta_count(results)} of {_cases(len(results))}"
            ),
            "NOT_PASSED_COUNT": str(_not_passed_count(results)),
            "INVARIANTS_ROWS": _render_invariants_rows(by_id),
            "DIFF_HTML": _render_diff_section(
                baseline_data, total_seconds, counts, results, by_id
            ),
            "SCENARIOS_HTML": _render_scenario_cards(results),
        },
    )


def _run_time_key(run: dict[str, Any]) -> tuple[bool, Any]:
    """The sort key of a run by its recorded time.

    The key parses the time as ISO 8601. A time without an offset is UTC. A time that
    does not parse sorts before each parsed time. Two such times compare as text.
    """
    text = _text_value(run.get("run_at")) or ""
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return False, text
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return True, moment


def _delta_cell(run: dict[str, Any]) -> str:
    """Delta of one run for the history table. Older entries hold SGD without a currency."""
    value = _number(run.get("max_equation_delta"))
    if value is None:
        return MISSING
    currency = _text_value(run.get("max_equation_delta_currency")) or "SGD"
    return f"{_format_number(value)} {html.escape(currency)}"


def _report_href(run: dict[str, Any]) -> str:
    """The link to the report of a run.

    The recorded report_url wins. Else the version gives "<version>/report.html".
    A run with neither links to "#".
    """
    url = _text_value(run.get("report_url"))
    if url is None:
        version = _text_value(run.get("version"))
        if version is None:
            return "#"
        url = f"{version}/report.html"
    return _href(url)


def _format_run_date(value: Any) -> str:
    """Format a run_at timestamp for the history table while preserving its timezone offset."""
    text = _text_value(value)
    if text is None:
        return MISSING
    formatted = _ISO_SUBSECOND.sub(r"\1", text.replace("T", " "))
    return html.escape(formatted)


def _render_dashboard_table_rows(sorted_runs: list[dict[str, Any]]) -> str:
    """Render historical table rows for the multi-version dashboard."""
    table_rows = ""
    for r in sorted_runs:
        v = html.escape(_text_value(r.get("version")) or MISSING)
        status_text = _text_value(r.get("status")) or UNKNOWN
        status = html.escape(status_text)
        badge_cls = _status_badge_class(status_text)
        run_date = _format_run_date(r.get("run_at"))
        env = _show(r.get("app_url"))
        cases_str = f"{_count(r.get('cases_passed'))} / {_count(r.get('cases_total'))}"
        dur_str = _duration_text(r.get("duration_seconds"))
        delta_cell = _delta_cell(r)
        rep_url = _report_href(r)

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
    """Render historical latency SVG trendline.

    A run without a valid duration keeps its place and its "n/a" label. It gets no
    point, and the line breaks there.
    """
    if not sorted_runs:
        return ""
    # `sorted_runs` is newest first: take the ten newest, then show them oldest to newest.
    chrono_runs = list(reversed(sorted_runs[:10]))
    durations = [_seconds_or_none(r.get("duration_seconds")) for r in chrono_runs]
    peak = max((d for d in durations if d is not None), default=None)
    width, height = 700, 160
    padding = 40
    base = height - padding

    segments: list[list[str]] = [[]]
    dots_svg = ""
    labels_svg = ""
    for i, (run, seconds) in enumerate(zip(chrono_runs, durations)):
        x = (
            padding + (i * (width - 2 * padding) / (len(chrono_runs) - 1))
            if len(chrono_runs) > 1
            else width / 2
        )
        ver_label = html.escape(_text_value(run.get("version")) or MISSING)
        labels_svg += f'<text x="{x:.1f}" y="{height - 10}" font-size="11" fill="#cbd5e1" text-anchor="middle">{ver_label}</text>'
        if seconds is None:
            segments.append([])
            dots_svg += f'<text x="{x:.1f}" y="{base - 10:.1f}" font-size="11" fill="#94a3b8" text-anchor="middle">{MISSING}</text>'
            continue
        y = base - (seconds / peak * (height - 2 * padding) if peak else 0.0)
        segments[-1].append(f"{x:.1f},{y:.1f}")
        dots_svg += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#3b82f6" stroke="#fff" stroke-width="2"/>'
        dots_svg += f'<text x="{x:.1f}" y="{y - 10:.1f}" font-size="11" fill="#94a3b8" text-anchor="middle">{seconds:.1f}s</text>'

    polylines = "".join(
        f'<polyline fill="none" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="{" ".join(points)}"/>'
        for points in segments
        if points
    )
    return f"""
    <svg viewBox="0 0 {width} {height}" class="trend-svg">
        <line x1="{padding}" y1="{base}" x2="{width - padding}" y2="{base}" stroke="#334155" stroke-width="1"/>
        {polylines}
        {dots_svg}
        {labels_svg}
    </svg>
    """


def generate_index_dashboard(manifest_data: Any) -> str:
    """Generate the root /benchmarks/index.html multi-version dashboard."""
    runs = (
        [run for run in manifest_data if isinstance(run, dict)]
        if isinstance(manifest_data, (list, tuple))
        else []
    )
    sorted_runs = sorted(runs, key=_run_time_key, reverse=True)

    has_run = bool(sorted_runs)
    latest_run = sorted_runs[0] if has_run else {}
    latest_ver_text = _text_value(latest_run.get("version")) or MISSING
    latest_status_text = _text_value(latest_run.get("status")) or UNKNOWN
    passed = _count(latest_run.get("cases_passed"))
    total = _count(latest_run.get("cases_total"))
    skipped_num = _whole_number(latest_run.get("cases_skipped"))
    counts = f"{passed} of {total} cases passed"
    if skipped_num:
        counts += f" ({skipped_num} skipped)"
    if not has_run:
        latest_summary = "The history holds no run yet"
    elif latest_status_text == PASS:
        latest_summary = counts
    elif latest_status_text == FAIL:
        latest_summary = f"The latest run did not pass: {counts}"
    else:
        latest_summary = f"The status of the latest run is unknown. {counts}"
    latest_report_link = (
        f'<a href="{_report_href(latest_run)}" class="btn-latest">View Latest Full Report →</a>'
        if has_run
        else ""
    )

    return _fill(
        DASHBOARD_HTML_TEMPLATE,
        {
            "LATEST_BADGE_CLASS": _status_badge_class(latest_status_text),
            "LATEST_STATUS": html.escape(latest_status_text),
            "LATEST_VER": html.escape(latest_ver_text),
            "LATEST_REPORT_LINK": latest_report_link,
            "TOTAL_RUNS": str(len(runs)),
            "LATEST_PASS_RATE": f"{passed}/{total}" if has_run else MISSING,
            "LATEST_PASS_PERCENT": _percent(
                latest_run.get("cases_passed"), latest_run.get("cases_total")
            ),
            "LATEST_DURATION": _duration_text(latest_run.get("duration_seconds")),
            "LATEST_DELTA": _delta_cell(latest_run),
            "LATEST_SUMMARY": html.escape(latest_summary),
            "CHART_SVG": _render_dashboard_trend_svg(sorted_runs),
            "TABLE_ROWS": _render_dashboard_table_rows(sorted_runs),
        },
    )
