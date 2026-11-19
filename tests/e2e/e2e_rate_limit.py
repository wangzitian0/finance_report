"""Rate-limit evidence capture for browser E2E reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

_MAX_EVIDENCE_LINES, _MAX_METHOD_LENGTH, _MAX_PATH_LENGTH = 5, 16, 240


@dataclass(frozen=True)
class RateLimitHit:
    method: str
    path: str


def _bounded_single_line(value: object, *, limit: int, fallback: str) -> str:
    return (" ".join(str(value).split()) or fallback)[:limit]


def record_rate_limit_response(response: Any, hits: list[RateLimitHit]) -> None:
    if response.status != 429:
        return
    hits.append(
        RateLimitHit(
            method=_bounded_single_line(
                response.request.method.upper(),
                limit=_MAX_METHOD_LENGTH,
                fallback="UNKNOWN",
            ),
            path=_bounded_single_line(
                urlsplit(response.url).path, limit=_MAX_PATH_LENGTH, fallback="/"
            ),
        )
    )


def fail_report_for_rate_limits(report: Any, hits: list[RateLimitHit]) -> bool:
    if not hits:
        return False
    evidence = "\n".join(
        f"  - HTTP 429 {h.method} {h.path}" for h in hits[:_MAX_EVIDENCE_LINES]
    )
    if (remaining := len(hits) - _MAX_EVIDENCE_LINES) > 0:
        evidence += f"\n  - {remaining} additional HTTP 429 response(s)"
    diagnostic = f"E2E_RATE_LIMIT_EXHAUSTED: the browser received HTTP 429; the journey result is not trustworthy.\n{evidence}"
    report.longrepr = (
        f"{report.longrepr}\n\n{diagnostic}"
        if report.longrepr is not None
        else diagnostic
    )
    report.outcome = "failed"
    return True


__all__ = ["RateLimitHit", "fail_report_for_rate_limits", "record_rate_limit_response"]
