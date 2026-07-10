"""The ``observability`` package — the backend's published observability language.

This is the registered ``observability`` package's BE implementation (its spec and
the stdlib ``openpanel_query`` analytics CLI live in ``common/observability``). It
publishes the cohesive surfaces:

* :mod:`src.observability.runtime` — the vendor-neutral OpenTelemetry runtime
  contract (status + startup readiness, FastAPI instrumentation state);
* :mod:`src.observability.audit` — the shared structured audit/security logging
  helpers with PII and secret redaction;
* :mod:`src.observability.pii_redaction` — the Singapore-pattern PII detector
  (``detect_pii``) the audit helpers and extraction's CSV path share (was the
  flat ``src.services.pii_redaction``, #1677);
* :mod:`src.observability.logger` — structlog + OTEL logging configuration and
  the ``get_logger`` factory (was the flat ``src.logger``);
* :mod:`src.observability.telemetry_metrics` — the OTEL metric instruments and
  ``record_*`` helpers (was the flat ``src.telemetry_metrics``);
* :mod:`src.observability.analytics` — the OpenPanel product-analytics ``track``
  emitter (was the flat ``src.analytics``); and
* :mod:`src.observability.error_ids` — the ``ErrorIds`` vocabulary for Sentry
  aggregation (was ``src.constants.error_ids``).

Identity's request-context binding (``bind_authenticated_user_context``) lives in
the ``identity`` package (``src.identity.extension.observability``, #1428).
"""

from __future__ import annotations

import src.config
from src.observability.analytics import track
from src.observability.audit import (
    current_request_id,
    log_financial_mutation,
    log_security_warning,
    safe_error_message,
    safe_log_fields,
)
from src.observability.error_ids import ErrorIds
from src.observability.logger import configure_logging, get_logger
from src.observability.pii_redaction import detect_pii
from src.observability.runtime import (
    get_observability_status,
    is_fastapi_instrumentation_active,
    log_observability_startup,
    mark_fastapi_instrumentation_active,
)
from src.observability.telemetry_metrics import (
    INVARIANT_VIOLATION_KINDS,
    configure_database_pool_metrics,
    configure_otel_metrics,
    http_route_label_from_scope,
    is_metrics_export_active,
    record_ai_provider_call,
    record_financial_invariant_violation,
    record_http_request,
    record_rate_limit_rejected,
    record_reconciliation_match_outcome,
    record_statement_parse_outcome,
    run_with_async_parse_tracking,
)

# The shared config singleton, surfaced at the package root so callers and tests
# can read/patch it via ``observability.settings`` (mirroring the prior flat
# module). Bound by assignment from the bare-root ``src.config`` import to respect
# the package-model cross-domain rule; not part of the published ``interface``.
settings = src.config.settings

__all__ = [
    "INVARIANT_VIOLATION_KINDS",
    "ErrorIds",
    "configure_database_pool_metrics",
    "configure_logging",
    "configure_otel_metrics",
    "current_request_id",
    "detect_pii",
    "get_logger",
    "get_observability_status",
    "http_route_label_from_scope",
    "is_fastapi_instrumentation_active",
    "is_metrics_export_active",
    "log_financial_mutation",
    "log_observability_startup",
    "log_security_warning",
    "mark_fastapi_instrumentation_active",
    "record_ai_provider_call",
    "record_financial_invariant_violation",
    "record_http_request",
    "record_rate_limit_rejected",
    "record_reconciliation_match_outcome",
    "record_statement_parse_outcome",
    "run_with_async_parse_tracking",
    "safe_error_message",
    "safe_log_fields",
    "track",
]
