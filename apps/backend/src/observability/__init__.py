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
* :mod:`infra2_sdk.telemetry` — SDK-owned JSON stdout logging and OTLP export;
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

import datetime
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

import src.config
from src.observability.analytics import track
from src.observability.audit import (
    RISKY_LOG_FIELD_NAMES,
    _redact_detected_pii,
    current_request_id,
    ensure_request_id,
    log_financial_mutation,
    log_security_warning,
    safe_error_message,
    safe_log_fields,
)
from src.observability.error_ids import ErrorIds
from src.observability.pii_redaction import detect_pii
from src.observability.runtime import (
    get_observability_status,
    is_fastapi_instrumentation_active,
    log_observability_startup,
    mark_fastapi_instrumentation_active,
)

_RESERVED_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def _sanitize_value(val: Any) -> Any:
    if val is None or isinstance(val, bool | int | float | bytes):
        return val
    if isinstance(val, str):
        return _redact_detected_pii(val)
    if isinstance(val, datetime.date | datetime.datetime):
        return val.isoformat()
    if isinstance(val, Mapping):
        return {
            str(k): "[REDACTED]" if str(k).lower() in RISKY_LOG_FIELD_NAMES else _sanitize_value(v)
            for k, v in val.items()
        }
    if isinstance(val, list | tuple | set | frozenset | Sequence) and not isinstance(val, str | bytes):
        return [_sanitize_value(x) for x in val]
    return _redact_detected_pii(str(val))


def _sanitize_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in fields.items():
        key = str(k)
        out[key] = "[REDACTED]" if key.lower() in RISKY_LOG_FIELD_NAMES else _sanitize_value(v)
    return out


class _StructuredLogger:
    """Thin stdlib logger adapter supporting keyword fields while honoring SDK JSON formatting."""

    def __init__(self, name: str | None = None, bound: dict[str, Any] | None = None) -> None:
        self._name = name
        self._std = logging.getLogger(name)
        self._bound = dict(bound or {})

    def bind(self, **kwargs: Any) -> _StructuredLogger:
        return _StructuredLogger(self._name, {**self._bound, **kwargs})

    def _emit(self, level: int, method: str, event: str, /, *args: Any, **kwargs: Any) -> None:
        exc_info = kwargs.pop("exc_info", None)
        stack_info = kwargs.pop("stack_info", False)
        stacklevel = kwargs.pop("stacklevel", 1) + 1
        caller_extra = kwargs.pop("extra", None)
        ctx_vars = structlog.contextvars.get_contextvars()
        merged = {**ctx_vars, **self._bound, **(caller_extra or {}), **kwargs}
        safe = _sanitize_fields(merged)
        msg = _redact_detected_pii(event) if isinstance(event, str) else event
        if structlog.is_configured():
            sl = structlog.get_logger(self._name)
            if exc_info is not None:
                safe["exc_info"] = exc_info
            getattr(sl, method)(msg, *args, **safe)
            return
        safe_extra = {k if k not in _RESERVED_RECORD_ATTRS else f"field_{k}": v for k, v in safe.items()}
        self._std.log(
            level,
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel,
            extra=safe_extra or None,
        )

    def debug(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._emit(logging.DEBUG, "debug", event, *args, **kwargs)

    def info(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._emit(logging.INFO, "info", event, *args, **kwargs)

    def warning(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._emit(logging.WARNING, "warning", event, *args, **kwargs)

    def warn(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._emit(logging.WARNING, "warning", event, *args, **kwargs)

    def error(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._emit(logging.ERROR, "error", event, *args, **kwargs)

    def critical(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._emit(logging.CRITICAL, "critical", event, *args, **kwargs)

    def exception(self, event: str, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("exc_info", True)
        self._emit(logging.ERROR, "exception", event, *args, **kwargs)


def get_logger(name: str | None = None) -> _StructuredLogger:
    return _StructuredLogger(name)


from src.observability.telemetry_metrics import (
    INVARIANT_VIOLATION_KINDS,
    configure_database_pool_metrics,
    configure_otel_metrics,
    is_metrics_export_active,
    record_ai_provider_call,
    record_confidence_tier,
    record_financial_invariant_violation,
    record_low_confidence_proportion,
    record_market_data_sync_failure,
    record_outbox_dead_letter,
    record_llm_call_failure,
    record_rate_limit_rejected,
    record_reconciliation_match_outcome,
    record_statement_classification_outcome,
    record_statement_parse_outcome,
    record_storage_sweep_failure,
    run_with_async_parse_tracking,
)
from src.observability.worker_telemetry import flow_run_telemetry


settings = src.config.settings

__all__ = [
    "INVARIANT_VIOLATION_KINDS",
    "ErrorIds",
    "configure_database_pool_metrics",
    "configure_otel_metrics",
    "current_request_id",
    "ensure_request_id",
    "flow_run_telemetry",
    "detect_pii",
    "get_logger",
    "get_observability_status",
    "is_fastapi_instrumentation_active",
    "is_metrics_export_active",
    "log_financial_mutation",
    "log_observability_startup",
    "log_security_warning",
    "mark_fastapi_instrumentation_active",
    "record_ai_provider_call",
    "record_confidence_tier",
    "record_financial_invariant_violation",
    "record_low_confidence_proportion",
    "record_market_data_sync_failure",
    "record_outbox_dead_letter",
    "record_llm_call_failure",
    "record_rate_limit_rejected",
    "record_reconciliation_match_outcome",
    "record_statement_classification_outcome",
    "record_statement_parse_outcome",
    "record_storage_sweep_failure",
    "run_with_async_parse_tracking",
    "safe_error_message",
    "safe_log_fields",
    "track",
]
