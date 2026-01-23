"""Integration tests for EPIC-011 Phase 2 dual write to Layer 1/2."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.services.extraction import ExtractionService


@pytest.fixture
def mock_ai_response():
    """Mock AI extraction response."""
    return {
        "account_last4": "1234",
        "currency": "SGD",
        "period_start": "2024-01-01",
        "period_end": "2024-01-31",
        "opening_balance": "1000.00",
        "closing_balance": "1500.00",
        "transactions": [
            {
                "date": "2024-01-15",
                "description": "Salary Deposit",
                "amount": "3000.00",
                "direction": "IN",
                "reference": "SAL001",
            },
            {
                "date": "2024-01-20",
                "description": "Rent Payment",
                "amount": "2500.00",
                "direction": "OUT",
                "reference": "RENT001",
            },
        ],
    }


@pytest.fixture
def sample_file_content():
    """Sample PDF content."""
    return b"PDF-SAMPLE-CONTENT"


@pytest.mark.asyncio
class TestDualWriteLayer2:
    async def test_dual_write_disabled_by_default(
        self, db, test_user, mock_ai_response, sample_file_content
    ):
        service = ExtractionService()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            statement, transactions = await service.parse_document(
                file_path=Path("test_statement.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=sample_file_content,
                file_hash=hashlib.sha256(sample_file_content).hexdigest(),
                original_filename="test_statement.pdf",
                db=db,
            )

        assert statement is not None
        assert len(transactions) == 2

        result = await db.execute(
            select(UploadedDocument).where(UploadedDocument.user_id == test_user.id)
        )
        uploaded_docs = result.scalars().all()
        assert len(uploaded_docs) == 0

        result = await db.execute(
            select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)
        )
        atomic_txns = result.scalars().all()
        assert len(atomic_txns) == 0

    async def test_dual_write_creates_layer1_document(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        monkeypatch.setattr("src.config.settings.enable_4_layer_write", True)

        service = ExtractionService()
        file_hash = hashlib.sha256(sample_file_content).hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            statement, transactions = await service.parse_document(
                file_path=Path("test_statement.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=sample_file_content,
                file_hash=file_hash,
                original_filename="test_statement.pdf",
                db=db,
            )

        await db.commit()

        result = await db.execute(
            select(UploadedDocument).where(UploadedDocument.user_id == test_user.id)
        )
        uploaded_doc = result.scalar_one()

        assert uploaded_doc.file_hash == file_hash
        assert uploaded_doc.original_filename == "test_statement.pdf"
        assert uploaded_doc.document_type == DocumentType.BANK_STATEMENT

    async def test_dual_write_creates_atomic_transactions(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        monkeypatch.setattr("src.config.settings.enable_4_layer_write", True)

        service = ExtractionService()
        file_hash = hashlib.sha256(sample_file_content).hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            statement, transactions = await service.parse_document(
                file_path=Path("test_statement.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=sample_file_content,
                file_hash=file_hash,
                original_filename="test_statement.pdf",
                db=db,
            )

        await db.commit()

        result = await db.execute(
            select(AtomicTransaction)
            .where(AtomicTransaction.user_id == test_user.id)
            .order_by(AtomicTransaction.txn_date)
        )
        atomic_txns = result.scalars().all()

        assert len(atomic_txns) == 2

        txn1 = atomic_txns[0]
        assert txn1.txn_date == date(2024, 1, 15)
        assert txn1.description == "Salary Deposit"
        assert txn1.amount == Decimal("3000.00")
        assert txn1.direction == TransactionDirection.IN
        assert txn1.currency == "SGD"
        assert txn1.reference == "SAL001"

        txn2 = atomic_txns[1]
        assert txn2.txn_date == date(2024, 1, 20)
        assert txn2.description == "Rent Payment"
        assert txn2.amount == Decimal("2500.00")
        assert txn2.direction == TransactionDirection.OUT
        assert txn2.reference == "RENT001"

    async def test_dual_write_deduplication_on_reupload(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        monkeypatch.setattr("src.config.settings.enable_4_layer_write", True)

        service = ExtractionService()
        file_hash = hashlib.sha256(sample_file_content).hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            await service.parse_document(
                file_path=Path("test_statement.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=sample_file_content,
                file_hash=file_hash,
                original_filename="test_statement.pdf",
                db=db,
            )
            await db.commit()

        result = await db.execute(
            select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)
        )
        atomic_txns_before = result.scalars().all()
        assert len(atomic_txns_before) == 2

        file_hash_2 = hashlib.sha256(b"DIFFERENT_FILE").hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            await service.parse_document(
                file_path=Path("test_statement_v2.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=b"DIFFERENT_FILE",
                file_hash=file_hash_2,
                original_filename="test_statement_v2.pdf",
                db=db,
            )
            await db.commit()

        result = await db.execute(
            select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)
        )
        atomic_txns_after = result.scalars().all()
        assert len(atomic_txns_after) == 2

        for txn in atomic_txns_after:
            assert isinstance(txn.source_documents, list)
            assert len(txn.source_documents) == 2

    async def test_dual_write_preserves_layer0_behavior(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        monkeypatch.setattr("src.config.settings.enable_4_layer_write", True)

        service = ExtractionService()
        file_hash = hashlib.sha256(sample_file_content).hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            statement, transactions = await service.parse_document(
                file_path=Path("test_statement.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=sample_file_content,
                file_hash=file_hash,
                original_filename="test_statement.pdf",
                db=db,
            )

        assert statement.institution == "DBS"
        assert statement.currency == "SGD"
        assert statement.opening_balance == Decimal("1000.00")
        assert statement.closing_balance == Decimal("1500.00")
        assert len(transactions) == 2

    async def test_dual_write_failure_raises_error(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        """Test that dual-write failures (non-IntegrityError) raise RuntimeError."""
        monkeypatch.setattr("src.config.settings.enable_4_layer_write", True)

        service = ExtractionService()
        file_hash = hashlib.sha256(sample_file_content).hexdigest()

        from src.services.extraction import ExtractionError

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            with patch(
                "src.services.extraction.DeduplicationService.create_uploaded_document",
                side_effect=Exception("DB error"),
            ):
                with pytest.raises(ExtractionError) as exc_info:
                    await service.parse_document(
                        file_path=Path("test_statement.pdf"),
                        institution="DBS",
                        user_id=test_user.id,
                        file_content=sample_file_content,
                        file_hash=file_hash,
                        original_filename="test_statement.pdf",
                        db=db,
                    )

        assert "Failed to parse document" in str(exc_info.value)
        assert "Failed to write to Layer 2" in str(exc_info.value.__cause__)

    async def test_dual_write_handles_missing_db_session(
        self, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        monkeypatch.setattr("src.config.settings.enable_4_layer_write", True)

        service = ExtractionService()
        file_hash = hashlib.sha256(sample_file_content).hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            statement, transactions = await service.parse_document(
                file_path=Path("test_statement.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=sample_file_content,
                file_hash=file_hash,
                original_filename="test_statement.pdf",
                db=None,
            )

        assert statement is not None
        assert len(transactions) == 2
