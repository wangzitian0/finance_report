"""The ``observability`` package — the backend's published observability language.

This is the registered ``observability`` package's BE implementation (its spec and
the stdlib ``openpanel_query`` analytics CLI live in ``common/observability``). It
publishes two cohesive surfaces:

* :mod:`src.observability.runtime` — the vendor-neutral OpenTelemetry runtime
  contract (status + startup readiness, FastAPI instrumentation state); and
* :mod:`src.observability.audit` — the shared structured audit/security logging
  helpers with PII and secret redaction.

Identity's request-context binding (``bind_authenticated_user_context``) is kept in
``src.observability_events`` and folded in by #1428.
"""

from __future__ import annotations

import src.config
from src.observability.audit import (
    current_request_id,
    log_financial_mutation,
    log_security_warning,
    safe_error_message,
    safe_log_fields,
)
from src.observability.runtime import (
    get_observability_status,
    is_fastapi_instrumentation_active,
    log_observability_startup,
    mark_fastapi_instrumentation_active,
)

# The shared config singleton, surfaced at the package root so callers and tests
# can read/patch it via ``observability.settings`` (mirroring the prior flat
# module). Bound by assignment from the bare-root ``src.config`` import to respect
# the package-model cross-domain rule; not part of the published ``interface``.
settings = src.config.settings

__all__ = [
    "current_request_id",
    "get_observability_status",
    "is_fastapi_instrumentation_active",
    "log_financial_mutation",
    "log_observability_startup",
    "log_security_warning",
    "mark_fastapi_instrumentation_active",
    "safe_error_message",
    "safe_log_fields",
]
