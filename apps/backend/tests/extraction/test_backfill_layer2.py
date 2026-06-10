"""Tests for EPIC-011 Stage 2 Layer 0 -> Layer 1/2 backfill."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer1 import UploadedDocument
from src.models.layer2 import AtomicTransaction
from src.models.statement import BankStatement, BankStatementTransaction
from src.models.user import User
from src.services.deduplication import backfill_atomic_transactions_from_statements


async def _seed_statement(db: AsyncSession, user_id, *, file_hash: str) -> BankStatement:
    statement = BankStatement(
        user_id=user_id,
        file_path=f"statements/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="legacy.pdf",
        institution="DBS",
        account_last4="1234",
        currency="SGD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )
    db.add(statement)
    await db.flush()
    db.add_all(
        [
            BankStatementTransaction(
                statement_id=statement.id,
                txn_date=date(2024, 1, 15),
                description="Salary Deposit",
                amount=Decimal("3000.00"),
                direction="IN",
                reference="SAL001",
            ),
            BankStatementTransaction(
                statement_id=statement.id,
                txn_date=date(2024, 1, 20),
                description="Rent Payment",
                amount=Decimal("2500.00"),
                direction="OUT",
                reference="RENT001",
            ),
        ]
    )
    await db.commit()
    return statement


@pytest.mark.asyncio
class TestBackfillLayer2:
    async def test_backfill_creates_layer1_and_layer2_from_legacy_statement(self, db, test_user):
        """AC11.14.1: Historical Layer 0 statements are projected into Layer 1/2."""
        await _seed_statement(db, test_user.id, file_hash="hash-backfill-1")

        result = await backfill_atomic_transactions_from_statements(db, user_id=test_user.id)
        await db.commit()

        assert result["statements_scanned"] == 1
        assert result["documents_created"] == 1
        assert result["atomic_transactions_upserted"] == 2
        assert result["statement_summaries_synced"] == 1

        docs = (
            (await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))).scalars().all()
        )
        assert len(docs) == 1
        assert docs[0].file_hash == "hash-backfill-1"

        atomic = (
            (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)))
            .scalars()
            .all()
        )
        assert {t.amount for t in atomic} == {Decimal("3000.00"), Decimal("2500.00")}

    async def test_backfill_is_idempotent(self, db, test_user):
        """AC11.14.2: Re-running the backfill upserts instead of duplicating."""
        await _seed_statement(db, test_user.id, file_hash="hash-backfill-2")

        await backfill_atomic_transactions_from_statements(db, user_id=test_user.id)
        await db.commit()
        second = await backfill_atomic_transactions_from_statements(db, user_id=test_user.id)
        await db.commit()

        # Second pass creates no new Layer 1 doc and inserts no new Layer 2 rows.
        assert second["documents_created"] == 0

        docs = (
            (await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))).scalars().all()
        )
        assert len(docs) == 1

        atomic = (
            (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)))
            .scalars()
            .all()
        )
        assert len(atomic) == 2

    async def test_backfill_scopes_to_requested_user(self, db, test_user):
        """AC11.14.3: User-scoped backfill ignores other users' statements."""
        other_user = User(email=f"other-{uuid4()}@example.com", hashed_password="hashed")
        db.add(other_user)
        await db.flush()
        await _seed_statement(db, other_user.id, file_hash="hash-other-user")
        await _seed_statement(db, test_user.id, file_hash="hash-this-user")

        result = await backfill_atomic_transactions_from_statements(db, user_id=test_user.id)
        await db.commit()

        assert result["statements_scanned"] == 1
        atomic = (
            (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == other_user.id)))
            .scalars()
            .all()
        )
        assert len(atomic) == 0
