"""E2E test configuration and fixtures for Playwright tests."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest_asyncio
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary
from tests.factories import (
    AtomicTransactionFactory,
    StatementSummaryFactory,
    UploadedDocumentFactory,
)


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
            txn_date=date(2026, 1, 10 + index),
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


@pytest_asyncio.fixture(scope="function")
async def seeded_parsed_statement(db: AsyncSession, test_user) -> SeededParsedStatement:
    """Fixture-seeded, already-parsed statement that bypasses the LLM/OCR provider.

    Enables the no-LLM merge-blocking tier (``-m "... and not llm"``) to run the
    statement review -> reconcile -> report journeys that previously required a
    real provider. See :func:`seed_parsed_statement`.
    """
    return await seed_parsed_statement(db, test_user.id)


@pytest_asyncio.fixture(scope="session")
async def browser() -> AsyncIterator[Browser]:
    """Launch browser instance for the test session."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest_asyncio.fixture(scope="function")
async def context(browser: Browser) -> AsyncIterator[BrowserContext]:
    """Create a new browser context for each test."""
    context = await browser.new_context()
    yield context
    await context.close()


@pytest_asyncio.fixture(scope="function")
async def page(context: BrowserContext) -> AsyncIterator[Page]:
    """Create a new page for each test."""
    page = await context.new_page()
    yield page
    await page.close()
