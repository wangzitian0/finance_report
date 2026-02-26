"""Test data factories using factory_boy pattern.

Provides reusable factories for creating test data with sensible defaults.
Reduces boilerplate and improves test maintainability.

Usage:
    # Simple creation
    account = AccountFactory.build()

    # With overrides
    account = AccountFactory.build(name="My Savings", currency="USD")

    # Create and flush to DB (transaction not committed)
    account = await AccountFactory.create_async(db, name="Cash")
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TypeVar
from uuid import UUID, uuid4

import factory
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.models.statement import BankStatement, BankStatementStatus, BankStatementTransaction
from src.models.user import User

T = TypeVar("T")


class AsyncFactoryMixin:
    """Mixin providing async database persistence for factories.

    Centralizes the common create_async pattern to avoid code duplication.
    Subclasses should override _build_kwargs() if they need to inject required fields.
    """

    @classmethod
    def _build_kwargs(cls, *args, **kwargs) -> dict:
        """Override this to inject required fields before build().

        Example:
            def _build_kwargs(cls, user_id: UUID, **kwargs):
                return {"user_id": user_id, **kwargs}
        """
        return kwargs

    @classmethod
    async def create_async(cls, db: AsyncSession, *args, **kwargs) -> T:
        """Create and flush to database (transaction not committed)."""
        build_kwargs = cls._build_kwargs(*args, **kwargs)
        instance = cls.build(**build_kwargs)
        db.add(instance)
        await db.flush()
        await db.refresh(instance)
        return instance


class UserFactory(factory.Factory, AsyncFactoryMixin):
    class Meta:
        model = User

    id = factory.LazyFunction(uuid4)
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    name = factory.Sequence(lambda n: f"User {n}")
    hashed_password = "hashed_test_password"
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))


class AccountFactory(factory.Factory, AsyncFactoryMixin):
    class Meta:
        model = Account

    id = factory.LazyFunction(uuid4)
    name = factory.Sequence(lambda n: f"Account {n}")
    type = AccountType.ASSET
    currency = "SGD"
    is_active = True
    description = None
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _build_kwargs(cls, user_id: UUID, **kwargs) -> dict:
        return {"user_id": user_id, **kwargs}


class JournalEntryFactory(factory.Factory, AsyncFactoryMixin):
    class Meta:
        model = JournalEntry

    id = factory.LazyFunction(uuid4)
    entry_date = factory.LazyFunction(lambda: date.today())
    memo = factory.Sequence(lambda n: f"Transaction {n}")
    status = JournalEntryStatus.POSTED
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _build_kwargs(cls, user_id: UUID, **kwargs) -> dict:
        return {"user_id": user_id, **kwargs}

    @classmethod
    async def create_balanced_async(
        cls, db: AsyncSession, user_id: UUID, amount: Decimal = Decimal("100.00"), **kwargs
    ) -> tuple[JournalEntry, Account, Account]:
        """Create a balanced journal entry with two lines (debit + credit).

        Args:
            db: Database session
            user_id: User ID
            amount: Transaction amount (default 100.00)
            **kwargs: Additional JournalEntry fields to override

        Returns:
            Tuple of (entry, debit_account, credit_account)
        """
        debit_account = await AccountFactory.create_async(db, user_id=user_id, type=AccountType.ASSET, name="Cash")
        credit_account = await AccountFactory.create_async(db, user_id=user_id, type=AccountType.INCOME, name="Revenue")

        entry = await cls.create_async(db, user_id=user_id, **kwargs)

        debit_line = JournalLine(
            id=uuid4(),
            journal_entry_id=entry.id,
            account_id=debit_account.id,
            direction=Direction.DEBIT,
            amount=amount,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        credit_line = JournalLine(
            id=uuid4(),
            journal_entry_id=entry.id,
            account_id=credit_account.id,
            direction=Direction.CREDIT,
            amount=amount,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        db.add(debit_line)
        db.add(credit_line)
        await db.flush()
        await db.refresh(entry)

        return entry, debit_account, credit_account


class JournalLineFactory(factory.Factory, AsyncFactoryMixin):
    class Meta:
        model = JournalLine

    id = factory.LazyFunction(uuid4)
    direction = Direction.DEBIT
    amount = Decimal("100.00")
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _build_kwargs(cls, entry_id: UUID, account_id: UUID, **kwargs) -> dict:
        return {"entry_id": entry_id, "account_id": account_id, **kwargs}


class BankStatementFactory(factory.Factory, AsyncFactoryMixin):
    class Meta:
        model = BankStatement

    id = factory.LazyFunction(uuid4)
    institution = factory.Sequence(lambda n: f"Bank {n}")
    account_last4 = factory.Sequence(lambda n: f"{n:04d}")
    original_filename = factory.Sequence(lambda n: f"statement_{n}.pdf")
    file_path = factory.Sequence(lambda n: f"s3://statements/statement_{n}.pdf")
    file_hash = factory.LazyFunction(lambda: uuid4().hex)
    currency = "SGD"
    status = BankStatementStatus.UPLOADED
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _build_kwargs(cls, user_id: UUID, **kwargs) -> dict:
        return {"user_id": user_id, **kwargs}


class BankStatementTransactionFactory(factory.Factory, AsyncFactoryMixin):
    class Meta:
        model = BankStatementTransaction

    id = factory.LazyFunction(uuid4)
    txn_date = factory.LazyFunction(lambda: date.today())
    description = factory.Sequence(lambda n: f"Transaction {n}")
    amount = Decimal("50.00")
    direction = "DR"
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _build_kwargs(cls, statement_id: UUID, **kwargs) -> dict:
        return {"statement_id": statement_id, **kwargs}


class ReconciliationMatchFactory(factory.Factory, AsyncFactoryMixin):
    class Meta:
        model = ReconciliationMatch

    id = factory.LazyFunction(uuid4)
    match_score = 95
    score_breakdown = {"amount": 1.0, "date": 0.9, "description": 0.85}
    status = ReconciliationStatus.PENDING_REVIEW
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _build_kwargs(cls, bank_txn_id: UUID, journal_entry_ids: list[str], **kwargs) -> dict:
        return {"bank_txn_id": bank_txn_id, "journal_entry_ids": journal_entry_ids, **kwargs}
