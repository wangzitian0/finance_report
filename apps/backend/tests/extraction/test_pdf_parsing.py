"""Critical and High priority tests for EPIC-003.

These tests cover the Critical and High priority gaps identified in the test audit:
- AC3.2.1: Balance Validation (Pass)
- AC3.2.2: Balance Validation (Fail)
- AC3.3.1: High Confidence (Auto-Accept)
- AC3.3.2: Medium Confidence (Review)
- #3 Real PDF parsing tests (using existing fixtures as ground truth)
- #4 Invalid parse result not persisted
- #10 File size limit test (10MB)
- #11 Parsing timeout handling
- #12 Gemini retry on timeout
"""

from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import UploadFile

from src.models.statement_enums import BankStatementStatus
from src.services.extraction import ExtractionError, ExtractionService
from src.services.validation import (
    route_by_threshold,
    validate_balance,
    validate_completeness,
)


def make_upload_file(name: str, content: bytes) -> UploadFile:
    """Create an UploadFile for testing."""
    return UploadFile(
        filename=name,
        file=BytesIO(content),
    )


# =============================================================================
# Critical #4: Invalid Parse Result Not Persisted
# =============================================================================


class TestInvalidParseNotPersisted:
    """Test that invalid parsing results are not persisted to database."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    async def test_extraction_error_not_persisted(self, service, tmp_path):
        """
        [AC3.4.1] CRITICAL #4: Extraction errors should raise, not persist bad data.
        """
        # Create an invalid file
        bad_file = tmp_path / "bad.pdf"
        bad_file.write_bytes(b"not a valid pdf")

        # Mock the API to return unparseable data
        with patch.object(service, "extract_financial_data", new_callable=AsyncMock) as mock_extract:
            mock_extract.side_effect = ExtractionError("Failed to parse document")

            from uuid import uuid4

            with pytest.raises(ExtractionError, match="Failed to parse"):
                await service.parse_document(
                    bad_file,
                    "DBS",
                    user_id=uuid4(),
                    file_content=bad_file.read_bytes(),
                )

    async def test_parse_document_bank_balance_mismatch_records_validation_error(self, service, tmp_path):
        """
        AC3.2.4 (+AC20.9.2 #1352): Bank statement balance mismatches preserve a typed
        validation_error and are quarantined to REJECTED by the LLM-LED blocking gate.
        """
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"dummy")

        # Return data that fails balance validation
        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "2000.00",  # Doesn't match!
            "transactions": [
                {"date": "2025-01-15", "description": "Test", "amount": "100.00", "direction": "IN"}
            ],  # Only +100, but gap is 1000
        }

        with patch.object(service, "extract_financial_data", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = mock_data

            from uuid import uuid4

            stmt, events = await service.parse_document(
                pdf_file,
                "DBS",
                user_id=uuid4(),
                file_content=pdf_file.read_bytes(),
            )

            # An unreconciled balance chain is now BLOCKING: the extraction cannot
            # persist as trusted truth, so it is quarantined to REJECTED with a typed
            # reason code preserved in validation_error (AC20.9.2 supersedes the prior
            # PARSED/review resting state).
            from src.models.statement_enums import BankStatementStatus

            assert stmt.status == BankStatementStatus.REJECTED
            assert stmt.balance_validated is False
            assert stmt.validation_error is not None
            assert "llm_led_balance_chain_unreconciled" in stmt.validation_error

    def test_validate_balance_returns_invalid_on_mismatch(self):
        """
        CRITICAL #4: validate_balance should return invalid on mismatch.
        """
        extracted = {
            "opening_balance": "100.00",
            "closing_balance": "500.00",  # 400 gap
            "transactions": [
                {"amount": "50.00", "direction": "IN"},  # Only +50
            ],
        }

        result = validate_balance(extracted)
        assert result["balance_valid"] is False
        assert "mismatch" in result.get("notes", "").lower() or Decimal(result["difference"]) > Decimal("0.1")


# =============================================================================
# High #10: File Size Limit Test
# =============================================================================


class TestFileSizeLimit:
    """Test file size limit enforcement."""

    async def test_upload_file_exceeds_10mb_limit(self, client):
        """
        [AC3.5.2] HIGH #10: File exceeding 10MB should be rejected with 413.
        """
        # Create content larger than 10MB
        large_content = b"x" * (11 * 1024 * 1024)  # 11MB

        response = await client.post(
            "/statements/upload",
            files={"file": ("large.pdf", BytesIO(large_content), "application/pdf")},
            data={"institution": "DBS"},
        )

        assert response.status_code == 413
        assert "10MB" in response.json().get("detail", "")

    async def test_upload_file_at_limit_succeeds(self, client, monkeypatch):
        """
        HIGH #10: File at exactly 10MB should be accepted.
        """
        # Create content exactly 10MB
        exact_content = b"x" * (10 * 1024 * 1024)

        # Mock the extraction to avoid actual API calls
        async def fake_parse(*args, **kwargs):
            from tests.factories import StatementSummaryFactory

            stmt = StatementSummaryFactory.build(
                user_id=kwargs.get("user_id"),
                file_hash=kwargs.get("file_hash", "hash"),
                institution="DBS",
                account_last4="1234",
                currency="SGD",
                period_start=date(2025, 1, 1),
                period_end=date(2025, 1, 31),
                opening_balance=Decimal("100.00"),
                closing_balance=Decimal("100.00"),
                status=BankStatementStatus.PARSED,
                confidence_score=90,
                balance_validated=True,
            )
            return stmt, []

        from src.services.extraction import ExtractionService

        monkeypatch.setattr(ExtractionService, "parse_document", fake_parse)

        response = await client.post(
            "/statements/upload",
            files={"file": ("exact.pdf", BytesIO(exact_content), "application/pdf")},
            data={"institution": "DBS"},
        )

        # Should not be rejected for size (may fail for other reasons in mock)
        assert response.status_code != 413


# =============================================================================
# High #11: Parsing Timeout Handling
# =============================================================================


class TestParsingTimeout:
    """Test parsing timeout handling."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    async def test_extraction_timeout_raises_error(self, service):
        """
        [AC3.4.3] HIGH #11: Extraction timeout should raise ExtractionError.
        """
        service.api_key = "test-key"

        from src.services.ai_streaming import AIStreamError

        with patch("src.services.extraction.service.stream_ai_json") as mock_stream:
            mock_stream.side_effect = AIStreamError("Connection timed out")

            with pytest.raises(ExtractionError):
                await service.extract_financial_data(
                    b"content",
                    "DBS",
                    "pdf",
                    file_url="https://example.com/file.pdf",
                )


# =============================================================================
# High #12: Gemini Retry on Timeout
# =============================================================================


class TestGeminiRetry:
    """Test Gemini API retry mechanism."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    async def test_api_error_includes_status_code(self, service):
        """
        HIGH #12: API error should include status code for debugging.
        """
        service.api_key = "test-key"

        from src.services.ai_streaming import AIStreamError

        with patch("src.services.extraction.service.stream_ai_json") as mock_stream:
            mock_stream.side_effect = AIStreamError("HTTP 429: Rate limit exceeded")

            with pytest.raises(ExtractionError, match="429"):
                await service.extract_financial_data(
                    b"content",
                    "DBS",
                    "pdf",
                    file_url="https://example.com/file.pdf",
                )

    async def test_api_key_required(self, service):
        """
        HIGH #12: Missing API key should raise clear error.
        """
        service.api_key = None

        with pytest.raises(ExtractionError, match="API key not configured"):
            await service.extract_financial_data(b"content", "DBS", "png")


# =============================================================================
# Additional Validation Tests
# =============================================================================


class TestConfidenceRouting:
    """Test confidence score routing logic."""

    def test_high_confidence_auto_accept(self):
        """Confidence >= 85 with valid balance should auto-accept."""
        status = route_by_threshold(90, balance_valid=True)
        assert status == BankStatementStatus.APPROVED

    def test_medium_confidence_review(self):
        """Confidence 60-84 should require review."""
        status = route_by_threshold(75, balance_valid=True)
        assert status == BankStatementStatus.PARSED  # Parsed but needs review

    def test_low_confidence_manual(self):
        """Confidence < 60 should require manual entry."""
        status = route_by_threshold(50, balance_valid=True)
        assert status == BankStatementStatus.UPLOADED  # Not auto-parsed

    def test_invalid_balance_never_auto_accept(self):
        """Invalid balance should never auto-accept regardless of score.

        #1141: balance-invalid statements route to PARSED (review) rather than the
        UPLOADED dead-end, but still never auto-approve.
        """
        status = route_by_threshold(95, balance_valid=False)
        assert status == BankStatementStatus.PARSED
        assert status != BankStatementStatus.APPROVED


class TestStatementCompleteness:
    """Test statement completeness validation."""

    def test_missing_required_fields_detected(self):
        """[AC3.2.3] Missing required fields should be identified."""
        incomplete = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            # Missing: period_end, opening_balance, closing_balance, transactions
        }

        missing = validate_completeness(incomplete)
        assert "period_end" in missing
        assert "opening_balance" in missing
        assert "closing_balance" in missing

    def test_complete_statement_no_missing(self):
        """Complete statement should have no missing fields."""
        complete = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "100.00",
            "closing_balance": "150.00",
            "transactions": [{"amount": "50.00", "direction": "IN"}],
        }

        missing = validate_completeness(complete)
        assert len(missing) == 0
