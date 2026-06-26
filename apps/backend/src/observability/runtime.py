"""Runtime observability contract for vendor-neutral OpenTelemetry logs and traces.

The app emits OTLP and reports its own OTEL runtime readiness; it deliberately
knows nothing about the observability *backend* (which collector/UI/alerting is
behind the OTLP endpoint). Choosing the backend, wiring alert rules, and proving
ingestion are infra2's concern, reached only through the vendor-neutral OTLP
endpoint.

``src.config`` is imported by its bare published root (the package-model
cross-domain rule: reach another registered package only via ``import src.<pkg>``
or a symbol in its ``__all__``); the config singleton is read at call time so a
monkeypatched ``src.config.settings`` is always reflected.
"""

from __future__ import annotations

from typing import Any

import src.config

# Runtime flag set by the app once FastAPI request instrumentation is actually
# applied to the app instance. This is real init state, not configuration: a
# misconfigured instrumentor leaves this False even when the exporter endpoint
# is configured, so /health and startup logs can no longer look green while
# request tracing is silently absent.
_fastapi_instrumentation_active = False


def mark_fastapi_instrumentation_active(active: bool = True) -> None:
    """Record whether FastAPI request instrumentation was applied to the app."""
    global _fastapi_instrumentation_active
    _fastapi_instrumentation_active = active


def is_fastapi_instrumentation_active() -> bool:
    return _fastapi_instrumentation_active


def _deployment_environment(resource_attributes: dict[str, str]) -> str:
    return (
        resource_attributes.get("deployment.environment")
        or src.config.settings.environment
    )


def get_observability_status() -> dict[str, Any]:
    """Return a redacted runtime view of the observability configuration.

    The payload is safe for `/health` and startup logs: it intentionally does not
    expose collector URLs, webhook URLs, API keys, or bot secrets.
    """
    settings = src.config.settings
    resource_attributes = src.config.parse_key_value_pairs(
        settings.otel_resource_attributes
    )
    exporter_configured = bool(settings.otel_exporter_otlp_endpoint)
    try:
        from src.telemetry_metrics import is_metrics_export_active

        metrics_export_enabled = is_metrics_export_active()
    except Exception:  # pragma: no cover - defensive import guard
        metrics_export_enabled = False

    return {
        "otel_exporter_configured": exporter_configured,
        "logs_export_enabled": exporter_configured,
        "traces_export_enabled": exporter_configured,
        "metrics_export_enabled": metrics_export_enabled,
        # Real init state: True only when FastAPI request instrumentation was
        # actually applied to the app instance (not merely configured).
        "request_instrumentation_active": _fastapi_instrumentation_active,
        "service_name": settings.otel_service_name,
        "service_version": settings.git_commit_sha,
        "deployment_environment": _deployment_environment(resource_attributes),
        "resource_attributes": resource_attributes,
    }


def log_observability_startup(logger: Any) -> None:
    """Emit one structured startup event capturing OTEL runtime readiness."""
    logger.info("Observability runtime configured", **get_observability_status())
