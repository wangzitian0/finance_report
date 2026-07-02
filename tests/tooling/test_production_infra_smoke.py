from __future__ import annotations

import io
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

import common.runtime.production_infra_smoke as production_infra_smoke
from common.runtime.production_infra_smoke import (
    HttpResponse,
    SmokeFailure,
    fetch_url,
    main,
    run_checks,
    write_summary,
)

VALID_HEALTH_BODY = (
    '{"status":"healthy","git_sha":"v0.1.3",'
    '"checks":{"database":true,"s3":true},'
    '"observability":{'
    '"otel_exporter_configured":true,'
    '"logs_export_enabled":true,'
    '"traces_export_enabled":true,'
    '"service_name":"finance-report-backend",'
    '"deployment_environment":"production"'
    "}}"
)


def test_AC8_13_64_production_infra_smoke_requires_db_s3_and_observability() -> None:
    """AC8.13.64: Production infra smoke proves app dependencies and vendor-neutral OTEL readiness."""

    def fetcher(url: str, timeout: float) -> HttpResponse:
        assert timeout == 5
        if url.endswith("/api/health"):
            return HttpResponse(200, VALID_HEALTH_BODY)
        if url.endswith("/api/ping"):
            return HttpResponse(200, '{"state":"ping","toggle_count":1}')
        return HttpResponse(200, "<html></html>")

    passed = run_checks(
        base_url="https://report.zitian.party",
        expected_sha="v0.1.3",
        timeout=5,
        fetcher=fetcher,
    )

    assert "database check true" in passed
    assert "s3 check true" in passed
    assert (
        "observability contract enabled (finance-report-backend production)" in passed
    )


def test_AC8_13_64_production_infra_smoke_fails_when_db_is_down() -> None:
    """AC8.13.64: Production infra smoke fails on unhealthy DB checks."""

    def fetcher(url: str, timeout: float) -> HttpResponse:
        if url.endswith("/api/health"):
            return HttpResponse(
                200,
                '{"status":"healthy","git_sha":"v0.1.3",'
                '"checks":{"database":false,"s3":true},'
                '"observability":{"otel_exporter_configured":true,'
                '"logs_export_enabled":true,"traces_export_enabled":true,'
                '"service_name":"finance-report-backend",'
                '"deployment_environment":"production"}}',
            )
        return HttpResponse(200, "{}")

    with pytest.raises(SmokeFailure, match="database"):
        run_checks(
            base_url="https://report.zitian.party",
            expected_sha="v0.1.3",
            timeout=5,
            fetcher=fetcher,
        )


@pytest.mark.parametrize(
    ("health_body", "expected_sha", "message"),
    [
        (
            '{"status":"degraded","git_sha":"v0.1.3",'
            '"checks":{"database":true,"s3":true}}',
            "v0.1.3",
            "status is not healthy",
        ),
        (
            '{"status":"healthy","checks":{"database":true,"s3":true}}',
            "v0.1.3",
            "missing git_sha/version",
        ),
        (
            '{"status":"healthy","git_sha":"old-sha",'
            '"checks":{"database":true,"s3":true}}',
            "new-sha",
            "version mismatch",
        ),
        (
            '{"status":"healthy","git_sha":"v0.1.3"}',
            "v0.1.3",
            "missing checks object",
        ),
        (
            '{"status":"healthy","git_sha":"v0.1.3",'
            '"checks":{"database":true,"s3":false}}',
            "v0.1.3",
            "s3",
        ),
        (
            '{"status":"healthy","git_sha":"v0.1.3",'
            '"checks":{"database":true,"s3":true}}',
            "v0.1.3",
            "missing observability object",
        ),
        (
            '{"status":"healthy","git_sha":"v0.1.3",'
            '"checks":{"database":true,"s3":true},'
            '"observability":{"otel_exporter_configured":false,'
            '"logs_export_enabled":true,"traces_export_enabled":true,'
            '"service_name":"finance-report-backend",'
            '"deployment_environment":"production"}}',
            "v0.1.3",
            "OTEL exporter is not configured",
        ),
        (
            '{"status":"healthy","git_sha":"v0.1.3",'
            '"checks":{"database":true,"s3":true},'
            '"observability":{"otel_exporter_configured":true,'
            '"logs_export_enabled":true,"traces_export_enabled":true,'
            '"service_name":"wrong-service",'
            '"deployment_environment":"production"}}',
            "v0.1.3",
            "service_name",
        ),
    ],
)
def test_AC8_13_64_production_infra_smoke_rejects_bad_health_payloads(
    health_body: str,
    expected_sha: str,
    message: str,
) -> None:
    """AC8.13.64: Production infra smoke rejects incomplete health proofs."""

    def fetcher(url: str, timeout: float) -> HttpResponse:
        assert url.endswith("/api/health")
        return HttpResponse(200, health_body)

    with pytest.raises(SmokeFailure, match=message):
        run_checks(
            base_url="https://report.zitian.party",
            expected_sha=expected_sha,
            timeout=5,
            fetcher=fetcher,
        )


