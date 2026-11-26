from __future__ import annotations

import logging
import threading
import types
from collections import defaultdict
from uuid import uuid4

import pytest
from opentelemetry import metrics as otel_metrics
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult

import src.observability.worker_telemetry as worker_telemetry
from src import statement_flow
from src.observability import telemetry_metrics

pytestmark = pytest.mark.no_db
OUTCOME_METRIC = "finance.statement_parse.outcome"


class CapturingMetricExporter(MetricExporter):
    instances: list[CapturingMetricExporter] = []

    def __init__(self, endpoint: str = "", **_kw: object) -> None:
        super().__init__()
        self.batches: list[object] = []
        self._lock = threading.Lock()
        CapturingMetricExporter.instances.append(self)

    def export(self, metrics_data, **_kw: object) -> MetricExportResult:
        with self._lock:
            self.batches.append(metrics_data)
        return MetricExportResult.SUCCESS

    force_flush = lambda self, _t=10000: True
    shutdown = lambda self, _t=30000, **_kw: None
    points = lambda self, name: [
        p
        for b in self.batches
        for rm in b.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name == name
        for p in m.data.data_points
    ]
    service_names = lambda self: {
        str(rm.resource.attributes.get("service.name")) for b in self.batches for rm in b.resource_metrics
    }


class CapturingLogExporter:
    instances: list[CapturingLogExporter] = []

    def __init__(self, *_a: object, **_kw: object) -> None:
        self.bodies: list[str] = []
        CapturingLogExporter.instances.append(self)

    def export(self, batch):
        from opentelemetry.sdk._logs.export import LogExportResult

        self.bodies.extend(str(getattr(item, "log_record", item).body) for item in batch)
        return LogExportResult.SUCCESS

    force_flush = lambda self, _t=10000: True
    shutdown = lambda self: None


def _fresh_process(monkeypatch) -> None:
    import infra2_sdk.telemetry as sdk_otel
    from opentelemetry import _logs as otel_logs, trace as otel_trace

    if worker_telemetry._providers is not None:
        worker_telemetry._providers.shutdown()
    for target, attr, value in (
        (worker_telemetry, "_configured", False),
        (worker_telemetry, "_providers", None),
        (sdk_otel, "_ACTIVE_GLOBAL", None),
        (otel_metrics._internal, "_METER_PROVIDER", None),
        (otel_metrics._internal._METER_PROVIDER_SET_ONCE, "_done", False),
        (otel_trace, "_TRACER_PROVIDER", None),
        (otel_trace._TRACER_PROVIDER_SET_ONCE, "_done", False),
        (otel_logs._internal, "_LOGGER_PROVIDER", None),
        (otel_logs._internal._LOGGER_PROVIDER_SET_ONCE, "_done", False),
    ):
        monkeypatch.setattr(target, attr, value)
    telemetry_metrics._clear_metrics_state()


@pytest.fixture
def worker_env(monkeypatch):
    import opentelemetry.exporter.otlp.proto.http._log_exporter as log_mod
    import opentelemetry.exporter.otlp.proto.http.metric_exporter as metric_mod
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as trace_mod
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    class _NoopSpan(SpanExporter):
        export = lambda self, _s: SpanExportResult.SUCCESS
        force_flush = lambda self, _t=30000: True
        shutdown = lambda self: None

    CapturingMetricExporter.instances.clear()
    CapturingLogExporter.instances.clear()
    monkeypatch.setattr(metric_mod, "OTLPMetricExporter", CapturingMetricExporter)
    monkeypatch.setattr(log_mod, "OTLPLogExporter", CapturingLogExporter)
    monkeypatch.setattr(trace_mod, "OTLPSpanExporter", lambda *_a, **_kw: _NoopSpan())
    for k, v in (
        ("otel_exporter_otlp_endpoint", "http://collector:4318"),
        ("otel_service_name", "finance-report-backend"),
        ("otel_resource_attributes", "deployment.environment=development"),
    ):
        monkeypatch.setattr(worker_telemetry.settings, k, v)
    monkeypatch.setenv("ENVIRONMENT", "development")
    _fresh_process(monkeypatch)
    yield
    telemetry_metrics._clear_metrics_state()


def _job() -> dict[str, object]:
    return {
        "statement_id": str(uuid4()),
        "run_id": str(uuid4()),
        "filename": "x.pdf",
        "institution": None,
        "user_id": str(uuid4()),
        "account_id": None,
        "file_hash": "h",
        "storage_key": "k",
        "model": None,
        "request_id": "req-1",
    }


def _fake_use_case_factory(*, fail: bool = False):
    async def _exec(_j):
        if fail:
            telemetry_metrics.record_statement_parse_outcome(outcome="failure")
            raise RuntimeError("boom")
        telemetry_metrics.record_statement_parse_outcome(outcome="success")

    return lambda **_k: types.SimpleNamespace(execute=_exec)


