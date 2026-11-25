from __future__ import annotations

import builtins
import sys
import types
from collections import defaultdict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.observability import telemetry_metrics

pytestmark = pytest.mark.no_db
REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def reset_metrics_state():
    def _reset():
        telemetry_metrics._clear_metrics_state()
        telemetry_metrics.set_async_parse_in_flight(0)
        telemetry_metrics.set_db_pool_observer(None)

    _reset()
    yield
    _reset()


def install_fake_otel(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    def _inst():
        ns = types.SimpleNamespace(add_calls=[], record_calls=[])
        ns.add = lambda v, a: ns.add_calls.append((v, a))
        ns.record = lambda v, a: ns.record_calls.append((v, a))
        return ns

    meter = types.SimpleNamespace(counters=defaultdict(_inst), histograms=defaultdict(_inst), gauges={})
    meter.create_counter = lambda name, **_kw: meter.counters[name]
    meter.create_histogram = lambda name, **_kw: meter.histograms[name]
    meter.create_observable_gauge = lambda name, **kw: meter.gauges.__setitem__(name, kw["callbacks"])

    mods: dict[str, types.ModuleType] = {}
    for name in (
        "opentelemetry",
        "opentelemetry.metrics",
        "opentelemetry.exporter",
        "opentelemetry.exporter.otlp",
        "opentelemetry.exporter.otlp.proto",
        "opentelemetry.exporter.otlp.proto.http",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
        "opentelemetry.sdk",
        "opentelemetry.sdk.metrics",
        "opentelemetry.sdk.metrics.export",
        "opentelemetry.sdk.resources",
    ):
        mod = types.ModuleType(name)
        mod.__path__ = []
        monkeypatch.setitem(sys.modules, name, mod)
        mods[name] = mod
        if "." in name:
            setattr(mods[name.rsplit(".", 1)[0]], name.rsplit(".", 1)[1], mod)

    mods["opentelemetry.metrics"].get_meter = lambda _n: meter
    mods["opentelemetry.metrics"].set_meter_provider = lambda _p: None
    mods["opentelemetry.metrics"].Observation = lambda v, attributes=None: (v, attributes or {})
    mods["opentelemetry.exporter.otlp.proto.http.metric_exporter"].OTLPMetricExporter = (
        lambda endpoint: types.SimpleNamespace(endpoint=endpoint)
    )
    mods["opentelemetry.sdk.metrics"].MeterProvider = lambda resource, metric_readers: types.SimpleNamespace(
        resource=resource, metric_readers=metric_readers
    )
    mods["opentelemetry.sdk.metrics.export"].PeriodicExportingMetricReader = lambda exporter: types.SimpleNamespace(
        exporter=exporter
    )
    mods["opentelemetry.sdk.resources"].Resource = types.SimpleNamespace(
        create=lambda attributes: types.SimpleNamespace(attributes=attributes)
    )
    return meter


def _enable_otel(
    monkeypatch: pytest.MonkeyPatch, endpoint: str | None = "http://collector:4318"
) -> types.SimpleNamespace:
    meter = install_fake_otel(monkeypatch)
    monkeypatch.setattr(telemetry_metrics.settings, "otel_exporter_otlp_endpoint", endpoint)
    monkeypatch.setattr(telemetry_metrics.settings, "otel_service_name", "finance-report-backend")
    monkeypatch.setattr(telemetry_metrics.settings, "otel_resource_attributes", "deployment.environment=staging")
    telemetry_metrics.configure_otel_metrics()
    return meter


def _obs_vals(obs) -> list[object]:
    return [item[0] if isinstance(item, tuple) else getattr(item, "value") for item in obs]


def test_AC10_10_1_configure_metrics_lifecycle_and_import_failure(monkeypatch) -> None:
    monkeypatch.setattr(telemetry_metrics.settings, "otel_exporter_otlp_endpoint", None)
    telemetry_metrics.mark_metrics_export_active(True)
    telemetry_metrics.configure_otel_metrics()
    assert not telemetry_metrics.is_metrics_export_active() and telemetry_metrics._instruments == {}

    meter = _enable_otel(monkeypatch)
    assert telemetry_metrics.is_metrics_export_active() is True
    assert "http.server.request.count" not in meter.counters and "http.server.request.duration" not in meter.histograms
    assert "finance.statement_parse.outcome" in meter.counters and "finance.ai_provider.latency" in meter.histograms
    assert {"db.pool.size", "finance.async_parse.in_flight"} <= set(meter.gauges)

    telemetry_metrics.record_rate_limit_rejected(scope="global_api")
    monkeypatch.setattr(telemetry_metrics.settings, "otel_exporter_otlp_endpoint", None)
    telemetry_metrics.configure_otel_metrics()
    telemetry_metrics.record_rate_limit_rejected(scope="global_api")
    assert (
        not telemetry_metrics.is_metrics_export_active()
        and telemetry_metrics._instruments == {}
        and len(meter.counters["finance.rate_limit.rejected"].add_calls) == 1
    )

    _enable_otel(monkeypatch)
    real_import = builtins.__import__
    monkeypatch.delitem(sys.modules, "opentelemetry.metrics", raising=False)
    monkeypatch.setattr(
        builtins,
        "__import__",
        lambda n, *a, **kw: (_ for _ in ()).throw(ImportError("blocked"))
        if n == "opentelemetry" or n.startswith("opentelemetry.metrics")
        else real_import(n, *a, **kw),
    )
    telemetry_metrics.configure_otel_metrics()
    assert not telemetry_metrics.is_metrics_export_active() and telemetry_metrics._instruments == {}


async def test_AC10_10_2_red_metrics_record_low_cardinality_labels(monkeypatch) -> None:
    from httpx import ASGITransport, AsyncClient
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from src import main as main_module

    reader = InMemoryMetricReader()
    monkeypatch.setitem(
        main_module.app._native_telemetry.config, "meter_provider", MeterProvider(metric_readers=[reader])
    )
    monkeypatch.setitem(main_module.app._native_telemetry.config, "metrics", True)
    async with AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test") as client:
        assert (await client.get("/openapi.json")).status_code == 200 and (await client.get("/health")).status_code in (
            200,
            503,
        )

    by_name = {
        m.name: [dict(dp.attributes or {}) for dp in m.data.data_points]
        for rm in reader.get_metrics_data().resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
    }
    assert (
        "http.server.request.duration" in by_name
        and "http.server.request.count" not in by_name
        and "http.server.duration" not in by_name
    )
    attrs = by_name["http.server.request.duration"]
    assert any(
        a.get("http.route") == "/openapi.json"
        and a.get("http.response.status_code") == 200
        and a.get("http.request.method") == "GET"
        and "http.response.status_code_class" not in a
        for a in attrs
    )
    assert not any(a.get("http.route") == "/health" for a in attrs)


def test_AC10_10_2_to_10_4_endpoints_gauges_and_record_metrics(monkeypatch) -> None:
    pipeline = (REPO_ROOT / "apps/backend/src/extraction/extension/statement_pipeline.py").read_text(encoding="utf-8")
    flow = (REPO_ROOT / "apps/backend/src/statement_flow.py").read_text(encoding="utf-8")
    assert all(
        tok in pipeline
        for tok in ("run_with_async_parse_tracking", "statement_id=job.statement_id", "request_id=job.request_id")
    )
    assert all(
        tok in flow
        for tok in (
            "run_with_async_parse_tracking",
            "statement_id=parse_job.statement_id",
            "request_id=parse_job.request_id",
        )
    )

    meter = _enable_otel(monkeypatch)
    telemetry_metrics.set_async_parse_in_flight(3)
    telemetry_metrics.set_db_pool_observer(lambda: {"size": 5, "checkedout": 2, "overflow": 1})
    assert (
        telemetry_metrics._observe_async_parse_in_flight(),
        telemetry_metrics._observe_db_pool_size(),
        telemetry_metrics._observe_db_pool_checkedout(),
        telemetry_metrics._observe_db_pool_overflow(),
    ) == ([(3, {})], [(5, {})], [(2, {})], [(1, {})])
    pool = types.SimpleNamespace(size=lambda: 7, checkedout=lambda: 3, overflow=lambda: 1)
    telemetry_metrics.configure_database_pool_metrics(
        types.SimpleNamespace(sync_engine=types.SimpleNamespace(pool=pool))
    )
    assert (
        _obs_vals(telemetry_metrics._observe_db_pool_size()),
        _obs_vals(telemetry_metrics._observe_db_pool_checkedout()),
        _obs_vals(telemetry_metrics._observe_db_pool_overflow()),
    ) == ([7], [3], [1])

    telemetry_metrics.record_statement_parse_outcome(outcome="success", parser="csv")
    telemetry_metrics.record_ai_provider_call(
        provider="openrouter", model="glm-5.1", outcome="success", duration_ms=321.0
    )
    telemetry_metrics.record_reconciliation_match_outcome(outcome="accepted")
    telemetry_metrics.record_statement_classification_outcome(outcome="failed")
    telemetry_metrics.record_statement_classification_outcome(outcome="classified")
    telemetry_metrics.record_rate_limit_rejected(scope="global_api")
    assert meter.counters["finance.statement_parse.outcome"].add_calls == [(1, {"outcome": "success", "parser": "csv"})]
    assert meter.histograms["finance.ai_provider.latency"].record_calls == [
        (321.0, {"provider": "openrouter", "model": "glm-5.1", "outcome": "success"})
    ]
    assert meter.counters["finance.reconciliation.match.outcome"].add_calls == [(1, {"outcome": "accepted"})]
    assert meter.counters["finance.statement_classification.outcome"].add_calls == [
        (1, {"outcome": "failed"}),
        (1, {"outcome": "classified"}),
    ]
    assert (
        meter.counters["finance.rate_limit.rejected"].add_calls == [(1, {"scope": "global_api"})]
        and "finance.confidence_north_star" not in meter.histograms
    )


async def test_AC10_10_3_and_AC10_12_1_async_parse_tracking_success_and_failure(monkeypatch) -> None:
    observed: list[list[object]] = []

    async def ok_work() -> None:
        observed.append(_obs_vals(telemetry_metrics._observe_async_parse_in_flight()))

    async def fail_work() -> None:
        raise RuntimeError("provider failed with a compact safe summary")

    await telemetry_metrics.run_with_async_parse_tracking(ok_work())
    assert observed == [[1]] and _obs_vals(telemetry_metrics._observe_async_parse_in_flight()) == [0]

    meter = _enable_otel(monkeypatch)
    exc_calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        telemetry_metrics, "logger", types.SimpleNamespace(exception=lambda ev, **kw: exc_calls.append((ev, kw)))
    )
    with pytest.raises(RuntimeError):
        await telemetry_metrics.run_with_async_parse_tracking(
            fail_work(), statement_id="statement-123", request_id="request-123"
        )
    assert _obs_vals(telemetry_metrics._observe_async_parse_in_flight()) == [0]
    assert meter.counters["finance.async_parse.failure"].add_calls == [
        (1, {"task": "statement_parse", "error_type": "RuntimeError"})
    ]
    assert exc_calls == [
        (
            "statement.parse.async_task.failed",
            {
                "audit_event": "statement.parse.async_task.failed",
                "statement_id": "statement-123",
                "request_id": "request-123",
                "task_name": "statement_parse",
                "error_type": "RuntimeError",
                "safe_error_message": "provider failed with a compact safe summary",
            },
        )
    ]


