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
    "alert_rule_name": "FinanceReportBackendErrorLogs",
    "alert_rule_service_name": "finance-report-backend",
    "alerting_pipeline": "component->otel->signoz->lark",
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


SIGNOZ_QUERY_PATH = "/api/v4/query_range"
SIGNOZ_SERVICE_NAME = "finance-report-backend"
DEFAULT_INGESTION_WINDOW_MINUTES = 15
DEFAULT_INGESTION_POLL_ATTEMPTS = 6
DEFAULT_INGESTION_POLL_INTERVAL = 10.0

# (url, body, headers, timeout) -> response. POST counterpart of ``Fetcher``.
Poster = Callable[[str, bytes, dict[str, str], float], HttpResponse]
# Keyword-only telemetry counter; injected in tests. Mirrors signoz_telemetry_count.
Counter = Callable[..., int]


def post_json(
    url: str, data: bytes, headers: dict[str, str], timeout: float
) -> HttpResponse:
    """POST a JSON body and return status plus body, mirroring ``fetch_url``."""
    request = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return HttpResponse(status=response.status, body=body)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return HttpResponse(status=exc.code, body=body)
    except URLError as exc:
        raise SmokeFailure(f"Cannot reach {url}: {exc}") from exc


def _signoz_query_body(
    *,
    data_source: str,
    environment: str,
    service_name: str,
    version: str | None,
    start_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    """Build a SigNoz v4 builder query that counts telemetry for a deployed service."""
    items = [
        {
            "key": {"key": "service.name", "type": "resource"},
            "op": "=",
            "value": service_name,
        },
        {
            "key": {"key": "deployment.environment", "type": "resource"},
            "op": "=",
            "value": environment,
        },
    ]
    if version:
        items.append(
            {
                "key": {"key": "service.version", "type": "resource"},
                "op": "=",
                "value": version,
            }
        )
    return {
        "start": start_ms,
        "end": end_ms,
        "step": 60,
        "compositeQuery": {
            "queryType": "builder",
            "panelType": "table",
            "builderQueries": {
                "A": {
                    "dataSource": data_source,
                    "queryName": "A",
                    "aggregateOperator": "count",
                    "expression": "A",
                    "disabled": False,
                    "filters": {"op": "AND", "items": items},
                }
            },
        },
    }


def _extract_count(payload: dict[str, Any]) -> int:
    """Pull the scalar count out of a SigNoz table response; missing data means zero.

    A logical query error (``{"status": "error"}`` with HTTP 200) or a non-numeric
    value is surfaced as a ``SmokeFailure`` rather than silently collapsing to zero,
    which would misreport a real query failure as "zero ingestion".
    """
    status = payload.get("status")
    if status is not None and status != "success":
        raise SmokeFailure(f"SigNoz query did not succeed: {payload}")
    result = (payload.get("data") or {}).get("result") or []
    if not result:
        return 0
    series = result[0].get("series") or []
    if not series:
        return 0
    values = series[0].get("values") or []
    if not values:
        return 0
    raw = values[-1].get("value", 0)
    try:
        return int(float(raw))
    except (TypeError, ValueError) as exc:
        raise SmokeFailure(
            f"SigNoz query returned a non-numeric count: {raw!r}"
        ) from exc


def signoz_telemetry_count(
    signoz_url: str,
    api_key: str,
    *,
    data_source: str,
    environment: str,
    service_name: str,
    version: str | None,
    window_minutes: int,
    timeout: float,
    now: float | None = None,
    poster: Poster = post_json,
) -> int:
    """Count deployed-service telemetry in SigNoz over a bounded lookback window."""
    end_ms = int((time.time() if now is None else now) * 1000)
    start_ms = end_ms - window_minutes * 60 * 1000
    body = json.dumps(
        _signoz_query_body(
            data_source=data_source,
            environment=environment,
            service_name=service_name,
            version=version,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    ).encode("utf-8")
    headers = {
        "SIGNOZ-API-KEY": api_key,
        "Content-Type": "application/json",
        # Cloudflare fronts signoz.zitian.party and returns 403 (error 1010) to the
        # default urllib browser signature; use the same agent as ``fetch_url``.
        "User-Agent": "finance-report-prod-smoke/1.0",
    }
    response = poster(_join_url(signoz_url, SIGNOZ_QUERY_PATH), body, headers, timeout)
    payload = _parse_json("SigNoz query", response)
    return _extract_count(payload)


def verify_ingestion(
    signoz_url: str,
    api_key: str,
    *,
    environment: str,
    expected_version: str | None,
    service_name: str = SIGNOZ_SERVICE_NAME,
    window_minutes: int = DEFAULT_INGESTION_WINDOW_MINUTES,
    timeout: float,
    counter: Counter = signoz_telemetry_count,
    poll_attempts: int = DEFAULT_INGESTION_POLL_ATTEMPTS,
    poll_interval: float = DEFAULT_INGESTION_POLL_INTERVAL,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Prove the *deployed version* actually ingests into SigNoz, not just that it is configured.

    Distinguishes the runtime failure modes a config-only smoke cannot see, with no SSH:
    - **zero ingestion** — no telemetry for the service/env at all (exporter not reaching
      the collector, or nothing emitted);
    - **stale image / version mismatch** — telemetry flows for the env but none carries the
      just-deployed ``service.version`` (the running container is an older image).
    """
    passed: list[str] = []
    for data_source in ("logs", "traces"):
        total = _poll_for_telemetry(
            counter,
            signoz_url,
            api_key,
            data_source=data_source,
            environment=environment,
            service_name=service_name,
            version=None,
            window_minutes=window_minutes,
            timeout=timeout,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
            sleeper=sleeper,
        )
        if total == 0:
            raise SmokeFailure(
                f"SigNoz ingestion proof: zero {data_source} for {service_name} in "
                f"{environment} within {window_minutes}m — the OTEL exporter is not "
                "reaching the collector or the deployed version emits nothing"
            )

        if not expected_version:
            passed.append(
                f"signoz {data_source} ingested ({environment}, {total} in {window_minutes}m)"
            )
            continue

        # Poll the version-filtered query with the same retry settings: right after a
        # deploy the version-tagged telemetry can lag the first (unfiltered) hits by a
        # few seconds, which would otherwise look like a false stale-image failure.
        versioned = _poll_for_telemetry(
            counter,
            signoz_url,
            api_key,
            data_source=data_source,
            environment=environment,
            service_name=service_name,
            version=expected_version,
            window_minutes=window_minutes,
            timeout=timeout,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
            sleeper=sleeper,
        )
        if versioned == 0:
            raise SmokeFailure(
                f"SigNoz ingestion proof: stale image — {environment} has {data_source} "
                f"but none tagged service.version={expected_version} within "
                f"{window_minutes}m (the running container is an older image)"
            )
        passed.append(
            f"signoz {data_source} ingested ({environment} "
            f"service.version={expected_version}, {versioned} in {window_minutes}m)"
        )
    return passed


def _poll_for_telemetry(
    counter: Counter,
    signoz_url: str,
    api_key: str,
    *,
    data_source: str,
    environment: str,
    service_name: str,
    version: str | None,
    window_minutes: int,
    timeout: float,
    poll_attempts: int,
    poll_interval: float,
    sleeper: Callable[[float], None],
) -> int:
    """Poll the counter until telemetry appears, tolerating post-deploy flush latency."""
    count = 0
    for attempt in range(max(1, poll_attempts)):
        count = counter(
            signoz_url,
            api_key,
            data_source=data_source,
            environment=environment,
            service_name=service_name,
            version=version,
            window_minutes=window_minutes,
            timeout=timeout,
        )
        if count > 0:
            return count
        if attempt + 1 < max(1, poll_attempts):
            sleeper(poll_interval)
    return count


def _run_ingestion_proof(
    signoz_url: str,
    *,
    signoz_api_key: str | None,
    deployment_environment: str | None,
    expected_version: str | None,
    ingestion_window_minutes: int,
    timeout: float,
    counter: Counter,
) -> list[str]:
    """Run the deployed-version ingestion proof, or an explicit visible skip note."""
    if not signoz_api_key:
        return [
            "signoz ingestion proof SKIPPED (no SIGNOZ_API_KEY — "
            "deployed-version telemetry not verified)"
        ]
    return verify_ingestion(
        signoz_url,
        signoz_api_key,
        environment=deployment_environment or "production",
        expected_version=expected_version,
        window_minutes=ingestion_window_minutes,
        timeout=timeout,
        counter=counter,
    )


def run_checks(
    *,
    base_url: str | None,
    expected_sha: str | None,
    signoz_url: str | None,
    timeout: float,
    fetcher: Fetcher = fetch_url,
    signoz_api_key: str | None = None,
    deployment_environment: str | None = None,
    expected_version: str | None = None,
    ingestion_window_minutes: int = DEFAULT_INGESTION_WINDOW_MINUTES,
    ingestion_only: bool = False,
    ingestion_counter: Counter = signoz_telemetry_count,
) -> list[str]:
    """Run production infrastructure smoke checks and return passed check labels.

    In ``ingestion_only`` mode (used by the staging deploy) only the deployed-version
    SigNoz ingestion proof runs — the prod-shaped health/public-runtime/control-plane
    checks are skipped so a non-production environment is not held to the production
    observability contract.
    """
    if ingestion_only:
        if not signoz_url:
            raise SmokeFailure("ingestion-only mode requires --signoz-url")
        return _run_ingestion_proof(
            signoz_url,
            signoz_api_key=signoz_api_key,
            deployment_environment=deployment_environment,
            expected_version=expected_version,
            ingestion_window_minutes=ingestion_window_minutes,
            timeout=timeout,
            counter=ingestion_counter,
        )

    if not base_url:
        raise SmokeFailure("--base-url is required unless --ingestion-only is set")

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
        passed.extend(
            _run_ingestion_proof(
                signoz_url,
                signoz_api_key=signoz_api_key,
                deployment_environment=deployment_environment,
                expected_version=expected_version,
                ingestion_window_minutes=ingestion_window_minutes,
                timeout=timeout,
                counter=ingestion_counter,
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
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--expected-sha", default=None)
    parser.add_argument("--signoz-url", default=None)
    parser.add_argument("--signoz-api-key", default=os.getenv("SIGNOZ_API_KEY") or None)
    parser.add_argument("--expected-version", default=None)
    parser.add_argument("--deployment-environment", default="production")
    parser.add_argument(
        "--ingestion-window-minutes",
        type=int,
        default=DEFAULT_INGESTION_WINDOW_MINUTES,
    )
    parser.add_argument(
        "--ingestion-only",
        action="store_true",
        help="Run only the deployed-version SigNoz ingestion proof "
        "(for non-production environments).",
    )
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
            signoz_api_key=args.signoz_api_key,
            deployment_environment=args.deployment_environment,
            expected_version=args.expected_version,
            ingestion_window_minutes=args.ingestion_window_minutes,
            ingestion_only=args.ingestion_only,
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
