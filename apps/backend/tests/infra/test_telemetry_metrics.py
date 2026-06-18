"""OTEL metrics contract tests for EPIC-010."""

from __future__ import annotations

import sys
import types

import pytest

from src import telemetry_metrics

pytestmark = pytest.mark.no_db


class FakeInstrument:
    def __init__(self) -> None:
        self.add_calls: list[tuple[int, dict[str, str]]] = []
        self.record_calls: list[tuple[float, dict[str, str]]] = []

    def add(self, value: int, attributes: dict[str, str]) -> None:
        self.add_calls.append((value, attributes))

    def record(self, value: float, attributes: dict[str, str]) -> None:
        self.record_calls.append((value, attributes))


class FakeMeter:
    def __init__(self) -> None:
        self.counters: dict[str, FakeInstrument] = {}
        self.histograms: dict[str, FakeInstrument] = {}
        self.gauges: dict[str, object] = {}

    def create_counter(self, name: str, **_kwargs: object) -> FakeInstrument:
        instrument = FakeInstrument()
        self.counters[name] = instrument
        return instrument

    def create_histogram(self, name: str, **_kwargs: object) -> FakeInstrument:
        instrument = FakeInstrument()
        self.histograms[name] = instrument
        return instrument

    def create_observable_gauge(self, name: str, **kwargs: object) -> None:
        self.gauges[name] = kwargs["callbacks"]


def install_fake_otel(monkeypatch: pytest.MonkeyPatch) -> FakeMeter:
    meter = FakeMeter()

    class FakeResource:
        @staticmethod
        def create(attributes: dict[str, str]) -> types.SimpleNamespace:
            return types.SimpleNamespace(attributes=attributes)

    class FakeExporter:
        def __init__(self, endpoint: str) -> None:
            self.endpoint = endpoint

    class FakeReader:
        def __init__(self, exporter: FakeExporter) -> None:
            self.exporter = exporter

    class FakeProvider:
        def __init__(self, resource: object, metric_readers: list[FakeReader]) -> None:
            self.resource = resource
            self.metric_readers = metric_readers

    def make_module(name: str, is_pkg: bool = False) -> types.ModuleType:
        module = types.ModuleType(name)
        if is_pkg:
            module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
        return module

    opentelemetry = make_module("opentelemetry", is_pkg=True)
    metrics = make_module("opentelemetry.metrics")
    metrics.get_meter = lambda _name: meter
    metrics.set_meter_provider = lambda _provider: None
    metrics.Observation = lambda value, attributes=None: (value, attributes or {})

    exporter = make_module("opentelemetry.exporter", is_pkg=True)
    otlp = make_module("opentelemetry.exporter.otlp", is_pkg=True)
    proto = make_module("opentelemetry.exporter.otlp.proto", is_pkg=True)
    http = make_module("opentelemetry.exporter.otlp.proto.http", is_pkg=True)
    metric_exporter = make_module("opentelemetry.exporter.otlp.proto.http.metric_exporter")
    metric_exporter.OTLPMetricExporter = FakeExporter

    sdk = make_module("opentelemetry.sdk", is_pkg=True)
    sdk_metrics = make_module("opentelemetry.sdk.metrics")
    sdk_metrics.MeterProvider = FakeProvider
    sdk_metrics_export = make_module("opentelemetry.sdk.metrics.export")
    sdk_metrics_export.PeriodicExportingMetricReader = FakeReader
    sdk_resources = make_module("opentelemetry.sdk.resources")
    sdk_resources.Resource = FakeResource

    opentelemetry.metrics = metrics
    opentelemetry.exporter = exporter
    exporter.otlp = otlp
    otlp.proto = proto
    proto.http = http
    http.metric_exporter = metric_exporter
    opentelemetry.sdk = sdk
    sdk.metrics = sdk_metrics
    sdk.resources = sdk_resources
    sdk_metrics.export = sdk_metrics_export
    return meter


