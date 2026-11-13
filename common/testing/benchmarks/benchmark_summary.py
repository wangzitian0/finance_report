"""Benchmark JSON-summary semantics: honest counts, verdicts, sanitisation."""

from __future__ import annotations

from common.testing.benchmarks.case_types import (
    FLOW_TO_CASES,
    FLOW_TO_DOMAIN,
    get_case_to_flows,
)
from common.testing.benchmarks.case_types import (
    FLOW_TO_CASES,
    FLOW_TO_DOMAIN,
    get_case_to_flows,
)
from decimal import Decimal
from decimal import InvalidOperation
from pathlib import Path
from typing import Any
import os
import re
import tempfile


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

COUNT_LIMIT = DURATION_LIMIT = 10**9

SUMMARY_FLAG_CASES = (
    ("zero_pnl_contamination", "case_3"),
    ("rollforward_balanced", "case_1"),
    ("multicurrency_consolidated", "case_4"),
    ("portfolio_holdings_verified", "case_5"),
    ("overdraft_articulation_verified", "case_6"),
)

TELEMETRY_DEPTH_LIMIT = 50

_SURROGATE = re.compile(r"[\ud800-\udfff]")

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

def _details_of(result: dict[str, Any]) -> dict[str, Any]:
    d = result.get("details")
    return d if isinstance(d, dict) else {}

def _case_id(result: dict[str, Any]) -> str | None:
    cid = result.get("case_id")
    return cid if isinstance(cid, str) and cid else None

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

def _whole_number(value: Any) -> int | None:
    n = _number(value)
    if n is None or not 0 <= n <= COUNT_LIMIT or n != n.to_integral_value():
        return None
    return int(n)

def _seconds_or_none(value: Any) -> float | None:
    n = _number(value)
    return abs(float(n)) if n is not None and 0 <= n <= DURATION_LIMIT else None

def _total_seconds(results: list[dict[str, Any]]) -> float | None:
    if not results:
        return None
    durs = [_seconds_or_none(r.get("duration_seconds")) for r in results]
    return (
        None if any(s is None for s in durs) else sum(s for s in durs if s is not None)
    )

def _format_number(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    size = value.copy_abs()
    if size == 0 or (
        DELTA_FIXED_MIN <= size < DELTA_FIXED_MAX and len(size.as_tuple().digits) <= 28
    ):
        rounded = size.quantize(Decimal("0.01"))
        return sign + (str(rounded) if rounded == size else format(size, "f"))
    return f"{sign}{size:.3E}"

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
