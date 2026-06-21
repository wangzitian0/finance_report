"""OpenTelemetry metrics wiring for backend runtime signals."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.config import parse_key_value_pairs, settings
from src.logger import get_logger

_metrics_export_active = False
_meter: Any | None = None
_instruments: dict[str, Any] = {}
_async_parse_in_flight = 0
_db_pool_observer: Callable[[], dict[str, int]] | None = None
logger = get_logger(__name__)


def _build_otel_resource() -> Any:
    from opentelemetry.sdk.resources import Resource

    attributes = {
        "service.name": settings.otel_service_name,
        "service.version": settings.git_commit_sha,
        "git.commit": settings.git_commit_sha,
    }
    attributes.update(parse_key_value_pairs(settings.otel_resource_attributes))
    return Resource.create(attributes)


def _build_otlp_metrics_endpoint(endpoint: str) -> str:
    trimmed = endpoint.rstrip("/")
    if trimmed.endswith("/v1/metrics"):
        return trimmed
    return f"{trimmed}/v1/metrics"


def mark_metrics_export_active(active: bool = True) -> None:
    global _metrics_export_active
    _metrics_export_active = active


def _clear_metrics_state() -> None:
    global _meter
    _meter = None
    _instruments.clear()
    mark_metrics_export_active(False)


def is_metrics_export_active() -> bool:
    return _metrics_export_active


def configure_otel_metrics() -> None:
    """Configure OTLP metric export when the shared OTEL endpoint is present."""
    global _meter
    if not settings.otel_exporter_otlp_endpoint:
        _clear_metrics_state()
        return

    try:
        from opentelemetry import metrics
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    except Exception:  # pragma: no cover - defensive import guard
        logging.getLogger(__name__).warning(
            "OTEL metric exporter not available",
            exc_info=True,
        )
        _clear_metrics_state()
        return

    exporter = OTLPMetricExporter(endpoint=_build_otlp_metrics_endpoint(settings.otel_exporter_otlp_endpoint))
    reader = PeriodicExportingMetricReader(exporter)
    provider = MeterProvider(resource=_build_otel_resource(), metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _meter = metrics.get_meter("finance-report-backend")
    _create_instruments(_meter)
    mark_metrics_export_active(True)


def http_route_label_from_scope(scope: dict[str, Any]) -> str:
    """Return a low-cardinality route label for FastAPI/Starlette request scopes."""
    route = scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return "__unmatched__"


def _create_instruments(meter: Any) -> None:
    _instruments["http_request_count"] = meter.create_counter(
        "http.server.request.count",
        unit="1",
        description="HTTP requests handled by route and status class.",
    )
    _instruments["http_request_duration"] = meter.create_histogram(
        "http.server.request.duration",
        unit="ms",
        description="HTTP request duration in milliseconds.",
    )
    _instruments["statement_parse_outcome"] = meter.create_counter(
        "finance.statement_parse.outcome",
        unit="1",
        description="Statement parse outcomes.",
    )
    _instruments["ai_provider_latency"] = meter.create_histogram(
        "finance.ai_provider.latency",
        unit="ms",
        description="AI provider call latency by model and outcome.",
    )
    _instruments["reconciliation_match_outcome"] = meter.create_counter(
        "finance.reconciliation.match.outcome",
        unit="1",
        description="Reconciliation match outcomes.",
    )
    _instruments["confidence_north_star"] = meter.create_histogram(
        "finance.confidence_north_star",
        unit="1",
        description="Confidence north-star score observations.",
    )
    _instruments["rate_limit_rejected"] = meter.create_counter(
        "finance.rate_limit.rejected",
        unit="1",
        description="Rate-limit rejections by low-cardinality scope.",
    )
    _instruments["async_parse_failure"] = meter.create_counter(
        "finance.async_parse.failure",
        unit="1",
        description="Async statement parse task failures.",
    )
    _instruments["financial_invariant_violation"] = meter.create_counter(
        "finance.invariant.violation",
        unit="1",
        description=(
            "Financial-invariant violations detected during statement parsing "
            "(balance mismatch, per-currency NAV fail, running-balance chain break, "
            "within-document dedup collapse), labelled by kind and anonymized "
            "institution class. A non-silent, queryable/alertable signal; emitting "
            "it does NOT change statement routing, status, or approval."
        ),
    )
    meter.create_observable_gauge(
        "finance.async_parse.in_flight",
        callbacks=[_observe_async_parse_in_flight],
        unit="1",
        description="In-flight async statement parse tasks.",
    )
    meter.create_observable_gauge(
        "db.pool.size",
        callbacks=[_observe_db_pool_size],
        unit="1",
        description="SQLAlchemy DB pool size.",
    )
    meter.create_observable_gauge(
        "db.pool.checkedout",
        callbacks=[_observe_db_pool_checkedout],
        unit="1",
        description="SQLAlchemy DB pool checked-out connections.",
    )
    meter.create_observable_gauge(
        "db.pool.overflow",
        callbacks=[_observe_db_pool_overflow],
        unit="1",
        description="SQLAlchemy DB pool overflow connections.",
    )


def _observation(value: int | float, attributes: dict[str, str] | None = None) -> Any:
    try:
        from opentelemetry.metrics import Observation

        return Observation(value, attributes or {})
    except Exception:  # pragma: no cover - used only when tests use simple callbacks
        return (value, attributes or {})


def _observe_async_parse_in_flight(_options: object | None = None) -> list[Any]:
    return [_observation(_async_parse_in_flight)]


def set_async_parse_in_flight(count: int) -> None:
    global _async_parse_in_flight
    _async_parse_in_flight = max(0, count)


def increment_async_parse_in_flight(delta: int = 1) -> None:
    set_async_parse_in_flight(_async_parse_in_flight + delta)


def _safe_error_message(message: str | None, *, limit: int = 300) -> str | None:
    if not message:
        return message
    compact = " ".join(str(message).split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def record_async_parse_failure(*, error_type: str, task_name: str = "statement_parse") -> None:
    counter = _instruments.get("async_parse_failure")
    if counter is not None:
        counter.add(1, {"task": task_name, "error_type": error_type})


async def run_with_async_parse_tracking(
    awaitable: Awaitable[None],
    *,
    statement_id: object | None = None,
    request_id: str | None = None,
    task_name: str = "statement_parse",
) -> None:
    """Track one in-process async statement parse until it completes or fails."""
    increment_async_parse_in_flight(1)
    try:
        await awaitable
    except Exception as exc:
        error_type = type(exc).__name__
        record_async_parse_failure(error_type=error_type, task_name=task_name)
        logger.exception(
            "statement.parse.async_task.failed",
            audit_event="statement.parse.async_task.failed",
            statement_id=str(statement_id) if statement_id is not None else None,
            request_id=request_id,
            task_name=task_name,
            error_type=error_type,
            safe_error_message=_safe_error_message(str(exc)),
        )
        raise
    finally:
        increment_async_parse_in_flight(-1)


def set_db_pool_observer(observer: Callable[[], dict[str, int]] | None) -> None:
    global _db_pool_observer
    _db_pool_observer = observer


def configure_database_pool_metrics(async_engine: Any) -> None:
    """Wire DB pool gauges to a SQLAlchemy engine when pool stats are available."""
    sync_engine = getattr(async_engine, "sync_engine", async_engine)
    pool = getattr(sync_engine, "pool", None)
    if pool is None:
        set_db_pool_observer(None)
        return

    set_db_pool_observer(
        lambda: {
            "size": _pool_stat(pool, "size"),
            "checkedout": _pool_stat(pool, "checkedout"),
            "overflow": _pool_stat(pool, "overflow"),
        }
    )


def _pool_stat(pool: Any, name: str) -> int:
    value = getattr(pool, name, 0)
    try:
        resolved = value() if callable(value) else value
        return max(0, int(resolved or 0))
    except Exception:
        return 0


def _db_pool_values() -> dict[str, int]:
    if _db_pool_observer is not None:
        return _db_pool_observer()
    return {"size": 0, "checkedout": 0, "overflow": 0}


def _observe_db_pool_size(_options: object | None = None) -> list[Any]:
    return [_observation(_db_pool_values().get("size", 0))]


def _observe_db_pool_checkedout(_options: object | None = None) -> list[Any]:
    return [_observation(_db_pool_values().get("checkedout", 0))]


def _observe_db_pool_overflow(_options: object | None = None) -> list[Any]:
    return [_observation(_db_pool_values().get("overflow", 0))]


def _status_class(status_code: int) -> str:
    if status_code < 100:
        return "unknown"
    return f"{status_code // 100}xx"


def record_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_ms: float,
) -> None:
    attributes = {
        "http.request.method": method,
        "http.route": route,
        "http.response.status_code_class": _status_class(status_code),
    }
    counter = _instruments.get("http_request_count")
    histogram = _instruments.get("http_request_duration")
    if counter is not None:
        counter.add(1, attributes)
    if histogram is not None:
        histogram.record(duration_ms, attributes)


def record_statement_parse_outcome(*, outcome: str, parser: str = "default") -> None:
    counter = _instruments.get("statement_parse_outcome")
    if counter is not None:
        counter.add(1, {"outcome": outcome, "parser": parser})


def record_ai_provider_call(
    *,
    provider: str,
    model: str,
    outcome: str,
    duration_ms: float,
) -> None:
    histogram = _instruments.get("ai_provider_latency")
    if histogram is not None:
        histogram.record(
            duration_ms,
            {"provider": provider, "model": model, "outcome": outcome},
        )


def record_reconciliation_match_outcome(*, outcome: str) -> None:
    counter = _instruments.get("reconciliation_match_outcome")
    if counter is not None:
        counter.add(1, {"outcome": outcome})


def record_confidence_north_star(*, score: float, source: str = "scheduled") -> None:
    histogram = _instruments.get("confidence_north_star")
    if histogram is not None:
        histogram.record(score, {"source": source})


def record_rate_limit_rejected(*, scope: str) -> None:
    counter = _instruments.get("rate_limit_rejected")
    if counter is not None:
        counter.add(1, {"scope": scope})


# Canonical low-cardinality kinds for the financial-invariant violation counter.
# Keeping this a closed set keeps the metric label space bounded and alertable.
INVARIANT_VIOLATION_KINDS = (
    "balance_mismatch",
    "per_currency_nav",
    "chain_break",
    "dedup_within_doc_collapse",
)

# Closed, anonymized institution-class vocabulary. Anything outside this set is
# coerced to ``"unknown"`` so a stray real institution name can never become a
# metric label (PII / unbounded-cardinality guard).
INVARIANT_INSTITUTION_CLASSES = ("bank", "brokerage", "unknown")


def record_financial_invariant_violation(*, kind: str, institution_class: str = "unknown") -> None:
    """Record one detected financial-invariant violation as a queryable counter.

    ``kind`` MUST be one of :data:`INVARIANT_VIOLATION_KINDS`; an unrecognized
    ``kind`` is logged and dropped (a no-op) rather than emitted, so a typo can
    never silently explode the metric's label cardinality. ``institution_class``
    is coerced into the closed :data:`INVARIANT_INSTITUTION_CLASSES` set
    (defaulting to ``"unknown"``) — never a real institution name or any account
    identifier — so the metric stays PII-free and bounded.

    This is the observability half of closing the "silent failure" gap: a slipped
    invariant violation (balance mismatch, per-currency NAV fail, running-balance
    chain break, within-document dedup collapse) becomes a structured, alertable
    signal. It is purely additive — it never changes routing, status, or approval.
    """
    if kind not in INVARIANT_VIOLATION_KINDS:
        # Reject out-of-vocabulary kinds rather than forwarding them as labels:
        # an unbounded/typo'd label is worse than a dropped metric, and the gap is
        # visible in logs.
        logger.warning(
            "Ignoring financial-invariant violation with unknown kind",
            kind=kind,
            valid_kinds=list(INVARIANT_VIOLATION_KINDS),
        )
        return
    safe_class = institution_class if institution_class in INVARIANT_INSTITUTION_CLASSES else "unknown"
    counter = _instruments.get("financial_invariant_violation")
    if counter is not None:
        counter.add(1, {"kind": kind, "institution_class": safe_class})
