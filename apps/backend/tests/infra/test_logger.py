"""Tests for logging helpers."""

import builtins
import logging
import sys
import types

from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer

from src.observability import logger as logger_module


def test_build_otlp_logs_endpoint_adds_suffix() -> None:
    """AC-observability.2.1: AC12.1.1: OTEL logs endpoint adds suffix /v1/logs."""
    assert logger_module._build_otlp_logs_endpoint("http://collector:4318") == "http://collector:4318/v1/logs"
    assert logger_module._build_otlp_logs_endpoint("http://collector:4318/") == "http://collector:4318/v1/logs"


def test_build_otlp_logs_endpoint_preserves_logs_path() -> None:
    """AC-observability.2.2 AC12.1.2: OTEL logs endpoint preserves logs path."""
    assert logger_module._build_otlp_logs_endpoint("http://collector:4318/v1/logs") == "http://collector:4318/v1/logs"


def test_build_otlp_logs_endpoint_delegates_to_public_sdk_helper(monkeypatch) -> None:
    """OTEL logs endpoint is derived by the SDK's public ``signal_endpoint`` (infra2-sdk >= 2.4.0)."""
    import infra2_sdk.runtime.otel as otel_mod

    calls: list[tuple[str, str]] = []

    def fake_endpoint_builder(base: str, signal: str) -> str:
        calls.append((base, signal))
        return "http://sentinel/logs"

    monkeypatch.setattr(otel_mod, "signal_endpoint", fake_endpoint_builder)

    assert logger_module._build_otlp_logs_endpoint("http://collector:4318") == "http://sentinel/logs"
    assert calls == [("http://collector:4318", "logs")]


def test_select_renderer_uses_console_in_debug(monkeypatch) -> None:
    """AC-observability.1.4: AC12.2.1: Debug mode uses ConsoleRenderer."""
    monkeypatch.setattr(logger_module.settings, "debug", True)
    renderer = logger_module._select_renderer()
    assert isinstance(renderer, ConsoleRenderer)


def test_select_renderer_uses_json_in_production(monkeypatch) -> None:
    """AC-observability.1.3 AC12.2.2: Production mode uses JSONRenderer and stdout fallback."""
    monkeypatch.setattr(logger_module.settings, "debug", False)
    renderer = logger_module._select_renderer()
    assert isinstance(renderer, JSONRenderer)


def test_configure_otel_logging_missing_dependency_warns(monkeypatch, caplog) -> None:
    """AC-observability.4.1 AC12.3.1: OTEL not available logs warning."""
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
    """AC-observability.1.2 AC-observability.4.2 AC-observability.7.2 AC12.4.1: OTEL logging uses an OTLP exporter."""
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

        def emit(self, record):
            pass

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
    batch_processor = next(p for p in provider.processors if getattr(p, "exporter", None) is not None)
    assert batch_processor.exporter.endpoint.endswith("/v1/logs")
    assert any(isinstance(p, logger_module.SanitizingLogRecordProcessor) for p in provider.processors)

    for handler in list(root_logger.handlers):
        if handler not in previous_handlers:
            root_logger.removeHandler(handler)


# =============================================================================
# Additional Coverage Tests
# =============================================================================


def test_build_processors_returns_list() -> None:
    """AC-observability.16.1: AC12.10.1: Build processors returns list."""
    processors = logger_module._build_processors()
    assert isinstance(processors, list)
    assert len(processors) >= 5  # contextvars, trace_context, log_level, exc_info, timestamper


# =============================================================================
# Trace Context Tests
# =============================================================================


