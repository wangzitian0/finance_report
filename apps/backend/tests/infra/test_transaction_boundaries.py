from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.pricing.extension import market_data
from src.pricing.orm.market_data import FxRate, StockPrice

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SERVICE_ROOT = PROJECT_ROOT / "apps" / "backend" / "src" / "extraction" / "extension"
PRICING_ROOT = PROJECT_ROOT / "apps" / "backend" / "src" / "pricing"
ALLOWED_SERVICE_COMMIT_BOUNDARIES = {("statement_parsing.py", "handle_parse_failure"), ("statement_parsing.py", "route_brokerage_for_review_if_present"), ("statement_parsing.py", "_execute_statement_ingestion"), ("statement_parsing.py", "_execute_statement_ingestion.update_progress"), ("statement_parsing.py", "StatementIngestionUseCase._end_failed_attempt"), ("statement_parsing_supervisor.py", "reap_stale_parsing_runs"), ("statement_parsing_supervisor.py", "parsing_heartbeat.beat"), ("statement_workflow.py", "approve_statement_workflow"), ("statement_workflow.py", "analyze_tenant_tables"), ("statement_classification_run.py", "execute_classify_run"), ("statement_classification_run.py", "_classify_in_phases"), ("statement_classification_run.py", "_write_batch"), ("statement_classification_run.py", "_finish"), ("statement_classification_run.py", "_fail"), ("statement_classification_run.py", "_approve_and_finish")}
ALLOWED_PRICING_COMMIT_BOUNDARIES = {("extension/scheduler.py", "run_daily_market_data_sync"), ("extension/ingest.py", "make_statement_price_handler._handle")}


def _commit_calls(root: Path) -> list[tuple[str, str, int]]:
    calls: list[tuple[str, str, int]] = []

    def walk(node: ast.AST, fn: str, stack: tuple[str, ...]) -> None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            stack = (*stack, node.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "commit":
            calls.append((fn, ".".join(stack), node.lineno))
        for child in ast.iter_child_nodes(node):
            walk(child, fn, stack)

    for p in sorted(root.rglob("*.py")):
        walk(ast.parse(p.read_text(), filename=str(p)), p.relative_to(root).as_posix(), ())
    return calls


def test_service_commit_calls_are_documented_boundary_exceptions() -> None:
    for root, allowed in ((SERVICE_ROOT, ALLOWED_SERVICE_COMMIT_BOUNDARIES), (PRICING_ROOT, ALLOWED_PRICING_COMMIT_BOUNDARIES)):
        assert [f"{fn}:{ln} in {qn}" for fn, qn, ln in _commit_calls(root) if (fn, qn) not in allowed] == []


async def test_market_data_fx_persistence_is_rollbackable_and_router_commits(client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    rate = await market_data._persist_fx_rate(db, market_data.FxRateObservation(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=date(2026, 1, 5), source="test"))
    await db.rollback()
    assert rate == Decimal("1.350000") and await db.scalar(select(FxRate).where(FxRate.base_currency == "USD", FxRate.quote_currency == "SGD", FxRate.rate_date == date(2026, 1, 5))) is None

    monkeypatch.setattr(market_data._providers, "_fetch_validated_fx_rate_series", lambda *_a: _async_ret(market_data.ValidatedMarketObservationSeries(observations=[market_data.FxRateObservation(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=date(2026, 1, 5), source="test")], provider_success=True)))
    monkeypatch.setattr(market_data._providers, "_fetch_validated_stock_price_series", lambda *_a: _async_ret(market_data.ValidatedMarketObservationSeries(observations=[market_data.StockPriceObservation(symbol="AAPL", price=Decimal("190.250000"), currency="USD", price_date=date(2026, 1, 5), source="test")], provider_success=True)))
    fx_resp, stock_resp = await client.post("/pricing/fx/syncs", json={"pairs": ["USD/SGD"], "start_date": "2026-01-05", "end_date": "2026-01-05"}), await client.post("/pricing/stocks/syncs", json={"symbols": ["AAPL"], "start_date": "2026-01-05", "end_date": "2026-01-05"})
    assert (fx_resp.status_code, fx_resp.json()["inserted"], stock_resp.status_code, stock_resp.json()["inserted"]) == (200, 1, 200, 1)
    assert await db.scalar(select(FxRate).where(FxRate.base_currency == "USD", FxRate.quote_currency == "SGD", FxRate.rate_date == date(2026, 1, 5))) is not None
    assert await db.scalar(select(StockPrice).where(StockPrice.symbol == "AAPL", StockPrice.price_date == date(2026, 1, 5))) is not None


async def _async_ret(val):
    return val
