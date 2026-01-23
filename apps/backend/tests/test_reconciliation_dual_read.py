"""Integration tests for EPIC-011 Phase 3 Dual Read Validation."""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import delete

from src.config import settings
from src.models import (
    AtomicTransaction,
)
from src.services.extraction import ExtractionService
from src.services.reconciliation import execute_matching


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
                "amount": "500.00",
                "direction": "IN",
                "reference": "SAL001",
            },
        ],
    }


@pytest.mark.asyncio
class TestReconciliationDualRead:
    """Tests for Phase 3 Dual Read validation in reconciliation."""

    async def test_dual_read_validation_logs_consistency(
        self, db, test_user, mock_ai_response, monkeypatch, capsys
    ):
        """Test that consistent Layer 0/2 data logs verification success."""
        monkeypatch.setattr(settings, "enable_4_layer_write", True)

        service = ExtractionService()
        content = b"PDF-CONTENT"
        file_hash = hashlib.sha256(content).hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            statement, transactions = await service.parse_document(
                file_path=Path("test.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=content,
                file_hash=file_hash,
                original_filename="test.pdf",
                db=db,
            )
            db.add(statement)
            for txn in transactions:
                db.add(txn)
        await db.commit()

        await execute_matching(db, user_id=test_user.id, statement_id=statement.id)

        captured = capsys.readouterr()
        assert "Layer 0/2 Consistency Verified" in captured.out
        assert "count': 1" in captured.out

    async def test_dual_read_validation_detects_mismatch(
        self, db, test_user, mock_ai_response, monkeypatch, capsys
    ):
        """Test that missing Layer 2 data triggers mismatch warning."""
        monkeypatch.setattr(settings, "enable_4_layer_write", True)

        service = ExtractionService()
        content = b"PDF-CONTENT-MISMATCH"
        file_hash = hashlib.sha256(content).hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            statement, transactions = await service.parse_document(
                file_path=Path("mismatch.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=content,
                file_hash=file_hash,
                original_filename="mismatch.pdf",
                db=db,
            )
            db.add(statement)
            for txn in transactions:
                db.add(txn)
        await db.commit()

        await db.execute(delete(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))
        await db.commit()

        await execute_matching(db, user_id=test_user.id, statement_id=statement.id)

        captured = capsys.readouterr()
        assert "Layer 0/2 Count Mismatch" in captured.out
        assert "layer0_count': 1" in captured.out
        assert "layer2_count': 0" in captured.out
