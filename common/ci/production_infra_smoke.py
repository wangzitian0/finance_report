#!/usr/bin/env python3
"""Production infrastructure smoke checks for release workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# The public-runtime checks run right after deploy_v2, while the frontend container
# and its Traefik route may still be rolling over. Poll the route until it is ready
# instead of failing the gate (and rolling back a good deploy) on a cold-start race.
DEFAULT_READY_ATTEMPTS = 12
DEFAULT_READY_INTERVAL = 5.0


class SmokeFailure(AssertionError):
    """Raised when a production infrastructure smoke check fails."""


@dataclass(frozen=True)
class HttpResponse:
    """Minimal HTTP response data used by smoke checks."""

    status: int
    body: str


Fetcher = Callable[[str, float], HttpResponse]

EXPECTED_OBSERVABILITY = {
    "service_name": "finance-report-backend",
    "deployment_environment": "production",
}


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

    observability = payload.get("observability")
    if not isinstance(observability, dict):
        raise SmokeFailure("Production health payload is missing observability object")

    flag_messages = {
        "otel_exporter_configured": "OTEL exporter is not configured",
        "logs_export_enabled": "OTEL log export is not enabled",
        "traces_export_enabled": "OTEL trace export is not enabled",
    }
    for key, message in flag_messages.items():
        if observability.get(key) is not True:
            raise SmokeFailure(f"Production observability {message}")

    for key, expected in EXPECTED_OBSERVABILITY.items():
        actual = observability.get(key)
        if actual != expected:
            raise SmokeFailure(
                f"Production observability {key} mismatch: "
                f"expected {expected}, got {actual}"
            )

    return [
        f"health status healthy ({git_sha})",
        "database check true",
        "s3 check true",
        "observability contract enabled (finance-report-backend production)",
    ]


def _fetch_until_ready(
    name: str,
    url: str,
    *,
    timeout: float,
    fetcher: Fetcher,
    attempts: int,
    interval: float,
    sleeper: Callable[[float], None],
) -> HttpResponse:
    """Fetch a URL, retrying transient not-ready responses.

    The deploy gate runs immediately after deploy_v2, but the frontend container and
    its Traefik route can still be rolling over a few seconds after the backend is
    healthy. A single immediate GET then races that window and a transient 404/5xx
    rolls back a perfectly good deploy. Retry until the route is ready (2xx/3xx) or
    the bounded window is exhausted; the final failure carries the last status.
    """
    last: HttpResponse | None = None
    for attempt in range(max(1, attempts)):
        try:
            response = fetcher(url, timeout)
        except SmokeFailure as exc:
            # URLError (host/route not up yet) surfaces as SmokeFailure from fetch_url.
            last = HttpResponse(0, str(exc))
        else:
            last = response
            if 200 <= response.status < 400:
                return response
        if attempt + 1 < max(1, attempts):
            sleeper(interval)
    _require_success(name, last if last is not None else HttpResponse(0, "no response"))
    return last  # pragma: no cover - _require_success raises on a non-2xx/3xx last


def verify_public_runtime(
    base_url: str,
    *,
    timeout: float,
    fetcher: Fetcher = fetch_url,
    ready_attempts: int = DEFAULT_READY_ATTEMPTS,
    ready_interval: float = DEFAULT_READY_INTERVAL,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Verify production public runtime endpoints without mutating data.

    The frontend shell and ping route are polled until the post-deploy route
    rollover settles, so a cold-start race no longer fails the gate.
    """
    ping_response = _fetch_until_ready(
        "Production ping",
        _join_url(base_url, "/api/ping"),
        timeout=timeout,
        fetcher=fetcher,
        attempts=ready_attempts,
        interval=ready_interval,
        sleeper=sleeper,
    )
    ping = _parse_json("Production ping", ping_response)
    if "state" not in ping or "toggle_count" not in ping:
        raise SmokeFailure(f"Production ping payload is incomplete: {ping}")

    _fetch_until_ready(
        "Production frontend",
        base_url.rstrip("/") + "/",
        timeout=timeout,
        fetcher=fetcher,
        attempts=ready_attempts,
        interval=ready_interval,
        sleeper=sleeper,
    )
    return ["ping API read-only check", "frontend shell reachable"]


def run_checks(
    *,
    base_url: str,
    expected_sha: str | None,
    timeout: float,
    fetcher: Fetcher = fetch_url,
    ready_attempts: int = DEFAULT_READY_ATTEMPTS,
    ready_interval: float = DEFAULT_READY_INTERVAL,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Run production infrastructure smoke checks and return passed check labels.

    Scope is deliberately app-side and vendor-neutral: app health, version, DB/S3
    dependencies, public runtime, and OTEL exporter readiness. Proving the
    observability *backend* is reachable and actually ingesting is infra2's job,
    not the app's deploy gate.
    """
    passed: list[str] = []
    passed.extend(
        verify_health(
            base_url,
            expected_sha=expected_sha,
            timeout=timeout,
            fetcher=fetcher,
        )
    )
    passed.extend(
        verify_public_runtime(
            base_url,
            timeout=timeout,
            fetcher=fetcher,
            ready_attempts=ready_attempts,
            ready_interval=ready_interval,
            sleeper=sleeper,
        )
    )
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
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        passed = run_checks(
            base_url=args.base_url,
            expected_sha=args.expected_sha,
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
