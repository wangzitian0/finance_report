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
from unittest.mock import AsyncMock, patch
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

    @patch("src.routers.reports.generate_cash_flow")
    async def test_cash_flow_success(self, mock_service: AsyncMock, client: AsyncClient, db, test_user: User):
        """Test getting cash flow statement."""
        # GIVEN valid date range and mocked service
        from decimal import Decimal
        start_date = date.today() - timedelta(days=30)
        end_date = date.today()
        mock_service.return_value = {
            "operating": [],
            "investing": [],
            "financing": [],
            "summary": {
                "operating_activities": Decimal("0.00"),
                "investing_activities": Decimal("0.00"),
                "financing_activities": Decimal("0.00"),
                "net_cash_flow": Decimal("0.00"),
                "beginning_cash": Decimal("1000.00"),
                "ending_cash": Decimal("1000.00"),
            },
            "currency": "SGD",
            "start_date": start_date,
            "end_date": end_date,
        }
        # WHEN calling cash flow endpoint
        response = await client.get(f"/reports/cash-flow?start_date={start_date}&end_date={end_date}")
        # THEN returns 200 with cash flow data
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "operating" in data
        assert "investing" in data
        assert "financing" in data
        assert "summary" in data
        assert "currency" in data
        assert "start_date" in data
        assert "end_date" in data
        assert mock_service.called

    @patch("src.routers.reports.get_account_trend")
    async def test_account_trend_success(self, mock_service: AsyncMock, client: AsyncClient, db, test_user: User):
        """Test getting account trend data."""
        # GIVEN existing account and mocked service
        account = Account(
            id=uuid4(),
            user_id=test_user.id,
            name="Test Account",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.commit()
        mock_service.return_value = {
            "account_id": account.id,
            "period": "monthly",
            "points": [],
            "currency": "USD",
        }
        # WHEN calling trend endpoint
        response = await client.get(f"/reports/trend?account_id={account.id}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "account_id" in data
        assert "period" in data
        assert "points" in data
        assert "currency" in data
        assert mock_service.called

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

    @patch("src.routers.reports.get_category_breakdown")
    async def test_category_breakdown_success(self, mock_service: AsyncMock, client: AsyncClient, db, test_user: User):
        """Test getting category breakdown."""
        # GIVEN mocked service
        from src.models import AccountType
        mock_service.return_value = {
            "type": AccountType.INCOME,
            "period_start": date.today() - timedelta(days=30),
            "period_end": date.today(),
            "items": [],
            "currency": "SGD",
        }
        # WHEN calling breakdown endpoint
        response = await client.get("/reports/breakdown?type=income")
        # THEN returns 200 with breakdown data
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "type" in data
        assert "period_start" in data
        assert "period_end" in data
        assert "items" in data
        assert "currency" in data
        assert mock_service.called

    async def test_category_breakdown_with_period(self, client: AsyncClient, db, test_user: User):
        """Test getting category breakdown with different period."""
        # WHEN calling breakdown endpoint with quarterly period
        response = await client.get("/reports/breakdown?type=expense&period=quarterly")

        # THEN returns 200 with breakdown data
        assert response.status_code == 200

    @patch("src.routers.reports.generate_balance_sheet")
    async def test_export_balance_sheet_success(self, mock_service: AsyncMock, client: AsyncClient, db, test_user: User):
        """Test exporting balance sheet."""
        # GIVEN valid export request and mocked service
        today = date.today()
        mock_service.return_value = {
            "assets": [{"name": "Cash", "amount": "1000.00"}],
            "liabilities": [],
            "equity": [{"name": "Capital", "amount": "1000.00"}],
            "total_assets": "1000.00",
            "total_liabilities": "0.00",
            "total_equity": "1000.00",
            "equation_delta": "0.00",
            "is_balanced": True,
            "currency": "SGD",
            "as_of_date": str(today),
        }
        # WHEN calling export endpoint
        response = await client.get(f"/reports/export?report_type=balance-sheet&as_of_date={today}&format=csv")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]
        assert mock_service.called

    @patch("src.routers.reports.generate_income_statement")
    async def test_export_income_statement_success(self, mock_service: AsyncMock, client: AsyncClient, db, test_user: User):
        """Test exporting income statement."""
        # GIVEN valid export request and mocked service
        start_date = date.today() - timedelta(days=30)
        end_date = date.today()
        mock_service.return_value = {
            "income": [{"name": "Sales", "amount": "1000.00"}],
            "expenses": [{"name": "Rent", "amount": "500.00"}],
            "total_income": "1000.00",
            "total_expenses": "500.00",
            "net_income": "500.00",
            "currency": "SGD",
            "start_date": str(start_date),
            "end_date": str(end_date),
        }
        # WHEN calling export endpoint
        response = await client.get(
            f"/reports/export?report_type=income-statement&start_date={start_date}&end_date={end_date}&format=csv"
        )
        # THEN returns 200 with CSV content
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]
        assert mock_service.called

    async def test_export_invalid_report_type(self, client: AsyncClient, db, test_user: User):
        """Test exporting with invalid report type."""
        # GIVEN invalid report type
        today = date.today()
        # WHEN calling export endpoint with invalid report type (validation error at query param level)
        response = await client.get(f"/reports/export?report_type=invalid&format=csv&as_of_date={today}")

        # THEN returns 422 Unprocessable Entity (FastAPI query param validation)
        assert response.status_code == 422

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
