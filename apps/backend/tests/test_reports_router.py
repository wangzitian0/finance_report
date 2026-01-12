"""Integration tests for Reports Router."""

import pytest
from datetime import date
from uuid import uuid4
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)


@pytest.fixture
def test_data_setup_reports(db: AsyncSession, test_user):
    """Setup test data for reports."""

    async def _setup():
        asset = Account(
            user_id=test_user.id, name="Cash Test", type=AccountType.ASSET, currency="SGD"
        )
        income = Account(
            user_id=test_user.id, name="Salary Test", type=AccountType.INCOME, currency="SGD"
        )
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
    """Test balance sheet endpoint."""
    await test_data_setup_reports()

    response = await client.get("/api/reports/balance-sheet", params={"currency": "SGD"})
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
    response = await client.get("/api/reports/income-statement", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["total_income"] == "1000.00"


@pytest.mark.asyncio
async def test_cash_flow_endpoint(client, test_data_setup_reports):
    """Test cash flow endpoint returns valid response when data exists."""
    await test_data_setup_reports()

    today = date.today()
    params = {"start_date": today.isoformat(), "end_date": today.isoformat()}
    response = await client.get("/api/reports/cash-flow", params=params)
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
    response = await client.get("/api/reports/trend", params=params)
    assert response.status_code == 200
    data = response.json()
    assert len(data["points"]) > 0


@pytest.mark.asyncio
async def test_breakdown_endpoint(client, test_data_setup_reports):
    """Test breakdown endpoint."""
    _, income = await test_data_setup_reports()

    params = {"type": "income", "period": "monthly", "currency": "SGD"}
    response = await client.get("/api/reports/breakdown", params=params)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_export_endpoint(client, test_data_setup_reports):
    """Test export endpoint."""
    await test_data_setup_reports()

    params = {"report_type": "balance-sheet", "format": "csv", "currency": "SGD"}
    response = await client.get("/api/reports/export", params=params)
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
    response_is = await client.get("/api/reports/export", params=params_is)
    assert response_is.status_code == 200
    assert "text/csv" in response_is.headers["content-type"]
