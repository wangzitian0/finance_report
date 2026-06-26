from __future__ import annotations

import io
import json
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
    signoz_telemetry_count,
    verify_ingestion,
    verify_signoz,
    write_summary,
)


def _make_counter(counts: dict[tuple[str, str | None], int]):
    """Build a fake telemetry counter keyed by (data_source, version)."""

    def counter(
        signoz_url: str,
        api_key: str,
        *,
        data_source: str,
        environment: str,
        service_name: str,
        version: str | None,
        window_minutes: int,
        timeout: float,
    ) -> int:
        assert signoz_url == "https://signoz.zitian.party"
        assert api_key == "tok"
        assert service_name == "finance-report-backend"
        return counts[(data_source, version)]

    return counter


def test_AC10_13_1_ingestion_proof_passes_when_deployed_version_is_queryable() -> None:
    """AC10.13.1: ingestion proof passes when deployed-version logs+traces are queryable."""
    counter = _make_counter(
        {
            ("logs", None): 173,
            ("logs", "v0.1.20"): 173,
            ("traces", None): 1050,
            ("traces", "v0.1.20"): 1050,
        }
    )

    passed = verify_ingestion(
        "https://signoz.zitian.party",
        "tok",
        environment="production",
        expected_version="v0.1.20",
        window_minutes=15,
        timeout=5,
        counter=counter,
        sleeper=lambda _seconds: None,
    )

    assert any("logs ingested" in label and "v0.1.20" in label for label in passed)
    assert any("traces ingested" in label and "v0.1.20" in label for label in passed)


def test_AC10_13_2_ingestion_proof_fails_distinctly_on_zero_ingestion() -> None:
    """AC10.13.2: zero ingestion (no logs at all) is reported distinctly."""
    counter = _make_counter(
        {
            ("logs", None): 0,
            ("logs", "v0.1.20"): 0,
            ("traces", None): 0,
            ("traces", "v0.1.20"): 0,
        }
    )

    with pytest.raises(SmokeFailure, match="zero logs"):
        verify_ingestion(
            "https://signoz.zitian.party",
            "tok",
            environment="production",
            expected_version="v0.1.20",
            window_minutes=15,
            timeout=5,
            counter=counter,
            poll_attempts=2,
            sleeper=lambda _seconds: None,
        )


def test_AC10_13_3_ingestion_proof_fails_distinctly_on_stale_image() -> None:
    """AC10.13.3: logs present but none tagged with the deployed version → stale image."""
    counter = _make_counter(
        {
            ("logs", None): 200,
            ("logs", "v0.1.20"): 0,
            ("traces", None): 200,
            ("traces", "v0.1.20"): 200,
        }
    )

    with pytest.raises(SmokeFailure, match="stale image"):
        verify_ingestion(
            "https://signoz.zitian.party",
            "tok",
            environment="production",
            expected_version="v0.1.20",
            window_minutes=15,
            timeout=5,
            counter=counter,
            sleeper=lambda _seconds: None,
        )


def test_AC10_13_4_ingestion_proof_fails_distinctly_on_absent_traces() -> None:
    """AC10.13.4: logs flow but traces are absent → distinct zero-traces failure."""
    counter = _make_counter(
        {
            ("logs", None): 200,
            ("logs", "v0.1.20"): 200,
            ("traces", None): 0,
            ("traces", "v0.1.20"): 0,
        }
    )

    with pytest.raises(SmokeFailure, match="zero traces"):
        verify_ingestion(
            "https://signoz.zitian.party",
            "tok",
            environment="production",
            expected_version="v0.1.20",
            window_minutes=15,
            timeout=5,
            counter=counter,
            poll_attempts=2,
            sleeper=lambda _seconds: None,
        )


def test_AC10_13_5_telemetry_count_builds_v4_query_and_parses_count() -> None:
    """AC10.13.5: query targets v4 query_range with resource filters; count is parsed."""
    captured: dict[str, object] = {}

    def poster(url: str, data: bytes, headers: dict[str, str], timeout: float):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(data.decode("utf-8"))
        return HttpResponse(
            200,
            '{"status":"success","data":{"result":[{"series":[{"values":'
            '[{"timestamp":0,"value":"173"}]}]}]}}',
        )

    count = signoz_telemetry_count(
        "https://signoz.zitian.party",
        "tok",
        data_source="logs",
        environment="production",
        service_name="finance-report-backend",
        version="v0.1.20",
        window_minutes=15,
        timeout=5,
        now=1_000_000.0,
        poster=poster,
    )

    assert count == 173
    assert str(captured["url"]).endswith("/api/v4/query_range")
    assert captured["headers"]["SIGNOZ-API-KEY"] == "tok"
    body_text = json.dumps(captured["body"])
    assert "finance-report-backend" in body_text
    assert "deployment.environment" in body_text
    assert "service.version" in body_text and "v0.1.20" in body_text


