import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from src.models.statement import BankStatementStatus
from src.services.extraction import ExtractionError, ExtractionService


async def mock_stream_generator(content: str):
    """Helper to create async generator for streaming mock."""
    yield content


class TestExtractionServiceFlow:
    """Tests for ExtractionService flow mocking external dependencies."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    @pytest.mark.asyncio
    async def test_parse_document_pdf_success(self, service, tmp_path):
        """Test parse_document flow for PDF with mocked extraction."""
        # Create dummy PDF
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"dummy content")

        # Mock extracted data
        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {
                    "date": "2025-01-15",
                    "description": "Test Txn",
                    "amount": "100.00",
                    "direction": "IN",
                }
            ],
        }

        # Mock extract_financial_data
        with patch.object(
            service, "extract_financial_data", new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = mock_data

            stmt, events = await service.parse_document(
                pdf_file,
                "DBS",
                user_id=UUID("00000000-0000-0000-0000-000000000001"),
                file_content=pdf_file.read_bytes(),
            )

            # Verify results
            assert stmt.institution == "DBS"
            assert stmt.period_start == date(2025, 1, 1)
            assert stmt.opening_balance == Decimal("1000.00")
            assert len(events) == 1
            assert events[0].amount == Decimal("100.00")

            # Verify clean up (nothing to clean really)

    @pytest.mark.asyncio
    async def test_parse_document_csv_success(self, service, tmp_path):
        """Test parse_document flow for CSV with mocked specific parser."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_bytes(b"dummy csv")

        mock_data = {"period_start": "2025-01-01", "period_end": "2025-01-31", "transactions": []}

        with patch.object(service, "_parse_csv_content", new_callable=AsyncMock) as mock_csv:
            mock_csv.return_value = mock_data

            stmt, events = await service.parse_document(
                csv_file,
                "DBS",
                user_id=UUID("00000000-0000-0000-0000-000000000001"),
                file_type="csv",
                file_content=csv_file.read_bytes(),
            )

            assert stmt.status == BankStatementStatus.PARSED  # High confidence as it validates
            assert len(events) == 0

    @pytest.mark.asyncio
    async def test_parse_document_unsupported_type(self, service, tmp_path):
        """Test parse_document raises error for unsupported type."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_bytes(b"text")

        with pytest.raises(ExtractionError, match="Unsupported file type"):
            await service.parse_document(
                txt_file,
                "DBS",
                user_id=UUID("00000000-0000-0000-0000-000000000001"),
                file_type="txt",
                file_content=txt_file.read_bytes(),
            )

    @pytest.mark.asyncio
    async def test_extract_financial_data_success_json(self, service, tmp_path):
        """Test extract_financial_data handles JSON response."""
        service.api_key = "test-key"

        json_content = json.dumps({"test": "data"})

        with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(json_content)

            result = await service.extract_financial_data(b"content", "DBS", "pdf")
            assert result == {"test": "data"}

    @pytest.mark.asyncio
    async def test_extract_financial_data_markdown_json(self, service):
        """Test extract_financial_data handles markdown wrapped JSON."""
        service.api_key = "test-key"

        content = 'Here is the json:\n```json\n{"test": "markdown"}\n```'

        with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(content)

            result = await service.extract_financial_data(b"content", "DBS", "pdf")
            assert result == {"test": "markdown"}

    @pytest.mark.asyncio
    async def test_extract_financial_data_api_error(self, service):
        """Test extract_financial_data handles API error."""
        service.api_key = "test-key"

        from src.services.openrouter_streaming import OpenRouterStreamError

        with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
            mock_stream.side_effect = OpenRouterStreamError("HTTP 400: Bad Request")

            with pytest.raises(ExtractionError, match="failed"):
                await service.extract_financial_data(b"content", "DBS", "pdf")

    @pytest.mark.asyncio
    async def test_extract_financial_data_no_key(self, service):
        """Test extract_financial_data raises error without key."""
        service.api_key = None
        with pytest.raises(ExtractionError, match="OpenRouter API key not configured"):
            await service.extract_financial_data(b"content", "DBS", "pdf")

    @pytest.mark.asyncio
    async def test_extract_financial_data_prefers_content(self, service):
        """Test that file_content is prioritized over file_url (base64 path)."""
        service.api_key = "test-key"

        content = b"file-content"
        url = "http://internal-url.local/file.pdf"

        json_content = json.dumps({"success": True})

        with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(json_content)

            await service.extract_financial_data(
                file_content=content, file_url=url, institution="DBS", file_type="pdf"
            )

            call_args = mock_stream.call_args
            payload = call_args.kwargs["messages"]
            message_content = payload[0]["content"]
            media_part = message_content[1]

            assert "data:application/pdf;base64," in media_part["image_url"]["url"]
            assert media_part["image_url"]["url"].startswith("data:")

    @pytest.mark.asyncio
    async def test_extract_financial_data_valid_public_url(self, service):
        """Test extract_financial_data uses valid public URL when no content."""
        service.api_key = "test-key"
        url = "https://example.com/public.pdf"

        json_content = json.dumps({"success": True})

        with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(json_content)

            await service.extract_financial_data(
                file_content=None, file_url=url, institution="DBS", file_type="pdf"
            )

            call_args = mock_stream.call_args
            payload = call_args.kwargs["messages"]
            media_part = payload[0]["content"][1]
            assert media_part["image_url"]["url"] == url

    @pytest.mark.asyncio
    async def test_extract_financial_data_rejects_private_url(self, service):
        """Test extract_financial_data rejects private URL when no content."""
        service.api_key = "test-key"
        url = "http://192.168.1.1/private.pdf"

        with pytest.raises(ExtractionError, match="No valid file content or accessible URL"):
            await service.extract_financial_data(
                file_content=None, file_url=url, institution="DBS", file_type="pdf"
            )
