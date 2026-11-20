from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src import composition
from src.platform import PreconditionFailedError
from src.pricing.extension import market_data
from src.pricing.orm.market_data import FxRate, MarketDataSyncState, StockPrice
from src.routers import pricing as pricing_router, reports as reports_router


async def test_market_data_sync_endpoints_and_validation(
    client: AsyncClient, db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_fx = await client.post(
        "/pricing/fx/syncs", json={"pairs": ["USD-SGD"], "start_date": "2026-01-05", "end_date": "2026-01-05"}
    )
    dis = market_data.ProviderDisagreement(
        "USD/SGD",
        date(2026, 1, 5),
        "yahoo_finance",
        "stooq",
        Decimal("1.34"),
        Decimal("1.35"),
        Decimal("0.007462"),
        Decimal("0.02"),
    )
    monkeypatch.setattr(
        pricing_router,
        "sync_stock_prices",
        lambda *_a, **_kw: _coro(market_data.MarketDataSyncResult(kind="stock", requested=1, inserted=1)),
    )
    monkeypatch.setattr(
        pricing_router,
        "sync_fx_rates",
        lambda *_a, **_kw: _coro(
            market_data.MarketDataSyncResult(kind="fx", requested=1, inserted=1, disagreements=[dis])
        ),
    )
    stock_resp = await client.post(
        "/pricing/stocks/syncs", json={"symbols": ["AAPL"], "start_date": "2026-01-05", "end_date": "2026-01-05"}
    )
    fx_resp = await client.post(
        "/pricing/fx/syncs", json={"pairs": ["USD/SGD"], "start_date": "2026-01-05", "end_date": "2026-01-05"}
    )

    async def fail_stock(db: AsyncSession, *_a, **_kw):
        db.add(
            StockPrice(
                symbol="BAD", price=Decimal("1.000000"), currency="USD", price_date=date(2026, 1, 5), source="test"
            )
        )
        await db.flush()
        raise PreconditionFailedError("invalid symbol")

    monkeypatch.setattr(pricing_router, "sync_stock_prices", fail_stock)
    bad_stock = await client.post(
        "/pricing/stocks/syncs", json={"symbols": ["BAD"], "start_date": "2026-01-05", "end_date": "2026-01-05"}
    )
    async with async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)() as session:
        persisted = await session.scalar(
            select(StockPrice).where(StockPrice.symbol == "BAD", StockPrice.price_date == date(2026, 1, 5))
        )
    assert (
        (stock_resp.status_code, stock_resp.json()["inserted"], stock_resp.json()["kind"]),
        (fx_resp.status_code, fx_resp.json()["kind"], fx_resp.json()["disagreements"][0]["asset"]),
        (bad_fx.status_code, "expected BASE/QUOTE" in bad_fx.json()["detail"]),
        (bad_stock.status_code, bad_stock.json()["detail"], persisted),
    ) == ((200, 1, "stock"), (200, "fx", "USD/SGD"), (422, True), (422, "invalid symbol", None))


async def _coro(v):
    return v


