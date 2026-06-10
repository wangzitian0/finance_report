"""Tests for transfer detection idempotency in execute_matching (Issue #3).

Verifies that calling execute_matching multiple times for the same pending
transactions does not create duplicate ReconciliationMatch records for the
transfer-detection phase.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementTransaction,
    BankTransactionStatus,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.services.reconciliation import execute_matching


class TestTransferDetectionIdempotency:
    """Phase 1 transfer detection must not create duplicate matches on re-runs."""

    async def _setup(self, db: AsyncSession, user_id, direction: str = "OUT", file_hash_suffix: str = "1"):
        """Helper: create a statement + transfer transaction."""
        cash = Account(
            user_id=user_id,
            name="Cash",
            code=f"1001_{direction}_{file_hash_suffix}",
            type=AccountType.ASSET,
            currency="SGD",
        )
        db.add(cash)
        await db.flush()

        statement = BankStatement(
            user_id=user_id,
            file_path=f"/tmp/test_{file_hash_suffix}.pdf",
            file_hash=f"idempotency_hash_{file_hash_suffix}",
            original_filename="test.pdf",
            institution="TestBank",
            account_id=cash.id,
        )
        db.add(statement)
        await db.flush()

        txn = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date(2025, 3, 1),
            description="TRANSFER TO SAVINGS",
            amount=Decimal("500.00"),
            direction=direction,
            status=BankTransactionStatus.PENDING,
        )
        db.add(txn)
        await db.flush()
        return statement, txn

    @pytest.mark.asyncio
    async def test_transfer_out_duplicate_detection_skipped(self, db: AsyncSession, test_user):
        """AC15.6.7 · Running matching twice for transfer-OUT should not create a second match."""
        user_id = test_user.id
        statement, txn = await self._setup(db, user_id, direction="OUT", file_hash_suffix="idem_out")

        # First run - creates the match
        matches_first = await execute_matching(db, user_id=user_id, statement_id=statement.id)
        assert len(matches_first) == 1, "First run should produce exactly one match"

        # Reset transaction status to PENDING so the second run picks it up
        txn.status = BankTransactionStatus.PENDING
        await db.flush()

        # Second run - should detect the existing match and skip
        matches_second = await execute_matching(db, user_id=user_id, statement_id=statement.id)

        # Verify: at most 0 new matches created (idempotency)
        assert len(matches_second) == 0, (
            f"Second run should produce no new matches (idempotent), got {len(matches_second)}"
        )

        # Verify: still only one active (non-superseded) match in DB for this txn
        all_matches_result = await db.execute(
            select(ReconciliationMatch).where(
                ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            )
        )
        active_matches = all_matches_result.scalars().all()
        assert len(active_matches) == 1, (
            f"Expected exactly 1 active match in DB after two runs, found {len(active_matches)}"
        )

    @pytest.mark.asyncio
    async def test_transfer_in_duplicate_detection_skipped(self, db: AsyncSession, test_user):
        """AC15.6.7 · Running matching twice for transfer-IN should not create a second match."""
        user_id = test_user.id
        statement, txn = await self._setup(db, user_id, direction="IN", file_hash_suffix="idem_in")

        # First run
        matches_first = await execute_matching(db, user_id=user_id, statement_id=statement.id)
        assert len(matches_first) == 1, "First run should produce exactly one match"

        # Reset to PENDING
        txn.status = BankTransactionStatus.PENDING
        await db.flush()

        # Second run
        matches_second = await execute_matching(db, user_id=user_id, statement_id=statement.id)
        assert len(matches_second) == 0, (
            f"Second run should produce no new matches (idempotent), got {len(matches_second)}"
        )

        # Verify: only one non-superseded match for this txn
        all_matches_result = await db.execute(
            select(ReconciliationMatch).where(
                ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            )
        )
        active_matches = all_matches_result.scalars().all()
        assert len(active_matches) == 1, f"Expected 1 active match in DB, found {len(active_matches)}"