@pytest.mark.parametrize(
    ("error_type", "status", "stage1"),
    [("ExtractionError", "rejected", "rejected"), ("TransactionIdentityReviewRequired", "parsed", "pending_review")],
)
async def test_AC10_12_3_parse_failure_state_and_log_contract_are_preserved(
    monkeypatch, error_type, status, stage1
) -> None:
    from src.extraction import BankStatementStatus
    from src.extraction.extension import statement_parsing
    from src.extraction.orm.statement_summary import StatementSummary

    stmt = StatementSummary(id=uuid4(), status=BankStatementStatus.PARSING, confidence_score=90, balance_validated=True)
    db, warning, metric = AsyncMock(), MagicMock(), MagicMock()
    db.get.return_value = stmt
    monkeypatch.setattr(statement_parsing.logger, "warning", warning)
    monkeypatch.setattr(statement_parsing, "record_statement_parse_outcome", metric)
    await statement_parsing.handle_parse_failure(
        stmt,
        db,
        message="Generated failure for synthetic@example.com " + "x" * 400,
        phase="extraction_started",
        error_type=error_type,
    )
    assert (stmt.status.value, stmt.stage1_status.value, stmt.confidence_score, stmt.balance_validated) == (
        status,
        stage1,
        0,
        False,
    )
    db.rollback.assert_awaited_once()
    db.get.assert_awaited_once_with(StatementSummary, stmt.id, with_for_update={"key_share": True})
    db.commit.assert_awaited_once()
    logged = warning.call_args.kwargs
    assert warning.call_args.args == ("statement.parse.failed",) and len(logged["safe_error_message"]) <= 300
    assert (logged["audit_event"], logged["statement_id"], logged["phase"], logged["error_type"]) == (
        "statement.parse.failed",
        str(stmt.id),
        "extraction_started",
        error_type,
    )
    assert (
        "synthetic@example.com" not in logged["safe_error_message"]
        and "synthetic@example.com" not in stmt.validation_error
    )
    metric.assert_called_once_with(outcome="failure")
