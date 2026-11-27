from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction import BankStatementStatus, StatementSourceType, StatementSummary
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.ledger import AccountType
from src.pricing.orm.market_data import StockPrice
from src.reporting import ReportError
from src.routers import reports as reports_router
from src.schemas.streaming import ExportStreamEnvelope, ExportStreamMediaType
from tests.factories import seed_accounts_and_entry
from tests.reporting._report_fixtures import post_pair, seed_accounts, seed_fx_rates


@pytest.fixture
async def seeded_report_data(db: AsyncSession, test_user):
    res = await seed_accounts_and_entry(db, test_user.id, amount=Decimal("1000.00"), memo="Test Income")
    await db.commit()
    return res


@pytest.mark.parametrize(
    ("path", "extra_params", "expected_key", "expected_val"),
    [
        ("/reports/balance-sheet", {"currency": "SGD"}, "total_assets", "1000.00"),
        (
            "/reports/income-statement",
            {"start_date": date.today().isoformat(), "end_date": date.today().isoformat(), "currency": "SGD"},
            "total_income",
            "1000.00",
        ),
        (
            "/reports/cash-flow",
            {"start_date": date.today().isoformat(), "end_date": date.today().isoformat()},
            "summary",
            None,
        ),
    ],
)
async def test_core_report_endpoints(
    client, seeded_report_data, path: str, extra_params: dict, expected_key: str, expected_val: str | None
) -> None:
    resp = await client.get(path, params=extra_params)
    assert resp.status_code == 200 and expected_key in resp.json()
    if expected_val is not None:
        assert resp.json()[expected_key] == expected_val


