#!/usr/bin/env python3
"""Production infrastructure smoke checks for release workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SmokeFailure(AssertionError):
    """Raised when a production infrastructure smoke check fails."""


@dataclass(frozen=True)
class HttpResponse:
    """Minimal HTTP response data used by smoke checks."""

    status: int
    body: str


Fetcher = Callable[[str, float], HttpResponse]


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def fetch_url(url: str, timeout: float) -> HttpResponse:
    """Fetch a URL with a small user agent and return status plus body."""
    request = Request(url, headers={"User-Agent": "finance-report-prod-smoke/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return HttpResponse(status=response.status, body=body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return HttpResponse(status=exc.code, body=body)
    except URLError as exc:
        raise SmokeFailure(f"Cannot reach {url}: {exc}") from exc


def _require_success(name: str, response: HttpResponse) -> None:
    if not 200 <= response.status < 400:
        snippet = response.body[:300].replace("\n", " ")
        raise SmokeFailure(f"{name} returned HTTP {response.status}: {snippet}")


def _parse_json(name: str, response: HttpResponse) -> dict[str, Any]:
    _require_success(name, response)
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(
            f"{name} did not return JSON: {response.body[:300]}"
        ) from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{name} returned non-object JSON")
    return payload


def _sha_matches(actual: str, expected: str) -> bool:
    return (
        actual == expected or actual.startswith(expected) or expected.startswith(actual)
    )


def verify_health(
    base_url: str,
    *,
    expected_sha: str | None,
    timeout: float,
    fetcher: Fetcher = fetch_url,
) -> list[str]:
    """Verify production health exposes version plus DB and object-storage checks."""
    payload = _parse_json(
        "Production health", fetcher(_join_url(base_url, "/api/health"), timeout)
    )

    if payload.get("status") != "healthy":
        raise SmokeFailure(f"Production health status is not healthy: {payload}")

    git_sha = str(payload.get("git_sha") or payload.get("version") or "")
    if not git_sha:
        raise SmokeFailure("Production health payload is missing git_sha/version")
    if expected_sha and not _sha_matches(git_sha, expected_sha):
        raise SmokeFailure(
            f"Production version mismatch: expected {expected_sha}, got {git_sha}"
        )

    checks = payload.get("checks")
    if not isinstance(checks, dict):
        raise SmokeFailure("Production health payload is missing checks object")

    required_checks = ("database", "s3")
    failed = [name for name in required_checks if checks.get(name) is not True]
    if failed:
        raise SmokeFailure(f"Production health dependency checks failed: {failed}")

    return [
        f"health status healthy ({git_sha})",
        "database check true",
        "s3 check true",
    ]


def verify_public_runtime(
    base_url: str,
    *,
    timeout: float,
    fetcher: Fetcher = fetch_url,
) -> list[str]:
    """Verify production public runtime endpoints without mutating data."""
    ping = _parse_json(
        "Production ping", fetcher(_join_url(base_url, "/api/ping"), timeout)
    )
    if "state" not in ping or "toggle_count" not in ping:
        raise SmokeFailure(f"Production ping payload is incomplete: {ping}")

    _require_success(
        "Production frontend", fetcher(base_url.rstrip("/") + "/", timeout)
    )
    return ["ping API read-only check", "frontend shell reachable"]


def verify_signoz(
    signoz_url: str,
    *,
    timeout: float,
    fetcher: Fetcher = fetch_url,
) -> list[str]:
    """Verify the shared SigNoz control plane is reachable."""
    health = _parse_json(
        "SigNoz health", fetcher(_join_url(signoz_url, "/api/v1/health"), timeout)
    )
    if health.get("status") != "ok":
        raise SmokeFailure(f"SigNoz health is not ok: {health}")

    version = _parse_json(
        "SigNoz version", fetcher(_join_url(signoz_url, "/api/v1/version"), timeout)
    )
    if version.get("setupCompleted") is not True:
        raise SmokeFailure(f"SigNoz setup is not complete: {version}")

    return [f"signoz health ok ({version.get('version', 'unknown version')})"]


def run_checks(
    *,
    base_url: str,
    expected_sha: str | None,
    signoz_url: str | None,
    timeout: float,
    fetcher: Fetcher = fetch_url,
) -> list[str]:
    """Run production infrastructure smoke checks and return passed check labels."""
    passed: list[str] = []
    passed.extend(
        verify_health(
            base_url,
            expected_sha=expected_sha,
            timeout=timeout,
            fetcher=fetcher,
        )
    )
    passed.extend(verify_public_runtime(base_url, timeout=timeout, fetcher=fetcher))
    if signoz_url:
        passed.extend(verify_signoz(signoz_url, timeout=timeout, fetcher=fetcher))
    return passed


def write_summary(passed: list[str]) -> None:
    """Append smoke results to GitHub Step Summary when available."""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as summary:
        summary.write("## Production Infrastructure Smoke\n\n")
        for label in passed:
            summary.write(f"- OK: {label}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-sha", default=None)
    parser.add_argument("--signoz-url", default=None)
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        passed = run_checks(
            base_url=args.base_url,
            expected_sha=args.expected_sha,
            signoz_url=args.signoz_url,
            timeout=args.timeout,
        )
    except SmokeFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for label in passed:
        print(f"OK: {label}")
    write_summary(passed)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