@pytest.mark.parametrize(
    ("env_name", "expected_service"), [(None, "finance-report-worker"), ("custom-worker", "custom-worker")]
)
async def test_flow_run_exports_parse_outcome_and_service_name(
    worker_env, monkeypatch, env_name: str | None, expected_service: str
) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False) if env_name is None else monkeypatch.setenv(
        "OTEL_SERVICE_NAME", env_name
    )
    await statement_flow.parse_statement_flow.fn(job=_job(), use_case_factory=_fake_use_case_factory())
    (exporter,) = CapturingMetricExporter.instances
    pts = exporter.points(OUTCOME_METRIC)
    assert {tuple(sorted(p.attributes.items())) for p in pts} == {(("outcome", "success"), ("parser", "default"))}
    assert [p.value for p in sorted(pts, key=lambda p: p.time_unix_nano)] == [0, 1] and exporter.service_names() == {
        expected_service
    }


async def test_flow_run_failure_missing_endpoint_and_flush(worker_env, monkeypatch) -> None:
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    with pytest.raises(RuntimeError, match="boom"):
        await statement_flow.parse_statement_flow.fn(job=_job(), use_case_factory=_fake_use_case_factory(fail=True))
    pts = CapturingMetricExporter.instances[0].points("finance.async_parse.failure")
    assert {tuple(sorted(p.attributes.items())) for p in pts} == {
        (("error_type", "RuntimeError"), ("task", "statement_parse"))
    } and [p.value for p in sorted(pts, key=lambda p: p.time_unix_nano)] == [0, 1]

    CapturingMetricExporter.instances.clear()
    _fresh_process(monkeypatch)
    monkeypatch.setattr(worker_telemetry.settings, "otel_exporter_otlp_endpoint", None)
    await statement_flow.parse_statement_flow.fn(job=_job(), use_case_factory=_fake_use_case_factory())
    assert CapturingMetricExporter.instances == [] and telemetry_metrics.is_metrics_export_active() is False

    calls: list[str] = []
    prov = lambda name: types.SimpleNamespace(force_flush=lambda _t: calls.append(name))
    monkeypatch.setattr(otel_metrics, "get_meter_provider", lambda: prov("metrics"))
    monkeypatch.setattr(
        worker_telemetry,
        "_providers",
        types.SimpleNamespace(logger_provider=prov("logs"), tracer_provider=prov("traces")),
    )
    worker_telemetry.flush_worker_telemetry()
    assert calls == ["metrics", "logs", "traces"]


def _prom_increase(exporters, metric: str, **labels: str) -> float:
    series: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    for exp in exporters:
        for b in exp.batches:
            for rm in b.resource_metrics:
                res = tuple(sorted((k, str(v)) for k, v in rm.resource.attributes.items()))
                for sm in rm.scope_metrics:
                    for md in sm.metrics:
                        if md.name == metric:
                            for pt in md.data.data_points:
                                if all(pt.attributes.get(k) == v for k, v in labels.items()):
                                    series[(res, tuple(sorted(pt.attributes.items())))].append(
                                        (pt.time_unix_nano, pt.value)
                                    )
    return sum(v - p if v >= p else v for s in series.values() for (_, p), (_, v) in zip(sorted(s), sorted(s)[1:]))


async def test_three_flow_run_processes_and_prefect_logs(worker_env, monkeypatch, capsys) -> None:
    from prefect.logging.configuration import setup_logging

    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    for _ in range(3):
        _fresh_process(monkeypatch)
        with pytest.raises(RuntimeError, match="boom"):
            await statement_flow.parse_statement_flow.fn(job=_job(), use_case_factory=_fake_use_case_factory(fail=True))
    exps = CapturingMetricExporter.instances
    assert (
        len(exps) == 3
        and len(
            {
                rm.resource.attributes["service.instance.id"]
                for e in exps
                for b in e.batches
                for rm in b.resource_metrics
            }
        )
        == 3
    )
    assert (
        _prom_increase(exps, OUTCOME_METRIC, outcome="failure"),
        _prom_increase(exps, "finance.async_parse.failure"),
    ) == (3, 3)

    single = CapturingMetricExporter()
    for i in range(3):
        single.batches.append(
            types.SimpleNamespace(
                resource_metrics=[
                    types.SimpleNamespace(
                        resource=types.SimpleNamespace(attributes={"service.name": "finance-report-worker"}),
                        scope_metrics=[
                            types.SimpleNamespace(
                                metrics=[
                                    types.SimpleNamespace(
                                        name=OUTCOME_METRIC,
                                        data=types.SimpleNamespace(
                                            data_points=[
                                                types.SimpleNamespace(
                                                    attributes={"outcome": "failure"}, value=1, time_unix_nano=i
                                                )
                                            ]
                                        ),
                                    )
                                ]
                            )
                        ],
                    )
                ]
            )
        )
    assert _prom_increase([single], OUTCOME_METRIC, outcome="failure") == 0

    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    root.handlers.clear()
    root.setLevel(logging.WARNING)
    setup_logging()
    CapturingLogExporter.instances.clear()
    monkeypatch.setattr(worker_telemetry.settings, "debug", False)
    _fresh_process(monkeypatch)
    try:
        await statement_flow.parse_statement_flow.fn(job=_job(), use_case_factory=_fake_use_case_factory())
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
    assert (
        any("statement.parse.flow_started" in body for body in CapturingLogExporter.instances[0].bodies)
        and "statement.parse.flow_started" in capsys.readouterr().out
    )