async def test_AC5_16_1_balance_sheet_scope_and_export(client, monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[bool] = []
    fake = {
        "as_of_date": date(2026, 1, 31),
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
    monkeypatch.setattr(reports_router, "generate_balance_sheet", lambda *_a, **kw: _rec_bs(received, kw, fake))
    for path, params in (
        ("/reports/balance-sheet", {"as_of_date": "2026-01-31", "currency": "SGD"}),
        ("/reports/balance-sheet", {"as_of_date": "2026-01-31", "currency": "SGD", "include_restricted": "false"}),
        (
            "/reports/exports",
            {
                "report_type": "balance-sheet",
                "format": "csv",
                "as_of_date": "2026-01-31",
                "currency": "SGD",
                "include_restricted": "true",
            },
        ),
    ):
        assert (await client.get(path, params=params)).status_code == 200
    assert received == [True, False, True]


async def _rec_bs(received: list[bool], kw: dict, fake: dict) -> dict:
    received.append(kw["include_restricted"])
    return fake


async def test_AC5_16_2_and_AC5_17_1_cash_flow_warnings_and_csv(client, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 31),
        "currency": "SGD",
        "operating": [
            {
                "category": "operating",
                "subcategory": "Salary",
                "amount": Decimal("1000.00"),
                "description": "January salary",
            }
        ],
        "investing": [],
        "financing": [],
        "proof_state": "unproven",
        "proof_reasons": ["fx_rate_missing"],
        "summary": {
            "operating_activities": Decimal("1000.00"),
            "investing_activities": Decimal("0.00"),
            "financing_activities": Decimal("0.00"),
            "net_cash_flow": Decimal("1000.00"),
            "beginning_cash": Decimal("500.00"),
            "ending_cash": Decimal("1500.00"),
        },
        "fx_warnings": [
            {"type": "spot_rate_fallback", "from_currency": "USD", "to_currency": "SGD", "date": "2026-01-31"}
        ],
    }
    monkeypatch.setattr(reports_router, "generate_cash_flow", AsyncMock(return_value=payload))
    params = {"start_date": "2026-01-01", "end_date": "2026-01-31", "currency": "SGD"}
    resp = await client.get("/reports/cash-flow", params=params)
    assert resp.status_code == 200 and resp.json()["fx_warnings"] == payload["fx_warnings"]
    csv_resp = await client.get("/reports/exports", params={**params, "report_type": "cash-flow", "format": "csv"})
    assert (
        csv_resp.status_code == 200
        and "text/csv" in csv_resp.headers["content-type"]
        and "cash-flow-2026-01-01-to-2026-01-31.csv" in csv_resp.headers["content-disposition"]
    )
    assert (
        "Operating,Salary,1000.00,SGD,January salary" in csv_resp.text
        and "Net Cash Flow,,1000.00,SGD," in csv_resp.text
    )


async def test_net_worth_timeseries_endpoint_does_not_commit(
    client, db_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ts(db: AsyncSession, *_a, **_kw):
        db.add(
            StockPrice(
                symbol="REPORT", price=Decimal("42.000000"), currency="USD", price_date=date(2026, 1, 31), source="test"
            )
        )
        await db.flush()
        return {"currency": "SGD", "granularity": "daily", "points": []}

    monkeypatch.setattr(reports_router, "get_net_worth_timeseries", fake_ts)
    resp = await client.get(
        "/reports/net-worth/timeseries",
        params={"from": "2026-01-01", "to": "2026-01-31", "granularity": "daily", "currency": "SGD"},
    )
    assert resp.status_code == 200 and resp.json()["points"] == []
    async with async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)() as session:
        assert (
            await session.scalar(
                select(StockPrice).where(StockPrice.symbol == "REPORT", StockPrice.price_date == date(2026, 1, 31))
            )
            is None
        )


async def test_AC17_14_2_net_worth_allocation_endpoint_returns_contract(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "as_of_date": date(2026, 1, 31),
        "currency": "SGD",
        "include_restricted": True,
        "total_assets": Decimal("1500.00"),
        "total_liabilities": Decimal("500.00"),
        "net_worth": Decimal("1000.00"),
        "rows": [
            {
                "asset_class": "cash",
                "liquidity_class": "liquid",
                "source_currency": "SGD",
                "value": Decimal("1500.00"),
                "percentage_of_net_worth": Decimal("150.00"),
                "source_line_count": 1,
                "source_lines": [
                    {
                        "source_type": "ledger_account",
                        "source_id": None,
                        "label": "Main Bank",
                        "value": Decimal("1500.00"),
                    }
                ],
            },
            {
                "asset_class": "liability",
                "liquidity_class": "liability",
                "source_currency": "SGD",
                "value": Decimal("-500.00"),
                "percentage_of_net_worth": Decimal("-50.00"),
                "source_line_count": 1,
                "source_lines": [
                    {
                        "source_type": "ledger_account",
                        "source_id": None,
                        "label": "Credit Card",
                        "value": Decimal("-500.00"),
                    }
                ],
            },
        ],
    }
    monkeypatch.setattr(reports_router, "get_net_worth_allocation_schedule", AsyncMock(return_value=payload))
    resp = await client.get(
        "/reports/net-worth/allocation",
        params={"as_of_date": "2026-01-31", "currency": "SGD", "include_restricted": "true"},
    )
    assert resp.status_code == 200 and (
        resp.json()["net_worth"],
        resp.json()["rows"][0]["source_currency"],
        resp.json()["rows"][1]["value"],
    ) == ("1000.00", "SGD", "-500.00")


async def test_export_endpoint_envelope_and_csv_rows(client, seeded_report_data) -> None:
    resp_bs = await client.get(
        "/reports/exports", params={"report_type": "balance-sheet", "format": "csv", "currency": "SGD"}
    )
    assert resp_bs.status_code == 200 and "text/csv" in resp_bs.headers["content-type"]
    disp = resp_bs.headers["content-disposition"]
    assert (
        disp.startswith("attachment; filename=")
        and ExportStreamEnvelope(
            media_type=ExportStreamMediaType.CSV, filename=disp.split("filename=", 1)[1]
        ).to_headers()["Content-Disposition"]
        == disp
    )
    today = date.today().isoformat()
    assert (
        await client.get(
            "/reports/exports",
            params={
                "report_type": "income-statement",
                "format": "csv",
                "start_date": today,
                "end_date": today,
                "currency": "SGD",
            },
        )
    ).status_code == 200

    with patch(
        "src.routers.reports.generate_balance_sheet",
        new_callable=AsyncMock,
        return_value={
            "as_of_date": date(2026, 1, 31),
            "currency": "SGD",
            "assets": [{"name": "Cash", "amount": Decimal("100.00")}],
            "liabilities": [],
            "equity": [],
            "total_assets": Decimal("100.00"),
            "total_liabilities": Decimal("0.00"),
            "total_equity": Decimal("100.00"),
        },
    ):
        r1 = await client.get("/reports/exports", params={"report_type": "balance-sheet"})
        assert r1.status_code == 200 and "Cash,100.0" in r1.text and "Total Assets,,100.0" in r1.text
    with patch(
        "src.routers.reports.generate_income_statement",
        new_callable=AsyncMock,
        return_value={
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 1, 31),
            "currency": "SGD",
            "income": [{"name": "Sales", "amount": Decimal("200.00")}],
            "expenses": [],
            "total_income": Decimal("200.00"),
            "total_expenses": Decimal("0.00"),
            "net_income": Decimal("200.00"),
        },
    ):
        r2 = await client.get(
            "/reports/exports",
            params={"report_type": "income-statement", "start_date": "2026-01-01", "end_date": "2026-01-31"},
        )
        assert r2.status_code == 200 and "Sales,200.0" in r2.text and "Total Income,,200.0" in r2.text


