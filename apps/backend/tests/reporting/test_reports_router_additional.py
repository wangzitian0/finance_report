"""Additional coverage tests for reports router error paths."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.services.reporting import ReportError


@pytest.mark.asyncio
class TestReportsRouterAdditionalCoverage:
    """Test additional reports router paths for coverage."""

    async def test_income_statement_report_error(self, client, test_user):
        """
        GIVEN service raises ReportError
        WHEN generating income statement
        THEN it should return 400
        """
        with patch("src.routers.reports.generate_income_statement") as mock_report:
            mock_report.side_effect = ReportError("Test report error")

            response = await client.get(
                "/reports/income-statement", params={"start_date": "2024-01-01", "end_date": "2024-12-31"}
            )
            assert response.status_code == 400
            assert "Test report error" in response.json()["detail"]

    async def test_cash_flow_report_error(self, client, test_user):
        """
        GIVEN service raises ReportError
        WHEN generating cash flow statement
        THEN it should return 400
        """
        with patch("src.routers.reports.generate_cash_flow") as mock_report:
            mock_report.side_effect = ReportError("Cash flow error")

            response = await client.get(
                "/reports/cash-flow", params={"start_date": "2024-01-01", "end_date": "2024-12-31"}
            )
            assert response.status_code == 400

    async def test_trend_analysis_report_error(self, client, test_user):
        """
        GIVEN service raises ReportError
        WHEN generating trend analysis
        THEN it should return 400
        """
        with patch("src.routers.reports.get_account_trend") as mock_report:
            mock_report.side_effect = ReportError("Trend analysis error")

            response = await client.get("/reports/trend", params={"account_id": str(uuid4()), "period": "monthly"})
            assert response.status_code == 400

    async def test_breakdown_analysis_report_error(self, client, test_user):
        """
        GIVEN service raises ReportError
        WHEN generating breakdown analysis
        THEN it should return 400
        """
        with patch("src.routers.reports.get_category_breakdown") as mock_report:
            mock_report.side_effect = ReportError("Breakdown error")

            response = await client.get(
                "/reports/breakdown",
                params={"type": "income"},
            )
            assert response.status_code == 400

    async def test_export_excel_not_found(self, client, test_user):
        """
        GIVEN non-existent report ID
        WHEN exporting to Excel
        THEN it should return 404
        """
        fake_id = uuid4()
        response = await client.get(f"/reports/{fake_id}/export/excel")
        assert response.status_code == 404

    async def test_get_available_currencies_success(self, client, db, test_user):
        """
        GIVEN FX rates exist in database
        WHEN getting available currencies
        THEN it should return list including base currency
        """
        from src.models.market_data import FxRate

        fx_rate = FxRate(
            base_currency="USD",
            quote_currency="EUR",
            rate=Decimal("0.85"),
            rate_date=date(2024, 1, 1),
            source="test",
        )
        db.add(fx_rate)
        await db.commit()

        response = await client.get("/reports/currencies")
        assert response.status_code == 200
        currencies = response.json()
        assert isinstance(currencies, list)
        assert "SGD" in currencies or "USD" in currencies
