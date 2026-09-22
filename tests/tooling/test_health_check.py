"""Tests for tools/health_check.py -- the Finance Report route-shadow diagnostics
layered on top of infra2_sdk.deploy_health.poll_until_healthy (finance_report#1535).

Complements AC-testing.deploy-gates.2 (test_post_merge_e2e_gates.py
::test_AC8_13_11_health_check_diagnoses_staging_api_route_404, the canonical
source-shape proof for that AC) with direct behavioral execution of the same
route-shadow-diagnostics property, now that it lives in importable Python
rather than bash.
"""

from __future__ import annotations

import pytest

from common.runtime.health_check import check_health

HEALTH_URL = "https://report-staging.zitian.party/api/health"
BASE_URL = "https://report-staging.zitian.party"


def _router(responses: dict[str, list[tuple[int, str]]]):
    """Route each URL to its own queue of (status, body) responses, repeating
    the last response once a URL's queue is exhausted."""

    def http_get(url: str) -> tuple[int, str]:
        queue = responses[url]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return http_get


def _assert_contains(haystack: str, *markers: str) -> None:
    for marker in markers:
        assert marker in haystack, f"expected output to contain {marker!r}"


def test_succeeds_immediately_on_a_healthy_response() -> None:
    http_get = _router(
        {HEALTH_URL: [(200, '{"status": "healthy", "git_sha": "abc1234"}')]}
    )
    exit_code = check_health(
        HEALTH_URL,
        "staging",
        image_tag="abc1234",
        http_get=http_get,
        sleep=lambda _: None,
    )
    assert exit_code == 0


def test_succeeds_without_an_image_tag() -> None:
    http_get = _router({HEALTH_URL: [(200, '{"status": "healthy"}')]})
    exit_code = check_health(
        HEALTH_URL, "staging", http_get=http_get, sleep=lambda _: None
    )
    assert exit_code == 0


def test_retries_through_a_connection_failure_then_succeeds() -> None:
    http_get = _router(
        {
            HEALTH_URL: [
                (0, "connection refused"),
                (200, '{"status": "healthy"}'),
            ]
        }
    )
    exit_code = check_health(
        HEALTH_URL, "staging", max_attempts=5, http_get=http_get, sleep=lambda _: None
    )
    assert exit_code == 0


def test_prints_route_diagnostics_on_a_404(capsys: pytest.CaptureFixture[str]) -> None:
    http_get = _router(
        {
            HEALTH_URL: [(404, "not found"), (200, '{"status": "healthy"}')],
            f"{BASE_URL}/api/ping": [(200, "pong")],
            f"{BASE_URL}/": [(200, "<html/>")],
        }
    )
    exit_code = check_health(
        HEALTH_URL, "staging", max_attempts=5, http_get=http_get, sleep=lambda _: None
    )
    assert exit_code == 0
    _assert_contains(
        capsys.readouterr().out,
        "route_probe attempt=1",
        "platform_failure_domain=traefik-public-route",
        "api_status=404",
        "ping_status=200",
    )


def test_fails_and_prints_404_diagnostics_after_exhausting_attempts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http_get = _router(
        {
            HEALTH_URL: [(404, "not found")],
            f"{BASE_URL}/api/ping": [(200, "pong")],
            f"{BASE_URL}/": [(200, "<html/>")],
        }
    )
    exit_code = check_health(
        HEALTH_URL, "staging", max_attempts=2, http_get=http_get, sleep=lambda _: None
    )
    assert exit_code == 1
    _assert_contains(
        capsys.readouterr().out,
        "[FAIL] Deployment Failed",
        "Route diagnostics:",
        "Traefik API route is missing or shadowed",
        "Troubleshooting: Check the observability backend",
    )


def test_fails_after_a_stable_version_mismatch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http_get = _router(
        {HEALTH_URL: [(200, '{"status": "healthy", "git_sha": "old0000"}')]}
    )
    exit_code = check_health(
        HEALTH_URL,
        "staging",
        max_attempts=3,
        image_tag="new1111",
        http_get=http_get,
        sleep=lambda _: None,
    )
    assert exit_code == 1
    _assert_contains(
        capsys.readouterr().out,
        "[FAIL] Deployment Failed",
        "still reporting version 'old0000'",
    )


def test_fails_when_the_backend_never_reports_healthy(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http_get = _router({HEALTH_URL: [(200, '{"status": "degraded"}')]})
    exit_code = check_health(
        HEALTH_URL, "staging", max_attempts=2, http_get=http_get, sleep=lambda _: None
    )
    assert exit_code == 1
    _assert_contains(capsys.readouterr().out, "did not become healthy")