@pytest.mark.parametrize(
    ("url_suffix", "response", "message"),
    [
        ("/api/health", HttpResponse(200, "not-json"), "did not return JSON"),
        ("/api/health", HttpResponse(200, "[]"), "non-object JSON"),
        (
            "/api/ping",
            HttpResponse(200, '{"state":"ping"}'),
            "ping payload is incomplete",
        ),
        ("/", HttpResponse(500, "server error"), "frontend returned HTTP 500"),
    ],
)
def test_AC8_13_64_production_infra_smoke_rejects_bad_runtime_responses(
    url_suffix: str,
    response: HttpResponse,
    message: str,
) -> None:
    """AC8.13.64: Production infra smoke rejects broken public runtime responses."""

    def fetcher(url: str, timeout: float) -> HttpResponse:
        if url.endswith(url_suffix):
            return response
        if url.endswith("/api/health"):
            return HttpResponse(200, VALID_HEALTH_BODY)
        if url.endswith("/api/ping"):
            return HttpResponse(200, '{"state":"ping","toggle_count":1}')
        return HttpResponse(200, "<html></html>")

    with pytest.raises(SmokeFailure, match=message):
        run_checks(
            base_url="https://report.zitian.party",
            expected_sha="v0.1.3",
            timeout=5,
            fetcher=fetcher,
            sleeper=lambda _seconds: None,
        )


def test_AC8_13_64_production_infra_smoke_retries_frontend_cold_start() -> None:
    """AC8.13.64: a transient post-deploy frontend 404/route-rollover is retried, not failed.

    Regression guard for the v0.1.21 prod release: the frontend `/` returned 404
    during the Traefik/container rollover and rolled back a good deploy. The gate
    must poll until the route is ready instead of failing on the first miss.
    """
    calls = {"frontend": 0}

    def fetcher(url: str, timeout: float) -> HttpResponse:
        if url.endswith("/api/health"):
            return HttpResponse(200, VALID_HEALTH_BODY)
        if url.endswith("/api/ping"):
            return HttpResponse(200, '{"state":"ping","toggle_count":1}')
        # frontend root: 404 twice (cold start), then 200 once routable.
        calls["frontend"] += 1
        if calls["frontend"] < 3:
            return HttpResponse(404, "404 page not found")
        return HttpResponse(200, "<html></html>")

    passed = run_checks(
        base_url="https://report.zitian.party",
        expected_sha="v0.1.3",
        timeout=5,
        fetcher=fetcher,
        sleeper=lambda _seconds: None,
    )

    assert "frontend shell reachable" in passed
    assert calls["frontend"] == 3


def test_AC8_13_64_production_infra_smoke_writes_github_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.64: Production infra smoke publishes concise GitHub summaries."""

    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    write_summary(["database check true", "s3 check true"])

    assert summary_path.read_text() == (
        "## Production Infrastructure Smoke\n\n"
        "- OK: database check true\n"
        "- OK: s3 check true\n"
    )


def test_AC8_13_64_production_infra_smoke_cli_reports_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.64: Production infra smoke CLI returns success after proof checks."""

    def run_checks_stub(**kwargs: object) -> list[str]:
        assert kwargs["base_url"] == "https://report.zitian.party"
        assert kwargs["expected_sha"] == "v0.1.3"
        assert kwargs["timeout"] == 3.0
        return ["database check true"]

    monkeypatch.setattr(production_infra_smoke, "run_checks", run_checks_stub)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert (
        main(
            [
                "--base-url",
                "https://report.zitian.party",
                "--expected-sha",
                "v0.1.3",
                "--timeout",
                "3",
            ]
        )
        == 0
    )

    assert "OK: database check true" in capsys.readouterr().out


def test_AC8_13_64_production_infra_smoke_cli_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.64: Production infra smoke CLI returns failure on proof gaps."""

    def run_checks_stub(**kwargs: object) -> list[str]:
        raise SmokeFailure("database down")

    monkeypatch.setattr(production_infra_smoke, "run_checks", run_checks_stub)

    assert main(["--base-url", "https://report.zitian.party"]) == 1
    assert "ERROR: database down" in capsys.readouterr().err


def test_AC8_13_64_production_infra_smoke_fetch_url_success_and_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.64: Production infra smoke preserves HTTP status and body."""

    class Response:
        status = 204

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"ok"

    def urlopen_success(request: object, timeout: float) -> Response:
        return Response()

    monkeypatch.setattr(production_infra_smoke, "urlopen", urlopen_success)
    assert fetch_url("https://report.zitian.party/api/health", 5) == HttpResponse(
        204,
        "ok",
    )

    error = HTTPError(
        "https://report.zitian.party/api/health",
        503,
        "Service Unavailable",
        {},
        io.BytesIO(b"down"),
    )

    def urlopen_http_error(request: object, timeout: float) -> Response:
        raise error

    monkeypatch.setattr(production_infra_smoke, "urlopen", urlopen_http_error)
    assert fetch_url("https://report.zitian.party/api/health", 5) == HttpResponse(
        503,
        "down",
    )


def test_AC8_13_64_production_infra_smoke_fetch_url_wraps_url_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.64: Production infra smoke reports unreachable production URLs."""

    def urlopen_url_error(request: object, timeout: float) -> None:
        raise URLError("timeout")

    monkeypatch.setattr(production_infra_smoke, "urlopen", urlopen_url_error)

    with pytest.raises(SmokeFailure, match="Cannot reach"):
        fetch_url("https://report.zitian.party/api/health", 5)