def test_AC10_13_5_telemetry_count_treats_empty_result_as_zero() -> None:
    """AC10.13.5: an empty SigNoz result set is parsed as a zero count, not an error."""

    def poster(url: str, data: bytes, headers: dict[str, str], timeout: float):
        return HttpResponse(200, '{"status":"success","data":{"result":[]}}')

    assert (
        signoz_telemetry_count(
            "https://signoz.zitian.party",
            "tok",
            data_source="logs",
            environment="production",
            service_name="finance-report-backend",
            version=None,
            window_minutes=15,
            timeout=5,
            now=1_000_000.0,
            poster=poster,
        )
        == 0
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            '{"status":"error","error":"query failed"}',
            "did not succeed",
        ),
        (
            '{"status":"success","data":{"result":[{"series":[{"values":'
            '[{"timestamp":0,"value":"NaN"}]}]}]}}',
            "non-numeric count",
        ),
    ],
)
def test_AC10_13_5_telemetry_count_surfaces_query_failures(
    body: str, message: str
) -> None:
    """AC10.13.5: logical query errors and non-numeric counts fail loudly, not as zero."""

    def poster(url: str, data: bytes, headers: dict[str, str], timeout: float):
        return HttpResponse(200, body)

    with pytest.raises(SmokeFailure, match=message):
        signoz_telemetry_count(
            "https://signoz.zitian.party",
            "tok",
            data_source="logs",
            environment="production",
            service_name="finance-report-backend",
            version=None,
            window_minutes=15,
            timeout=5,
            now=1_000_000.0,
            poster=poster,
        )


def test_AC10_13_3_version_filtered_query_is_polled_before_stale_image() -> None:
    """AC10.13.3: a lagging version-tagged count is polled, not flagged stale on first miss."""
    sequence = {
        ("logs", None): [200],
        ("logs", "v0.1.20"): [0, 0, 42],  # appears only on the third poll
        ("traces", None): [200],
        ("traces", "v0.1.20"): [200],
    }
    calls: dict[tuple[str, str | None], int] = {}

    def counter(
        signoz_url: str,
        api_key: str,
        *,
        data_source: str,
        environment: str,
        service_name: str,
        version: str | None,
        window_minutes: int,
        timeout: float,
    ) -> int:
        key = (data_source, version)
        idx = calls.get(key, 0)
        calls[key] = idx + 1
        values = sequence[key]
        return values[min(idx, len(values) - 1)]

    passed = verify_ingestion(
        "https://signoz.zitian.party",
        "tok",
        environment="production",
        expected_version="v0.1.20",
        window_minutes=15,
        timeout=5,
        counter=counter,
        poll_attempts=4,
        sleeper=lambda _seconds: None,
    )

    assert any("logs ingested" in label and "v0.1.20" in label for label in passed)
    assert calls[("logs", "v0.1.20")] == 3


def test_AC10_13_6_run_checks_skips_ingestion_proof_without_api_key() -> None:
    """AC10.13.6: without an API key the ingestion proof is explicitly skipped, not silent."""

    def fetcher(url: str, timeout: float) -> HttpResponse:
        if url.endswith("/api/health"):
            return HttpResponse(200, VALID_HEALTH_BODY)
        if url.endswith("/api/ping"):
            return HttpResponse(200, '{"state":"ping","toggle_count":1}')
        if url.endswith("/api/v1/health"):
            return HttpResponse(200, '{"status":"ok"}')
        if url.endswith("/api/v1/version"):
            return HttpResponse(200, '{"version":"v0.105.1","setupCompleted":true}')
        return HttpResponse(200, "<html></html>")

    passed = run_checks(
        base_url="https://report.zitian.party",
        expected_sha="v0.1.3",
        signoz_url="https://signoz.zitian.party",
        timeout=5,
        fetcher=fetcher,
        signoz_api_key=None,
        deployment_environment="production",
        expected_version="v0.1.20",
    )

    assert any("ingestion proof skipped" in label.lower() for label in passed)


def test_AC10_13_7_ingestion_only_runs_proof_without_prod_health_checks() -> None:
    """AC10.13.7: ingestion-only mode proves staging telemetry without the prod-shaped health gate."""
    calls: list[str] = []

    def counter(
        signoz_url: str,
        api_key: str,
        *,
        data_source: str,
        environment: str,
        service_name: str,
        version: str | None,
        window_minutes: int,
        timeout: float,
    ) -> int:
        assert environment == "staging"
        return 42

    def fetcher(url: str, timeout: float) -> HttpResponse:
        calls.append(url)
        return HttpResponse(200, "{}")

    passed = run_checks(
        base_url=None,
        expected_sha=None,
        signoz_url="https://signoz.zitian.party",
        timeout=5,
        fetcher=fetcher,
        signoz_api_key="tok",
        deployment_environment="staging",
        expected_version="v0.1.20",
        ingestion_only=True,
        ingestion_counter=counter,
    )

    # No app health / public-runtime / signoz-control fetches happen in ingestion-only mode.
    assert calls == []
    assert any("logs ingested" in label and "staging" in label for label in passed)


def test_AC10_13_6_cli_wires_ingestion_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC10.13.6: the CLI threads SigNoz API key, version, and environment into checks."""

    def run_checks_stub(**kwargs: object) -> list[str]:
        assert kwargs["signoz_api_key"] == "tok"
        assert kwargs["expected_version"] == "v0.1.20"
        assert kwargs["deployment_environment"] == "staging"
        return ["database check true"]

    monkeypatch.setattr(production_infra_smoke, "run_checks", run_checks_stub)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert (
        main(
            [
                "--base-url",
                "https://report.zitian.party",
                "--signoz-url",
                "https://signoz.zitian.party",
                "--signoz-api-key",
                "tok",
                "--expected-version",
                "v0.1.20",
                "--deployment-environment",
                "staging",
            ]
        )
        == 0
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
    assert (
        "observability contract enabled (finance-report-backend production)" in passed
    )
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
