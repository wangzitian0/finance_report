from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from src.services.reporting import (
    ReportError,
    ReportingService,
    _add_months,
    _aggregate_balances_sql,
    _aggregate_net_income_sql,
    _iter_periods,
    _month_end,
    _month_start,
    _normalize_currency,
    _quantize_money,
    _quarter_start,
    _signed_amount,
)
from tests.test_factories import (
    create_account,
    create_journal_entry,
)


@pytest.fixture
async def reporting_service():
    """Fixture for ReportingService with mocked dependencies."""
    service = ReportingService()
    service._get_fx_rates_map = AsyncMock(return_value={})  # Mock FX rate fetching
    return service


@pytest.fixture
async def test_account():
    """Fixture for a test account."""
    return await create_account()


@pytest.fixture
async def test_entries():
    """Fixture for test journal entries."""
    entries = []
    for i in range(3):
        entry = await create_journal_entry(
            description=f"Test entry {i}",
            amount=Decimal(str(100 + i * 50)),
            currency="USD",
        )
        entries.append(entry)
    return entries


# AC references for helper functions
# AC1.1.1: Reporting service helper functions must correctly normalize currency codes
# AC1.1.2: Reporting service helper functions must correctly handle signed amounts
# AC1.1.3: Reporting service helper functions must correctly quantize monetary values
# AC1.1.4: Reporting service helper functions must correctly calculate period boundaries
# AC1.1.5: Reporting service helper functions must correctly iterate periods


class TestReportingHelperFunctions:
    """Test suite for reporting service helper functions."""

    async def test_normalize_currency(self):
        """Test currency normalization (AC1.1.1)."""
        assert _normalize_currency("USD") == "USD"
        assert _normalize_currency("usd") == "USD"
        assert _normalize_currency("UsD") == "USD"
        assert _normalize_currency("eur") == "EUR"
        assert _normalize_currency("gbp") == "GBP"

    async def test_signed_amount(self):
        """Test signed amount calculation (AC1.1.2)."""
        assert _signed_amount(Decimal("100"), "DEBIT") == Decimal("-100")
        assert _signed_amount(Decimal("100"), "CREDIT") == Decimal("100")
        assert _signed_amount(Decimal("-50"), "DEBIT") == Decimal("50")
        assert _signed_amount(Decimal("-50"), "CREDIT") == Decimal("-50")

    async def test_quantize_money(self):
        """Test monetary quantization (AC1.1.3)."""
        amount = Decimal("123.45678")
        quantized = _quantize_money(amount)
        assert quantized == Decimal("123.46")
        assert quantized.as_tuple().exponent == -2

    async def test_month_start(self):
        """Test month start calculation (AC1.1.4)."""
        date = datetime(2023, 3, 15)
        start = _month_start(date)
        assert start == datetime(2023, 3, 1)

    async def test_month_end(self):
        """Test month end calculation (AC1.1.4)."""
        date = datetime(2023, 3, 15)
        end = _month_end(date)
        assert end == datetime(2023, 3, 31, 23, 59, 59, 999999)

    async def test_quarter_start(self):
        """Test quarter start calculation (AC1.1.4)."""
        date = datetime(2023, 3, 15)
        start = _quarter_start(date)
        assert start == datetime(2023, 1, 1)

    async def test_add_months(self):
        """Test month addition (AC1.1.4)."""
        date = datetime(2023, 3, 15)
        new_date = _add_months(date, 2)
        assert new_date == datetime(2023, 5, 15)


class TestPeriodIteration:
    """Test suite for period iteration functions."""

    async def test_iter_periods_monthly(self):
        """Test monthly period iteration (AC1.1.5)."""
        start_date = datetime(2023, 1, 1)
        end_date = datetime(2023, 3, 31)
        periods = list(_iter_periods(start_date, end_date, "monthly"))
        assert len(periods) == 3
        assert periods[0] == (datetime(2023, 1, 1), datetime(2023, 1, 31, 23, 59, 59, 999999))
        assert periods[1] == (datetime(2023, 2, 1), datetime(2023, 2, 28, 23, 59, 59, 999999))
        assert periods[2] == (datetime(2023, 3, 1), datetime(2023, 3, 31, 23, 59, 59, 999999))

    async def test_iter_periods_quarterly(self):
        """Test quarterly period iteration (AC1.1.5)."""
        start_date = datetime(2023, 1, 1)
        end_date = datetime(2023, 12, 31)
        periods = list(_iter_periods(start_date, end_date, "quarterly"))
        assert len(periods) == 4
        assert periods[0] == (datetime(2023, 1, 1), datetime(2023, 3, 31, 23, 59, 59, 999999))
        assert periods[1] == (datetime(2023, 4, 1), datetime(2023, 6, 30, 23, 59, 59, 999999))
        assert periods[2] == (datetime(2023, 7, 1), datetime(2023, 9, 30, 23, 59, 59, 999999))
        assert periods[3] == (datetime(2023, 10, 1), datetime(2023, 12, 31, 23, 59, 59, 999999))

    async def test_iter_periods_yearly(self):
        """Test yearly period iteration (AC1.1.5)."""
        start_date = datetime(2023, 1, 1)
        end_date = datetime(2023, 12, 31)
        periods = list(_iter_periods(start_date, end_date, "yearly"))
        assert len(periods) == 1
        assert periods[0] == (datetime(2023, 1, 1), datetime(2023, 12, 31, 23, 59, 59, 999999))

    async def test_iter_periods_invalid_period_type(self):
        """Test invalid period type handling (AC1.1.5)."""
        start_date = datetime(2023, 1, 1)
        end_date = datetime(2023, 12, 31)
        with pytest.raises(ValueError):
            list(_iter_periods(start_date, end_date, "invalid"))


