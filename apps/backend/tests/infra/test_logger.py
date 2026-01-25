"""Tests for logging helpers."""

import builtins
import logging
import sys
import types

from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer

from src import logger as logger_module


def test_build_otlp_logs_endpoint_adds_suffix() -> None:
    assert logger_module._build_otlp_logs_endpoint("http://collector:4318") == "http://collector:4318/v1/logs"
    assert logger_module._build_otlp_logs_endpoint("http://collector:4318/") == "http://collector:4318/v1/logs"


def test_build_otlp_logs_endpoint_preserves_logs_path() -> None:
    assert logger_module._build_otlp_logs_endpoint("http://collector:4318/v1/logs") == "http://collector:4318/v1/logs"


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


# =============================================================================
# Timing Utilities Tests
# =============================================================================


def test_log_timing_basic(caplog) -> None:
    """Test log_timing context manager logs operation with timing."""
    test_logger = logger_module.get_logger("test_timing")

    with caplog.at_level(logging.INFO):
        with logger_module.log_timing("test_operation", logger=test_logger):
            pass

    assert "test_operation completed" in caplog.text
    assert "duration_ms" in caplog.text


def test_log_timing_with_context(caplog) -> None:
    """Test log_timing includes additional context."""
    test_logger = logger_module.get_logger("test_timing")

    with caplog.at_level(logging.INFO):
        with logger_module.log_timing("fetch_data", logger=test_logger, source="api"):
            pass

    assert "fetch_data completed" in caplog.text
    assert "source" in caplog.text


def test_log_timing_yields_mutable_dict(caplog) -> None:
    """Test log_timing yields a dict that can be updated."""
    test_logger = logger_module.get_logger("test_timing")

    with caplog.at_level(logging.INFO):
        with logger_module.log_timing("process", logger=test_logger) as ctx:
            ctx["items_processed"] = 42

    assert "items_processed" in caplog.text


def test_log_timing_with_custom_level(caplog) -> None:
    """Test log_timing respects custom log level."""
    test_logger = logger_module.get_logger("test_timing")

    with caplog.at_level(logging.DEBUG):
        with logger_module.log_timing("debug_op", logger=test_logger, level="debug"):
            pass

    assert "debug_op completed" in caplog.text


async def test_async_log_timing_basic(caplog) -> None:
    """Test async_log_timing context manager logs operation with timing."""
    import asyncio

    test_logger = logger_module.get_logger("test_async_timing")

    with caplog.at_level(logging.INFO):
        async with logger_module.async_log_timing("async_operation", logger=test_logger):
            await asyncio.sleep(0.001)

    assert "async_operation completed" in caplog.text
    assert "duration_ms" in caplog.text


async def test_async_log_timing_with_context(caplog) -> None:
    """Test async_log_timing includes additional context."""
    test_logger = logger_module.get_logger("test_async_timing")

    with caplog.at_level(logging.INFO):
        async with logger_module.async_log_timing("db_query", logger=test_logger, table="users"):
            pass

    assert "db_query completed" in caplog.text
    assert "table" in caplog.text


def test_log_external_api_sync_success(caplog) -> None:
    """Test log_external_api decorator with sync function success."""

    @logger_module.log_external_api("test_service")
    def sync_api_call():
        return "success"

    with caplog.at_level(logging.INFO):
        result = sync_api_call()

    assert result == "success"
    assert "External API call to test_service" in caplog.text
    assert "duration_ms" in caplog.text


def test_log_external_api_sync_failure(caplog) -> None:
    """Test log_external_api decorator with sync function failure."""

    @logger_module.log_external_api("failing_service")
    def failing_api_call():
        raise ValueError("API error")

    import pytest

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValueError, match="API error"):
            failing_api_call()

    assert "External API call to failing_service failed" in caplog.text
    assert "ValueError" in caplog.text


async def test_log_external_api_async_success(caplog) -> None:
    """Test log_external_api decorator with async function success."""

    @logger_module.log_external_api("async_service")
    async def async_api_call():
        return "async_success"

    with caplog.at_level(logging.INFO):
        result = await async_api_call()

    assert result == "async_success"
    assert "External API call to async_service" in caplog.text
    assert "duration_ms" in caplog.text


async def test_log_external_api_async_failure(caplog) -> None:
    """Test log_external_api decorator with async function failure."""
    import pytest

    @logger_module.log_external_api("async_failing_service")
    async def failing_async_api_call():
        raise RuntimeError("Async API error")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="Async API error"):
            await failing_async_api_call()

    assert "External API call to async_failing_service failed" in caplog.text
    assert "RuntimeError" in caplog.text


