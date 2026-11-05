"""OpenTelemetry bootstrap for Prefect flow-run processes (#2850).

The API process configures OTEL in ``src.main``. A flow run executes in the Prefect
worker container and never imports ``src.main``, so without this module its metric
instruments stay empty and its logs stay local. This module reuses the backend's
own setup functions and only changes the service name.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import src.config
from src.observability.logger import configure_logging, flush_otel_logs_and_traces
from src.observability.telemetry_metrics import configure_otel_metrics, flush_otel_metrics

settings = src.config.settings

DEFAULT_WORKER_SERVICE_NAME = "finance-report-worker"

_configured = False


def configure_worker_telemetry() -> bool:
    """Configure OTEL metrics, logs and traces once per process.

    Returns ``True`` when export is on. Does nothing without
    ``OTEL_EXPORTER_OTLP_ENDPOINT``. The service name is ``OTEL_SERVICE_NAME`` when
    set, else ``finance-report-worker``.
    """
    global _configured
    if not settings.otel_exporter_otlp_endpoint:
        return False
    if _configured:
        return True
    settings.otel_service_name = os.environ.get("OTEL_SERVICE_NAME") or DEFAULT_WORKER_SERVICE_NAME
    configure_logging()
    configure_otel_metrics()
    _configured = True
    return True


def flush_worker_telemetry() -> None:
    """Flush metrics, logs and traces so a short-lived process keeps its data."""
    flush_otel_metrics()
    flush_otel_logs_and_traces()


@contextmanager
def flow_run_telemetry() -> Iterator[None]:
    """Configure OTEL on entry and flush on exit, including on failure."""
    configure_worker_telemetry()
    try:
        yield
    finally:
        flush_worker_telemetry()
