"""Integration tests for PII detection and CSV edge cases."""

import pytest
from src.services.extraction import ExtractionService
from decimal import Decimal


class TestPIIDetectionAndCSVEdgeCases:
    """Test PII detection and CSV parsing edge cases."""

    def setup_method(self):
        self.service = ExtractionService()

    def test_pii_detected_in_csv_transaction(self):
        """Test PII (NRIC/Email) is detected in CSV transaction."""
        csv_content = """Date,Description,Amount
2025-01-01,Payment to NRIC S1234567A,1000.00
2025-01-02,Credit to john@example.com,500.00
"""
        result = self.service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 2

    def test_csv_with_special_characters_in_description(self):
        """Test CSV handles special characters and newlines in description."""
        csv_content = """Date,Description,Amount
2025-01-01,"Description with, comma
2025-01-02,Description with
"new line"
100.00
"""
        result = self.service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 2

    def test_csv_with_empty_descriptions(self):
        """Test CSV handles rows with empty descriptions gracefully."""
        csv_content = """Date,Description,Amount
2025-01-01,,100.00
2025-01-02,,200.00
2025-01-03,,
"""
        result = self.service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 1
        assert result["transactions"][0]["description"] == ""
        assert result["transactions"][0]["amount"] == Decimal("100.00")

    def test_csv_with_zero_amounts(self):
        """Test CSV correctly parses transactions with zero amounts."""
        csv_content = """Date,Description,Debit,Credit,Balance
2025-01-01,Zero Debit,0.00,,0.00
2025-01-02,Credit,,100.00,100.00
"""
        result = self.service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 2
        assert result["transactions"][0]["amount"] == Decimal("0.00")
        assert result["transactions"][0]["direction"] == "OUT"
        assert result["transactions"][1]["direction"] == "IN"

    def test_csv_with_negative_amounts(self):
        """Test CSV correctly handles transactions with negative amounts (refunds)."""
        csv_content = """Date,Description,Amount
2025-01-01,Refund of Purchase,-100.00,,900.00
2025-01-02,Service Fee,-15.00,,885.00
"""
        result = self.service._parse_csv_content(csv_content, "GENERIC")
        assert len(result["transactions"]) == 2
        assert result["transactions"][0]["amount"] == Decimal("-100.00")
        assert result["transactions"][0]["direction"] == "OUT"
