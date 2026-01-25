"""Structured logging configuration.

This module provides:
- Structured logging via structlog with JSON output for production
- OpenTelemetry (OTEL) export to SigNoz for centralized logging
- Timing utilities for performance tracking
- Exception logging helpers with full context
"""

import logging
import sys
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import structlog
from structlog.stdlib import BoundLogger
from structlog.types import Processor

from src.config import parse_key_value_pairs, settings

P = ParamSpec("P")
T = TypeVar("T")


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

    resource_attributes = {"service.name": settings.otel_service_name}
    resource_attributes.update(parse_key_value_pairs(settings.otel_resource_attributes))
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
    """Configure structlog for structured logging and optional OTEL export."""

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


# =============================================================================
# Timing Utilities
# =============================================================================


@contextmanager
def log_timing(
    operation: str,
    logger: BoundLogger | None = None,
    level: str = "info",
    **context: Any,
) -> Iterator[dict[str, Any]]:
    """Context manager to log operation timing.

    Usage:
        with log_timing("process_data", logger=logger, source="db"):
            result = process_data(items)  # synchronous operation

    For async operations, use async_log_timing instead.

    Args:
        operation: Name of the operation being timed
        logger: Logger instance (uses module logger if not provided)
        level: Log level to use (default: info)
        **context: Additional context to include in the log

    Yields:
        A dict that can be updated with additional context during the operation.
        The dict will include 'duration_ms' after the operation completes.
    """
    log = logger or get_logger(__name__)
    start = time.perf_counter()
    result_context: dict[str, Any] = {}

    try:
        yield result_context
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        result_context["duration_ms"] = round(duration_ms, 2)

        # Build final context, excluding duration_ms from result_context since we add it explicitly
        extra_context = {k: v for k, v in result_context.items() if k != "duration_ms"}

        log_method = getattr(log, level, log.info)
        log_method(
            f"{operation} completed",
            operation=operation,
            duration_ms=result_context["duration_ms"],
            **context,
            **extra_context,
        )


@asynccontextmanager
async def async_log_timing(
    operation: str,
    logger: BoundLogger | None = None,
    level: str = "info",
    **context: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Async context manager to log operation timing.

    Usage:
        async with async_log_timing("db_query", logger=logger, table="users"):
            result = await db.execute(query)

    Args:
        operation: Name of the operation being timed
        logger: Logger instance (uses module logger if not provided)
        level: Log level to use (default: info)
        **context: Additional context to include in the log

    Yields:
        A dict that can be updated with additional context during the operation.
        The dict will include 'duration_ms' after the operation completes.
    """
    log = logger or get_logger(__name__)
    start = time.perf_counter()
    result_context: dict[str, Any] = {}

    try:
        yield result_context
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        result_context["duration_ms"] = round(duration_ms, 2)

        # Build final context, excluding duration_ms from result_context since we add it explicitly
        extra_context = {k: v for k, v in result_context.items() if k != "duration_ms"}

        log_method = getattr(log, level, log.info)
        log_method(
            f"{operation} completed",
            operation=operation,
            duration_ms=result_context["duration_ms"],
            **context,
            **extra_context,
        )


def log_external_api(
    service: str,
    *,
    logger: BoundLogger | None = None,
    log_args: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator to log external API calls with timing.

    Usage:
        @log_external_api("openrouter")
        async def fetch_models():
            ...

    Args:
        service: Name of the external service
        logger: Logger instance (uses decorated function's module logger if not provided)
        log_args: If True, log function arguments (be careful with sensitive data)
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        log = logger or get_logger(func.__module__)

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            start = time.perf_counter()
            extra: dict[str, Any] = {"service": service, "function": func.__name__}

            if log_args:
                extra["args_count"] = len(args)
                extra["kwargs_keys"] = list(kwargs.keys())

            try:
                result = await func(*args, **kwargs)  # type: ignore[misc]
                duration_ms = (time.perf_counter() - start) * 1000
                log.info(
                    f"External API call to {service}",
                    duration_ms=round(duration_ms, 2),
                    success=True,
                    **extra,
                )
                return result
            except Exception as exc:
                duration_ms = (time.perf_counter() - start) * 1000
                log.error(
                    f"External API call to {service} failed",
                    duration_ms=round(duration_ms, 2),
                    success=False,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    **extra,
                )
                raise

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            start = time.perf_counter()
            extra: dict[str, Any] = {"service": service, "function": func.__name__}

            if log_args:
                extra["args_count"] = len(args)
                extra["kwargs_keys"] = list(kwargs.keys())

            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                log.info(
                    f"External API call to {service}",
                    duration_ms=round(duration_ms, 2),
                    success=True,
                    **extra,
                )
                return result
            except Exception as exc:
                duration_ms = (time.perf_counter() - start) * 1000
                log.error(
                    f"External API call to {service} failed",
                    duration_ms=round(duration_ms, 2),
                    success=False,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    **extra,
                )
                raise

        import inspect

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


# =============================================================================
# Exception Logging Helpers
# =============================================================================


def log_exception(
    logger: BoundLogger,
    exc: BaseException,
    context: str,
    *,
    level: str = "error",
    include_traceback: bool = True,
    **extra: Any,
) -> None:
    """Log an exception with full context.

    Usage:
        except ValueError as exc:
            log_exception(logger, exc, "Failed to parse amount", user_id=user_id)

    Args:
        logger: Logger instance
        exc: The exception to log
        context: Human-readable context message
        level: Log level (default: error)
        include_traceback: Whether to include full traceback (default: True)
        **extra: Additional context to include
    """
    log_method = getattr(logger, level, logger.error)

    log_kwargs: dict[str, Any] = {
        "error": str(exc),
        "error_type": type(exc).__name__,
        "error_module": type(exc).__module__,
        **extra,
    }

    if include_traceback:
        log_method(context, exc_info=exc, **log_kwargs)
    else:
        log_method(context, **log_kwargs)
