
import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.schemas.extraction import StatementStatusEnum
from src.services.extraction import ExtractionError, ExtractionService


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
                    "direction": "IN"
                }
            ]
        }
        
        # Mock extract_financial_data
        with patch.object(
            service, "extract_financial_data", new_callable=AsyncMock
        ) as mock_extract:
            mock_extract.return_value = mock_data
            
            stmt, events = await service.parse_document(pdf_file, "DBS")
            
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
        
        mock_data = {
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "transactions": []
        }
        
        with patch.object(service, "_parse_csv", new_callable=AsyncMock) as mock_csv:
            mock_csv.return_value = mock_data
            
            stmt, events = await service.parse_document(csv_file, "DBS", file_type="csv")
            
            assert stmt.status == StatementStatusEnum.PARSED # High confidence as it validates
            assert len(events) == 0

    @pytest.mark.asyncio
    async def test_parse_document_unsupported_type(self, service, tmp_path):
        """Test parse_document raises error for unsupported type."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_bytes(b"text")
        
        with pytest.raises(ExtractionError, match="Unsupported file type"):
            await service.parse_document(txt_file, "DBS", file_type="txt")

    @pytest.mark.asyncio
    async def test_extract_financial_data_success_json(self, service, tmp_path):
        """Test extract_financial_data handles JSON response."""
        # Setup API key
        service.api_key = "test-key"
        
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"test": "data"})
                    }
                }
            ]
        }
        
        # Mock httpx using patch on src.services.extraction.httpx
        with patch("src.services.extraction.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_instance
            
            # Setup response mock (MagicMock for sync methods like .json())
            response_mock = MagicMock()
            response_mock.status_code = 200
            response_mock.json.return_value = mock_response
            mock_instance.post.return_value = response_mock
            
            result = await service.extract_financial_data(b"content", "DBS", "pdf")
            assert result == {"test": "data"}

    @pytest.mark.asyncio
    async def test_extract_financial_data_markdown_json(self, service):
        """Test extract_financial_data handles markdown wrapped JSON."""
        service.api_key = "test-key"
        
        content = "Here is the json:\n```json\n{\"test\": \"markdown\"}\n```"
        mock_response = {
            "choices": [{"message": {"content": content}}]
        }
        
        with patch("src.services.extraction.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_instance
            
            response_mock = MagicMock()
            response_mock.status_code = 200
            response_mock.json.return_value = mock_response
            mock_instance.post.return_value = response_mock
            
            result = await service.extract_financial_data(b"content", "DBS", "pdf")
            assert result == {"test": "markdown"}

    @pytest.mark.asyncio
    async def test_extract_financial_data_api_error(self, service):
        """Test extract_financial_data handles API error."""
        service.api_key = "test-key"
        
        with patch("src.services.extraction.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value.__aenter__.return_value = mock_instance
            
            response_mock = MagicMock()
            response_mock.status_code = 400
            response_mock.text = "Bad Request"
            mock_instance.post.return_value = response_mock
            
            with pytest.raises(ExtractionError, match="OpenRouter API error: 400"):
                await service.extract_financial_data(b"content", "DBS", "pdf")

    @pytest.mark.asyncio
    async def test_extract_financial_data_no_key(self, service):
        """Test extract_financial_data raises error without key."""
        service.api_key = None
        with pytest.raises(ExtractionError, match="OpenRouter API key not configured"):
            await service.extract_financial_data(b"content", "DBS", "pdf")
