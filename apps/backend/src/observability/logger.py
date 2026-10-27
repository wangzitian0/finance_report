"""Structured logging configuration.

This module provides:
- Structured logging via structlog with JSON output for production
- OpenTelemetry (OTEL) OTLP export for centralized logging (backend chosen by infra2)
"""

import datetime
import logging
import sys
from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from structlog.stdlib import BoundLogger
from structlog.types import Processor

import src.config

# Bound from the bare published root (``import src.config``) to respect the
# package-model cross-domain rule (config publishes no named symbols).
settings = src.config.settings
parse_key_value_pairs = src.config.parse_key_value_pairs


def _sanitize_value(val: Any) -> Any:
    """Sanitize arbitrary Python values for OTel and structlog encoders.

    OTel Protobuf encoder accepts only bool, str, int, float, bytes,
    and Sequences/Mappings thereof. Dates, datetimes, UUIDs, decimals,
    exceptions, etc. must be converted to compliant types.
    """
    if val is None or isinstance(val, bool | str | int | float | bytes):
        return val
    if isinstance(val, datetime.date | datetime.datetime):
        return val.isoformat()
    if isinstance(val, Mapping):
        return {str(k): _sanitize_value(v) for k, v in val.items()}
    if isinstance(val, list | tuple | set | frozenset | Sequence) and not isinstance(val, str | bytes):
        return [_sanitize_value(x) for x in val]
    return str(val)


def _sanitize_event_dict(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Structlog processor to sanitize non-primitive values in event_dict."""
    _ = (logger, method_name)
    for key, val in list(event_dict.items()):
        event_dict[key] = _sanitize_value(val)
    return event_dict


def _build_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        _add_trace_context,
        _sanitize_event_dict,
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]


def _add_trace_context(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Structlog processor to inject OTEL trace context into logs.

    Extracts trace_id and span_id from the current OTEL span context
    and adds them to the log event. This enables correlation between
    logs and traces in the observability backend.
    """
    _ = (logger, method_name)
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            # Format as 32-char hex for trace_id, 16-char hex for span_id
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except Exception:
        # OTEL not available or no active span - skip silently
        pass
    return event_dict


def _select_renderer() -> Processor:
    if settings.debug:
        # Human-readable logs for development
        return structlog.dev.ConsoleRenderer()
    # JSON logs for production/staging (easy ingestion by any OTLP/log backend)
    return structlog.processors.JSONRenderer()


def _build_otlp_logs_endpoint(endpoint: str) -> str:
    """Build the full OTLP logs endpoint URL with /v1/logs suffix."""
    from infra2_sdk.runtime.otel import signal_endpoint

    return signal_endpoint(endpoint, "logs")


def _build_otel_resource() -> Any:
    """Build OTEL resource with service name and attributes via infra2_sdk contract."""
    import os

    from infra2_sdk.runtime.environment import resolve_environment_tier
    from infra2_sdk.runtime.otel import OtelSettings, resource_attributes as sdk_resource_attributes
    from opentelemetry.sdk.resources import Resource

    parsed_attrs = parse_key_value_pairs(settings.otel_resource_attributes)
    dep_env = parsed_attrs.get("deployment.environment") or settings.environment
    try:
        is_github_actions = os.getenv("GITHUB_ACTIONS", "").lower() == "true"
        env_tier = resolve_environment_tier(
            dep_env,
            github_actions=is_github_actions,
            unknown="production",
        ).value
        otel_settings = OtelSettings(
            service_name=settings.otel_service_name,
            endpoint=settings.otel_exporter_otlp_endpoint,
            service_version=settings.git_commit_sha,
            environment=env_tier,
            deployment_environment=dep_env,
            resource_attributes=parsed_attrs,
            enabled=bool(settings.otel_exporter_otlp_endpoint),
        )
        attrs = sdk_resource_attributes(otel_settings)
    except Exception:
        attrs = {
            "service.name": settings.otel_service_name,
            "service.version": settings.git_commit_sha,
            **parsed_attrs,
        }
    final_attrs = {
        **attrs,
        "git.commit": settings.git_commit_sha,
    }
    return Resource.create(final_attrs)


def _configure_otel_tracing() -> None:
    """Configure OpenTelemetry tracing with OTLP export.

    Sets up TracerProvider with a vendor-neutral OTLP exporter for traces.
    This enables distributed tracing correlation with logs.
    """
    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:  # pragma: no cover - defensive import guard
        logging.getLogger(__name__).warning(
            "OTEL trace exporter not available",
            exc_info=True,
        )
        return

    resource = _build_otel_resource()
    provider = TracerProvider(resource=resource)

    # Build traces endpoint
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint = f"{endpoint}/v1/traces"

    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


class SanitizingLogRecordProcessor:
    """OTel LogRecordProcessor that ensures all attributes and body are encode-safe."""

    def __init__(self, exporter: Any = None) -> None:
        self.exporter = exporter

    def on_emit(self, log_record: Any) -> None:
        raw_record = getattr(log_record, "log_record", log_record)
        attrs = getattr(raw_record, "attributes", None)
        if attrs is not None and hasattr(attrs, "items"):
            for k, v in list(attrs.items()):
                attrs[k] = _sanitize_value(v)
        body = getattr(raw_record, "body", None)
        if body is not None and not isinstance(body, bool | str | int | float | bytes):
            raw_record.body = _sanitize_value(body)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def _configure_otel_logging() -> None:
    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        # OTLP log exporter moved between modules across opentelemetry versions.
        try:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        except ImportError:
            from opentelemetry.exporter.otlp.proto.http.log_exporter import OTLPLogExporter
    except Exception:  # pragma: no cover - defensive import guard
        logging.getLogger(__name__).warning(
            "OTEL log exporter not available",
            exc_info=True,
        )
        return

    resource = _build_otel_resource()

    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(SanitizingLogRecordProcessor())
    exporter = OTLPLogExporter(
        endpoint=_build_otlp_logs_endpoint(settings.otel_exporter_otlp_endpoint),
    )
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(provider)

    handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
    logging.getLogger().addHandler(handler)


def configure_logging() -> None:
    """Configure structlog for structured logging and optional OTEL export."""
    # Configure tracing first so trace context is available for logs
    _configure_otel_tracing()

    processors = _build_processors()
    renderer = _select_renderer()

    structlog.configure(
        processors=processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=processors,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logging.basicConfig(
        handlers=[handler],
        level=logging.DEBUG if settings.debug else logging.INFO,
    )

    _configure_otel_logging()


def get_logger(name: str | None = None) -> BoundLogger:
    """Get a structured logger."""
    return structlog.get_logger(name)
