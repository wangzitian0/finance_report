"""OpenTelemetry metrics wiring for backend runtime signals."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import src.config
from src.observability.audit import safe_error_message
from src.observability.logger import get_logger

settings = src.config.settings
parse_key_value_pairs = src.config.parse_key_value_pairs

_metrics_export_active = False
_meter: Any | None = None
_meter_provider: Any | None = None
_instruments: dict[str, Any] = {}
_async_parse_in_flight = 0
_prime_new_series = False
_primed_series: set[tuple[str, frozenset[tuple[str, str]]]] = set()
_db_pool_observer: Callable[[], dict[str, int]] | None = None
logger = get_logger(__name__)

_COUNTER_SPECS: tuple[tuple[str, str, str], ...] = (
    ("http_request_count", "http.server.request.count", "HTTP requests handled by route and status class."),
    ("statement_parse_outcome", "finance.statement_parse.outcome", "Statement parse outcomes."),
    (
        "statement_classification_outcome",
        "finance.statement_classification.outcome",
        "Outcomes of the classification pass that runs after a statement is parsed.",
    ),
    ("reconciliation_match_outcome", "finance.reconciliation.match.outcome", "Reconciliation match outcomes."),
    ("rate_limit_rejected", "finance.rate_limit.rejected", "Rate-limit rejections by low-cardinality scope."),
    ("async_parse_failure", "finance.async_parse.failure", "Async statement parse task failures."),
    (
        "financial_invariant_violation",
        "finance.invariant.violation",
        "Financial-invariant violations detected during statement parsing.",
    ),
)

_HISTOGRAM_SPECS: tuple[tuple[str, str, str], ...] = (
    ("http_request_duration", "http.server.request.duration", "HTTP request duration in milliseconds."),
    ("ai_provider_latency", "finance.ai_provider.latency", "AI provider call latency by model and outcome."),
)

INVARIANT_VIOLATION_KINDS = (
    "balance_mismatch",
    "per_currency_nav",
    "per_currency_balance",
    "chain_break",
    "dedup_within_doc_collapse",
    "closing_balance_not_in_source",
    "llm_led_gate_quarantine_balance",
    "llm_led_gate_quarantine_dedup",
)
INVARIANT_INSTITUTION_CLASSES = ("bank", "brokerage", "unknown")


def _build_otel_resource() -> Any:
    from src.observability.logger import _build_otel_resource as _shared_build_resource

    return _shared_build_resource()


def _build_otlp_metrics_endpoint(endpoint: str) -> str:
    from infra2_sdk.runtime.otel import signal_endpoint

    return signal_endpoint(endpoint, "metrics")


def mark_metrics_export_active(active: bool = True) -> None:
    global _metrics_export_active
    _metrics_export_active = active


def flush_otel_metrics(timeout_millis: int = 10000) -> None:
    if _meter_provider is None:
        return
    try:
        _meter_provider.force_flush(timeout_millis)
    except Exception:
        logging.getLogger(__name__).warning("OTEL metric flush failed", exc_info=True)


def enable_series_priming(enabled: bool = True) -> None:
    global _prime_new_series
    _prime_new_series = enabled


def _add_counter(name: str, counter: Any, attributes: dict[str, str]) -> None:
    if _prime_new_series:
        key = (name, frozenset(attributes.items()))
        if key not in _primed_series:
            _primed_series.add(key)
            counter.add(0, attributes)
            flush_otel_metrics(timeout_millis=2000)
    counter.add(1, attributes)


def _clear_metrics_state() -> None:
    global _meter, _meter_provider
    _primed_series.clear()
    enable_series_priming(False)
    _meter = None
    _meter_provider = None
    _instruments.clear()
    mark_metrics_export_active(False)


def is_metrics_export_active() -> bool:
    return _metrics_export_active


def configure_otel_metrics() -> None:
    global _meter, _meter_provider
    if not settings.otel_exporter_otlp_endpoint:
        _clear_metrics_state()
        return
    try:
        from opentelemetry import metrics
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    except Exception:  # pragma: no cover
        logging.getLogger(__name__).warning("OTEL metric exporter not available", exc_info=True)
        _clear_metrics_state()
        return

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=_build_otlp_metrics_endpoint(settings.otel_exporter_otlp_endpoint))
    )
    provider = MeterProvider(resource=_build_otel_resource(), metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _meter_provider = provider
    _meter = metrics.get_meter("finance-report-backend")
    _create_instruments(_meter)
    mark_metrics_export_active(True)


def http_route_label_from_scope(scope: dict[str, Any]) -> str:
    route_path = getattr(scope.get("route"), "path", None)
    return route_path if isinstance(route_path, str) and route_path else "__unmatched__"


def _create_instruments(meter: Any) -> None:
    for key, metric_name, desc in _COUNTER_SPECS:
        _instruments[key] = meter.create_counter(metric_name, unit="1", description=desc)
    for key, metric_name, desc in _HISTOGRAM_SPECS:
        _instruments[key] = meter.create_histogram(metric_name, unit="ms", description=desc)
    for metric_name, cb, desc in (
        ("finance.async_parse.in_flight", _observe_async_parse_in_flight, "In-flight async statement parse tasks."),
        ("db.pool.size", _observe_db_pool_size, "SQLAlchemy DB pool size."),
        ("db.pool.checkedout", _observe_db_pool_checkedout, "SQLAlchemy DB pool checked-out connections."),
        ("db.pool.overflow", _observe_db_pool_overflow, "SQLAlchemy DB pool overflow connections."),
    ):
        meter.create_observable_gauge(metric_name, callbacks=[cb], unit="1", description=desc)


def _observation(value: int | float, attributes: dict[str, str] | None = None) -> Any:
    try:
        from opentelemetry.metrics import Observation

        return Observation(value, attributes or {})
    except Exception:  # pragma: no cover
        return (value, attributes or {})


def _observe_async_parse_in_flight(_options: object | None = None) -> list[Any]:
    return [_observation(_async_parse_in_flight)]


def set_async_parse_in_flight(count: int) -> None:
    global _async_parse_in_flight
    _async_parse_in_flight = max(0, count)


def increment_async_parse_in_flight(delta: int = 1) -> None:
    set_async_parse_in_flight(_async_parse_in_flight + delta)


def record_async_parse_failure(*, error_type: str, task_name: str = "statement_parse") -> None:
    if (counter := _instruments.get("async_parse_failure")) is not None:
        _add_counter("async_parse_failure", counter, {"task": task_name, "error_type": error_type})


async def run_with_async_parse_tracking(
    awaitable: Awaitable[None],
    *,
    statement_id: object | None = None,
    request_id: str | None = None,
    task_name: str = "statement_parse",
) -> None:
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
            safe_error_message=safe_error_message(str(exc)),
        )
        raise
    finally:
        increment_async_parse_in_flight(-1)


def set_db_pool_observer(observer: Callable[[], dict[str, int]] | None) -> None:
    global _db_pool_observer
    _db_pool_observer = observer


def configure_database_pool_metrics(async_engine: Any) -> None:
    pool = getattr(getattr(async_engine, "sync_engine", async_engine), "pool", None)
    if pool is None:
        set_db_pool_observer(None)
        return
    set_db_pool_observer(lambda: {k: _pool_stat(pool, k) for k in ("size", "checkedout", "overflow")})


def _pool_stat(pool: Any, name: str) -> int:
    value = getattr(pool, name, 0)
    try:
        return max(0, int((value() if callable(value) else value) or 0))
    except Exception:
        return 0


def _db_pool_values() -> dict[str, int]:
    return _db_pool_observer() if _db_pool_observer is not None else {"size": 0, "checkedout": 0, "overflow": 0}


def _observe_db_pool_size(_options: object | None = None) -> list[Any]:
    return [_observation(_db_pool_values().get("size", 0))]


def _observe_db_pool_checkedout(_options: object | None = None) -> list[Any]:
    return [_observation(_db_pool_values().get("checkedout", 0))]


def _observe_db_pool_overflow(_options: object | None = None) -> list[Any]:
    return [_observation(_db_pool_values().get("overflow", 0))]


def _status_class(status_code: int) -> str:
    return "unknown" if status_code < 100 else f"{status_code // 100}xx"


def record_http_request(*, method: str, route: str, status_code: int, duration_ms: float) -> None:
    attrs = {
        "http.request.method": method,
        "http.route": route,
        "http.response.status_code_class": _status_class(status_code),
    }
    if (counter := _instruments.get("http_request_count")) is not None:
        counter.add(1, attrs)
    if (histogram := _instruments.get("http_request_duration")) is not None:
        histogram.record(duration_ms, attrs)


def record_statement_parse_outcome(*, outcome: str, parser: str = "default") -> None:
    if (counter := _instruments.get("statement_parse_outcome")) is not None:
        _add_counter("statement_parse_outcome", counter, {"outcome": outcome, "parser": parser})


def record_statement_classification_outcome(*, outcome: str) -> None:
    if (counter := _instruments.get("statement_classification_outcome")) is not None:
        counter.add(1, {"outcome": outcome})


def record_ai_provider_call(*, provider: str, model: str, outcome: str, duration_ms: float) -> None:
    if (histogram := _instruments.get("ai_provider_latency")) is not None:
        histogram.record(duration_ms, {"provider": provider, "model": model, "outcome": outcome})


def record_reconciliation_match_outcome(*, outcome: str) -> None:
    if (counter := _instruments.get("reconciliation_match_outcome")) is not None:
        counter.add(1, {"outcome": outcome})


def record_rate_limit_rejected(*, scope: str) -> None:
    if (counter := _instruments.get("rate_limit_rejected")) is not None:
        counter.add(1, {"scope": scope})


def record_financial_invariant_violation(*, kind: str, institution_class: str = "unknown") -> None:
    if kind not in INVARIANT_VIOLATION_KINDS:
        logger.warning(
            "Ignoring financial-invariant violation with unknown kind",
            kind=kind,
            valid_kinds=list(INVARIANT_VIOLATION_KINDS),
        )
        return
    safe_class = institution_class if institution_class in INVARIANT_INSTITUTION_CLASSES else "unknown"
    if (counter := _instruments.get("financial_invariant_violation")) is not None:
        counter.add(1, {"kind": kind, "institution_class": safe_class})
