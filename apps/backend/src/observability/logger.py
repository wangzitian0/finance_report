"""Structured logging and OpenTelemetry log/trace export configuration."""

from __future__ import annotations

import datetime
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from structlog.stdlib import BoundLogger
from structlog.types import Processor

import src.config
from src.observability.audit import RISKY_LOG_FIELD_NAMES, _redact_detected_pii

settings = src.config.settings
parse_key_value_pairs = src.config.parse_key_value_pairs
_tracer_provider: Any | None = None
_logger_provider: Any | None = None


def _sanitize_value(val: Any) -> Any:
    if val is None or isinstance(val, bool | int | float | bytes):
        return val
    if isinstance(val, str):
        return _redact_detected_pii(val)
    if isinstance(val, datetime.date | datetime.datetime):
        return val.isoformat()
    if isinstance(val, Mapping):
        return {
            str(k): "[REDACTED]" if str(k).lower() in RISKY_LOG_FIELD_NAMES else _sanitize_value(v)
            for k, v in val.items()
        }
    if isinstance(val, list | tuple | set | frozenset | Sequence) and not isinstance(val, str | bytes):
        return [_sanitize_value(x) for x in val]
    return _redact_detected_pii(str(val))


def _sanitize_event_dict(
    logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    _ = (logger, method_name)
    for key, val in list(event_dict.items()):
        event_dict[key] = "[REDACTED]" if str(key).lower() in RISKY_LOG_FIELD_NAMES else _sanitize_value(val)
    return event_dict


def _add_trace_context(
    logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    _ = (logger, method_name)
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except Exception:
        pass
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


def _select_renderer() -> Processor:
    return structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer()


def _build_otlp_logs_endpoint(endpoint: str) -> str:
    from infra2_sdk.runtime.otel import signal_endpoint

    return signal_endpoint(endpoint, "logs")


def _build_otel_resource() -> Any:
    from infra2_sdk.runtime.environment import resolve_environment_tier
    from infra2_sdk.runtime.otel import OtelSettings, resource_attributes as sdk_resource_attributes
    from opentelemetry.sdk.resources import Resource

    parsed_attrs = parse_key_value_pairs(settings.otel_resource_attributes)
    dep_env = parsed_attrs.get("deployment.environment") or settings.environment
    try:
        env_tier = resolve_environment_tier(
            dep_env, github_actions=os.getenv("GITHUB_ACTIONS", "").lower() == "true", unknown="production"
        ).value
        attrs = sdk_resource_attributes(
            OtelSettings(
                service_name=settings.otel_service_name,
                endpoint=settings.otel_exporter_otlp_endpoint,
                service_version=settings.git_commit_sha,
                environment=env_tier,
                deployment_environment=dep_env,
                resource_attributes=parsed_attrs,
                enabled=bool(settings.otel_exporter_otlp_endpoint),
            )
        )
    except Exception:
        attrs = {"service.name": settings.otel_service_name, "service.version": settings.git_commit_sha, **parsed_attrs}
    return Resource.create({**attrs, "git.commit": settings.git_commit_sha})


def flush_otel_logs_and_traces(timeout_millis: int = 10000) -> None:
    for provider in (_logger_provider, _tracer_provider):
        if provider is not None:
            try:
                provider.force_flush(timeout_millis)
            except Exception:
                logging.getLogger(__name__).warning("OTEL flush failed", exc_info=True)


def _configure_otel_tracing() -> None:
    global _tracer_provider
    if not settings.otel_exporter_otlp_endpoint:
        return
    try:
        from infra2_sdk.runtime.otel import signal_endpoint
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:  # pragma: no cover
        logging.getLogger(__name__).warning("OTEL trace exporter not available", exc_info=True)
        return
    provider = TracerProvider(resource=_build_otel_resource())
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=signal_endpoint(settings.otel_exporter_otlp_endpoint, "traces")))
    )
    trace.set_tracer_provider(provider)
    _tracer_provider = provider


class SanitizingLogRecordProcessor:
    """OTel LogRecordProcessor that ensures all attributes and body are encode-safe."""

    def __init__(self, exporter: Any = None) -> None:
        self.exporter = exporter

    def on_emit(self, log_record: Any) -> None:
        raw_record = getattr(log_record, "log_record", log_record)
        attrs = getattr(raw_record, "attributes", None)
        if attrs is not None and hasattr(attrs, "items"):
            for k, v in list(attrs.items()):
                attrs[k] = "[REDACTED]" if str(k).lower() in RISKY_LOG_FIELD_NAMES else _sanitize_value(v)
        body = getattr(raw_record, "body", None)
        if body is not None and not isinstance(body, bool | int | float | bytes):
            raw_record.body = _sanitize_value(body)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        _ = timeout_millis
        return True


def _configure_otel_logging() -> None:
    global _logger_provider
    if not settings.otel_exporter_otlp_endpoint:
        return
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        try:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        except ImportError:
            from opentelemetry.exporter.otlp.proto.http.log_exporter import OTLPLogExporter
    except Exception:  # pragma: no cover
        logging.getLogger(__name__).warning("OTEL log exporter not available", exc_info=True)
        return

    provider = LoggerProvider(resource=_build_otel_resource())
    provider.add_log_record_processor(SanitizingLogRecordProcessor())
    provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(endpoint=_build_otlp_logs_endpoint(settings.otel_exporter_otlp_endpoint))
        )
    )
    set_logger_provider(provider)
    _logger_provider = provider
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=provider))


def configure_logging(*, take_over_root: bool = False) -> None:
    _configure_otel_tracing()
    processors = _build_processors()
    structlog.configure(
        processors=[*processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(processor=_select_renderer(), foreign_pre_chain=processors)
    )
    if take_over_root:
        root_logger = logging.getLogger()
        for existing in list(root_logger.handlers):
            root_logger.removeHandler(existing)
    logging.basicConfig(handlers=[handler], level=logging.DEBUG if settings.debug else logging.INFO)
    _configure_otel_logging()


def get_logger(name: str | None = None) -> BoundLogger:
    return structlog.get_logger(name)
