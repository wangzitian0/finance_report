"""Rate-limit evidence capture for browser E2E reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

_MAX_EVIDENCE_LINES = 5
_MAX_METHOD_LENGTH = 16
_MAX_PATH_LENGTH = 240


class _RequestLike(Protocol):
    method: str


class _ResponseLike(Protocol):
    status: int
    url: str
    request: _RequestLike


class _ReportLike(Protocol):
    outcome: str
    longrepr: object | None


@dataclass(frozen=True)
class RateLimitHit:
    """Redaction-safe evidence that a browser request received HTTP 429."""

    method: str
    path: str


def _bounded_single_line(value: object, *, limit: int, fallback: str) -> str:
    text = " ".join(str(value).split()) or fallback
    return text[:limit]


def record_rate_limit_response(
    response: _ResponseLike,
    hits: list[RateLimitHit],
) -> None:
    """Record bounded method/path evidence for an HTTP 429 response."""
    if response.status != 429:
        return

    method = _bounded_single_line(
        response.request.method.upper(),
        limit=_MAX_METHOD_LENGTH,
        fallback="UNKNOWN",
    )
    path = _bounded_single_line(
        urlsplit(response.url).path,
        limit=_MAX_PATH_LENGTH,
        fallback="/",
    )
    hits.append(RateLimitHit(method=method, path=path))


def fail_report_for_rate_limits(
    report: _ReportLike,
    hits: list[RateLimitHit],
) -> bool:
    """Fail a pytest report without discarding an earlier failure reason."""
    if not hits:
        return False

    evidence = "\n".join(
        f"  - HTTP 429 {hit.method} {hit.path}"
        for hit in hits[:_MAX_EVIDENCE_LINES]
    )
    remaining = len(hits) - _MAX_EVIDENCE_LINES
    if remaining > 0:
        evidence += f"\n  - {remaining} additional HTTP 429 response(s)"

    diagnostic = (
        "E2E_RATE_LIMIT_EXHAUSTED: the browser received HTTP 429; "
        "the journey result is not trustworthy.\n"
        f"{evidence}"
    )
    if report.longrepr is not None:
        diagnostic = f"{report.longrepr}\n\n{diagnostic}"

    report.outcome = "failed"
    report.longrepr = diagnostic
    return True


__all__ = [
    "RateLimitHit",
    "fail_report_for_rate_limits",
    "record_rate_limit_response",
]
