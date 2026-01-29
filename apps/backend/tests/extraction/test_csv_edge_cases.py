"""Tests for CSV parsing edge cases - malformed rows, duplicates, and format issues."""

import pytest
from unittest.mock import AsyncMock
from src.services.extraction import ExtractionError, ExtractionService


class TestCSVMalformedRowHandling:
    """Test CSV parser handles malformed rows and duplicate data."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    @pytest.mark.asyncio
    async def test_csv_skips_row_with_invalid_characters(self, service):
        """Test parser skips rows with non-UTF8 characters."""
        csv_content = b"""Date,Description,Amount
2025-01-01,Coffee at\xc3\xa9,10.00
2025-01-02,Salary,1000.00
"""
        with pytest.raises(ExtractionError, match="encoding"):
            await service._parse_csv_content(csv_content, "GENERIC")

    @pytest.mark.asyncio
    async def test_csv_skips_row_with_duplicate_dates(self, service):
        """Test parser skips transactions with duplicate dates."""
        csv_content = """Date,Description,Amount
2025-01-01,Coffee,10.00
2025-01-01,Lunch,5.00
"""
        result = await service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 1

    @pytest.mark.asyncio
    async def test_csv_handles_negative_amounts_in_description(self, service):
        """Test CSV with negative amounts in description field."""
        csv_content = """Date,Description,Amount
2025-01-01,"-5.00 refund",10.00
2025-01-02,"Payment",20.00
"""
        result = await service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 2

    @pytest.mark.asyncio
    async def test_csv_with_mixed_delimiters(self, service):
        """Test CSV with inconsistent delimiters (comma, semicolon)."""
        csv_content = b"""Date;Description;Amount
2025-01-01;Coffee;10.00
2025-01-02;Salary;1000.00
"""
        with pytest.raises(ExtractionError, match="encoding"):
            await service._parse_csv_content(csv_content, "GENERIC")


class TestCSVParsingWithAI:
    """Test CSV parsing with AI assistance scenarios."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    @pytest.mark.asyncio
    async def test_csv_with_missing_account_last4(self, service):
        """Test CSV extraction when account_last4 is missing."""
        csv_content = """Date,Description,Amount
2025-01-01,Coffee,10.00
2025-01-02,Salary,1000.00
"""
        service.extract_financial_data = AsyncMock(
            return_value={
                "institution": "DBS",
                "currency": "SGD",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "opening_balance": "1010.00",
                "closing_balance": "2010.00",
                "transactions": [
                    {"date": "2025-01-01", "amount": "10.00", "direction": "IN", "description": "Coffee"},
                    {"date": "2025-01-02", "amount": "1000.00", "direction": "IN", "description": "Salary"},
                ],
            }
        )

        stmt, txns = await service.parse_document(
            Path("test.csv"),
            "DBS",
            user_id=pytest.lazy_fixture(lambda: str(uuid4())),
            file_content=csv_content,
        )

        assert stmt.account_last4 == "Unknown"

    @pytest.mark.asyncio
    async def test_csv_with_zero_balance_range(self, service):
        """Test CSV extraction with zero opening and closing balances."""
        csv_content = """Date,Description,Amount
2025-01-01,Coffee,10.00
2025-01-02,Salary,-10.00
"""
        service.extract_financial_data = AsyncMock(
            return_value={
                "institution": "DBS",
                "currency": "SGD",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "opening_balance": "0.00",
                "closing_balance": "0.00",
                "transactions": [
                    {"date": "2025-01-01", "amount": "10.00", "direction": "IN", "description": "Coffee"},
                ],
            }
        )

        stmt, txns = await service.parse_document(
            Path("test.csv"),
            "DBS",
            user_id=pytest.lazy_fixture(lambda: str(uuid4())),
            file_content=csv_content,
        )

        assert stmt.status.name == "REJECTED"
        assert "zero" in stmt.validation_error.lower() or "balance" in stmt.validation_error.lower()