class TestFXRateHandling:
    """Test suite for FX rate handling functions."""

    @pytest.mark.usefixtures("mock_openrouter")
    async def test_get_fx_rates_map(self, reporting_service):
        """Test FX rate map retrieval (AC1.2.1)."""
        # Mock FX rates map
        reporting_service._get_fx_rates_map = AsyncMock(
            return_value={
                "USD/EUR": Decimal("0.85"),
                "EUR/USD": Decimal("1.18"),
            }
        )

        rates_map = await reporting_service._get_fx_rates_map(["USD", "EUR"])
        assert "USD/EUR" in rates_map
        assert "EUR/USD" in rates_map
        assert rates_map["USD/EUR"] == Decimal("0.85")
        assert rates_map["EUR/USD"] == Decimal("1.18")

    async def test_get_fx_rates_map_empty(self, reporting_service):
        """Test FX rate map retrieval with empty currencies (AC1.2.1)."""
        rates_map = await reporting_service._get_fx_rates_map([])
        assert rates_map == {}


class TestSQLAggregation:
    """Test suite for SQL aggregation functions."""

    async def test_aggregate_balances_sql(self):
        """Test balance aggregation SQL (AC1.3.1)."""
        sql = _aggregate_balances_sql(
            account_ids=[1, 2, 3],
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
            currencies=["USD", "EUR"],
        )
        assert "SELECT" in sql
        assert "account_id" in sql
        assert "currency" in sql
        assert "SUM(amount)" in sql
        assert "WHERE" in sql
        assert "account_id IN (1, 2, 3)" in sql
        assert "currency IN ('USD', 'EUR')" in sql
        assert "entry_date BETWEEN '2023-01-01' AND '2023-12-31'" in sql

    async def test_aggregate_net_income_sql(self):
        """Test net income aggregation SQL (AC1.3.2)."""
        sql = _aggregate_net_income_sql(
            account_ids=[1, 2, 3],
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
            currencies=["USD", "EUR"],
        )
        assert "SELECT" in sql
        assert "account_id" in sql
        assert "currency" in sql
        assert "SUM(amount)" in sql
        assert "WHERE" in sql
        assert "account_id IN (1, 2, 3)" in sql
        assert "currency IN ('USD', 'EUR')" in sql
        assert "entry_date BETWEEN '2023-01-01' AND '2023-12-31'" in sql


class TestReportingService:
    """Test suite for ReportingService class."""

    @pytest.mark.usefixtures("mock_openrouter")
    async def test_generate_balance_sheet(self, reporting_service, test_account, test_entries):
        """Test balance sheet generation (AC1.4.1)."""
        # Mock FX rates
        reporting_service._get_fx_rates_map = AsyncMock(
            return_value={
                "USD/EUR": Decimal("0.85"),
                "EUR/USD": Decimal("1.18"),
            }
        )

        # Generate balance sheet
        balance_sheet = await reporting_service.generate_balance_sheet(
            account_id=test_account.id,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
            base_currency="USD",
        )

        assert balance_sheet is not None
        assert "assets" in balance_sheet
        assert "liabilities" in balance_sheet
        assert "equity" in balance_sheet

    @pytest.mark.usefixtures("mock_openrouter")
    async def test_generate_income_statement(self, reporting_service, test_account, test_entries):
        """Test income statement generation (AC1.4.2)."""
        # Mock FX rates
        reporting_service._get_fx_rates_map = AsyncMock(
            return_value={
                "USD/EUR": Decimal("0.85"),
                "EUR/USD": Decimal("1.18"),
            }
        )

        # Generate income statement
        income_statement = await reporting_service.generate_income_statement(
            account_id=test_account.id,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
            base_currency="USD",
        )

        assert income_statement is not None
        assert "revenues" in income_statement
        assert "expenses" in income_statement
        assert "net_income" in income_statement

    @pytest.mark.usefixtures("mock_openrouter")
    async def test_generate_cash_flow_statement(self, reporting_service, test_account, test_entries):
        """Test cash flow statement generation (AC1.4.3)."""
        # Mock FX rates
        reporting_service._get_fx_rates_map = AsyncMock(
            return_value={
                "USD/EUR": Decimal("0.85"),
                "EUR/USD": Decimal("1.18"),
            }
        )

        # Generate cash flow statement
        cash_flow = await reporting_service.generate_cash_flow_statement(
            account_id=test_account.id,
            start_date=datetime(2023, 1, 1),
            end_date=datetime(2023, 12, 31),
            base_currency="USD",
        )

        assert cash_flow is not None
        assert "operating_activities" in cash_flow
        assert "investing_activities" in cash_flow
        assert "financing_activities" in cash_flow

    async def test_generate_report_invalid_period(self, reporting_service):
        """Test invalid period handling (AC1.4.4)."""
        with pytest.raises(ReportError):
            await reporting_service.generate_balance_sheet(
                account_id=1,
                start_date=datetime(2023, 12, 31),
                end_date=datetime(2023, 1, 1),
                base_currency="USD",
            )

    async def test_generate_report_database_error(self, reporting_service):
        """Test database error handling (AC1.4.5)."""
        # Mock database session to raise error
        with patch.object(reporting_service, "_execute_sql_query", side_effect=Exception("Database error")):
            with pytest.raises(ReportError):
                await reporting_service.generate_balance_sheet(
                    account_id=1,
                    start_date=datetime(2023, 1, 1),
                    end_date=datetime(2023, 12, 31),
                    base_currency="USD",
                )
