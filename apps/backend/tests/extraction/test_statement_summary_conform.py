"""Tests for the StatementSummary conform sync + custody-account resolver (EPIC-011 PR-A)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement import BankStatement, BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary
from src.services.statement_summary import resolve_custody_account_id, sync_statement_summary


async def _make_account(db: AsyncSession, user_id) -> Account:
    account = Account(user_id=user_id, name="DBS Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    return account


async def _make_statement(db: AsyncSession, user_id, *, file_hash: str, account_id=None) -> BankStatement:
    statement = BankStatement(
        user_id=user_id,
        account_id=account_id,
        file_path=f"statements/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="dbs.pdf",
        institution="DBS",
        account_last4="1234",
        currency="SGD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1500.00"),
        status=BankStatementStatus.APPROVED,
        stage1_status=Stage1Status.APPROVED,
        balance_validated=True,
    )
    db.add(statement)
    await db.flush()
    return statement


@pytest.mark.asyncio
class TestStatementSummaryConform:
    async def test_sync_mirrors_bank_statement_envelope(self, db, test_user):
        """AC11.15.1: sync projects the BankStatement envelope into StatementSummary."""
        account = await _make_account(db, test_user.id)
        await _make_statement(db, test_user.id, file_hash="hash-sum-1", account_id=account.id)
        statement = (
            await db.execute(select(BankStatement).where(BankStatement.file_hash == "hash-sum-1"))
        ).scalar_one()

        summary = await sync_statement_summary(db, statement)
        await db.commit()

        assert summary.user_id == test_user.id
        assert summary.file_hash == "hash-sum-1"
        assert summary.account_id == account.id
        assert summary.institution == "DBS"
        assert summary.period_start == date(2024, 1, 1)
        assert summary.closing_balance == Decimal("1500.00")
        assert summary.status == BankStatementStatus.APPROVED
        assert summary.balance_validated is True

    async def test_sync_is_idempotent_and_links_uploaded_document(self, db, test_user):
        """AC11.15.2: re-sync updates in place and links the UploadedDocument when present."""
        account = await _make_account(db, test_user.id)
        statement = await _make_statement(db, test_user.id, file_hash="hash-sum-2", account_id=None)
        doc = UploadedDocument(
            user_id=test_user.id,
            file_path="statements/hash-sum-2.pdf",
            file_hash="hash-sum-2",
            original_filename="dbs.pdf",
            document_type=DocumentType.BANK_STATEMENT,
        )
        db.add(doc)
        await db.flush()

        # First sync: no account yet.
        await sync_statement_summary(db, statement)
        await db.commit()

        # Confirm sets the custody account; re-sync should update in place.
        statement.account_id = account.id
        await sync_statement_summary(db, statement)
        await db.commit()

        summaries = (
            (await db.execute(select(StatementSummary).where(StatementSummary.user_id == test_user.id))).scalars().all()
        )
        assert len(summaries) == 1
        assert summaries[0].account_id == account.id
        assert summaries[0].uploaded_document_id == doc.id

    async def test_resolve_custody_account_from_atomic_txn(self, db, test_user):
        """AC11.15.3: custody account resolves from an atomic txn via the conform (DWD-native)."""
        account = await _make_account(db, test_user.id)
        statement = await _make_statement(db, test_user.id, file_hash="hash-sum-3", account_id=account.id)
        doc = UploadedDocument(
            user_id=test_user.id,
            file_path="statements/hash-sum-3.pdf",
            file_hash="hash-sum-3",
            original_filename="dbs.pdf",
            document_type=DocumentType.BANK_STATEMENT,
        )
        db.add(doc)
        await db.flush()
        await sync_statement_summary(db, statement)

        atomic = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("500.00"),
            direction=TransactionDirection.OUT,
            description="TRANSFER TO SAVINGS",
            currency="SGD",
            dedup_hash="dedup-sum-3",
            source_documents=[{"doc_id": str(doc.id), "doc_type": "bank_statement"}],
        )
        db.add(atomic)
        await db.commit()

        resolved = await resolve_custody_account_id(db, atomic)
        assert resolved == account.id

    async def test_resolve_returns_none_without_account(self, db, test_user):
        """AC11.15.4: resolver returns None when the source statement has no custody account."""
        atomic = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("500.00"),
            direction=TransactionDirection.OUT,
            description="UNKNOWN",
            currency="SGD",
            dedup_hash="dedup-none",
            source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}],
        )
        db.add(atomic)
        await db.commit()

        assert await resolve_custody_account_id(db, atomic) is None
