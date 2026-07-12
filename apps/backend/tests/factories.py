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

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TypeVar
from uuid import UUID, uuid4

import factory
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import DocumentType, UploadedDocument
from src.identity import User
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary

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


class UploadedDocumentFactory(factory.Factory, AsyncFactoryMixin):
    """Layer 1 (ODS) raw-document landing — the durable source kept after Stage 3."""

    class Meta:
        model = UploadedDocument

    id = factory.LazyFunction(uuid4)
    file_path = factory.Sequence(lambda n: f"statements/doc_{n}.pdf")
    file_hash = factory.LazyFunction(lambda: uuid4().hex)
    original_filename = factory.Sequence(lambda n: f"statement_{n}.pdf")
    document_type = DocumentType.BANK_STATEMENT
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _build_kwargs(cls, user_id: UUID, **kwargs) -> dict:
        return {"user_id": user_id, **kwargs}


class StatementSummaryFactory(factory.Factory, AsyncFactoryMixin):
    """DWD conform envelope — the statement metadata table that replaces BankStatement."""

    class Meta:
        model = StatementSummary

    id = factory.LazyFunction(uuid4)
    file_hash = factory.LazyFunction(lambda: uuid4().hex)
    institution = factory.Sequence(lambda n: f"Bank {n}")
    account_last4 = factory.Sequence(lambda n: f"{n:04d}")
    currency = "SGD"
    status = BankStatementStatus.UPLOADED
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _build_kwargs(cls, user_id: UUID, **kwargs) -> dict:
        return {"user_id": user_id, **kwargs}


class AtomicTransactionFactory(factory.Factory, AsyncFactoryMixin):
    """Layer 2 deduplicated transaction fact."""

    class Meta:
        model = AtomicTransaction

    id = factory.LazyFunction(uuid4)
    txn_date = factory.LazyFunction(date.today)
    description = factory.Sequence(lambda n: f"Transaction {n}")
    amount = Decimal("50.00")
    direction = TransactionDirection.OUT
    reference = None
    currency = "SGD"
    # Unique by default so factory-built rows never collide; dedup tests override this.
    dedup_hash = factory.LazyFunction(lambda: uuid4().hex + uuid4().hex)
    created_at = factory.LazyFunction(lambda: datetime.now(UTC))
    updated_at = factory.LazyFunction(lambda: datetime.now(UTC))

    @classmethod
    def _build_kwargs(cls, user_id: UUID, *, source_doc_id: UUID | None = None, **kwargs) -> dict:
        source_documents = kwargs.pop(
            "source_documents",
            [{"doc_id": str(source_doc_id or uuid4()), "doc_type": DocumentType.BANK_STATEMENT.value}],
        )
        return {"user_id": user_id, "source_documents": source_documents, **kwargs}


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
    def _build_kwargs(cls, atomic_txn_id: UUID, journal_entry_ids: list[str], **kwargs) -> dict:
        return {"atomic_txn_id": atomic_txn_id, "journal_entry_ids": journal_entry_ids, **kwargs}


# ---------------------------------------------------------------------------
# Seeded no-LLM parsed statement (EPIC-008 / AC8.21)
# ---------------------------------------------------------------------------


@dataclass
class SeededParsedStatement:
    """Handle for a fixture-seeded, already-parsed statement.

    Carries the layered DWD records (ODS document, conform envelope, atomic
    transactions) injected directly into the test database so the downstream
    review -> reconcile -> report journeys can run with **zero provider calls**.
    The provider/LLM extraction seam (``ExtractionService.parse_document`` ->
    ``stream_ai_json``) is bypassed entirely: the parsed result is materialized
    by hand, exactly as the extraction pipeline would have persisted it.
    """

    user_id: UUID
    document: UploadedDocument
    statement: StatementSummary
    transactions: list[AtomicTransaction] = field(default_factory=list)

    @property
    def id(self) -> UUID:
        """The statement (DWD conform) id, as the statements API addresses it."""
        return self.statement.id

    @property
    def original_filename(self) -> str:
        """The ODS filename the statement-list row link renders (#1142)."""
        return self.document.original_filename


async def seed_parsed_statement(
    db: AsyncSession,
    user_id: UUID,
    *,
    institution: str = "DBS",
    original_filename: str = "dbs_statement_2026_01.pdf",
    opening_balance: Decimal = Decimal("1000.00"),
    transactions: list[dict] | None = None,
) -> SeededParsedStatement:
    """Inject an already-parsed statement into the database (no provider call).

    Seeds the three layered records the extraction pipeline would have written:

    * ODS ``UploadedDocument`` — carries ``original_filename`` (the field the
      statement-list stretched-link row renders; empty during real parsing,
      which is the #1142 invisible-link bug).
    * DWD ``StatementSummary`` — ``status=PARSED`` / ``stage1_status=PENDING_REVIEW``
      conform envelope, linked to the ODS document.
    * Layer-2 ``AtomicTransaction`` rows — joined back to the statement via
      ``source_documents[*].doc_id == uploaded_document_id`` (the exact join
      ``resolve_statement_transactions`` performs).

    Returns a :class:`SeededParsedStatement` handle. All amounts use ``Decimal``
    (never ``float``) per the monetary red line.
    """
    rows = (
        transactions
        if transactions is not None
        else [
            {"description": "Salary", "amount": Decimal("5000.00"), "direction": TransactionDirection.IN},
            {"description": "Coffee Shop", "amount": Decimal("5.00"), "direction": TransactionDirection.OUT},
        ]
    )

    file_hash = uuid4().hex + uuid4().hex[:32]
    document = await UploadedDocumentFactory.create_async(
        db,
        user_id=user_id,
        file_hash=file_hash,
        original_filename=original_filename,
        document_type=DocumentType.BANK_STATEMENT,
    )

    # Compute the closing balance from the seeded movements so the balance chain
    # (open + ΣIN − ΣOUT ≈ close) ties out without any provider involvement.
    closing_balance = opening_balance
    for row in rows:
        if row["direction"] == TransactionDirection.IN:
            closing_balance += row["amount"]
        else:
            closing_balance -= row["amount"]

    statement = await StatementSummaryFactory.create_async(
        db,
        user_id=user_id,
        file_hash=file_hash,
        uploaded_document_id=document.id,
        institution=institution,
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        status=BankStatementStatus.PARSED,
        stage1_status=Stage1Status.PENDING_REVIEW,
        confidence_score=95,
    )

    doc_marker = {"doc_id": str(document.id), "doc_type": DocumentType.BANK_STATEMENT.value}
    base_date = date(2026, 1, 10)
    seeded_txns: list[AtomicTransaction] = []
    running_balance = opening_balance
    for index, row in enumerate(rows):
        if row["direction"] == TransactionDirection.IN:
            running_balance += row["amount"]
        else:
            running_balance -= row["amount"]
        txn = await AtomicTransactionFactory.create_async(
            db,
            user_id=user_id,
            source_documents=[doc_marker],
            # A row may carry its own date (corpus rows preserve the source
            # statement's same-day duplicates, #1254); otherwise the timedelta
            # keeps the date valid for any transaction count (avoids
            # day-overflow once index pushes past the month end).
            txn_date=row.get("date") or (base_date + timedelta(days=index)),
            description=row["description"],
            amount=row["amount"],
            direction=row["direction"],
            currency="SGD",
            balance_after=running_balance,
        )
        seeded_txns.append(txn)

    await db.commit()
    return SeededParsedStatement(
        user_id=user_id,
        document=document,
        statement=statement,
        transactions=seeded_txns,
    )
