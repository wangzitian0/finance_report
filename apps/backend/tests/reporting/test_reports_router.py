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
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.routers import reports as reports_router
from src.services.reporting import ReportError


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


@pytest.mark.asyncio
async def test_balance_sheet_endpoint(client, test_data_setup_reports):
    """[AC5.1.4] Test balance sheet endpoint."""
    await test_data_setup_reports()

    response = await client.get("/reports/balance-sheet", params={"currency": "SGD"})
    assert response.status_code == 200
    data = response.json()
    assert data["total_assets"] == "1000.00"
    assert data["currency"] == "SGD"


@pytest.mark.asyncio
async def test_income_statement_endpoint(client, test_data_setup_reports):
    """Test income statement endpoint."""
    await test_data_setup_reports()

    today = date.today()
    params = {"start_date": today.isoformat(), "end_date": today.isoformat(), "currency": "SGD"}
    response = await client.get("/reports/income-statement", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["total_income"] == "1000.00"


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_trending_endpoint(client, test_data_setup_reports):
    """Test trend endpoint."""
    asset, _ = await test_data_setup_reports()

    params = {"account_id": str(asset.id), "period": "monthly", "currency": "SGD"}
    response = await client.get("/reports/trend", params=params)
    assert response.status_code == 200
    data = response.json()
    assert len(data["points"]) > 0


@pytest.mark.asyncio
async def test_breakdown_endpoint(client, test_data_setup_reports):
    """Test breakdown endpoint."""
    _, income = await test_data_setup_reports()

    params = {"type": "income", "period": "monthly", "currency": "SGD"}
    response = await client.get("/reports/breakdown", params=params)
    assert response.status_code == 200


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
