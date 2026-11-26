"""OpenTelemetry bootstrap for Prefect flow-run processes (#2850)."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from infra2_sdk.telemetry import init_worker

import src.config
from src.observability import telemetry_metrics
from src.observability.telemetry_metrics import configure_otel_metrics, flush_otel_metrics

settings = src.config.settings
DEFAULT_WORKER_SERVICE_NAME = "finance-report-worker"
_configured = False
_providers: Any | None = None


def configure_worker_telemetry() -> bool:
    """Initialize worker JSON logging and OTel providers via infra2-sdk."""
    global _configured, _providers
    if not settings.otel_exporter_otlp_endpoint:
        return False
    if _configured:
        return True
    # Remove Prefect's root stderr handlers so SDK stdout JSON logging attaches cleanly.
    logging.getLogger().handlers.clear()
    service_name = os.environ.get("OTEL_SERVICE_NAME") or DEFAULT_WORKER_SERVICE_NAME
    settings.otel_service_name = service_name
    base_attrs = ",".join(
        part
        for part in (settings.otel_resource_attributes or "").split(",")
        if part.strip() and not part.strip().startswith("service.instance.id=")
    )
    attrs = f"{base_attrs},service.instance.id={uuid4()}" if base_attrs else f"service.instance.id={uuid4()}"
    settings.otel_resource_attributes = attrs
    env = dict(os.environ)
    env["OTEL_SERVICE_NAME"] = service_name
    env["OTEL_EXPORTER_OTLP_ENDPOINT"] = settings.otel_exporter_otlp_endpoint
    env["OTEL_RESOURCE_ATTRIBUTES"] = attrs
    env.setdefault("ENVIRONMENT", settings.environment)
    _providers = init_worker(
        DEFAULT_WORKER_SERVICE_NAME,
        strict=False,
        log_level=logging.DEBUG if settings.debug else logging.INFO,
        set_global=True,
        environ=env,
    )
    if _providers is None:
        return False
    configure_otel_metrics()
    telemetry_metrics.enable_series_priming()
    _configured = True
    return True


def flush_worker_telemetry() -> None:
    """Force-flush SDK metric, log, and trace providers for a worker flow run."""
    flush_otel_metrics()
    if _providers is None:
        return
    for provider in (_providers.logger_provider, _providers.tracer_provider):
        if provider is not None:
            try:
                provider.force_flush(10000)
            except Exception:
                logging.getLogger(__name__).warning("OTEL flush failed", exc_info=True)


@contextmanager
def flow_run_telemetry() -> Iterator[None]:
    configure_worker_telemetry()
    try:
        yield
    finally:
        flush_worker_telemetry()