async def test_market_data_status_and_freshness_read_only_boundary(
    client: AsyncClient, db, db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    obs_at = datetime(2026, 1, 6, tzinfo=UTC)
    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.350000"),
                rate_date=date(2026, 1, 5),
                source="test",
            ),
            StockPrice(
                symbol="IBM", price=Decimal("160.000000"), currency="USD", price_date=date(2026, 1, 5), source="test"
            ),
            MarketDataSyncState(
                kind="fx",
                scope="USD/SGD",
                last_success_at=obs_at,
                last_success_date=date(2026, 1, 5),
                last_observation_date=date(2026, 1, 5),
                created_at=obs_at,
                updated_at=obs_at,
            ),
            MarketDataSyncState(
                kind="stock",
                scope="IBM",
                last_success_at=obs_at,
                last_success_date=date(2026, 1, 5),
                last_observation_date=date(2026, 1, 5),
                created_at=obs_at,
                updated_at=obs_at,
            ),
        ]
    )
    await db.commit()
    status_resp = await client.get("/pricing/market-data/status", params=[("pairs", "USD/SGD"), ("symbols", "IBM")])

    from src.database import get_db
    from src.main import app
    from src.portfolio.orm.portfolio import ManagedPosition

    calls: list[tuple[list[str], list[str], date]] = []
    in_tx_during_fetch: list[bool] = []
    sessions: list[AsyncSession] = []
    fail_fetch = False

    async def fake_fetch(plan, *, max_concurrency: int = 4):
        assert sessions, "Expected request DB session to be captured"
        in_tx_during_fetch.append(sessions[-1].in_transaction())
        calls.append(
            (
                sorted(item.scope_name for item in plan.fx.items),
                sorted(item.scope_name for item in plan.stock.items),
                plan.fx.end_date,
            )
        )
        if fail_fetch:
            raise RuntimeError("provider unavailable")
        return market_data.FetchedFreshnessSync(
            fx=market_data.FetchedMarketSync(kind="fx", items=()),
            stock=market_data.FetchedMarketSync(kind="stock", items=()),
        )

    async def override_get_db():
        async for session in get_db():
            sessions.append(session)
            yield session

    monkeypatch.setattr(composition.settings, "market_data_lazy_fetch_enabled", True)
    monkeypatch.setattr(composition, "fetch_planned_freshness", fake_fetch)
    monkeypatch.setattr(
        reports_router,
        "generate_balance_sheet",
        lambda *_a, **_kw: _coro(
            {
                "as_of_date": date(2026, 1, 6),
                "currency": "SGD",
                "assets": [],
                "liabilities": [],
                "equity": [],
                "total_assets": Decimal("0.00"),
                "total_liabilities": Decimal("0.00"),
                "total_equity": Decimal("0.00"),
                "net_income": Decimal("0.00"),
                "unrealized_fx_gain_loss": Decimal("0.00"),
                "net_worth_adjustment_gain_loss": Decimal("0.00"),
                "fx_warnings": [],
                "equation_delta": Decimal("0.00"),
                "is_balanced": True,
            }
        ),
    )
    app.dependency_overrides[get_db] = override_get_db
    try:
        imp = await client.post(
            "/portfolio/brokerage-imports",
            json={
                "filename": "sync-check.json",
                "payload": {
                    "institution": "Sync Broker",
                    "statement": {"period_end": "2026-01-06", "currency": "USD"},
                    "positions": [{"symbol": "AAPL", "quantity": "1", "market_value": "100.00", "currency": "USD"}],
                },
            },
        )
        calls_after_import = list(calls)
        calls.clear()
        rep = await client.get("/reports/balance-sheet", params={"as_of_date": "2026-01-06"})
        calls_after_report = list(calls)
        fail_fetch = True
        imp_fail = await client.post(
            "/portfolio/brokerage-imports",
            json={
                "filename": "sync-fail.json",
                "payload": {
                    "institution": "Sync Broker Fail",
                    "statement": {"period_end": "2026-01-06", "currency": "USD"},
                    "positions": [{"symbol": "MSFT", "quantity": "2", "market_value": "200.00", "currency": "USD"}],
                },
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    async with async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)() as check_db:
        msft_pos = await check_db.scalar(select(ManagedPosition).where(ManagedPosition.asset_identifier == "MSFT"))

    e2e_src = (Path(__file__).resolve().parents[4] / "tests/e2e/test_market_data_price_paths.py").read_text()
    assert (
        (
            status_resp.status_code,
            {(i["kind"], i["scope"]) for i in status_resp.json()},
            all(i["last_success_date"] == "2026-01-05" for i in status_resp.json()),
        ),
        (
            imp.status_code,
            calls_after_import,
            in_tx_during_fetch,
            rep.status_code,
            calls_after_report,
            hasattr(reports_router, "_ensure_report_market_data_fresh"),
        ),
        (imp_fail.status_code, msft_pos is not None),
        (
            "@pytest.mark.e2e" in e2e_src,
            "@pytest.mark.tier3" in e2e_src,
            "@pytest.mark.critical" in e2e_src,
            "RUN_MARKET_DATA_PROVIDER_E2E" in e2e_src,
            "/pricing/market-data/status" in e2e_src,
            "/pricing/stocks/syncs" not in e2e_src,
            "/reports/balance-sheet" in e2e_src,
        ),
    ) == (
        (200, {("fx", "USD/SGD"), ("stock", "IBM")}, True),
        (200, [(["USD/SGD"], ["AAPL"], date(2026, 1, 6))], [False, False], 200, [], False),
        (200, True),
        (True, True, True, True, True, True, True),
    )


async def test_statement_brokerage_import_releases_tx_without_expired_statement_error(
    client: AsyncClient, db, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Statement brokerage import must not read expired ORM attrs after refresh_market_data rollback."""
    import hashlib
    from uuid import uuid4

    from src.audit import SqlTraceRecordRepository, TraceEmitter
    from src.database import get_db
    from src.extraction import (
        BankStatementStatus,
        DocumentType,
        ExtractedPositionFact,
        ExtractionMethod,
        SourceProvenance,
        StatementEvidenceType,
        StatementExtractionResult,
        StatementSourceType,
        UploadedDocument,
        persist_statement_extraction_result,
    )
    from src.extraction.extension.extraction_trace import (
        build_extraction_trace_records,
        extraction_trace_policy_registry,
    )
    from src.extraction.orm.statement_summary import StatementSummary
    from src.main import app

    doc_hash = hashlib.sha256(f"brk-sync-{uuid4().hex}".encode()).hexdigest()
    doc = UploadedDocument(
        id=uuid4(),
        user_id=test_user.id,
        file_hash=doc_hash,
        file_path=f"statements/{doc_hash}.pdf",
        original_filename="moomoo.pdf",
        document_type=DocumentType.BROKERAGE_STATEMENT,
    )
    stmt = StatementSummary(
        id=uuid4(),
        user_id=test_user.id,
        uploaded_document_id=doc.id,
        file_hash=doc_hash,
        institution="Moomoo",
        currency="USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 6),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.PARSED,
        confidence_score=90,
        balance_validated=True,
    )
    result = StatementExtractionResult.create(
        producer_version="test@1",
        source_content_digest=doc_hash,
        source_type=StatementSourceType.BROKERAGE,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        institution="Moomoo",
        account_last4="1234",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 6),
        balances=(),
        transactions=(),
        positions=(
            ExtractedPositionFact(
                fact_id="pos-nvda",
                symbol="NVDA",
                quantity=Decimal("3"),
                market_value=Decimal("300.00"),
                currency="USD",
                confidence=Decimal("0.95"),
                asset_type="stock",
            ),
        ),
        confidence=Decimal("0.95"),
        balance_validated=True,
        warnings=(),
        review_reasons=(),
        provenance=SourceProvenance(
            intake_mode="pdf",
            method=ExtractionMethod.GOLDEN_FIXTURE,
            provider="fixture-provider",
            model="fixture-model",
        ),
        statement_currency="USD",
    )
    stmt.extraction_metadata = {"statement_extraction_result": result.to_payload()}
    db.add_all([doc, stmt])
    await db.flush()
    traces = build_extraction_trace_records(
        result,
        user_id=test_user.id,
        execution_id=f"stmt-brk-{stmt.id}",
        occurred_at=datetime.now(UTC),
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(traces)
    await persist_statement_extraction_result(
        db, statement=stmt, result=result, source_trace_record_id=traces[0].record_id
    )
    await db.commit()

    sessions: list[AsyncSession] = []
    in_tx_during_fetch: list[bool] = []

    async def fake_fetch(plan, *, max_concurrency: int = 4):
        assert sessions, "Expected request DB session to be captured"
        in_tx_during_fetch.append(sessions[-1].in_transaction())
        return market_data.FetchedFreshnessSync(
            fx=market_data.FetchedMarketSync(kind="fx", items=()),
            stock=market_data.FetchedMarketSync(kind="stock", items=()),
        )

    async def override_get_db():
        async for session in get_db():
            sessions.append(session)
            yield session

    monkeypatch.setattr(composition.settings, "market_data_lazy_fetch_enabled", True)
    monkeypatch.setattr(composition, "fetch_planned_freshness", fake_fetch)
    app.dependency_overrides[get_db] = override_get_db
    try:
        resp = await client.post("/portfolio/brokerage-imports", json={"statement_id": str(stmt.id)})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["account_id"] is not None
    assert body["parsed_positions"] == 1
    assert in_tx_during_fetch == [False]