def test_add_trace_context_with_valid_span(monkeypatch) -> None:
    """AC-observability.16.2: AC12.11.1: Trace context injects trace_id and span_id."""
    import types

    class MockSpanContext:
        trace_id = 0x1234567890ABCDEF1234567890ABCDEF
        span_id = 0xFEDCBA0987654321
        is_valid = True

    class MockSpan:
        def get_span_context(self):
            return MockSpanContext()

    # Create mock trace module
    mock_trace = types.ModuleType("opentelemetry.trace")
    mock_trace.get_current_span = lambda: MockSpan()

    # Patch the import
    monkeypatch.setitem(sys.modules, "opentelemetry", types.ModuleType("opentelemetry"))
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", mock_trace)

    event_dict: dict[str, object] = {"event": "test"}
    result = logger_module._add_trace_context(None, "info", event_dict)  # type: ignore[arg-type]

    assert "trace_id" in result
    assert "span_id" in result
    assert result["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert result["span_id"] == "fedcba0987654321"


def test_add_trace_context_with_invalid_span(monkeypatch) -> None:
    """AC-observability.16.3: AC12.11.2: Trace context skips injection when invalid."""
    import types

    class MockSpanContext:
        trace_id = 0
        span_id = 0
        is_valid = False

    class MockSpan:
        def get_span_context(self):
            return MockSpanContext()

    mock_trace = types.ModuleType("opentelemetry.trace")
    mock_trace.get_current_span = lambda: MockSpan()

    monkeypatch.setitem(sys.modules, "opentelemetry", types.ModuleType("opentelemetry"))
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", mock_trace)

    event_dict: dict[str, object] = {"event": "test"}
    result = logger_module._add_trace_context(None, "info", event_dict)  # type: ignore[arg-type]

    assert "trace_id" not in result
    assert "span_id" not in result


def test_add_trace_context_handles_import_error(monkeypatch) -> None:
    """AC-observability.16.4: AC12.11.3: Trace context handles missing opentelemetry."""

    def raise_import_error(name, *args, **kwargs):
        if "opentelemetry" in name:
            raise ImportError("opentelemetry not installed")
        return original_import(name, *args, **kwargs)

    original_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", raise_import_error)

    # Remove any cached opentelemetry modules
    modules_to_remove = [k for k in sys.modules if k.startswith("opentelemetry")]
    for mod in modules_to_remove:
        monkeypatch.delitem(sys.modules, mod, raising=False)

    event_dict: dict[str, object] = {"event": "test"}
    result = logger_module._add_trace_context(None, "info", event_dict)  # type: ignore[arg-type]

    # Should return event_dict unchanged without raising
    assert result == event_dict
    assert "trace_id" not in result


# =============================================================================
# OTEL Tracing Configuration Tests
# =============================================================================


def test_configure_otel_tracing_no_endpoint(monkeypatch) -> None:
    """AC-observability.4.8: AC12.12.1: OTEL tracing returns early when no endpoint."""
    monkeypatch.setattr(logger_module.settings, "otel_exporter_otlp_endpoint", None)
    # Should not raise and should return early
    logger_module._configure_otel_tracing()


def test_configure_otel_tracing_missing_dependency_warns(monkeypatch, caplog) -> None:
    """AC-observability.4.5: AC12.3.2: OTEL trace exporter not available logs warning."""
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
        logger_module._configure_otel_tracing()

    assert "OTEL trace exporter not available" in caplog.text


def test_configure_otel_tracing_with_fake_exporter(monkeypatch) -> None:
    """AC-observability.4.9: AC12.12.2: TracerProvider created correctly."""
    calls: list[object] = []

    class DummyTracerProvider:
        def __init__(self, resource=None):
            self.resource = resource
            self.span_processors: list[object] = []

        def add_span_processor(self, processor) -> None:
            self.span_processors.append(processor)

    class DummyBatchSpanProcessor:
        def __init__(self, exporter) -> None:
            self.exporter = exporter

    class DummySpanExporter:
        def __init__(self, endpoint: str) -> None:
            self.endpoint = endpoint

    class DummyResource:
        @staticmethod
        def create(attributes: dict[str, str]) -> dict[str, str]:
            return attributes

    def dummy_set_tracer_provider(provider) -> None:
        calls.append(provider)

    def make_module(name: str, is_pkg: bool = False) -> types.ModuleType:
        module = types.ModuleType(name)
        if is_pkg:
            module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
        return module

    # Build module hierarchy
    opentelemetry = make_module("opentelemetry", is_pkg=True)
    opentelemetry_trace = make_module("opentelemetry.trace")
    opentelemetry_trace.set_tracer_provider = dummy_set_tracer_provider

    opentelemetry_sdk = make_module("opentelemetry.sdk", is_pkg=True)
    opentelemetry_sdk_trace = make_module("opentelemetry.sdk.trace")
    opentelemetry_sdk_trace.TracerProvider = DummyTracerProvider
    opentelemetry_sdk_trace_export = make_module("opentelemetry.sdk.trace.export")
    opentelemetry_sdk_trace_export.BatchSpanProcessor = DummyBatchSpanProcessor
    opentelemetry_sdk_resources = make_module("opentelemetry.sdk.resources")
    opentelemetry_sdk_resources.Resource = DummyResource

    opentelemetry_exporter = make_module("opentelemetry.exporter", is_pkg=True)
    opentelemetry_otlp = make_module("opentelemetry.exporter.otlp", is_pkg=True)
    opentelemetry_proto = make_module("opentelemetry.exporter.otlp.proto", is_pkg=True)
    opentelemetry_proto_http = make_module("opentelemetry.exporter.otlp.proto.http", is_pkg=True)
    opentelemetry_trace_exporter = make_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    opentelemetry_trace_exporter.OTLPSpanExporter = DummySpanExporter

    # Wire up hierarchy
    opentelemetry.trace = opentelemetry_trace
    opentelemetry.sdk = opentelemetry_sdk
    opentelemetry.exporter = opentelemetry_exporter
    opentelemetry_sdk.trace = opentelemetry_sdk_trace
    opentelemetry_sdk.resources = opentelemetry_sdk_resources
    opentelemetry_sdk_trace.export = opentelemetry_sdk_trace_export
    opentelemetry_exporter.otlp = opentelemetry_otlp
    opentelemetry_otlp.proto = opentelemetry_proto
    opentelemetry_proto.http = opentelemetry_proto_http
    opentelemetry_proto_http.trace_exporter = opentelemetry_trace_exporter

    monkeypatch.setattr(
        logger_module.settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318",
    )
    monkeypatch.setattr(logger_module.settings, "otel_service_name", "test-service")
    monkeypatch.setattr(
        logger_module.settings,
        "otel_resource_attributes",
        "deployment.environment=test",
    )

    logger_module._configure_otel_tracing()

    assert len(calls) == 1
    provider = calls[0]
    assert provider.resource["service.name"] == "test-service"
    assert provider.resource["deployment.environment"] == "test"
    assert provider.span_processors[0].exporter.endpoint.endswith("/v1/traces")


def test_configure_otel_tracing_appends_traces_path(monkeypatch) -> None:
    """AC-observability.4.10: AC12.12.3: Traces path appends /v1/traces."""
    calls: list[object] = []

    class DummyTracerProvider:
        def __init__(self, resource=None):
            self.resource = resource
            self.span_processors: list[object] = []

        def add_span_processor(self, processor) -> None:
            self.span_processors.append(processor)

    class DummyBatchSpanProcessor:
        def __init__(self, exporter) -> None:
            self.exporter = exporter

    class DummySpanExporter:
        def __init__(self, endpoint: str) -> None:
            self.endpoint = endpoint
            calls.append(endpoint)

    class DummyResource:
        @staticmethod
        def create(attributes: dict[str, str]) -> dict[str, str]:
            return attributes

    def make_module(name: str, is_pkg: bool = False) -> types.ModuleType:
        module = types.ModuleType(name)
        if is_pkg:
            module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
        return module

    opentelemetry = make_module("opentelemetry", is_pkg=True)
    opentelemetry_trace = make_module("opentelemetry.trace")
    opentelemetry_trace.set_tracer_provider = lambda p: None

    opentelemetry_sdk = make_module("opentelemetry.sdk", is_pkg=True)
    opentelemetry_sdk_trace = make_module("opentelemetry.sdk.trace")
    opentelemetry_sdk_trace.TracerProvider = DummyTracerProvider
    opentelemetry_sdk_trace_export = make_module("opentelemetry.sdk.trace.export")
    opentelemetry_sdk_trace_export.BatchSpanProcessor = DummyBatchSpanProcessor
    opentelemetry_sdk_resources = make_module("opentelemetry.sdk.resources")
    opentelemetry_sdk_resources.Resource = DummyResource

    opentelemetry_exporter = make_module("opentelemetry.exporter", is_pkg=True)
    opentelemetry_otlp = make_module("opentelemetry.exporter.otlp", is_pkg=True)
    opentelemetry_proto = make_module("opentelemetry.exporter.otlp.proto", is_pkg=True)
    opentelemetry_proto_http = make_module("opentelemetry.exporter.otlp.proto.http", is_pkg=True)
    opentelemetry_trace_exporter = make_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    opentelemetry_trace_exporter.OTLPSpanExporter = DummySpanExporter

    opentelemetry.trace = opentelemetry_trace
    opentelemetry.sdk = opentelemetry_sdk
    opentelemetry.exporter = opentelemetry_exporter
    opentelemetry_sdk.trace = opentelemetry_sdk_trace
    opentelemetry_sdk.resources = opentelemetry_sdk_resources
    opentelemetry_sdk_trace.export = opentelemetry_sdk_trace_export
    opentelemetry_exporter.otlp = opentelemetry_otlp
    opentelemetry_otlp.proto = opentelemetry_proto
    opentelemetry_proto.http = opentelemetry_proto_http
    opentelemetry_proto_http.trace_exporter = opentelemetry_trace_exporter

    # Test with trailing slash
    monkeypatch.setattr(
        logger_module.settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318/",
    )
    monkeypatch.setattr(logger_module.settings, "otel_service_name", "test")
    monkeypatch.setattr(logger_module.settings, "otel_resource_attributes", "")

    logger_module._configure_otel_tracing()

    assert calls[-1] == "http://collector:4318/v1/traces"


# =============================================================================
# OTEL Resource Tests
# =============================================================================


def test_build_otel_resource(monkeypatch) -> None:
    """AC-observability.4.7: AC12.5.1: OTEL resource created with correct attributes."""

    class DummyResource:
        @staticmethod
        def create(attributes: dict[str, str]) -> dict[str, str]:
            return attributes

    def make_module(name: str, is_pkg: bool = False) -> types.ModuleType:
        module = types.ModuleType(name)
        if is_pkg:
            module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
        return module

    opentelemetry = make_module("opentelemetry", is_pkg=True)
    opentelemetry_sdk = make_module("opentelemetry.sdk", is_pkg=True)
    opentelemetry_sdk_resources = make_module("opentelemetry.sdk.resources")
    opentelemetry_sdk_resources.Resource = DummyResource

    opentelemetry.sdk = opentelemetry_sdk
    opentelemetry_sdk.resources = opentelemetry_sdk_resources

    monkeypatch.setattr(logger_module.settings, "otel_service_name", "my-service")
    monkeypatch.setattr(
        logger_module.settings,
        "otel_resource_attributes",
        "env=prod,version=1.0",
    )

    resource = logger_module._build_otel_resource()

    assert resource["service.name"] == "my-service"
    assert resource["env"] == "prod"
    assert resource["version"] == "1.0"


def test_configure_otel_logging_no_endpoint(monkeypatch) -> None:
    """AC-observability.4.6: AC12.3.3: OTEL logging returns early when no endpoint."""
    monkeypatch.setattr(logger_module.settings, "otel_exporter_otlp_endpoint", None)
    # Should not raise and should return early
    logger_module._configure_otel_logging()


def test_configure_logging_basic(monkeypatch) -> None:
    """AC-observability.1.5: AC12.15.1: Configure logging in debug mode."""
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
    """AC-observability.1.6: AC12.15.2: Configure logging in production mode."""
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


def test_sanitize_value_primitives_and_dates() -> None:
    """_sanitize_value converts datetime.date and datetime.datetime to ISO format strings."""
    import datetime

    assert logger_module._sanitize_value(123) == 123
    assert logger_module._sanitize_value("text") == "text"
    assert logger_module._sanitize_value(True) is True
    assert logger_module._sanitize_value(None) is None
    d = datetime.date(2025, 4, 30)
    assert logger_module._sanitize_value(d) == "2025-04-30"
    dt = datetime.datetime(2025, 4, 30, 12, 0, 0)
    assert logger_module._sanitize_value(dt) == "2025-04-30T12:00:00"
    nested = {"date": d, "list": [dt, 1]}
    assert logger_module._sanitize_value(nested) == {
        "date": "2025-04-30",
        "list": ["2025-04-30T12:00:00", 1],
    }


def test_sanitize_event_dict_processor() -> None:
    """_sanitize_event_dict processor converts date objects in structlog events."""
    import datetime

    event_dict = {"event": "test", "snapshot_date": datetime.date(2025, 4, 30)}
    processed = logger_module._sanitize_event_dict(None, "info", event_dict)  # type: ignore[arg-type]
    assert processed["snapshot_date"] == "2025-04-30"


def test_sanitizing_log_record_processor_encodes_cleanly_for_otel() -> None:
    """SanitizingLogRecordProcessor prevents Invalid type datetime.date crashes in OTel."""
    import datetime

    from opentelemetry.exporter.otlp.proto.common._internal import _encode_value

    class FakeRecord:
        def __init__(self):
            self.attributes = {"report_date": datetime.date(2025, 4, 30), "count": 10}
            self.body = {"nested_date": datetime.date(2025, 4, 30)}

    record = FakeRecord()
    processor = logger_module.SanitizingLogRecordProcessor()
    processor.on_emit(record)

    assert record.attributes["report_date"] == "2025-04-30"
    # Verify OTel protobuf encoder encodes without raising Exception
    encoded_attr = _encode_value(record.attributes["report_date"])
    assert encoded_attr.string_value == "2025-04-30"
    encoded_body = _encode_value(record.body)
    assert encoded_body is not None
