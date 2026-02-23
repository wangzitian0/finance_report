"""Coverage boost tests for reports router — currencies endpoint and happy paths."""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)


@pytest_asyncio.fixture(scope="function")
async def reports_seed_data(db, test_user):
    """Seed accounts + posted journal entry for report generation."""
    asset = Account(user_id=test_user.id, name="Cash CB", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Salary CB", type=AccountType.INCOME, currency="SGD")
    expense = Account(user_id=test_user.id, name="Food CB", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([asset, income, expense])
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2024, 6, 15),
        memo="Coverage boost seed",
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
                amount=Decimal("500.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("500.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()
    return asset, income, expense


@pytest.mark.asyncio
class TestCurrenciesEndpoint:
    """Tests for GET /reports/currencies."""

    async def test_currencies_empty_database(self, client, test_user):
        """
        GIVEN no FX rate data
        WHEN GET /reports/currencies
        THEN base currency should still appear
        """
        response = await client.get("/reports/currencies")
        assert response.status_code == 200
        currencies = response.json()
        assert isinstance(currencies, list)
        assert "SGD" in currencies

    async def test_currencies_with_fx_data(self, client, db, test_user):
        """
        GIVEN FX rates for USD/EUR exist
        WHEN GET /reports/currencies
        THEN all currencies plus base should appear
        """
        from src.models.market_data import FxRate

        db.add_all(
            [
                FxRate(
                    base_currency="USD",
                    quote_currency="EUR",
                    rate=Decimal("0.92"),
                    rate_date=date(2024, 6, 1),
                    source="test",
                ),
                FxRate(
                    base_currency="SGD",
                    quote_currency="USD",
                    rate=Decimal("0.74"),
                    rate_date=date(2024, 6, 1),
                    source="test",
                ),
            ]
        )
        await db.commit()

        response = await client.get("/reports/currencies")
        assert response.status_code == 200
        currencies = response.json()
        assert "SGD" in currencies
        assert "USD" in currencies
        assert "EUR" in currencies

    async def test_currencies_without_base_currency_in_fx(self, client, db, test_user):
        """
        GIVEN FX rates that don't include the base currency (SGD)
        WHEN GET /reports/currencies
        THEN base currency should be prepended to the list
        """
        from src.models.market_data import FxRate

        db.add(
            FxRate(
                base_currency="EUR",
                quote_currency="GBP",
                rate=Decimal("0.86"),
                rate_date=date(2024, 6, 1),
                source="test",
            )
        )
        await db.commit()

        response = await client.get("/reports/currencies")
        assert response.status_code == 200
        currencies = response.json()
        assert currencies[0] == "SGD"
        assert "EUR" in currencies
        assert "GBP" in currencies


@pytest.mark.asyncio
class TestReportsHappyPaths:
    """Duplicate happy path tests to ensure coverage measurement across all shards."""

    async def test_balance_sheet_returns_report(self, client, reports_seed_data):
        """
        GIVEN posted journal entries exist
        WHEN GET /reports/balance-sheet
        THEN return 200 with BalanceSheetResponse
        """
        response = await client.get("/reports/balance-sheet", params={"currency": "SGD"})
        assert response.status_code == 200
        data = response.json()
        assert "total_assets" in data
        assert data["currency"] == "SGD"

    async def test_income_statement_returns_report(self, client, reports_seed_data):
        """
        GIVEN posted journal entries exist
        WHEN GET /reports/income-statement
        THEN return 200 with IncomeStatementResponse
        """
        params = {"start_date": "2024-01-01", "end_date": "2024-12-31", "currency": "SGD"}
        response = await client.get("/reports/income-statement", params=params)
        assert response.status_code == 200
        data = response.json()
        assert "total_income" in data

    async def test_cash_flow_returns_report(self, client, reports_seed_data):
        """
        GIVEN posted journal entries exist
        WHEN GET /reports/cash-flow
        THEN return 200 with CashFlowResponse
        """
        params = {"start_date": "2024-01-01", "end_date": "2024-12-31", "currency": "SGD"}
        response = await client.get("/reports/cash-flow", params=params)
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data

    async def test_trend_returns_report(self, client, reports_seed_data):
        """
        GIVEN posted journal entries exist
        WHEN GET /reports/trend
        THEN return 200 with AccountTrendResponse
        """
        asset, _, _ = reports_seed_data
        params = {"account_id": str(asset.id), "period": "monthly", "currency": "SGD"}
        response = await client.get("/reports/trend", params=params)
        assert response.status_code == 200

    async def test_breakdown_returns_report(self, client, reports_seed_data):
        """
        GIVEN posted journal entries exist
        WHEN GET /reports/breakdown
        THEN return 200 with CategoryBreakdownResponse
        """
        params = {"type": "income", "period": "monthly", "currency": "SGD"}
        response = await client.get("/reports/breakdown", params=params)
        assert response.status_code == 200

    async def test_export_balance_sheet_csv(self, client, reports_seed_data):
        """
        GIVEN posted journal entries exist
        WHEN GET /reports/export?report_type=balance-sheet
        THEN return CSV content
        """
        params = {"report_type": "balance-sheet", "format": "csv", "currency": "SGD"}
        response = await client.get("/reports/export", params=params)
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    async def test_export_income_statement_csv(self, client, reports_seed_data):
        """
        GIVEN posted journal entries exist
        WHEN GET /reports/export?report_type=income-statement
        THEN return CSV content
        """
        params = {
            "report_type": "income-statement",
            "format": "csv",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "currency": "SGD",
        }
        response = await client.get("/reports/export", params=params)
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
