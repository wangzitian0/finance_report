"""EPIC-012 transaction-boundary guardrails."""

from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import FxRate, StockPrice
from src.services import market_data

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SERVICE_ROOT = PROJECT_ROOT / "apps" / "backend" / "src" / "services"

ALLOWED_SERVICE_COMMIT_BOUNDARIES = {
    ("ai_advisor.py", "AIAdvisorService._stream_and_store"),
    ("market_data_scheduler.py", "run_daily_market_data_sync"),
    ("statement_parsing.py", "handle_parse_failure"),
    ("statement_parsing.py", "import_brokerage_payload_if_present"),
    ("statement_parsing.py", "parse_statement_background"),
    ("statement_parsing.py", "parse_statement_background.update_progress"),
    ("statement_parsing_supervisor.py", "reset_stale_parsing_jobs"),
}


class _CommitCallVisitor(ast.NodeVisitor):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.stack: list[str] = []
        self.calls: list[tuple[str, str, int]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_callable(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Attribute) and node.func.attr == "commit":
            self.calls.append((self.filename, ".".join(self.stack), node.lineno))
        self.generic_visit(node)

    def _visit_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def _service_commit_calls() -> list[tuple[str, str, int]]:
    calls: list[tuple[str, str, int]] = []
    for path in sorted(SERVICE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        visitor = _CommitCallVisitor(path.name)
        visitor.visit(tree)
        calls.extend(visitor.calls)
    return calls


def test_service_commit_calls_are_documented_boundary_exceptions() -> None:
    """AC12.26.1: service commit calls are limited to documented boundary exceptions."""
    unexpected = [
        f"{filename}:{lineno} in {qualname}"
        for filename, qualname, lineno in _service_commit_calls()
        if (filename, qualname) not in ALLOWED_SERVICE_COMMIT_BOUNDARIES
    ]

    assert unexpected == []


async def test_market_data_fx_persistence_is_rollbackable_until_boundary_commit(db: AsyncSession) -> None:
    """AC12.26.2: market-data persistence helpers flush but do not finalize transactions."""
    rate = await market_data._persist_fx_rate(
        db,
        market_data.FxRateObservation(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.350000"),
            rate_date=date(2026, 1, 5),
            source="test",
        ),
    )

    assert rate == Decimal("1.350000")
    await db.rollback()

    persisted = await db.scalar(
        select(FxRate)
        .where(FxRate.base_currency == "USD")
        .where(FxRate.quote_currency == "SGD")
        .where(FxRate.rate_date == date(2026, 1, 5))
    )
    assert persisted is None


async def test_market_data_sync_endpoint_commits_service_writes_at_router_boundary(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC12.26.3: market-data sync endpoints commit service writes at the router boundary."""

    async def fake_fetch(
        _base_currency: str,
        _quote_currency: str,
        _start_date: date,
        _end_date: date,
    ) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.FxRateObservation(
                    base_currency="USD",
                    quote_currency="SGD",
                    rate=Decimal("1.350000"),
                    rate_date=date(2026, 1, 5),
                    source="test",
                )
            ],
            provider_success=True,
        )

    async def fake_stock_fetch(
        _symbol: str,
        _start_date: date,
        _end_date: date,
    ) -> market_data.ValidatedMarketObservationSeries:
        return market_data.ValidatedMarketObservationSeries(
            observations=[
                market_data.StockPriceObservation(
                    symbol="AAPL",
                    price=Decimal("190.250000"),
                    currency="USD",
                    price_date=date(2026, 1, 5),
                    source="test",
                )
            ],
            provider_success=True,
        )

    monkeypatch.setattr(market_data, "_fetch_validated_fx_rate_series", fake_fetch)
    monkeypatch.setattr(market_data, "_fetch_validated_stock_price_series", fake_stock_fetch)

    fx_response = await client.post(
        "/market-data/sync/fx",
        json={
            "pairs": ["USD/SGD"],
            "start_date": "2026-01-05",
            "end_date": "2026-01-05",
        },
    )
    stock_response = await client.post(
        "/market-data/sync/stocks",
        json={
            "symbols": ["AAPL"],
            "start_date": "2026-01-05",
            "end_date": "2026-01-05",
        },
    )

    assert fx_response.status_code == 200
    assert fx_response.json()["inserted"] == 1
    assert stock_response.status_code == 200
    assert stock_response.json()["inserted"] == 1
    persisted = await db.scalar(
        select(FxRate)
        .where(FxRate.base_currency == "USD")
        .where(FxRate.quote_currency == "SGD")
        .where(FxRate.rate_date == date(2026, 1, 5))
    )
    assert persisted is not None
    persisted_stock = await db.scalar(
        select(StockPrice).where(StockPrice.symbol == "AAPL").where(StockPrice.price_date == date(2026, 1, 5))
    )
    assert persisted_stock is not None
