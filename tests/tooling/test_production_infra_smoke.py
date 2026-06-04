from __future__ import annotations

import io
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

import common.ci.production_infra_smoke as production_infra_smoke
from common.ci.production_infra_smoke import (
    HttpResponse,
    SmokeFailure,
    fetch_url,
    main,
    run_checks,
    verify_signoz,
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
    '"deployment_environment":"production",'
    '"alert_rule_name":"FinanceReportBackendErrorLogs",'
    '"alert_rule_service_name":"finance-report-backend",'
    '"alerting_pipeline":"component->otel->signoz->lark"'
    "}}"
)


def test_AC8_13_64_production_infra_smoke_requires_db_s3_and_signoz() -> None:
    """AC8.13.64: Production infra smoke proves app dependencies, observability, and SigNoz health."""

    def fetcher(url: str, timeout: float) -> HttpResponse:
        assert timeout == 5
        if url.endswith("/api/health"):
            return HttpResponse(200, VALID_HEALTH_BODY)
        if url.endswith("/api/ping"):
            return HttpResponse(200, '{"state":"ping","toggle_count":1}')
        if url.endswith("/api/v1/health"):
            return HttpResponse(200, '{"status":"ok"}')
        if url.endswith("/api/v1/version"):
            return HttpResponse(
                200,
                '{"version":"v0.105.1","setupCompleted":true}',
            )
        return HttpResponse(200, "<html></html>")

    passed = run_checks(
        base_url="https://report.zitian.party",
        expected_sha="v0.1.3",
        signoz_url="https://signoz.zitian.party",
        timeout=5,
        fetcher=fetcher,
    )

    assert "database check true" in passed
    assert "s3 check true" in passed
    assert "observability contract enabled (finance-report-backend production)" in passed
    assert "signoz health ok (v0.105.1)" in passed


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
                '"deployment_environment":"production",'
                '"alert_rule_name":"FinanceReportBackendErrorLogs",'
                '"alert_rule_service_name":"finance-report-backend",'
                '"alerting_pipeline":"component->otel->signoz->lark"}}',
            )
        return HttpResponse(200, "{}")

    with pytest.raises(SmokeFailure, match="database"):
        run_checks(
            base_url="https://report.zitian.party",
            expected_sha="v0.1.3",
            signoz_url=None,
            timeout=5,
            fetcher=fetcher,
        )


def test_AC8_13_64_production_infra_smoke_fails_when_signoz_is_down() -> None:
    """AC8.13.64: Production infra smoke fails when SigNoz health is not ok."""

    def fetcher(url: str, timeout: float) -> HttpResponse:
        if url.endswith("/api/health"):
            return HttpResponse(200, VALID_HEALTH_BODY)
        if url.endswith("/api/ping"):
            return HttpResponse(200, '{"state":"ping","toggle_count":1}')
        if url.endswith("/api/v1/health"):
            return HttpResponse(503, '{"status":"error"}')
        return HttpResponse(200, "<html></html>")

    with pytest.raises(SmokeFailure, match="SigNoz health"):
        run_checks(
            base_url="https://report.zitian.party",
            expected_sha="v0.1.3",
            signoz_url="https://signoz.zitian.party",
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
            '"deployment_environment":"production",'
            '"alert_rule_name":"FinanceReportBackendErrorLogs",'
            '"alert_rule_service_name":"finance-report-backend",'
            '"alerting_pipeline":"component->otel->signoz->lark"}}',
            "v0.1.3",
            "OTEL exporter is not configured",
        ),
        (
            '{"status":"healthy","git_sha":"v0.1.3",'
            '"checks":{"database":true,"s3":true},'
            '"observability":{"otel_exporter_configured":true,'
            '"logs_export_enabled":true,"traces_export_enabled":true,'
            '"service_name":"wrong-service",'
            '"deployment_environment":"production",'
            '"alert_rule_name":"FinanceReportBackendErrorLogs",'
            '"alert_rule_service_name":"finance-report-backend",'
            '"alerting_pipeline":"component->otel->signoz->lark"}}',
            "v0.1.3",
            "service_name",
        ),
        (
            '{"status":"healthy","git_sha":"v0.1.3",'
            '"checks":{"database":true,"s3":true},'
            '"observability":{"otel_exporter_configured":true,'
            '"logs_export_enabled":true,"traces_export_enabled":true,'
            '"service_name":"finance-report-backend",'
            '"deployment_environment":"production",'
            '"alert_rule_name":"WrongRule",'
            '"alert_rule_service_name":"finance-report-backend",'
            '"alerting_pipeline":"component->otel->signoz->lark"}}',
            "v0.1.3",
            "alert_rule_name",
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
            signoz_url=None,
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
            signoz_url=None,
            timeout=5,
            fetcher=fetcher,
        )


@pytest.mark.parametrize(
    ("health_response", "version_response", "message"),
    [
        (
            HttpResponse(200, '{"status":"bad"}'),
            HttpResponse(200, '{"version":"v0.105.1","setupCompleted":true}'),
            "SigNoz health is not ok",
        ),
        (
            HttpResponse(200, '{"status":"ok"}'),
            HttpResponse(200, '{"version":"v0.105.1","setupCompleted":false}'),
            "SigNoz setup is not complete",
        ),
    ],
)
def test_AC8_13_64_production_infra_smoke_rejects_bad_signoz_payloads(
    health_response: HttpResponse,
    version_response: HttpResponse,
    message: str,
) -> None:
    """AC8.13.64: Production infra smoke rejects incomplete SigNoz proofs."""

    def fetcher(url: str, timeout: float) -> HttpResponse:
        if url.endswith("/api/v1/health"):
            return health_response
        return version_response

    with pytest.raises(SmokeFailure, match=message):
        verify_signoz(
            "https://signoz.zitian.party",
            timeout=5,
            fetcher=fetcher,
        )


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
        assert kwargs["signoz_url"] == "https://signoz.zitian.party"
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
                "--signoz-url",
                "https://signoz.zitian.party",
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
