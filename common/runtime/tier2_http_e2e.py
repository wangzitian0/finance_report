#!/usr/bin/env python3
"""Tier 2 deployed HTTP E2E probe.

This command is intentionally narrower than the browser E2E suite: it proves
that a deployed URL serves the expected version through real HTTP routing and
basic authenticated/unauthenticated API boundaries.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

from common.runtime.http_probe import (
    HttpResponse,
    request_http,
    sha_matches,
    write_json_report,
    write_junit_report,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) in sys.path:
    sys.path.remove(str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR))

PROOF_TIER = "tier2_http"
BASE_URL_ENV_VARS = ("TIER2_HTTP_BASE_URL", "APP_URL", "FRONTEND_URL")


@dataclass(frozen=True)
class CheckResult:
    name: str
    url: str
    passed: bool
    status_code: int
    detail: str


@dataclass(frozen=True)
class Tier2Config:
    base_url: str
    expected_sha: str
    mode: str = "staging"
    timeout_seconds: float = 10.0


RequestFunc = Callable[[str, float], HttpResponse]


def normalize_base_url(base_url: str) -> str:
    trimmed = base_url.strip().rstrip("/")
    if not trimmed.startswith(("http://", "https://")):
        raise ValueError("Tier 2 HTTP E2E requires an http:// or https:// base URL")
    return trimmed


def deployed_input_report(
    *, mode: str, missing_inputs: Sequence[str]
) -> dict[str, object]:
    return {
        "proof_tier": PROOF_TIER,
        "mode": mode,
        "status": "not_run",
        "proof_eligible": False,
        "env_gated": True,
        "missing_inputs": list(missing_inputs),
        "checks": [],
    }


def _json_field(body: str, *field_names: str) -> str | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    for field_name in field_names:
        value = payload.get(field_name)
        if isinstance(value, str) and value:
            return value
    return None


def _result(
    name: str, url: str, response: HttpResponse, passed: bool, detail: str
) -> CheckResult:
    if not passed and response.error:
        detail = f"{detail}: {response.error}"
    return CheckResult(
        name=name,
        url=url,
        passed=passed,
        status_code=response.status_code,
        detail=detail,
    )


def run_tier2_http_e2e(
    config: Tier2Config, requester: RequestFunc = request_http
) -> dict[str, object]:
    base_url = normalize_base_url(config.base_url)
    checks: list[CheckResult] = []

    health_url = urljoin(f"{base_url}/", "api/health")
    health = requester(health_url, config.timeout_seconds)
    checks.append(
        _result(
            "api_health_http_200",
            health_url,
            health,
            health.status_code == 200 and "healthy" in health.body.lower(),
            "GET /api/health must return HTTP 200 with healthy body",
        )
    )
    deployed_version = _json_field(health.body, "git_sha", "version") or ""
    checks.append(
        _result(
            "deployed_version_matches_expected",
            health_url,
            health,
            sha_matches(deployed_version, config.expected_sha),
            f"deployed version must match expected_sha={config.expected_sha}",
        )
    )

    ping_url = urljoin(f"{base_url}/", "api/ping")
    ping = requester(ping_url, config.timeout_seconds)
    checks.append(
        _result(
            "api_ping_http_200",
            ping_url,
            ping,
            ping.status_code == 200,
            "GET /api/ping must return HTTP 200",
        )
    )

    frontend_url = f"{base_url}/"
    frontend = requester(frontend_url, config.timeout_seconds)
    checks.append(
        _result(
            "frontend_http_success",
            frontend_url,
            frontend,
            200 <= frontend.status_code < 400,
            "GET / must return a frontend success/redirect response",
        )
    )

    protected_url = urljoin(f"{base_url}/", "api/statements")
    protected = requester(protected_url, config.timeout_seconds)
    checks.append(
        _result(
            "protected_api_requires_auth",
            protected_url,
            protected,
            protected.status_code in {401, 429},
            "GET /api/statements without credentials must return 401 or rate-limit 429",
        )
    )

    passed = all(check.passed for check in checks)
    return {
        "proof_tier": PROOF_TIER,
        "mode": config.mode,
        "base_url": base_url,
        "expected_sha": config.expected_sha,
        "status": "passed" if passed else "failed",
        "proof_eligible": passed,
        "env_gated": False,
        "checks": [asdict(check) for check in checks],
    }


def _env_value(environ: Mapping[str, str], names: Sequence[str]) -> str | None:
    for name in names:
        value = environ.get(name)
        if value:
            return value
    return None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Tier 2 deployed HTTP E2E checks.")
    parser.add_argument(
        "--base-url",
        help="Deployed app base URL. Falls back to TIER2_HTTP_BASE_URL/APP_URL/FRONTEND_URL.",
    )
    parser.add_argument(
        "--expected-sha",
        help="Expected deployed git_sha/version. Falls back to EXPECTED_SHA.",
    )
    parser.add_argument(
        "--mode", default="staging", help="Environment label for reports."
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--junit-xml", type=Path)
    parser.add_argument(
        "--advisory-if-missing",
        action="store_true",
        help="Return success for local advisory runs with missing inputs, but write proof_eligible=false reports.",
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    requester: RequestFunc = request_http,
) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    env = environ if environ is not None else {}
    base_url = args.base_url or _env_value(env, BASE_URL_ENV_VARS)
    expected_sha = args.expected_sha or env.get("EXPECTED_SHA")

    missing_inputs = []
    if not base_url:
        missing_inputs.append("base_url")
    if not expected_sha:
        missing_inputs.append("expected_sha")
    if missing_inputs:
        report = deployed_input_report(mode=args.mode, missing_inputs=missing_inputs)
        if args.json_report:
            write_json_report(report, args.json_report)
        if args.junit_xml:
            write_junit_report(report, args.junit_xml)
        message = f"Tier 2 HTTP E2E missing required deployed input(s): {', '.join(missing_inputs)}"
        if args.advisory_if_missing:
            print(message)
            return 0
        print(message, file=sys.stderr)
        return 2

    try:
        config = Tier2Config(
            base_url=base_url,
            expected_sha=expected_sha,
            mode=args.mode,
            timeout_seconds=args.timeout_seconds,
        )
        report = run_tier2_http_e2e(config, requester=requester)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json_report:
        write_json_report(report, args.json_report)
    if args.junit_xml:
        write_junit_report(report, args.junit_xml)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:], environ=dict(os.environ)))