def test_AC10_10_1_configure_metrics_is_noop_without_endpoint(monkeypatch) -> None:
    """AC10.10.1: metrics export is disabled when OTEL endpoint is absent."""
    monkeypatch.setattr(telemetry_metrics.settings, "otel_exporter_otlp_endpoint", None)
    telemetry_metrics.mark_metrics_export_active(True)

    telemetry_metrics.configure_otel_metrics()

    assert telemetry_metrics.is_metrics_export_active() is False


def test_AC10_10_1_configure_metrics_creates_otlp_provider(monkeypatch) -> None:
    """AC10.10.1: MeterProvider and OTLP exporter use the shared endpoint."""
    meter = install_fake_otel(monkeypatch)
    monkeypatch.setattr(
        telemetry_metrics.settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318",
    )
    monkeypatch.setattr(telemetry_metrics.settings, "otel_service_name", "finance-report-backend")
    monkeypatch.setattr(
        telemetry_metrics.settings,
        "otel_resource_attributes",
        "deployment.environment=staging",
    )

    telemetry_metrics.configure_otel_metrics()

    assert telemetry_metrics.is_metrics_export_active() is True
    assert "http.server.request.count" in meter.counters
    assert "http.server.request.duration" in meter.histograms
    assert "db.pool.size" in meter.gauges
    assert "finance.async_parse.in_flight" in meter.gauges


def test_AC10_10_2_red_metrics_record_low_cardinality_labels(monkeypatch) -> None:
    """AC10.10.2: HTTP RED metrics record route and status class."""
    meter = install_fake_otel(monkeypatch)
    monkeypatch.setattr(
        telemetry_metrics.settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318",
    )
    telemetry_metrics.configure_otel_metrics()

    telemetry_metrics.record_http_request(
        method="GET",
        route="/api/health",
        status_code=200,
        duration_ms=12.5,
    )

    counter = meter.counters["http.server.request.count"]
    histogram = meter.histograms["http.server.request.duration"]
    assert counter.add_calls == [
        (
            1,
            {
                "http.request.method": "GET",
                "http.route": "/api/health",
                "http.response.status_code_class": "2xx",
            },
        )
    ]
    assert histogram.record_calls[0][0] == 12.5


def test_AC10_10_3_saturation_gauges_observe_current_values(monkeypatch) -> None:
    """AC10.10.3: async and DB pool gauges expose current saturation values."""
    install_fake_otel(monkeypatch)
    telemetry_metrics.set_async_parse_in_flight(3)
    telemetry_metrics.set_db_pool_observer(lambda: {"size": 5, "checkedout": 2, "overflow": 1})

    assert telemetry_metrics._observe_async_parse_in_flight() == [(3, {})]
    assert telemetry_metrics._observe_db_pool_size() == [(5, {})]
    assert telemetry_metrics._observe_db_pool_checkedout() == [(2, {})]
    assert telemetry_metrics._observe_db_pool_overflow() == [(1, {})]

    telemetry_metrics.set_db_pool_observer(None)


def test_AC10_10_4_business_metric_helpers_record_outcomes(monkeypatch) -> None:
    """AC10.10.4: parse, AI, reconciliation, and confidence helpers record metrics."""
    meter = install_fake_otel(monkeypatch)
    monkeypatch.setattr(
        telemetry_metrics.settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318",
    )
    telemetry_metrics.configure_otel_metrics()

    telemetry_metrics.record_statement_parse_outcome(outcome="success", parser="csv")
    telemetry_metrics.record_ai_provider_call(
        provider="openrouter",
        model="glm-5.1",
        outcome="success",
        duration_ms=321.0,
    )
    telemetry_metrics.record_reconciliation_match_outcome(outcome="accepted")
    telemetry_metrics.record_confidence_north_star(score=0.98, source="scheduled")

    assert meter.counters["finance.statement_parse.outcome"].add_calls == [(1, {"outcome": "success", "parser": "csv"})]
    assert meter.histograms["finance.ai_provider.latency"].record_calls == [
        (
            321.0,
            {"provider": "openrouter", "model": "glm-5.1", "outcome": "success"},
        )
    ]
    assert meter.counters["finance.reconciliation.match.outcome"].add_calls == [(1, {"outcome": "accepted"})]
    assert meter.histograms["finance.confidence_north_star"].record_calls == [(0.98, {"source": "scheduled"})]
