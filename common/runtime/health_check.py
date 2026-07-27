"""Poll a deployed Finance Report URL until the target release is actually live.

Ownership: the generic polling algorithm (HTTP-200 + status-field check, the
version/git_sha stable-mismatch budget) is infra's responsibility, not app's --
extracted to ``infra2_sdk.deploy_health`` (finance_report#1535, infra2-sdk
v0.5.0). This module keeps only Finance Report's own presentation on top of
that shared core: periodic route-shadow probing on a 404 (diagnosing a
missing/shadowed Traefik API route), and the SigNoz observability link. Do
not add behavioral changes to what "healthy" means here -- that belongs in
infra2's deploy contract, which infra2_sdk.deploy_health serves.

Usage:
  python tools/health_check.py <health_url> <environment> [max_attempts] [image_tag]

Exit codes:
  0 - Health check passed
  1 - Health check failed (connection error, HTTP error, or unhealthy status)
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Sequence

from infra2_sdk.deploy_health import HttpGet, default_http_get, poll_until_healthy

SIGNOZ_URL = "https://signoz.zitian.party"
SERVICE_NAME = "finance-report-backend"
DEFAULT_MAX_ATTEMPTS = 24
INTERVAL_SECONDS = 10.0


def check_health(
    health_url: str,
    environment: str,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    image_tag: str = "",
    http_get: HttpGet | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Poll health_url; print progress/diagnostics; return a shell exit code."""
    http_get = http_get or default_http_get()
    app_base_url = health_url.removesuffix("/api/health")
    attempts = [0]
    last_status = [0]

    def probing_http_get(url: str) -> tuple[int, str]:
        attempts[0] += 1
        attempt = attempts[0]
        print(f"[WAITING] Health check attempt {attempt}/{max_attempts}...")
        status_code, body = http_get(url)
        last_status[0] = status_code
        if status_code == 0:
            print(f"[WARNING] Connection failed (attempt {attempt}/{max_attempts})")
        elif status_code != 200:
            print(f"[WARNING] HTTP {status_code} (attempt {attempt}/{max_attempts})")
            if status_code == 404 and (
                attempt == 1 or attempt % 6 == 0 or attempt == max_attempts
            ):
                _print_route_probe(
                    attempt,
                    max_attempts,
                    app_base_url,
                    health_url,
                    status_code,
                    http_get,
                )
        return status_code, body

    print(f"Starting health check for {environment} environment")
    print(f"URL: {health_url}")
    print(
        f"Max attempts: {max_attempts} (timeout: {int(max_attempts * INTERVAL_SECONDS)}s)"
    )
    print()

    try:
        result = poll_until_healthy(
            health_url,
            http_get=probing_http_get,
            expected_version=image_tag,
            require_status="healthy",
            max_attempts=max_attempts,
            interval_seconds=INTERVAL_SECONDS,
            sleep=sleep,
        )
    except RuntimeError as exc:
        print()
        print("=" * 41)
        print("[FAIL] Deployment Failed")
        print("=" * 41)
        print(str(exc))
        if last_status[0] == 404:
            _print_404_route_diagnostics(app_base_url, http_get)
        print()
        _print_troubleshooting_footer(environment)
        print("=" * 41)
        return 1

    elapsed = int(result.attempts * INTERVAL_SECONDS)
    print()
    print("=" * 41)
    print(f"[SUCCESS] Deployment Successful ({elapsed} seconds)")
    print("=" * 41)
    if image_tag:
        print(f"Version: {image_tag}")
    print(f"Environment: {environment}")
    print(f"URL: {app_base_url}")
    print(f"Response: {result.body}")
    print()
    print(f"Logs (observability backend): {SIGNOZ_URL}")
    print(f"Filter: deployment.environment={environment} service_name={SERVICE_NAME}")
    print("=" * 41)
    return 0


def _print_route_probe(
    attempt: int,
    max_attempts: int,
    app_base_url: str,
    health_url: str,
    api_status: int,
    http_get: HttpGet,
) -> None:
    ping_status, _ = http_get(f"{app_base_url}/api/ping")
    frontend_status, _ = http_get(f"{app_base_url}/")
    print(
        f"route_probe attempt={attempt} platform_failure_domain=traefik-public-route "
        f"api_status={api_status} ping_status={ping_status} frontend_status={frontend_status} "
        f"api_url={health_url} frontend_url={app_base_url}/"
    )


def _print_404_route_diagnostics(app_base_url: str, http_get: HttpGet) -> None:
    print()
    print("Route diagnostics:")
    print("The backend health endpoint returned 404 after deployment.")
    print(
        "This usually means the Traefik API route is missing or shadowed by the "
        "frontend route."
    )
    print(
        "Expected route: Host(report*) && PathPrefix(/api) -> backend, with higher "
        "priority than the web route."
    )
    for label, url in (
        ("API ping", f"{app_base_url}/api/ping"),
        ("Frontend shell", f"{app_base_url}/"),
    ):
        status, body = http_get(url)
        print(f"  - {label}: HTTP {status} ({url})")
        print(body[:200])
    print()


def _print_troubleshooting_footer(environment: str) -> None:
    print("Troubleshooting: Check the observability backend for application logs")
    print(f"Filter: deployment.environment={environment} service_name={SERVICE_NAME}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("health_url")
    parser.add_argument("environment")
    parser.add_argument(
        "max_attempts", nargs="?", type=int, default=DEFAULT_MAX_ATTEMPTS
    )
    parser.add_argument("image_tag", nargs="?", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return check_health(
        args.health_url,
        args.environment,
        max_attempts=args.max_attempts,
        image_tag=args.image_tag,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
