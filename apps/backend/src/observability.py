"""Runtime observability contract for logs, traces, and alert routing."""

from __future__ import annotations

from typing import Any

from src.config import parse_key_value_pairs, settings

ERROR_LOG_ALERT_RULE_NAME = "FinanceReportBackendErrorLogs"
ERROR_LOG_ALERT_SERVICE_NAME = "finance-report-backend"
ALERTING_PIPELINE = "component->otel->signoz->lark"


def _deployment_environment(resource_attributes: dict[str, str]) -> str:
    return resource_attributes.get("deployment.environment") or settings.environment


def get_observability_status() -> dict[str, Any]:
    """Return a redacted runtime view of the observability configuration.

    The payload is safe for `/health` and startup logs: it intentionally does not
    expose collector URLs, webhook URLs, API keys, or bot secrets.
    """
    resource_attributes = parse_key_value_pairs(settings.otel_resource_attributes)
    exporter_configured = bool(settings.otel_exporter_otlp_endpoint)

    return {
        "otel_exporter_configured": exporter_configured,
        "logs_export_enabled": exporter_configured,
        "traces_export_enabled": exporter_configured,
        "service_name": settings.otel_service_name,
        "deployment_environment": _deployment_environment(resource_attributes),
        "resource_attributes": resource_attributes,
        "alert_rule_name": ERROR_LOG_ALERT_RULE_NAME,
        "alert_rule_service_name": ERROR_LOG_ALERT_SERVICE_NAME,
        "alerting_pipeline": ALERTING_PIPELINE,
    }


def log_observability_startup(logger: Any) -> None:
    """Emit one structured startup event for SigNoz/Lark alert triage."""
    logger.info("Observability runtime configured", **get_observability_status())
