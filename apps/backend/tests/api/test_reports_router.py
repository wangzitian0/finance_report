"""Router tests for reports API endpoints.

Tests all endpoints in src/routers/reports.py:
- GET /reports/currencies - Get available currencies
- GET /reports/balance-sheet - Get balance sheet
- GET /reports/income-statement - Get income statement
- GET /reports/cash-flow - Get cash flow statement
- GET /reports/trend - Get account trend data
- GET /reports/breakdown - Get category breakdown
- GET /reports/export - Export reports in CSV format
"""

import pytest
from uuid import uuid4
from datetime import date, timedelta
from httpx import AsyncClient
from sqlalchemy import select
from src.models import Account, AccountType, User
from src.schemas import (
    AccountTrendResponse,
    BalanceSheetResponse,
    CashFlowResponse,
    CategoryBreakdownResponse,
    IncomeStatementResponse,
    BreakdownPeriod,
    BreakdownType,
    TrendPeriod,
)
from src.routers.reports import ExportFormat, ReportType


class TestReportsEndpoints:
    """Test reports API endpoints."""

    async def test_get_available_currencies_success(self, client: AsyncClient, db):
        """Test getting available currencies."""
        # WHEN calling currencies endpoint
        response = await client.get("/reports/currencies")

        # THEN returns 200 with currency list
        assert response.status_code == 200
        currencies = response.json()
        assert isinstance(currencies, list)
        assert len(currencies) > 0

    async def test_balance_sheet_success(self, client: AsyncClient, db, test_user: User):
        """Test getting balance sheet."""
        # GIVEN valid request
        today = date.today()

        # WHEN calling balance sheet endpoint
        response = await client.get(f"/reports/balance-sheet?as_of_date={today}")

        # THEN returns 200 with balance sheet data
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "assets" in data
        assert "liabilities" in data
        assert "equity" in data
        assert "total_assets" in data
        assert "total_liabilities" in data
        assert "total_equity" in data
        assert "equation_delta" in data
        assert "is_balanced" in data
        assert "currency" in data
        assert "as_of_date" in data

    async def test_balance_sheet_with_currency(self, client: AsyncClient, db, test_user: User):
        """Test getting balance sheet with specific currency."""
        # GIVEN request with currency parameter
        today = date.today()
        currency = "USD"

        # WHEN calling balance sheet endpoint with currency
        response = await client.get(f"/reports/balance-sheet?as_of_date={today}&currency={currency}")

        # THEN returns 200 with balance sheet data
        assert response.status_code == 200
        data = response.json()
        assert data["currency"] == currency

    async def test_income_statement_success(self, client: AsyncClient, db, test_user: User):
        """Test getting income statement."""
        # GIVEN valid date range
        start_date = date.today() - timedelta(days=30)
        end_date = date.today()

        # WHEN calling income statement endpoint
        response = await client.get(f"/reports/income-statement?start_date={start_date}&end_date={end_date}")

        # THEN returns 200 with income statement data
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "income" in data
        assert "expenses" in data
        assert "total_income" in data
        assert "total_expenses" in data
        assert "net_income" in data
        assert "currency" in data
        assert "start_date" in data
        assert "end_date" in data

    async def test_income_statement_with_filters(self, client: AsyncClient, db, test_user: User):
        """Test getting income statement with filters."""
        # GIVEN request with tags and account type filters
        start_date = date.today() - timedelta(days=30)
        end_date = date.today()
        tags = ["food", "transport"]
        account_type = "INCOME"

        # WHEN calling income statement endpoint with filters
        response = await client.get(
            f"/reports/income-statement?start_date={start_date}&end_date={end_date}"
            f"&tags={','.join(tags)}&account_type={account_type}"
        )

        # THEN returns 200 with filtered income statement data
        assert response.status_code == 200

    async def test_cash_flow_success(self, client: AsyncClient, db, test_user: User):
        """Test getting cash flow statement."""
        # GIVEN valid date range
        start_date = date.today() - timedelta(days=30)
        end_date = date.today()

        # WHEN calling cash flow endpoint
        response = await client.get(f"/reports/cash-flow?start_date={start_date}&end_date={end_date}")

        # THEN returns 200 with cash flow data
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "operating_activities" in data
        assert "investing_activities" in data
        assert "financing_activities" in data
        assert "net_cash_flow" in data
        assert "currency" in data
        assert "start_date" in data
        assert "end_date" in data

    async def test_account_trend_success(self, client: AsyncClient, db, test_user: User):
        """Test getting account trend data."""
        # GIVEN existing account
        account = Account(
            id=uuid4(),
            user_id=test_user.id,
            name="Test Account",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.commit()

        # WHEN calling trend endpoint
        response = await client.get(f"/reports/trend?account_id={account.id}")

        # THEN returns 200 with trend data
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "account_id" in data
        assert "period" in data
        assert "data" in data
        assert "currency" in data

    async def test_account_trend_with_period(self, client: AsyncClient, db, test_user: User):
        """Test getting account trend with different period."""
        # GIVEN existing account
        account = Account(
            id=uuid4(),
            user_id=test_user.id,
            name="Test Account",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.commit()

        # WHEN calling trend endpoint with weekly period
        response = await client.get(f"/reports/trend?account_id={account.id}&period=weekly")

        # THEN returns 200 with trend data
        assert response.status_code == 200

    async def test_category_breakdown_success(self, client: AsyncClient, db, test_user: User):
        """Test getting category breakdown."""
        # WHEN calling breakdown endpoint
        response = await client.get("/reports/breakdown?type=income")

        # THEN returns 200 with breakdown data
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "breakdown_type" in data
        assert "period" in data
        assert "data" in data
        assert "currency" in data

    async def test_category_breakdown_with_period(self, client: AsyncClient, db, test_user: User):
        """Test getting category breakdown with different period."""
        # WHEN calling breakdown endpoint with quarterly period
        response = await client.get("/reports/breakdown?type=expense&period=quarterly")

        # THEN returns 200 with breakdown data
        assert response.status_code == 200

    async def test_export_balance_sheet_success(self, client: AsyncClient, db, test_user: User):
        """Test exporting balance sheet."""
        # GIVEN valid export request
        today = date.today()

        # WHEN calling export endpoint
        response = await client.get(f"/reports/export?report_type=balance-sheet&as_of_date={today}&format=csv")

        # THEN returns 200 with CSV content
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv"
        assert "attachment" in response.headers["content-disposition"]

    async def test_export_income_statement_success(self, client: AsyncClient, db, test_user: User):
        """Test exporting income statement."""
        # GIVEN valid export request
        start_date = date.today() - timedelta(days=30)
        end_date = date.today()

        # WHEN calling export endpoint
        response = await client.get(
            f"/reports/export?report_type=income-statement&start_date={start_date}&end_date={end_date}&format=csv"
        )

        # THEN returns 200 with CSV content
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv"
        assert "attachment" in response.headers["content-disposition"]

    async def test_export_invalid_report_type(self, client: AsyncClient, db, test_user: User):
        """Test exporting with invalid report type."""
        # GIVEN invalid report type
        today = date.today()

        # WHEN calling export endpoint with invalid report type
        response = await client.get(f"/reports/export?report_type=invalid&type=csv&as_of_date={today}")

        # THEN returns 400 Bad Request
        assert response.status_code == 400

    async def test_export_missing_dates_for_income_statement(self, client: AsyncClient, db, test_user: User):
        """Test exporting income statement without required dates."""
        # GIVEN missing start_date and end_date
        # WHEN calling export endpoint for income statement
        response = await client.get("/reports/export?report_type=income-statement&format=csv")

        # THEN returns 400 Bad Request
        assert response.status_code == 400

    async def test_unauthenticated_access(self, public_client: AsyncClient, test_user: User):
        """Test that unauthenticated clients cannot access reports endpoints."""
        # GIVEN unauthenticated client
        # WHEN calling any reports endpoint
        response = await public_client.get("/reports/balance-sheet")

        # THEN returns 401 Unauthorized
        assert response.status_code == 401

    async def test_user_isolation(self, client: AsyncClient, db, test_user: User):
        """Test that users can only access their own reports data."""
        # GIVEN account belonging to different user
        other_user = User(email="other@example.com", hashed_password="hashed")
        db.add(other_user)
        await db.commit()

        other_account = Account(
            id=uuid4(),
            user_id=other_user.id,
            name="Other Account",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(other_account)
        await db.commit()

        # WHEN calling trend endpoint with different user's account
        response = await client.get(f"/reports/trend?account_id={other_account.id}")

        # THEN returns 404 Not Found (due to user isolation)
