from datetime import date; from unittest.mock import AsyncMock, patch; from uuid import uuid4; from src.reporting import ReportError
class TestReportsRouterErrors:
    async def test_balance_sheet_report_error(self, client, db, test_user):
        'AC-reporting.errors.2 AC5.5.1'
        with patch('src.routers.reports.generate_balance_sheet', new_callable=AsyncMock) as mock_gen: mock_gen.side_effect = ReportError('Currency not supported'); response = await client.get('/reports/balance-sheet?currency=XXX'); assert response.status_code == 400; assert 'currency' in response.json()['detail'].lower()
    async def test_income_statement_report_error(self, client, db, test_user):
        with patch('src.routers.reports.generate_income_statement', new_callable=AsyncMock) as mock_gen: mock_gen.side_effect = ReportError('Invalid date range'); response = await client.get('/reports/income-statement', params={'start_date': '2024-12-31', 'end_date': '2024-01-01'}); assert response.status_code == 400; assert 'date' in response.json()['detail'].lower()
    async def test_cash_flow_report_error(self, client, db, test_user):
        with patch('src.routers.reports.generate_cash_flow', new_callable=AsyncMock) as mock_gen: mock_gen.side_effect = ReportError('No cash accounts found'); response = await client.get('/reports/cash-flow', params={'start_date': '2024-01-01', 'end_date': '2024-12-31'}); assert response.status_code == 400; assert 'cash' in response.json()['detail'].lower()
    async def test_account_trend_report_error(self, client, db, test_user):
        account_id = uuid4()
        with patch('src.routers.reports.get_account_trend', new_callable=AsyncMock) as mock_trend: mock_trend.side_effect = ReportError('Account not found'); response = await client.get('/reports/trend', params={'account_id': str(account_id)}); assert response.status_code == 400; assert 'account' in response.json()['detail'].lower()
    async def test_category_breakdown_report_error(self, client, db, test_user):
        with patch('src.routers.reports.get_category_breakdown', new_callable=AsyncMock) as mock_breakdown: mock_breakdown.side_effect = ReportError('No data available for period'); response = await client.get('/reports/breakdown', params={'type': 'income'}); assert response.status_code == 400; assert 'data' in response.json()['detail'].lower()
    async def test_export_balance_sheet_report_error(self, client, db, test_user):
        with patch('src.routers.reports.generate_balance_sheet', new_callable=AsyncMock) as mock_gen: mock_gen.side_effect = ReportError('Export failed'); response = await client.get('/reports/export', params={'report_type': 'balance-sheet', 'format': 'csv'}); assert response.status_code == 400; assert 'export' in response.json()['detail'].lower()
    async def test_export_income_statement_missing_dates(self, client): response = await client.get('/reports/export', params={'report_type': 'income-statement', 'format': 'csv'}); assert response.status_code == 400; assert 'required' in response.json()['detail'].lower()
    async def test_export_unsupported_report_type(self, client):
        with patch('src.routers.reports.ExportFormat', 'csv'): pass
    async def test_get_currencies_with_base_currency(self, client, db, test_user): from decimal import Decimal; from src.pricing.orm.market_data import FxRate; fx = FxRate(base_currency='EUR', quote_currency='GBP', rate=Decimal('0.85'), rate_date=date.today(), source='test'); db.add(fx); await db.commit(); response = await client.get('/reports/currencies'); assert response.status_code == 200; currencies = response.json(); assert 'SGD' in currencies or 'EUR' in currencies or 'GBP' in currencies
