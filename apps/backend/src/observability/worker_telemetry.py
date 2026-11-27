"""OpenTelemetry bootstrap for Prefect flow-run processes (#2850)."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from infra2_sdk.telemetry import TelemetryProviders, worker_run

import src.config
from src.observability import telemetry_metrics
from src.observability.telemetry_metrics import configure_otel_metrics, flush_otel_metrics

settings = src.config.settings
DEFAULT_WORKER_SERVICE_NAME = "finance-report-worker"
_configured = False
_providers: TelemetryProviders | None = None


def _build_worker_env() -> tuple[str, dict[str, str]]:
    service_name = os.environ.get("OTEL_SERVICE_NAME") or DEFAULT_WORKER_SERVICE_NAME
    settings.otel_service_name = service_name
    env = dict(os.environ)
    env["OTEL_SERVICE_NAME"] = service_name
    env["OTEL_EXPORTER_OTLP_ENDPOINT"] = settings.otel_exporter_otlp_endpoint or ""
    if settings.otel_resource_attributes:
        env.setdefault("OTEL_RESOURCE_ATTRIBUTES", settings.otel_resource_attributes)
    env.setdefault("ENVIRONMENT", settings.environment)
    return service_name, env


def flush_worker_telemetry() -> None:
    """Force-flush SDK metric, log, and trace providers for a worker flow run."""
    flush_otel_metrics()
    if _providers is None:
        return
    if not _providers.force_flush(10000):
        logging.getLogger(__name__).warning("OTEL flush failed")


@contextmanager
def flow_run_telemetry() -> Iterator[None]:
    """Run a worker flow inside infra2_sdk.telemetry.worker_run with metrics priming and flush."""
    global _configured, _providers
    if not settings.otel_exporter_otlp_endpoint:
        yield
        return
    if _configured:
        try:
            yield
        finally:
            flush_worker_telemetry()
        return

    service_name, env = _build_worker_env()
    log_level = logging.DEBUG if settings.debug else logging.INFO
    try:
        with worker_run(
            service_name,
            environ=env,
            strict=False,
            log_level=log_level,
            set_global=True,
            clear_root_handlers=True,
        ) as providers:
            _providers = providers
            if providers is not None:
                configure_otel_metrics()
                telemetry_metrics.enable_series_priming()
                _configured = True
            yield
    finally:
        _configured = False
        _providers = None
