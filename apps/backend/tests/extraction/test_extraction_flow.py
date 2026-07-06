import json
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from src.extraction.extension.service import ExtractionError, ExtractionService
from src.models.statement_enums import BankStatementStatus, Stage1Status


async def mock_stream_generator(content: str):
    """Helper to create async generator for streaming mock."""
    yield content


class TestExtractionServiceFlow:
    """AC-extraction.5.1 AC-extraction.5.2 AC-extraction.5.3 AC-extraction.5.4 AC18.1.1 AC18.1.2: Extraction Flow Tests

    These tests validate the complete extraction service flow including document parsing,
    AI institution auto-detection, transaction extraction, error handling, and
    various file format support (CSV, PDF, images) with proper mocking.
    """

    @pytest.fixture
    def service(self):
        return ExtractionService()

    async def test_parse_document_auto_detects_institution(self, service, tmp_path):
        """Test that AI auto-detection sets institution correctly when institution=None."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"dummy content")

        mock_data = {
            "institution": "UOB",
            "account_last4": "6789",
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {"date": "2025-01-15", "description": "Salary", "amount": "1000.00", "direction": "IN"},
            ],
        }

        with patch.object(service, "extract_financial_data", new=AsyncMock(return_value=mock_data)):
            stmt, events = await service.parse_document(
                pdf_file,
                institution=None,
                user_id=uuid4(),
                file_content=pdf_file.read_bytes(),
            )

        assert stmt.institution == "UOB"
        assert stmt.account_last4 == "6789"

    async def test_parse_document_csv_success(self, service, tmp_path):
        """Test parse_document flow for CSV with mocked specific parser."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_bytes(b"dummy csv")

        mock_data = {
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0.00",
            "closing_balance": "0.00",
            "transactions": [],
        }

        with patch.object(service, "_parse_csv_content", new_callable=AsyncMock) as mock_csv:
            mock_csv.return_value = mock_data

            stmt, events = await service.parse_document(
                csv_file,
                "DBS",
                user_id=UUID("00000000-0000-0000-0000-000000000001"),
                file_type="csv",
                file_content=csv_file.read_bytes(),
            )

            assert stmt.status == BankStatementStatus.PARSED  # Medium confidence requires review
            assert len(events) == 0

    async def test_parsed_statement_sets_stage1_pending_review(self, service, tmp_path):
        """AC-extraction.1622.8: a statement routed to parsed/review carries stage1_status=pending_review
        explicitly, so the pending-review queue does not depend on a NULL fallback."""
        csv_file = tmp_path / "review.csv"
        csv_file.write_bytes(b"dummy csv")

        mock_data = {
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0.00",
            "closing_balance": "0.00",
            "transactions": [],
        }

        with patch.object(service, "_parse_csv_content", new_callable=AsyncMock) as mock_csv:
            mock_csv.return_value = mock_data

            stmt, _events = await service.parse_document(
                csv_file,
                "DBS",
                user_id=UUID("00000000-0000-0000-0000-000000000002"),
                file_type="csv",
                file_content=csv_file.read_bytes(),
            )

        assert stmt.status == BankStatementStatus.PARSED
        assert stmt.stage1_status == Stage1Status.PENDING_REVIEW

    async def test_parse_document_csv_without_statement_balances_remains_reviewable(self, service, tmp_path):
        """AC-extraction.2.5: CSV transaction exports without statement balances remain reviewable."""
        csv_file = tmp_path / "dbs-export.csv"
        csv_file.write_bytes(
            b"Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1\n"
            b"15 Jan 2025,REF001,,500.00,SALARY\n"
            b"16 Jan 2025,REF002,100.00,,GROCERIES\n"
        )

        stmt, events = await service.parse_document(
            csv_file,
            "DBS",
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            file_type="csv",
            file_content=csv_file.read_bytes(),
        )

        assert len(events) == 2
        assert stmt.status == BankStatementStatus.PARSED
        assert stmt.balance_validated is False
        assert stmt.confidence_score == 45
        assert stmt.validation_error == (
            "CSV import does not include source statement opening/closing balances; manual review required"
        )

    async def test_parse_document_unsupported_type(self, service, tmp_path):
        """[AC-extraction.4.2] Test parse_document raises error for unsupported type."""
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

    async def test_extract_financial_data_success_json(self, service, tmp_path):
        """Test extract_financial_data handles JSON response."""
        service.api_key = "test-key"

        json_content = json.dumps({"test": "data"})

        with patch("src.extraction.extension.service.stream_ai_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(json_content)

            result = await service.extract_financial_data(b"content", "DBS", "png")
            assert result == {"test": "data"}

    async def test_extract_financial_data_markdown_json(self, service):
        """AC-extraction.114.5: markdown-fenced JSON is salvaged, not rejected (#982)."""
        service.api_key = "test-key"

        content = 'Here is json:\n```json\n{"test": "markdown"}\n```'

        with patch("src.extraction.extension.service.stream_ai_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(content)

            result = await service.extract_financial_data(b"content", "DBS", "png")
            assert result == {"test": "markdown"}

    async def test_extract_financial_data_salvages_extra_text(self, service):
        """AC-extraction.114.2: a valid object padded with prose is salvaged (#982)."""
        service.api_key = "test-key"

        content = 'Sure! {"test": "value"}\nThanks!'

        with patch("src.extraction.extension.service.stream_ai_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(content)

            result = await service.extract_financial_data(b"content", "DBS", "png")
            assert result == {"test": "value"}

    async def test_extract_financial_data_rejects_array(self, service):
        """Test extract_financial_data rejects JSON arrays."""
        service.api_key = "test-key"

        content = json.dumps([{"test": "value"}])

        with patch("src.extraction.extension.service.stream_ai_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(content)

            with pytest.raises(ExtractionError, match="strict JSON object"):
                await service.extract_financial_data(b"content", "DBS", "png")

    async def test_extract_financial_data_api_error(self, service):
        """Test extract_financial_data handles API error."""
        service.api_key = "test-key"

        from src.services.ai_streaming import AIStreamError

        with patch("src.extraction.extension.service.stream_ai_json") as mock_stream:
            mock_stream.side_effect = AIStreamError("HTTP 400: Bad Request")

            with pytest.raises(ExtractionError, match="failed"):
                await service.extract_financial_data(b"content", "DBS", "png")

    async def test_extract_financial_data_no_key(self, service):
        """Test extract_financial_data raises error without key."""
        service.api_key = None
        with pytest.raises(ExtractionError, match="AI provider API key not configured"):
            await service.extract_financial_data(b"content", "DBS", "pdf")

    async def test_extract_financial_data_prefers_content(self, service):
        """Test that file_content is prioritized over file_url for images."""
        service.api_key = "test-key"

        content = b"file-content"
        url = "http://internal-url.local/file.png"

        json_content = json.dumps({"success": True})

        with patch("src.extraction.extension.service.stream_ai_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(json_content)

            await service.extract_financial_data(file_content=content, file_url=url, institution="DBS", file_type="png")

            call_args = mock_stream.call_args
            payload = call_args.kwargs["messages"]
            message_content = payload[0]["content"]
            media_part = message_content[1]

            assert media_part["type"] == "image_url"
            assert media_part["image_url"]["url"].startswith("data:image/png;base64,")

    async def test_extract_financial_data_valid_public_url(self, service):
        """Test extract_financial_data uses valid public URL when no content."""
        service.api_key = "test-key"
        service.ocr_model = None
        url = "https://example.com/public.pdf"

        json_content = json.dumps({"success": True})

        with patch("src.extraction.extension.service.stream_ai_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator(json_content)

            await service.extract_financial_data(file_content=None, file_url=url, institution="DBS", file_type="pdf")

            call_args = mock_stream.call_args
            payload = call_args.kwargs["messages"]
            media_part = payload[0]["content"][1]
            assert media_part["type"] == "image_url"
            assert media_part["image_url"]["url"] == url

    async def test_extract_financial_data_rejects_private_url(self, service):
        """Test extract_financial_data rejects private URL when no content."""
        service.api_key = "test-key"
        url = "http://192.168.1.1/private.pdf"

        with pytest.raises(ExtractionError, match="No valid file content or accessible URL"):
            await service.extract_financial_data(file_content=None, file_url=url, institution="DBS", file_type="pdf")

    async def test_extract_financial_data_pdf_renders_content_for_zai_vision(self, service):
        """Test that Z.AI PDF vision fallback renders uploaded PDF content to images."""
        service.api_key = "test-key"
        service.ocr_model = None
        pdf_bytes = b"%PDF-1.4 fake content"
        image_payload = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
        }
        json_content = json.dumps({"success": True})

        with (
            patch.object(service, "_render_pdf_pages_as_image_payloads", return_value=[image_payload]) as mock_render,
            patch("src.extraction.extension.service.stream_ai_json") as mock_stream,
        ):
            mock_stream.return_value = mock_stream_generator(json_content)
            await service.extract_financial_data(
                file_content=pdf_bytes, file_url=None, institution="DBS", file_type="pdf"
            )

            mock_render.assert_called_once_with(pdf_bytes)
            payload = mock_stream.call_args.kwargs["messages"]
            assert payload[0]["content"][1] == image_payload

    async def test_force_model_pdf_renders_content_for_zai(self, service):
        """AC-extraction.105.1: Forced Z.AI PDF vision extraction can use rendered PDF images."""
        service.api_key = "test-key"
        pdf_bytes = b"%PDF-1.4 fake content"
        image_payload = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
        }
        json_content = json.dumps({"success": True})

        with (
            patch.object(service, "_render_pdf_pages_as_image_payloads", return_value=[image_payload]) as mock_render,
            patch("src.extraction.extension.service.stream_ai_json") as mock_stream,
        ):
            mock_stream.return_value = mock_stream_generator(json_content)
            await service.extract_financial_data(
                file_content=pdf_bytes,
                file_url=None,
                institution="DBS",
                file_type="pdf",
                force_model="glm-4.6v",
            )

            mock_render.assert_called_once_with(pdf_bytes)
            payload = mock_stream.call_args.kwargs["messages"]
            assert payload[0]["content"][1] == image_payload

    async def test_extract_financial_data_pdf_prefers_rendered_content_for_zai_vision(self, service):
        """Z.AI PDF vision fallback renders content instead of sending PDF URLs as images."""
        service.api_key = "test-key"
        service.ocr_model = None
        pdf_bytes = b"%PDF-1.4 fake content"
        url = "https://example.com/public.pdf"
        image_payload = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
        }

        json_content = json.dumps({"success": True})

        with (
            patch.object(service, "_render_pdf_pages_as_image_payloads", return_value=[image_payload]) as mock_render,
            patch("src.extraction.extension.service.stream_ai_json") as mock_stream,
        ):
            mock_stream.return_value = mock_stream_generator(json_content)

            await service.extract_financial_data(
                file_content=pdf_bytes, file_url=url, institution="DBS", file_type="pdf"
            )

            mock_render.assert_called_once_with(pdf_bytes)
            call_args = mock_stream.call_args
            payload = call_args.kwargs["messages"]
            media_part = payload[0]["content"][1]
            assert media_part["type"] == "image_url"
            assert media_part["image_url"]["url"].startswith("data:image/png;base64,")

    async def test_extract_financial_data_pdf_no_content_no_url_raises(self, service):
        """Test that PDF extraction raises when neither content nor URL is available."""
        service.api_key = "test-key"

        with pytest.raises(ExtractionError, match="File content is required"):
            await service.extract_financial_data(file_content=None, file_url=None, institution="DBS", file_type="pdf")
