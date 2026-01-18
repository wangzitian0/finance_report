"""Structured logging configuration."""

import logging
import sys
from typing import Any

import structlog
from structlog.stdlib import BoundLogger
from structlog.types import Processor

from src.config import settings


def configure_logging() -> None:
    """Configure structlog for structured logging."""

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.debug:
        # Human-readable logs for development
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # JSON logs for production/staging (easy ingestion by Signoz/ELK)
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bridge standard logging to structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if settings.debug else logging.INFO,
    )


def get_logger(name: str | None = None) -> BoundLogger:
    """Get a structured logger."""
    return structlog.get_logger(name)