def test_log_external_api_with_log_args(caplog) -> None:
    """Test log_external_api with log_args=True."""

    @logger_module.log_external_api("service_with_args", log_args=True)
    def api_with_args(a, b, key=None):
        return a + b

    with caplog.at_level(logging.INFO):
        result = api_with_args(1, 2, key="value")

    assert result == 3
    assert "args_count" in caplog.text
    assert "kwargs_keys" in caplog.text


def test_log_exception_basic(caplog) -> None:
    """Test log_exception logs exception with context."""
    test_logger = logger_module.get_logger("test_exception")

    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("Test error message")
        except ValueError as exc:
            logger_module.log_exception(test_logger, exc, "Failed to process")

    assert "Failed to process" in caplog.text
    assert "ValueError" in caplog.text
    assert "Test error message" in caplog.text


def test_log_exception_with_extra_context(caplog) -> None:
    """Test log_exception includes extra context fields."""
    test_logger = logger_module.get_logger("test_exception")

    with caplog.at_level(logging.ERROR):
        try:
            raise KeyError("missing_key")
        except KeyError as exc:
            logger_module.log_exception(test_logger, exc, "Key lookup failed", user_id="user123", operation="lookup")

    assert "Key lookup failed" in caplog.text
    assert "user_id" in caplog.text


def test_log_exception_without_traceback(caplog) -> None:
    """Test log_exception without traceback."""
    test_logger = logger_module.get_logger("test_exception")

    with caplog.at_level(logging.ERROR):
        try:
            raise TypeError("Type mismatch")
        except TypeError as exc:
            logger_module.log_exception(test_logger, exc, "Type error", include_traceback=False)

    assert "Type error" in caplog.text
    assert "TypeError" in caplog.text


def test_log_exception_custom_level(caplog) -> None:
    """Test log_exception with custom log level."""
    test_logger = logger_module.get_logger("test_exception")

    with caplog.at_level(logging.WARNING):
        try:
            raise RuntimeError("Warning level error")
        except RuntimeError as exc:
            logger_module.log_exception(test_logger, exc, "Non-critical error", level="warning")

    assert "Non-critical error" in caplog.text


# =============================================================================
# Additional Coverage Tests
# =============================================================================


def test_build_processors_returns_list() -> None:
    """Test _build_processors returns a list of processors."""
    processors = logger_module._build_processors()
    assert isinstance(processors, list)
    assert len(processors) >= 4  # contextvars, log_level, exc_info, timestamper


def test_configure_otel_logging_no_endpoint(monkeypatch) -> None:
    """Test _configure_otel_logging returns early when endpoint is not set."""
    monkeypatch.setattr(logger_module.settings, "otel_exporter_otlp_endpoint", None)
    # Should not raise and should return early
    logger_module._configure_otel_logging()


def test_configure_logging_basic(monkeypatch) -> None:
    """Test configure_logging sets up structlog correctly."""
    import structlog

    # Ensure no OTEL endpoint to avoid side effects
    monkeypatch.setattr(logger_module.settings, "otel_exporter_otlp_endpoint", None)
    monkeypatch.setattr(logger_module.settings, "debug", True)

    # Save original config
    original_config = structlog.get_config()

    try:
        logger_module.configure_logging()

        # Verify structlog is configured
        config = structlog.get_config()
        assert config["logger_factory"] is not None
    finally:
        # Restore original config
        structlog.configure(**original_config)


def test_configure_logging_production_mode(monkeypatch) -> None:
    """Test configure_logging in production mode (non-debug)."""
    import structlog

    monkeypatch.setattr(logger_module.settings, "otel_exporter_otlp_endpoint", None)
    monkeypatch.setattr(logger_module.settings, "debug", False)

    original_config = structlog.get_config()

    try:
        logger_module.configure_logging()
        config = structlog.get_config()
        assert config["logger_factory"] is not None
    finally:
        structlog.configure(**original_config)


async def test_log_external_api_async_with_log_args(caplog) -> None:
    """Test log_external_api with log_args=True for async functions."""

    @logger_module.log_external_api("async_service_with_args", log_args=True)
    async def async_api_with_args(a, b, key=None):
        return a * b

    with caplog.at_level(logging.INFO):
        result = await async_api_with_args(3, 4, key="test")

    assert result == 12
    assert "args_count" in caplog.text
    assert "kwargs_keys" in caplog.text


async def test_log_external_api_async_failure_with_log_args(caplog) -> None:
    """Test log_external_api async failure path with log_args=True."""
    import pytest

    @logger_module.log_external_api("async_failing_with_args", log_args=True)
    async def failing_async_with_args(x, y):
        raise ValueError("Async failure with args")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValueError, match="Async failure with args"):
            await failing_async_with_args(1, 2)

    assert "args_count" in caplog.text
