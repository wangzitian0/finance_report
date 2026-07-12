"""Tests for transfer detection idempotency in execute_matching (Issue #3).

Verifies that calling execute_matching multiple times for the same pending
transactions does not create duplicate ReconciliationMatch records for the
transfer-detection phase.

Fixtures are built natively on Layer 2: an Account + UploadedDocument +
StatementSummary (carrying the confirmed custody account) plus an
AtomicTransaction whose ``source_documents`` reference the UploadedDocument so
``resolve_custody_account_id`` can resolve the transfer source account.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import DocumentType, UploadedDocument
from src.ledger import Account, AccountType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_enums import BankStatementStatus
from src.models.statement_summary import StatementSummary
from src.reconciliation import ReconciliationMatch, ReconciliationStatus, execute_matching


class TestTransferDetectionIdempotency:
    """Phase 1 transfer detection must not create duplicate matches on re-runs."""

    async def _setup(self, db: AsyncSession, user_id, direction: str = "OUT", file_hash_suffix: str = "1"):
        """Helper: create an account + conform statement + Layer-2 transfer transaction."""
        cash = Account(
            user_id=user_id,
            name="Cash",
            code=f"1001_{direction}_{file_hash_suffix}",
            type=AccountType.ASSET,
            currency="SGD",
        )
        db.add(cash)
        await db.flush()

        file_hash = f"idempotency_hash_{file_hash_suffix}"
        doc = UploadedDocument(
            user_id=user_id,
            file_path=f"/tmp/test_{file_hash_suffix}.pdf",
            file_hash=file_hash,
            original_filename="test.pdf",
            document_type=DocumentType.BANK_STATEMENT,
        )
        db.add(doc)
        await db.flush()

        summary = StatementSummary(
            user_id=user_id,
            account_id=cash.id,
            uploaded_document_id=doc.id,
            file_hash=file_hash,
            institution="TestBank",
            account_last4="1234",
            currency="SGD",
            status=BankStatementStatus.PARSED,
        )
        db.add(summary)
        await db.flush()

        txn = AtomicTransaction(
            user_id=user_id,
            txn_date=date(2025, 3, 1),
            description="TRANSFER TO SAVINGS",
            amount=Decimal("500.00"),
            direction=TransactionDirection(direction),
            currency="SGD",
            dedup_hash=uuid4().hex + uuid4().hex,
            source_documents=[{"doc_id": str(doc.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
        )
        db.add(txn)
        await db.flush()
        return summary, txn

    async def test_transfer_out_duplicate_detection_skipped(self, db: AsyncSession, test_user):
        """AC-ledger.76.7 · Running matching twice for transfer-OUT should not create a second match."""
        user_id = test_user.id
        _, txn = await self._setup(db, user_id, direction="OUT", file_hash_suffix="idem_out")

        # First run - creates the match
        matches_first = await execute_matching(db, user_id=user_id)
        assert len(matches_first) == 1, "First run should produce exactly one match"

        # Second run - should detect the existing match and skip
        matches_second = await execute_matching(db, user_id=user_id)

        # Verify: at most 0 new matches created (idempotency)
        assert len(matches_second) == 0, (
            f"Second run should produce no new matches (idempotent), got {len(matches_second)}"
        )

        # Verify: still only one active (non-superseded) match in DB for this txn.
        all_matches_result = await db.execute(
            select(ReconciliationMatch).where(
                ReconciliationMatch.atomic_txn_id == txn.id,
                ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            )
        )
        active_matches = all_matches_result.scalars().all()
        assert len(active_matches) == 1, (
            f"Expected exactly 1 active match in DB after two runs, found {len(active_matches)}"
        )

    async def test_transfer_in_duplicate_detection_skipped(self, db: AsyncSession, test_user):
        """AC-ledger.76.7 · Running matching twice for transfer-IN should not create a second match."""
        user_id = test_user.id
        _, txn = await self._setup(db, user_id, direction="IN", file_hash_suffix="idem_in")

        # First run
        matches_first = await execute_matching(db, user_id=user_id)
        assert len(matches_first) == 1, "First run should produce exactly one match"

        # Second run
        matches_second = await execute_matching(db, user_id=user_id)
        assert len(matches_second) == 0, (
            f"Second run should produce no new matches (idempotent), got {len(matches_second)}"
        )

        # Verify: only one non-superseded match for this txn.
        all_matches_result = await db.execute(
            select(ReconciliationMatch).where(
                ReconciliationMatch.atomic_txn_id == txn.id,
                ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            )
        )
        active_matches = all_matches_result.scalars().all()
        assert len(active_matches) == 1, f"Expected 1 active match in DB, found {len(active_matches)}"
