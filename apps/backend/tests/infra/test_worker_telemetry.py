"""Flow-run OTEL contract (#2850): a Prefect flow-run process must export its metrics."""

from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from opentelemetry import metrics as otel_metrics
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult

import src.observability.worker_telemetry as worker_telemetry
from src.extraction.extension import statement_flow
from src.observability import telemetry_metrics

pytestmark = pytest.mark.no_db

OUTCOME_METRIC = "finance.statement_parse.outcome"


class CapturingMetricExporter(MetricExporter):
    """Stands in for the OTLP exporter and keeps every exported batch."""

    instances: list[CapturingMetricExporter] = []

    def __init__(self, endpoint: str = "", **_kwargs: object) -> None:
        super().__init__()
        self.endpoint = endpoint
        self.batches: list[object] = []
        self._lock = threading.Lock()
        CapturingMetricExporter.instances.append(self)

    def export(self, metrics_data, timeout_millis: float = 10_000, **_kwargs: object) -> MetricExportResult:
        with self._lock:
            self.batches.append(metrics_data)
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **_kwargs: object) -> None:
        return None

    def points(self, name: str) -> list[object]:
        found = []
        for batch in self.batches:
            for resource_metrics in batch.resource_metrics:
                for scope_metrics in resource_metrics.scope_metrics:
                    for metric in scope_metrics.metrics:
                        if metric.name == name:
                            found.extend(metric.data.data_points)
        return found

    def service_names(self) -> set[str]:
        return {
            str(rm.resource.attributes.get("service.name")) for batch in self.batches for rm in batch.resource_metrics
        }


@pytest.fixture
def worker_env(monkeypatch):
    """Point settings at a fake endpoint, swap in the capturing exporter, reset globals."""
    import opentelemetry.exporter.otlp.proto.http.metric_exporter as metric_exporter_module

    CapturingMetricExporter.instances.clear()
    monkeypatch.setattr(metric_exporter_module, "OTLPMetricExporter", CapturingMetricExporter)
    monkeypatch.setattr(worker_telemetry.settings, "otel_exporter_otlp_endpoint", "http://collector:4318")
    monkeypatch.setattr(worker_telemetry.settings, "otel_service_name", "finance-report-backend")
    monkeypatch.setattr(worker_telemetry, "_configured", False)
    # The global meter provider is set-once; reopen it so each test installs its own.
    monkeypatch.setattr(otel_metrics._internal, "_METER_PROVIDER", None)
    monkeypatch.setattr(otel_metrics._internal._METER_PROVIDER_SET_ONCE, "_done", False)
    # Logs and traces are not under test here: keep them off the network.
    monkeypatch.setattr(worker_telemetry, "configure_logging", lambda: None)
    telemetry_metrics._clear_metrics_state()
    yield
    telemetry_metrics._clear_metrics_state()


def _job() -> dict[str, str | None]:
    return {
        "statement_id": str(uuid4()),
        "filename": "x.pdf",
        "institution": None,
        "user_id": str(uuid4()),
        "account_id": None,
        "file_hash": "h",
        "storage_key": "k",
        "model": None,
        "request_id": "req-1",
    }


def _install_fake_use_case(monkeypatch, *, fail: bool = False) -> None:
    class FakeUseCase:
        async def execute(self, _job):
            if fail:
                raise RuntimeError("boom")
            telemetry_metrics.record_statement_parse_outcome(outcome="success")

    monkeypatch.setattr(statement_flow, "compose_statement_ingestion_use_case", lambda **_k: FakeUseCase())


async def test_flow_run_exports_parse_outcome_point_before_exit(worker_env, monkeypatch) -> None:
    """AC-observability.12.4: the flow body leaves a parse-outcome point in the exporter by the time it returns."""
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    _install_fake_use_case(monkeypatch)

    await statement_flow.parse_statement_flow.fn(job=_job())

    (exporter,) = CapturingMetricExporter.instances
    points = exporter.points(OUTCOME_METRIC)
    assert [dict(p.attributes) for p in points] == [{"outcome": "success", "parser": "default"}]
    assert exporter.service_names() == {"finance-report-worker"}


async def test_flow_run_service_name_honours_otel_service_name_env(worker_env, monkeypatch) -> None:
    monkeypatch.setenv("OTEL_SERVICE_NAME", "custom-worker")
    _install_fake_use_case(monkeypatch)

    await statement_flow.parse_statement_flow.fn(job=_job())

    (exporter,) = CapturingMetricExporter.instances
    assert exporter.service_names() == {"custom-worker"}


async def test_flow_run_flushes_async_failure_counter_when_the_parse_raises(worker_env, monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    _install_fake_use_case(monkeypatch, fail=True)

    with pytest.raises(RuntimeError, match="boom"):
        await statement_flow.parse_statement_flow.fn(job=_job())

    (exporter,) = CapturingMetricExporter.instances
    points = exporter.points("finance.async_parse.failure")
    assert [dict(p.attributes) for p in points] == [{"task": "statement_parse", "error_type": "RuntimeError"}]


async def test_flow_run_without_endpoint_configures_and_flushes_nothing(worker_env, monkeypatch) -> None:
    monkeypatch.setattr(worker_telemetry.settings, "otel_exporter_otlp_endpoint", None)
    _install_fake_use_case(monkeypatch)

    await statement_flow.parse_statement_flow.fn(job=_job())

    assert CapturingMetricExporter.instances == []
    assert telemetry_metrics.is_metrics_export_active() is False


def test_flush_worker_telemetry_flushes_logs_and_traces_providers(monkeypatch) -> None:
    from src.observability import logger as logger_module

    calls: list[str] = []

    class Provider:
        def __init__(self, name: str) -> None:
            self.name = name

        def force_flush(self, _timeout: int) -> None:
            calls.append(self.name)

    monkeypatch.setattr(logger_module, "_logger_provider", Provider("logs"))
    monkeypatch.setattr(logger_module, "_tracer_provider", Provider("traces"))
    monkeypatch.setattr(telemetry_metrics, "_meter_provider", Provider("metrics"))

    worker_telemetry.flush_worker_telemetry()

    assert calls == ["metrics", "logs", "traces"]
