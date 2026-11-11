"""OpenTelemetry bootstrap for Prefect flow-run processes (#2850)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import src.config
from src.observability import telemetry_metrics
from src.observability.logger import configure_logging, flush_otel_logs_and_traces
from src.observability.telemetry_metrics import configure_otel_metrics, flush_otel_metrics

settings = src.config.settings
DEFAULT_WORKER_SERVICE_NAME = "finance-report-worker"
_configured = False


def configure_worker_telemetry() -> bool:
    global _configured
    if not settings.otel_exporter_otlp_endpoint:
        return False
    if _configured:
        return True
    settings.otel_service_name = os.environ.get("OTEL_SERVICE_NAME") or DEFAULT_WORKER_SERVICE_NAME
    instance = f"service.instance.id={uuid4()}"
    settings.otel_resource_attributes = (
        f"{settings.otel_resource_attributes},{instance}" if settings.otel_resource_attributes else instance
    )
    configure_logging(take_over_root=True)
    configure_otel_metrics()
    telemetry_metrics.enable_series_priming()
    _configured = True
    return True


def flush_worker_telemetry() -> None:
    flush_otel_metrics()
    flush_otel_logs_and_traces()


@contextmanager
def flow_run_telemetry() -> Iterator[None]:
    configure_worker_telemetry()
    try:
        yield
    finally:
        flush_worker_telemetry()
