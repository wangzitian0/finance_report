"""Runtime observability contract for vendor-neutral OpenTelemetry logs and traces."""

from __future__ import annotations

from typing import Any

import src.config

_fastapi_instrumentation_active = False


def mark_fastapi_instrumentation_active(active: bool = True) -> None:
    global _fastapi_instrumentation_active
    _fastapi_instrumentation_active = active


def is_fastapi_instrumentation_active() -> bool:
    return _fastapi_instrumentation_active


def _deployment_environment(resource_attributes: dict[str, str]) -> str:
    return resource_attributes.get("deployment.environment") or src.config.settings.environment


def get_observability_status() -> dict[str, Any]:
    """Return a redacted runtime view of the observability configuration."""
    settings = src.config.settings
    resource_attributes = src.config.parse_key_value_pairs(settings.otel_resource_attributes)
    exporter_configured = bool(settings.otel_exporter_otlp_endpoint)
    try:
        from src.observability.telemetry_metrics import is_metrics_export_active

        metrics_export_enabled = is_metrics_export_active()
    except Exception:  # pragma: no cover
        metrics_export_enabled = False
    return {
        "otel_exporter_configured": exporter_configured,
        "logs_export_enabled": exporter_configured,
        "traces_export_enabled": exporter_configured,
        "metrics_export_enabled": metrics_export_enabled,
        "request_instrumentation_active": _fastapi_instrumentation_active,
        "service_name": settings.otel_service_name,
        "service_version": settings.git_commit_sha,
        "deployment_environment": _deployment_environment(resource_attributes),
        "resource_attributes": resource_attributes,
    }


def log_observability_startup(logger: Any) -> None:
    logger.info("Observability runtime configured", **get_observability_status())
