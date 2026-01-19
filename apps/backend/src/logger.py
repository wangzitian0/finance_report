"""Structured logging configuration."""

import logging
import sys

import structlog
from structlog.stdlib import BoundLogger
from structlog.types import Processor

from src.config import settings


def _build_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]


def _select_renderer() -> Processor:
    if settings.debug:
        # Human-readable logs for development
        return structlog.dev.ConsoleRenderer()
    # JSON logs for production/staging (easy ingestion by SigNoz/ELK)
    return structlog.processors.JSONRenderer()


def _parse_resource_attributes(value: str | None) -> dict[str, str]:
    if not value:
        return {}

    attributes: dict[str, str] = {}
    for item in value.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if key and raw_value:
            attributes[key] = raw_value
    return attributes


def _build_otlp_logs_endpoint(endpoint: str) -> str:
    trimmed = endpoint.rstrip("/")
    if trimmed.endswith("/v1/logs"):
        return trimmed
    return f"{trimmed}/v1/logs"


def _configure_otel_logging() -> None:
    if not settings.otel_exporter_otlp_endpoint:
        return

    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
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

    resource_attributes = {"service.name": settings.otel_service_name}
    resource_attributes.update(_parse_resource_attributes(settings.otel_resource_attributes))
    resource = Resource.create(resource_attributes)

    provider = LoggerProvider(resource=resource)
    exporter = OTLPLogExporter(
        endpoint=_build_otlp_logs_endpoint(settings.otel_exporter_otlp_endpoint),
    )
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(provider)

    handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
    logging.getLogger().addHandler(handler)


def configure_logging() -> None:
    """Configure structlog for structured logging."""

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
