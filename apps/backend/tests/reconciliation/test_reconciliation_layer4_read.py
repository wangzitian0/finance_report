"""AC4.4.1: Reconciliation Layer 2 Read Tests

These tests validate Phase 4 Layer 2 Read functionality
including atomic transaction creation from bank transactions, linking to accounts,
dual-write mode behavior, and Layer 2 status transitions.
Tests verify atomic transaction guarantees, proper account linking,
and correct status state management in the reconciliation layer architecture.
"""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import settings
from src.models import (
    Account,
    AccountType,
    AtomicTransaction,
    BankStatementTransaction,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ReconciliationStatus,
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
class TestReconciliationLayer4Read:
    """Tests for Phase 4 Layer 2 Read in reconciliation."""

    async def _create_candidate_entry(self, db, user_id):
        """Helper to create a matching journal entry."""
        account = Account(
            user_id=user_id,
            name="Bank",
            type=AccountType.ASSET,
            currency="SGD",
            code="1000",
        )
        db.add(account)
        await db.flush()

        entry = JournalEntry(
            user_id=user_id,
            entry_date=date(2024, 1, 15),
            memo="Salary Deposit",
            status=JournalEntryStatus.POSTED,
            source_type="manual",
        )
        db.add(entry)
        await db.flush()

        line1 = JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.DEBIT,
            amount=Decimal("500.00"),
            currency="SGD",
        )
        line2 = JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.CREDIT,
            amount=Decimal("500.00"),
            currency="SGD",
        )
        db.add_all([line1, line2])
        await db.commit()
        return entry

    async def test_reconciliation_reads_layer2(self, db, test_user, mock_ai_response, monkeypatch, capsys):
        """Test that reconciliation uses AtomicTransaction when enabled."""
        await self._create_candidate_entry(db, test_user.id)

        # 1. Enable Dual Write AND Layer 4 Read
        monkeypatch.setattr(settings, "enable_4_layer_write", True)
        monkeypatch.setattr(settings, "enable_4_layer_read", True)

        service = ExtractionService()
        content = b"PDF-CONTENT-L4"
        file_hash = hashlib.sha256(content).hexdigest()

        # Parse document to generate Layer 2 data
        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            statement, transactions = await service.parse_document(
                file_path=Path("test_l4.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=content,
                file_hash=file_hash,
                original_filename="test_l4.pdf",
                db=db,
            )
            # Add Layer 0 objects to session (even though we shouldn't use them)
            db.add(statement)
            for txn in transactions:
                db.add(txn)
        await db.commit()

        # 2. Run Reconciliation
        matches = await execute_matching(db, user_id=test_user.id)

        # 3. Verify matches link to AtomicTransaction
        assert len(matches) == 1
        match = matches[0]
        assert match.atomic_txn_id is not None
        assert match.bank_txn_id is None
        assert match.status in (
            ReconciliationStatus.AUTO_ACCEPTED,
            ReconciliationStatus.PENDING_REVIEW,
        )

        # Verify linked AtomicTransaction
        atomic_txn = await db.get(AtomicTransaction, match.atomic_txn_id)
        assert atomic_txn.amount == Decimal("500.00")
        assert atomic_txn.description == "Salary Deposit"

        # 4. Verify Layer 0 Status is UNTOUCHED (still PENDING)
        # Because we skipped status updates in Layer 4 mode
        l0_txn = await db.get(BankStatementTransaction, transactions[0].id)
        # Wait, if status is default PENDING, it remains PENDING.
        from src.models import BankStatementTransactionStatus

        assert l0_txn.status == BankStatementTransactionStatus.PENDING

    async def test_reconciliation_idempotency_layer2(self, db, test_user, mock_ai_response, monkeypatch):
        """Test that already matched Layer 2 transactions are skipped."""
        await self._create_candidate_entry(db, test_user.id)

        monkeypatch.setattr(settings, "enable_4_layer_write", True)
        monkeypatch.setattr(settings, "enable_4_layer_read", True)

        # ... setup data ...
        service = ExtractionService()
        content = b"PDF-CONTENT-L4-IDEM"
        file_hash = hashlib.sha256(content).hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            statement, transactions = await service.parse_document(
                file_path=Path("test_l4_idem.pdf"),
                institution="DBS",
                user_id=test_user.id,
                file_content=content,
                file_hash=file_hash,
                original_filename="test_l4_idem.pdf",
                db=db,
            )
            db.add(statement)
            for txn in transactions:
                db.add(txn)
        await db.commit()

        # Run once
        matches1 = await execute_matching(db, user_id=test_user.id)
        assert len(matches1) == 1

        # Run again
        matches2 = await execute_matching(db, user_id=test_user.id)
        assert len(matches2) == 0  # Should be skipped because matched
