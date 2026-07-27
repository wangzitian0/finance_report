"""AC5.5.1 - AC5.5.4: Reports Router Tests

These tests validate report generation endpoints including balance sheet,
income statement, cash flow, trend analysis, breakdown, and export functionality.
Tests cover various report types (CSV, PDF, JSON), format validation,
date parameter handling, and error scenarios for invalid requests.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.pricing.orm.market_data import StockPrice
from src.reporting import ReportError
from src.routers import reports as reports_router


@pytest.fixture
def test_data_setup_reports(db: AsyncSession, test_user):
    """Setup test data for reports."""

    async def _setup():
        asset = Account(user_id=test_user.id, name="Cash Test", type=AccountType.ASSET, currency="SGD")
        income = Account(user_id=test_user.id, name="Salary Test", type=AccountType.INCOME, currency="SGD")
        db.add_all([asset, income])
        await db.commit()
        await db.refresh(asset)
        await db.refresh(income)

        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Test Income",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        db.add_all(
            [
                JournalLine(
                    journal_entry_id=entry.id,
                    account_id=asset.id,
                    direction=Direction.DEBIT,
                    amount=Decimal("1000.00"),
                    currency="SGD",
                ),
                JournalLine(
                    journal_entry_id=entry.id,
                    account_id=income.id,
                    direction=Direction.CREDIT,
                    amount=Decimal("1000.00"),
                    currency="SGD",
                ),
            ]
        )
        await db.commit()
        return asset, income

    return _setup


async def test_balance_sheet_endpoint(client, test_data_setup_reports):
    """AC-reporting.balance-sheet.4: [AC5.1.4] Test balance sheet endpoint."""
    await test_data_setup_reports()

    response = await client.get("/reports/balance-sheet", params={"currency": "SGD"})
    assert response.status_code == 200
    data = response.json()
    assert data["total_assets"] == "1000.00"
    assert data["currency"] == "SGD"


async def test_AC5_16_1_balance_sheet_defaults_to_excluding_restricted_holdings(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-reporting.trust-signals.1: AC5.16.1: Balance sheet endpoint defaults restricted holdings to excluded."""

    async def fake_generate_balance_sheet(*_args, **kwargs):
        assert kwargs["include_restricted"] is False
        return {
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

    monkeypatch.setattr(reports_router, "generate_balance_sheet", fake_generate_balance_sheet)

    response = await client.get("/reports/balance-sheet", params={"as_of_date": "2026-01-31", "currency": "SGD"})

    assert response.status_code == 200


async def test_income_statement_endpoint(client, test_data_setup_reports):
    """AC-reporting.errors.4: Test income statement endpoint."""
    await test_data_setup_reports()

    today = date.today()
    params = {"start_date": today.isoformat(), "end_date": today.isoformat(), "currency": "SGD"}
    response = await client.get("/reports/income-statement", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["total_income"] == "1000.00"


async def test_cash_flow_endpoint(client, test_data_setup_reports):
    """Test cash flow endpoint returns valid response when data exists."""
    await test_data_setup_reports()

    today = date.today()
    params = {"start_date": today.isoformat(), "end_date": today.isoformat()}
    response = await client.get("/reports/cash-flow", params=params)
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "operating" in data
    assert "investing" in data
    assert "financing" in data


async def test_AC5_16_2_cash_flow_response_preserves_fx_warnings(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-reporting.trust-signals.2: AC5.16.2: Cash flow response model exposes partial FX warnings."""

    async def fake_generate_cash_flow(*_args, **_kwargs):
        return {
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 1, 31),
            "currency": "SGD",
            "operating": [],
            "investing": [],
            "financing": [],
            "proof_state": "unproven",
            "proof_reasons": ["fx_rate_missing"],
            "summary": {
                "operating_activities": Decimal("0.00"),
                "investing_activities": Decimal("0.00"),
                "financing_activities": Decimal("0.00"),
                "net_cash_flow": Decimal("0.00"),
                "beginning_cash": Decimal("0.00"),
                "ending_cash": Decimal("0.00"),
            },
            "fx_warnings": [
                {
                    "type": "spot_rate_fallback",
                    "from_currency": "USD",
                    "to_currency": "SGD",
                    "date": "2026-01-31",
                }
            ],
        }

    monkeypatch.setattr(reports_router, "generate_cash_flow", fake_generate_cash_flow)

    response = await client.get(
        "/reports/cash-flow",
        params={"start_date": "2026-01-01", "end_date": "2026-01-31", "currency": "SGD"},
    )

    assert response.status_code == 200
    assert response.json()["fx_warnings"] == [
        {
            "type": "spot_rate_fallback",
            "from_currency": "USD",
            "to_currency": "SGD",
            "date": "2026-01-31",
        }
    ]


async def test_trending_endpoint(client, test_data_setup_reports):
    """Test trend endpoint."""
    asset, _ = await test_data_setup_reports()

    params = {"account_id": str(asset.id), "period": "monthly", "currency": "SGD"}
    response = await client.get("/reports/trend", params=params)
    assert response.status_code == 200
    data = response.json()
    assert len(data["points"]) > 0


async def test_net_worth_timeseries_endpoint_commits_boundary(
    client,
    db_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC12.26.2: Report endpoints commit flushed market-data writes at the router boundary."""

    async def fake_timeseries(db: AsyncSession, *_args, **_kwargs):
        db.add(
            StockPrice(
                symbol="REPORT",
                price=Decimal("42.000000"),
                currency="USD",
                price_date=date(2026, 1, 31),
                source="test",
            )
        )
        await db.flush()
        return {
            "currency": "SGD",
            "granularity": "daily",
            "points": [],
        }

    monkeypatch.setattr(reports_router, "get_net_worth_timeseries", fake_timeseries)

    response = await client.get(
        "/reports/net-worth/timeseries",
        params={"from": "2026-01-01", "to": "2026-01-31", "granularity": "daily", "currency": "SGD"},
    )

    assert response.status_code == 200
    assert response.json()["points"] == []
    sessionmaker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with sessionmaker() as session:
        persisted = await session.scalar(
            select(StockPrice).where(StockPrice.symbol == "REPORT").where(StockPrice.price_date == date(2026, 1, 31))
        )
    assert persisted is not None


async def test_AC17_14_2_net_worth_allocation_endpoint_returns_contract(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC17.14.2: Net-worth allocation endpoint returns the signed allocation contract."""

    async def fake_allocation_schedule(*_args, **kwargs):
        assert kwargs["as_of_date"] == date(2026, 1, 31)
        assert kwargs["currency"] == "SGD"
        assert kwargs["include_restricted"] is True
        return {
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
                            "href": "/reports/account-lineage",
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
                            "href": "/reports/account-lineage",
                        }
                    ],
                },
            ],
        }

    monkeypatch.setattr(reports_router, "get_net_worth_allocation_schedule", fake_allocation_schedule)

    response = await client.get(
        "/reports/net-worth/allocation",
        params={"as_of_date": "2026-01-31", "currency": "SGD", "include_restricted": "true"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["net_worth"] == "1000.00"
    assert data["rows"][0]["source_currency"] == "SGD"
    assert data["rows"][1]["value"] == "-500.00"


async def test_breakdown_endpoint(client, test_data_setup_reports):
    """Test breakdown endpoint."""
    _, income = await test_data_setup_reports()

    params = {"type": "income", "period": "monthly", "currency": "SGD"}
    response = await client.get("/reports/breakdown", params=params)
    assert response.status_code == 200


async def test_export_endpoint(client, test_data_setup_reports):
    """Test export endpoint."""
    await test_data_setup_reports()

    params = {"report_type": "balance-sheet", "format": "csv", "currency": "SGD"}
    response = await client.get("/reports/export", params=params)
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]

    today = date.today()
    params_is = {
        "report_type": "income-statement",
        "format": "csv",
        "start_date": today.isoformat(),
        "end_date": today.isoformat(),
        "currency": "SGD",
    }
    response_is = await client.get("/reports/export", params=params_is)
    assert response_is.status_code == 200
    assert "text/csv" in response_is.headers["content-type"]


async def test_AC6_33_8_export_response_matches_typed_envelope(client, test_data_setup_reports):
    """AC-reporting.export-envelope.3: AC6.33.8: /reports/export emits the media type + attachment header declared by the typed envelope."""
    from src.schemas.streaming import ExportStreamEnvelope, ExportStreamMediaType

    await test_data_setup_reports()

    params = {"report_type": "balance-sheet", "format": "csv", "currency": "SGD"}
    response = await client.get("/reports/export", params=params)

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment; filename=")
    filename = disposition.split("filename=", 1)[1]
    # The wire header must equal what the typed envelope would produce.
    envelope = ExportStreamEnvelope(media_type=ExportStreamMediaType.CSV, filename=filename)
    assert envelope.to_headers()["Content-Disposition"] == disposition


async def test_AC5_16_1_balance_sheet_export_honors_restricted_query(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5.16.1: Balance-sheet CSV export uses the same restricted toggle as the page."""

    async def fake_generate_balance_sheet(*_args, **kwargs):
        assert kwargs["include_restricted"] is True
        return {
            "as_of_date": date(2026, 1, 31),
            "currency": "SGD",
            "assets": [],
            "liabilities": [],
            "equity": [],
            "total_assets": Decimal("0.00"),
            "total_liabilities": Decimal("0.00"),
            "total_equity": Decimal("0.00"),
            "equation_delta": Decimal("0.00"),
            "is_balanced": True,
        }

    monkeypatch.setattr(reports_router, "generate_balance_sheet", fake_generate_balance_sheet)

    response = await client.get(
        "/reports/export",
        params={
            "report_type": "balance-sheet",
            "format": "csv",
            "as_of_date": "2026-01-31",
            "currency": "SGD",
            "include_restricted": "true",
        },
    )

    assert response.status_code == 200


async def test_AC5_17_1_cash_flow_export_returns_csv(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-reporting.csv-export.1: AC5.17.1: Cash-flow report export is a first-class CSV export type."""

    async def fake_generate_cash_flow(*_args, **kwargs):
        assert kwargs["start_date"] == date(2026, 1, 1)
        assert kwargs["end_date"] == date(2026, 1, 31)
        assert kwargs["currency"] == "SGD"
        return {
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
            "summary": {
                "operating_activities": Decimal("1000.00"),
                "investing_activities": Decimal("0.00"),
                "financing_activities": Decimal("0.00"),
                "net_cash_flow": Decimal("1000.00"),
                "beginning_cash": Decimal("500.00"),
                "ending_cash": Decimal("1500.00"),
            },
            "fx_warnings": [],
        }

    monkeypatch.setattr(reports_router, "generate_cash_flow", fake_generate_cash_flow)

    response = await client.get(
        "/reports/export",
        params={
            "report_type": "cash-flow",
            "format": "csv",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "currency": "SGD",
        },
    )

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "cash-flow-2026-01-01-to-2026-01-31.csv" in response.headers["content-disposition"]
    assert "Operating,Salary,1000.00,SGD,January salary" in response.text
    assert "Net Cash Flow,,1000.00,SGD," in response.text


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
        (
            "/reports/trend",
            "get_account_trend",
            {"account_id": str(uuid4()), "period": "monthly"},
        ),
        ("/reports/breakdown", "get_category_breakdown", {"type": "income"}),
    ],
)
async def test_reports_router_handles_report_error(
    client, monkeypatch: pytest.MonkeyPatch, path: str, attr: str, params: dict[str, str]
) -> None:
    async def raise_error(*_args, **_kwargs):
        raise ReportError("boom")

    monkeypatch.setattr(reports_router, attr, raise_error)

    response = await client.get(path, params=params)

    assert response.status_code == 400
    assert response.json()["detail"] == "boom"


async def test_export_report_invalid_format(client, test_data_setup_reports) -> None:
    """Test export with invalid format."""
    await test_data_setup_reports()
    params = {
        "report_type": "balance-sheet",
        "format": "json",
        "currency": "SGD",
    }
    response = await client.get("/reports/export", params=params)
    assert response.status_code == 422


async def test_export_report_missing_income_dates(client, test_data_setup_reports) -> None:
    """Test export income statement without dates."""
    await test_data_setup_reports()
    params = {
        "report_type": "income-statement",
        "format": "csv",
        "currency": "SGD",
    }
    response = await client.get("/reports/export", params=params)
    assert response.status_code == 400
    assert "start_date and end_date are required" in response.json()["detail"]


async def test_export_report_unsupported_type(client, test_data_setup_reports) -> None:
    """Test export with unsupported report type."""
    await test_data_setup_reports()
    params = {
        "report_type": "unsupported",
        "format": "csv",
        "currency": "SGD",
    }
    # FastAPI validation will likely catch this before the endpoint if using Enum
    # But if we force it (e.g. by not using the Enum in the client call which sends strings),
    # it depends on how FastAPI validates Query params against Enum.
    # If we send a string not in the Enum, FastAPI returns 422 Validation Error.
    # To hit the "else" block in the code, we need to pass a value that IS a valid ReportType
    # but not handled in the if/elif chain.
    # Currently ReportType has BALANCE_SHEET and INCOME_STATEMENT.
    # If we add a new type to Enum but forget to handle it, this test would catch it.
    # Since we can't easily pass an "invalid" enum member that validates,
    # we can only test this if we mock the ReportType enum or if there are other types.
    # Looking at ReportType definition in reports.py:
    # class ReportType(str, Enum): BALANCE_SHEET, INCOME_STATEMENT
    # So it's impossible to pass a valid ReportType that falls through the if/elif chain
    # unless we modify the Enum.

    # However, let's keep the client call and expect 422 if it's invalid value.
    response = await client.get("/reports/export", params=params)
    assert response.status_code == 422
