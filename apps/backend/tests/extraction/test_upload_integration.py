"""Integration tests for complete upload-parse-store workflow."""

import pytest
from uuid import uuid4
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

from src.models.statement import BankStatement, BankStatementStatus
from src.services.extraction import ExtractionService, ExtractionError
from src.services.storage import StorageError


@pytest.fixture
def service():
    return ExtractionService()


class TestUploadParseStoreWorkflow:
    """Integration tests for end-to-end upload → parse → store workflow."""

    @pytest.mark.asyncio
    async def test_complete_pdf_upload_workflow(self, db, service):
        """Test complete PDF upload, parse, and storage workflow."""
        import tempfile
        from pathlib import Path

        pdf_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_file.write(b"PDF content")
        pdf_path = Path(pdf_file.name)

        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {
                    "date": "2025-01-15",
                    "description": "Salary Deposit",
                    "amount": "1000.00",
                    "direction": "IN",
                    "reference": "SAL001",
                },
                {
                    "date": "2025-01-20",
                    "description": "Rent Payment",
                    "amount": "250.00",
                    "direction": "OUT",
                    "reference": "RENT001",
                },
            ],
        }

        service.api_key = "test-key"

        with patch.object(service, "storage_service") as mock_storage:
            mock_storage.upload_bytes.return_value = "file-path"
            mock_storage.generate_presigned_url.return_value = "presigned-url"

            with patch.object(service, "extract_financial_data", new_callable=AsyncMock(return_value=mock_data)):
                stmt, txns = await service.parse_document(
                    pdf_path,
                    "DBS",
                    user_id=uuid4(),
                    file_content=pdf_file.read_bytes(),
                )

        assert stmt is not None
        assert stmt.institution == "DBS"
        assert stmt.account_last4 == "1234"
        assert stmt.opening_balance == Decimal("1000.00")
        assert stmt.closing_balance == Decimal("1100.00")
        assert len(txns) == 2

    @pytest.mark.asyncio
    async def test_csv_upload_with_auto_detection(self, db, service):
        """Test CSV upload without specifying institution (auto-detect)."""
        import tempfile

        csv_file = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        csv_file.write(b"""Date,Description,Amount
2025-01-01,Salary,1000.00
2025-01-02,Rent,250.00
""")
        csv_path = Path(csv_file.name)

        mock_data = {
            "institution": "Wise",
            "account_last4": "9876",
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0.00",
            "closing_balance": "750.00",
            "transactions": [
                {
                    "date": "2025-01-01",
                    "description": "Salary",
                    "amount": "1000.00",
                    "direction": "IN",
                },
                {
                    "date": "2025-01-02",
                    "description": "Rent",
                    "amount": "250.00",
                    "direction": "OUT",
                },
            ],
        }

        service.api_key = "test-key"

        with patch.object(service, "extract_financial_data", new_callable=AsyncMock(return_value=mock_data)):
            stmt, txns = await service.parse_document(
                csv_path,
                None,
                user_id=uuid4(),
                file_content=csv_file.read_bytes(),
            )

        assert stmt is not None
        assert stmt.institution == "Wise"

    @pytest.mark.asyncio
    async def test_upload_duplicate_detection(self, db, service):
        """Test that duplicate file uploads are detected and rejected."""
        from sqlalchemy import select

        pdf_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_file.write(b"Duplicate content")

        existing_stmt = BankStatement(
            id=uuid4(),
            user_id=uuid4(),
            file_hash="sha256hash",
            status=BankStatementStatus.PARSED,
        )
        db.add(existing_stmt)
        await db.commit()

        file_hash = "sha256hash"
        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "transactions": [],
        }

        service.api_key = "test-key"

        with patch("sqlalchemy.engine.Connection.execute") as mock_execute:
            mock_execute.return_value.scalar_one_or_none.return_value = None

            with pytest.raises(ExtractionError, match="Duplicate statement"):
                await service.parse_document(
                    Path("test.pdf"),
                    "DBS",
                    user_id=uuid4(),
                    file_content=pdf_file.read_bytes(),
                    file_hash=file_hash,
                )

    @pytest.mark.asyncio
    async def test_parse_error_with_storage_failure(self, db, service):
        """Test that storage errors during parsing are handled correctly."""
        import tempfile

        pdf_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_file.write(b"Content causing storage error")

        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "transactions": [
                {"date": "2025-01-15", "description": "Test", "amount": "100.00", "direction": "IN"},
            ],
        }

        service.api_key = "test-key"

        with patch.object(service, "storage_service") as mock_storage:
            mock_storage.upload_bytes.side_effect = StorageError("Upload failed")

            with patch.object(service, "_dual_write_layer2") as mock_dual_write:
                mock_dual_write.side_effect = Exception("Database error")

                with pytest.raises(ExtractionError, match="storage error"):
                    await service.parse_document(
                        Path("test.pdf"),
                        "DBS",
                        user_id=uuid4(),
                        file_content=pdf_file.read_bytes(),
                    )

    @pytest.mark.asyncio
    async def test_validation_error_handling(self, db, service):
        """Test that balance validation errors result in rejection."""
        import tempfile

        pdf_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_file.write(b"Content with balance mismatch")

        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "2000.00",
            "transactions": [
                {"date": "2025-01-15", "description": "Test", "amount": "1000.00", "direction": "IN"},
            ],
        }

        service.api_key = "test-key"

        with patch.object(service, "extract_financial_data", new_callable=AsyncMock(return_value=mock_data)):
            stmt, txns = await service.parse_document(
                Path("test.pdf"),
                "DBS",
                user_id=uuid4(),
                file_content=pdf_file.read_bytes(),
            )

        assert stmt is not None
        assert stmt.status == BankStatementStatus.REJECTED
        assert "balance" in stmt.validation_error.lower()

    @pytest.mark.asyncio
    async def test_successful_parsing_confidence_routing(self, db, service):
        """Test that confidence score correctly routes to PARSED status."""
        import tempfile

        pdf_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_file.write(b"Content with high confidence")

        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {"date": "2025-01-15", "description": "Salary", "amount": "1000.00", "direction": "IN"},
            ],
        }

        service.api_key = "test-key"

        with patch.object(service, "extract_financial_data", new_callable=AsyncMock(return_value=mock_data)):
            stmt, txns = await service.parse_document(
                Path("test.pdf"),
                "DBS",
                user_id=uuid4(),
                file_content=pdf_file.read_bytes(),
            )

        assert stmt is not None
        assert stmt.status == BankStatementStatus.PARSED
        assert stmt.confidence_score >= 85

    @pytest.mark.asyncio
    async def test_medium_confidence_requires_manual_review(self, db, service):
        """Test that medium confidence routes to PENDING_REVIEW status."""
        import tempfile

        pdf_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_file.write(b"Content with medium confidence (balance mismatch)")

        mock_data = {
            "institution": "DBS",
            "account_last4": "1234",
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "2000.00",
            "transactions": [
                {"date": "2025-01-15", "description": "Salary", "amount": "1000.00", "direction": "IN"},
            ],
        }

        service.api_key = "test-key"

        with patch.object(service, "extract_financial_data", new_callable=AsyncMock(return_value=mock_data)):
            stmt, txns = await service.parse_document(
                Path("test.pdf"),
                "DBS",
                user_id=uuid4(),
                file_content=pdf_file.read_bytes(),
            )

        assert stmt is not None
        assert stmt.status == BankStatementStatus.PENDING_REVIEW
        assert 60 <= stmt.confidence_score < 85
