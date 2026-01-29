"""Tests for institutional CSV parsing logic in extraction.py."""

import pytest

from src.services.extraction import ExtractionService


class TestCSVHeaderParsing:
    """Test CSV header detection and parsing for various institutions."""

    @pytest.mark.asyncio
    async def test_uob_headers_detected(self):
        """Test UOB CSV headers are correctly identified."""
        csv_content = """Date,Description,Debit,Credit,Balance
2025-01-01,Coffee Shop,5.00,,995.00
2025-01-05,Salary,5000.00,,5995.00
"""
        service = ExtractionService()
        result = await service._parse_csv_content(csv_content, "UOB")
        assert result["account_last4"] == "1234"
        assert result["transactions"][0]["description"] == "Coffee Shop"
        assert len(result["transactions"]) == 2

    @pytest.mark.asyncio
    async def test_scb_headers_detected(self):
        """Test SCB (Standard Chartered) CSV headers are correctly identified."""
        csv_content = """Transaction Date,Description,Withdrawals,Deposits,Balance
2025-01-01,ATM Withdrawal,50.00,,1000.00
2025-01-02,Credit Interest,5.00,,995.00
"""
        service = ExtractionService()
        result = await service._parse_csv_content(csv_content, "SCB")
        assert result["account_last4"] == "5678"
        assert len(result["transactions"]) == 2

    @pytest.mark.asyncio
    async def test_citibank_headers_detected(self):
        """Test Citibank CSV headers are correctly identified."""
        csv_content = """Date,Details,Debit,Credit,Running Balance
2025-01-01,Restaurant Payment,25.50,,975.00
2025-01-02,Transfer Out,50.00,,1000.00
"""
        service = ExtractionService()
        result = await service._parse_csv_content(csv_content, "CITIBANK")
        assert result["account_last4"] == "7890"
        assert len(result["transactions"]) == 2

    @pytest.mark.asyncio
    async def test_uob_handles_missing_columns(self):
        """Test UOB parser handles missing date column gracefully."""
        csv_content = """Description,Debit,Credit,Balance
Coffee Shop,5.00,,995.00
"""
        service = ExtractionService()
        result = await service._parse_csv_content(csv_content, "UOB")
        assert len(result["transactions"]) == 0

    @pytest.mark.asyncio
    async def test_scb_handles_missing_columns(self):
        """Test SCB parser handles missing date column gracefully."""
        csv_content = """Description,Withdrawals,Deposits,Balance
Coffee Shop,5.00,,995.00
"""
        service = ExtractionService()
        result = await service._parse_csv_content(csv_content, "SCB")
        assert len(result["transactions"]) == 0

    @pytest.mark.asyncio
    async def test_citibank_handles_missing_columns(self):
        """Test Citibank parser handles missing date column gracefully."""
        csv_content = """Details,Debit,Credit,Running Balance
Restaurant Payment,25.50,,975.00
"""
        service = ExtractionService()
        result = await service._parse_csv_content(csv_content, "CITIBANK")
        assert len(result["transactions"]) == 0

    @pytest.mark.asyncio
    async def test_uob_amount_parsing(self):
        """Test UOB correctly parses debit/credit columns."""
        csv_content = """Date,Description,Debit,Credit,Balance
2025-01-01,Coffee Shop,5.00,,995.00
2025-01-02,Salary,,5000.00,5995.00
"""
        service = ExtractionService()
        result = await service._parse_csv_content(csv_content, "UOB")
        assert result["transactions"][0]["direction"] == "OUT"
        assert result["transactions"][1]["direction"] == "IN"
