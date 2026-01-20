"""Tests for logging helpers."""

import builtins
import logging
import sys
import types

from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer

from src import logger as logger_module


def test_build_otlp_logs_endpoint_adds_suffix() -> None:
    assert (
        logger_module._build_otlp_logs_endpoint("http://collector:4318")
        == "http://collector:4318/v1/logs"
    )
    assert (
        logger_module._build_otlp_logs_endpoint("http://collector:4318/")
        == "http://collector:4318/v1/logs"
    )


def test_build_otlp_logs_endpoint_preserves_logs_path() -> None:
    assert (
        logger_module._build_otlp_logs_endpoint("http://collector:4318/v1/logs")
        == "http://collector:4318/v1/logs"
    )


def test_select_renderer_uses_console_in_debug(monkeypatch) -> None:
    monkeypatch.setattr(logger_module.settings, "debug", True)
    renderer = logger_module._select_renderer()
    assert isinstance(renderer, ConsoleRenderer)


def test_select_renderer_uses_json_in_production(monkeypatch) -> None:
    monkeypatch.setattr(logger_module.settings, "debug", False)
    renderer = logger_module._select_renderer()
    assert isinstance(renderer, JSONRenderer)


def test_configure_otel_logging_missing_dependency_warns(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        logger_module.settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318",
    )
    original_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("opentelemetry"):
            raise ImportError("opentelemetry not installed")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with caplog.at_level(logging.WARNING):
        logger_module._configure_otel_logging()

    assert "OTEL log exporter not available" in caplog.text


def test_configure_otel_logging_with_fake_exporter(monkeypatch) -> None:
    calls: list[object] = []

    class DummyProvider:
        def __init__(self, resource=None):
            self.resource = resource
            self.processors: list[object] = []

        def add_log_record_processor(self, processor) -> None:
            self.processors.append(processor)

    class DummyHandler(logging.Handler):
        def __init__(self, level=logging.NOTSET, logger_provider=None):
            super().__init__(level=level)
            self.logger_provider = logger_provider

    class DummyProcessor:
        def __init__(self, exporter) -> None:
            self.exporter = exporter

    class DummyExporter:
        def __init__(self, endpoint: str) -> None:
            self.endpoint = endpoint

    class DummyResource:
        @staticmethod
        def create(attributes: dict[str, str]) -> dict[str, str]:
            return attributes

    def dummy_set_logger_provider(provider) -> None:
        calls.append(provider)

    def make_module(name: str, is_pkg: bool = False) -> types.ModuleType:
        module = types.ModuleType(name)
        if is_pkg:
            module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
        return module

    opentelemetry = make_module("opentelemetry", is_pkg=True)
    opentelemetry_logs = make_module("opentelemetry._logs")
    opentelemetry_logs.set_logger_provider = dummy_set_logger_provider

    opentelemetry_sdk = make_module("opentelemetry.sdk", is_pkg=True)
    opentelemetry_sdk_logs = make_module("opentelemetry.sdk._logs")
    opentelemetry_sdk_logs.LoggerProvider = DummyProvider
    opentelemetry_sdk_logs.LoggingHandler = DummyHandler
    opentelemetry_sdk_logs_export = make_module("opentelemetry.sdk._logs.export")
    opentelemetry_sdk_logs_export.BatchLogRecordProcessor = DummyProcessor
    opentelemetry_sdk_resources = make_module("opentelemetry.sdk.resources")
    opentelemetry_sdk_resources.Resource = DummyResource

    opentelemetry_exporter = make_module("opentelemetry.exporter", is_pkg=True)
    opentelemetry_otlp = make_module("opentelemetry.exporter.otlp", is_pkg=True)
    opentelemetry_proto = make_module("opentelemetry.exporter.otlp.proto", is_pkg=True)
    opentelemetry_proto_http = make_module("opentelemetry.exporter.otlp.proto.http", is_pkg=True)
    opentelemetry_log_exporter = make_module("opentelemetry.exporter.otlp.proto.http._log_exporter")
    opentelemetry_log_exporter.OTLPLogExporter = DummyExporter

    opentelemetry._logs = opentelemetry_logs
    opentelemetry.sdk = opentelemetry_sdk
    opentelemetry.exporter = opentelemetry_exporter
    opentelemetry_sdk._logs = opentelemetry_sdk_logs
    opentelemetry_sdk.resources = opentelemetry_sdk_resources
    opentelemetry_sdk_logs.export = opentelemetry_sdk_logs_export
    opentelemetry_exporter.otlp = opentelemetry_otlp
    opentelemetry_otlp.proto = opentelemetry_proto
    opentelemetry_proto.http = opentelemetry_proto_http
    opentelemetry_proto_http._log_exporter = opentelemetry_log_exporter

    monkeypatch.setattr(
        logger_module.settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318",
    )
    monkeypatch.setattr(logger_module.settings, "otel_service_name", "test-service")
    monkeypatch.setattr(
        logger_module.settings,
        "otel_resource_attributes",
        "deployment.environment=staging",
    )

    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    logger_module._configure_otel_logging()

    assert len(calls) == 1
    provider = calls[0]
    assert provider.resource["service.name"] == "test-service"
    assert provider.resource["deployment.environment"] == "staging"
    assert provider.processors[0].exporter.endpoint.endswith("/v1/logs")

    for handler in list(root_logger.handlers):
        if handler not in previous_handlers:
            root_logger.removeHandler(handler)
