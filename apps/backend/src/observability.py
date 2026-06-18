"""Runtime observability contract for logs, traces, and alert routing."""

from __future__ import annotations

from typing import Any

from src.config import parse_key_value_pairs, settings

ERROR_LOG_ALERT_RULE_NAME = "FinanceReportBackendErrorLogs"
ERROR_LOG_ALERT_SERVICE_NAME = "finance-report-backend"
ALERTING_PIPELINE = "component->otel->signoz->lark"

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
    return resource_attributes.get("deployment.environment") or settings.environment


def get_observability_status() -> dict[str, Any]:
    """Return a redacted runtime view of the observability configuration.

    The payload is safe for `/health` and startup logs: it intentionally does not
    expose collector URLs, webhook URLs, API keys, or bot secrets.
    """
    resource_attributes = parse_key_value_pairs(settings.otel_resource_attributes)
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
        "alert_rule_name": ERROR_LOG_ALERT_RULE_NAME,
        "alert_rule_service_name": ERROR_LOG_ALERT_SERVICE_NAME,
        "alerting_pipeline": ALERTING_PIPELINE,
    }


def log_observability_startup(logger: Any) -> None:
    """Emit one structured startup event for SigNoz/Lark alert triage."""
    logger.info("Observability runtime configured", **get_observability_status())
