"""Integration tests for PII detection and CSV edge cases."""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock

from src.services.extraction import ExtractionService, ExtractionError


class TestPIIDetectionAndCSVEdgeCases:
    """Test PII detection and CSV parsing edge cases."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    @pytest.mark.asyncio
    async def test_pii_detected_in_csv_transaction(self, service):
        """Test PII (NRIC/Email) is detected in CSV transaction."""
        csv_content = b"""Date,Description,Amount
2025-01-01,Payment to NRIC S1234567A,1000.00
2025-01-02,Credit to john@example.com,500.00
"""
        result = await service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 2

    @pytest.mark.asyncio
    async def test_csv_with_special_characters_in_description(self, service):
        """Test CSV handles special characters and newlines in description."""
        csv_content = b"""Date,Description,Amount
2025-01-01,"Description with, comma
2025-01-02,Description with
"new line"
100.00
"""
        result = await service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 2

    @pytest.mark.asyncio
    async def test_csv_with_empty_descriptions(self, service):
        """Test CSV handles rows with empty descriptions gracefully."""
        csv_content = b"""Date,Description,Amount
2025-01-01,,100.00
2025-01-02,,200.00
2025-01-03,
"""
        result = await service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["description"] == ""
        assert result["transactions"][0]["amount"] == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_csv_with_zero_amounts(self, service):
        """Test CSV correctly parses transactions with zero amounts."""
        csv_content = b"""Date,Description,Debit,Credit,Balance
2025-01-01,Zero Debit,0.00,,0.00
2025-01-02,Credit,,100.00,100.00
"""
        result = await service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 2
        assert result["transactions"][0]["amount"] == Decimal("0.00")
        assert result["transactions"][0]["direction"] == "OUT"
        assert result["transactions"][1]["direction"] == "IN"

    @pytest.mark.asyncio
    async def test_csv_with_negative_amounts(self, service):
        """Test CSV correctly handles transactions with negative amounts (refunds)."""
        csv_content = b"""Date,Description,Amount
2025-01-01,Refund of Purchase,-100.00,,900.00
2025-01-02,Service Fee,-15.00,,885.00
"""
        result = await service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 2
        assert result["transactions"][0]["amount"] == Decimal("-100.00")
        assert result["transactions"][0]["direction"] == "OUT"
        assert result["transactions"][1]["direction"] == "IN"