@pytest.mark.parametrize(
    ("path", "attr", "params"),
    [
        ("/reports/balance-sheet", "generate_balance_sheet", {"currency": "SGD"}),
        (
            "/reports/income-statement",
            "generate_income_statement",
            {"start_date": date.today().isoformat(), "end_date": date.today().isoformat()},
        ),
        (
            "/reports/cash-flow",
            "generate_cash_flow",
            {"start_date": date.today().isoformat(), "end_date": date.today().isoformat()},
        ),
        ("/reports/exports", "generate_balance_sheet", {"report_type": "balance-sheet", "format": "csv"}),
    ],
)
async def test_reports_router_handles_report_error(
    client, monkeypatch: pytest.MonkeyPatch, path: str, attr: str, params: dict[str, str]
) -> None:
    monkeypatch.setattr(reports_router, attr, AsyncMock(side_effect=ReportError("boom")))
    resp = await client.get(path, params=params)
    assert resp.status_code == 400 and resp.json()["detail"] == "boom"


@pytest.mark.parametrize(
    ("params", "status_code", "detail"),
    [
        ({"report_type": "balance-sheet", "format": "json", "currency": "SGD"}, 422, None),
        ({"report_type": "unsupported", "format": "csv", "currency": "SGD"}, 422, None),
        (
            {"report_type": "income-statement", "format": "csv", "currency": "SGD"},
            400,
            "start_date and end_date are required",
        ),
        ({"report_type": "cash-flow", "format": "csv"}, 400, None),
    ],
)
async def test_export_report_validation_errors(client, params: dict, status_code: int, detail: str | None) -> None:
    resp = await client.get("/reports/exports", params=params)
    assert resp.status_code == status_code and (detail is None or detail in resp.json()["detail"])


async def test_get_currencies_requires_auth_and_uses_user_base_currency(
    client, public_client, db: AsyncSession, test_user
) -> None:
    assert (await public_client.get("/reports/currencies")).status_code == 401
    test_user.base_currency = "JPY"
    await db.commit()
    resp = await client.get("/reports/currencies")
    assert resp.status_code == 200
    assert resp.json()[0] == "JPY"


