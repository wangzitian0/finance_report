"""Comprehensive edge case tests for extraction flow."""

import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from pathlib import Path

from src.services.extraction import ExtractionService, ExtractionError
from src.models.statement import BankStatementStatus


class TestExtractionEdgeCases:
    """Test extraction flow edge cases and error paths."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    @pytest.mark.asyncio
    async def test_extract_financial_data_timeout_after_retries(self, service):
        """Test that extraction fails after all models timeout."""
        from src.services.openrouter_streaming import OpenRouterStreamError

        service.api_key = "test-key"

        with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
            # All models timeout
            mock_stream.side_effect = [
                OpenRouterStreamError("HTTP 429: Quota Exceeded"),
                OpenRouterStreamError("HTTP 429: Quota Exceeded"),
            ]

            with pytest.raises(ExtractionError, match="All 2 models failed.*Breakdown"):
                await service.extract_financial_data(
                    b"content",
                    "DBS",
                    "pdf",
                    file_url="https://example.com/file.pdf",
                )

    @pytest.mark.asyncio
    async def test_extract_financial_data_json_parse_error(self, service):
        """Test JSON parse error is handled correctly."""
        service.api_key = "test-key"

        with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
            # Return invalid JSON that can't be parsed
            mock_stream.return_value = mock_stream_generator("Not JSON at all")

            with pytest.raises(ExtractionError, match="strict JSON object"):
                await service.extract_financial_data(
                    b"content",
                    "DBS",
                    "pdf",
                    file_url="https://example.com/file.pdf",
                )

    @pytest.mark.asyncio
    async def test_extract_financial_data_empty_transactions(self, service):
        """Test extraction with empty transactions array."""
        service.api_key = "test-key"

        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [],
        }

        with patch.object(service, "extract_financial_data", new_callable=AsyncMock(return_value=mock_data)):
            stmt, txns = await service.parse_document(
                Path("test.pdf"),
                "DBS",
                user_id=uuid4(),
                file_content=b"content",
            )

        assert stmt is not None
        assert len(txns) == 0

    @pytest.mark.asyncio
    async def test_extract_financial_data_missing_required_fields(self, service):
        """Test extraction with missing required fields."""
        service.api_key = "test-key"

        mock_data = {
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
        }

        with patch.object(service, "extract_financial_data", new_callable=AsyncMock(return_value=mock_data)):
            with pytest.raises(ExtractionError, match="Missing required field"):
                await service.parse_document(
                    Path("test.pdf"),
                    "DBS",
                    user_id=uuid4(),
                    file_content=b"content",
                )

    @pytest.mark.asyncio
    async def test_extract_financial_data_all_zero_balances(self, service):
        """Test extraction with all zero balances."""
        service.api_key = "test-key"

        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0.00",
            "closing_balance": "0.00",
            "transactions": [
                {"date": "2025-01-15", "amount": "100.00", "direction": "IN", "description": "Salary"},
                {"date": "2025-01-20", "amount": "100.00", "direction": "OUT", "description": "Rent"},
            ],
        }

        with patch.object(service, "extract_financial_data", new_callable=AsyncMock(return_value=mock_data)):
            stmt, txns = await service.parse_document(
                Path("test.pdf"),
                "DBS",
                user_id=uuid4(),
                file_content=b"content",
            )

        assert stmt is not None
        assert len(txns) == 2


def mock_stream_generator(content: str):
    """Helper to create async generator for streaming mock."""
    yield content