async def test_currencies_diagnostics_lineage_and_statement_custody_cash_flow(
    client, db: AsyncSession, test_user
) -> None:
    assert (await client.get("/reports/currencies")).json()[0] == "SGD"
    await seed_fx_rates(db, ("EUR", "GBP", "0.86", date(2024, 6, 1)), ("SGD", "USD", "0.74", date(2024, 6, 1)))
    assert {"SGD", "USD", "EUR", "GBP"} <= set((await client.get("/reports/currencies")).json())

    resp = await client.get("/reports/balance-sheet/diagnostics")
    assert resp.status_code == 200 and {"is_balanced", "equation_delta", "primary_category", "suggested_action"} <= set(
        resp.json()
    )
    with patch("src.routers.reports.run_balance_sheet_diagnostics", side_effect=ReportError("Diagnostics failure")):
        assert (await client.get("/reports/balance-sheet/diagnostics")).status_code == 400
    assert (await client.get(f"/reports/account-lineage?account_id={uuid4()}")).status_code == 404

    custody, income = await seed_accounts(
        db, test_user.id, ("DBS Multiplier", AccountType.ASSET), ("Bonus Income", AccountType.INCOME)
    )
    stmt = StatementSummary(
        user_id=test_user.id,
        file_hash=sha256(f"{test_user.id}:{custody.id}:2026-01".encode()).hexdigest(),
        institution="DBS",
        account_id=custody.id,
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("1500.00"),
        status=BankStatementStatus.APPROVED,
    )
    db.add(stmt)
    await db.flush()
    rec = StatementExtractionResultRecord(
        user_id=test_user.id,
        statement_id=stmt.id,
        content_digest=sha256(f"res:{stmt.id}".encode()).hexdigest(),
        source_content_digest=sha256(f"src:{stmt.id}".encode()).hexdigest(),
        schema_version="2",
        producer_version="test-2765",
        payload={"source_type": StatementSourceType.BANK.value, "period_start": "2026-01-01"},
        source_trace_record_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    db.add(rec)
    await db.flush()
    stmt.current_extraction_result_id = rec.id
    await post_pair(db, test_user.id, date(2026, 1, 15), "Multiplier Bonus", custody, income, "1500.00", commit=True)

    lin = await client.get(f"/reports/account-lineage?account_id={custody.id}&currency=SGD")
    assert lin.status_code == 200 and lin.json()["account_id"] == str(custody.id)
    params = {"start_date": "2026-01-01", "end_date": "2026-01-31", "currency": "SGD"}
    preview = (await client.get("/reports/cash-flow", params=params)).json()
    assert (
        preview["summary"]["operating_activities"],
        preview["summary"]["net_cash_flow"],
        preview["summary"]["ending_cash"],
    ) == ("1500.00", "1500.00", "1500.00")
    assert "cash_identity_compatibility_fallback" not in preview["proof_reasons"] and len(preview["operating"]) == 1
    events_page = (
        await client.get(
            "/reports/cash-flow/line-events", params={**params, "line_id": preview["operating"][0]["line_id"]}
        )
    ).json()
    assert (events_page["total"], events_page["events"][0]["memo"], events_page["events"][0]["amount"]) == (
        1,
        "Multiplier Bonus",
        "1500.00",
    )
    export_resp = await client.get("/reports/exports", params={**params, "report_type": "cash-flow", "format": "csv"})
    assert (
        export_resp.status_code == 200
        and "Operating,Bonus Income,1500.00,SGD,Inflow - Bonus Income" in export_resp.text
    )


async def test_credit_card_only_user_cash_flow_keeps_empty_custody_set(client, db: AsyncSession, test_user) -> None:
    """Liability-only approved statement yields empty cash custody set rather than None fallback."""
    card, dining = await seed_accounts(
        db, test_user.id, ("Liberty Card", AccountType.LIABILITY), ("Dining Expense", AccountType.EXPENSE)
    )
    stmt = StatementSummary(
        user_id=test_user.id,
        file_hash=sha256(f"{test_user.id}:{card.id}:2026-02".encode()).hexdigest(),
        institution="Liberty Card",
        account_id=card.id,
        currency="SGD",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("-200.00"),
        status=BankStatementStatus.APPROVED,
    )
    db.add(stmt)
    await db.flush()
    rec = StatementExtractionResultRecord(
        user_id=test_user.id,
        statement_id=stmt.id,
        content_digest=sha256(f"cc-res:{stmt.id}".encode()).hexdigest(),
        source_content_digest=sha256(f"cc-src:{stmt.id}".encode()).hexdigest(),
        schema_version="2",
        producer_version="test-3253",
        payload={"source_type": StatementSourceType.BANK.value, "period_start": "2026-02-01"},
        source_trace_record_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    db.add(rec)
    await db.flush()
    stmt.current_extraction_result_id = rec.id
    await post_pair(db, test_user.id, date(2026, 2, 10), "Dining charge", dining, card, "200.00", commit=False)
    manual_bank, salary = await seed_accounts(
        db, test_user.id, ("Unbound Cash", AccountType.ASSET), ("Side Income", AccountType.INCOME)
    )
    await post_pair(
        db, test_user.id, date(2026, 2, 12), "Manual cash entry", manual_bank, salary, "500.00", commit=True
    )

    resp = await client.get(
        "/reports/cash-flow",
        params={"start_date": "2026-02-01", "end_date": "2026-02-28", "currency": "SGD"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["summary"]["ending_cash"] == "0.00"
    assert payload["summary"]["net_cash_flow"] == "0.00"
