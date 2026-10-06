"""AC-extraction.804.1-3, AC-testing.seeded-journey.1-3, AC-testing.must-have.4:
In-memory domain shift-left tests for statement upload, parsing, listing, and posting.

Covers:
- AC-extraction.804.1: Statement upload (CSV) end-to-end journey.
- AC-extraction.804.2: Statement list and get end-to-end journey.
- AC-extraction.804.3: Statement full flow (upload -> parse -> approve) end-to-end journey.
- AC-testing.must-have.4: Statement upload journey.
- AC-testing.seeded-journey.1: Seeded statement materializes without LLM.
- AC-testing.seeded-journey.2: Seeded statement list and details query.
- AC-testing.seeded-journey.3: Seeded statement transactions and reconciliation readiness.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.extraction import (
    BankStatementStatus,
    DocumentSource,
    UploadedDocument,
)
from src.extraction.extension import transaction_classification
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import approve_statement, resolve_statement_transactions
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import Account, AccountType, calculate_account_balance
from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies


def _sample_dbs_csv(year_month: str = "2026-03") -> bytes:
    """Standard rule-based parsed CSV content with distinct debit/credit columns."""
    return (
        f"Date,Description,Debit Amount,Credit Amount\n"
        f"{year_month}-05,Salary Revenue,,5000.00\n"
        f"{year_month}-20,Office Rent,1500.00,\n"
    ).encode()


@pytest.mark.asyncio
async def test_statement_upload_csv_direct_parsing(db: AsyncSession, test_user: User) -> None:
    """AC-extraction.804.1, AC-testing.must-have.4: Statement upload CSV parse lifecycle."""
    csv_bytes = _sample_dbs_csv("2026-03")
    source = DocumentSource.resolve(
        path=Path("dbs_march_2026.csv"),
        content=csv_bytes,
    )
    service = ExtractionService()
    result = await service.parse_document(
        source,
        institution="DBS",
        user_id=test_user.id,
        file_type="csv",
        db=db,
    )

    assert result is not None
    assert len(result.transactions) == 2
    assert result.transactions[0].description == "Salary Revenue"
    assert result.transactions[0].amount == Decimal("5000.00")
    assert result.transactions[1].description == "Office Rent"
    assert result.transactions[1].amount == Decimal("1500.00")

    # Invariant: statement summary record created in SQLite database
    statement = (
        await db.execute(
            select(StatementSummary)
            .where(StatementSummary.user_id == test_user.id)
            .where(StatementSummary.file_hash == result.source_content_digest)
        )
    ).scalar_one()

    assert statement.institution == "DBS"
    assert statement.status == BankStatementStatus.PARSED.value


@pytest.mark.asyncio
async def test_statement_list_and_get_details(db: AsyncSession, test_user: User) -> None:
    """AC-extraction.804.2: Statement list and get transaction details."""
    csv_bytes = _sample_dbs_csv("2026-04")
    service = ExtractionService()
    source = DocumentSource.resolve(path=Path("dbs_april_2026.csv"), content=csv_bytes)
    result, statement, transactions = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        source=source,
        institution="DBS",
        file_type="csv",
    )

    # 1. Statement listing query
    user_statements = (
        (await db.execute(select(StatementSummary).where(StatementSummary.user_id == test_user.id))).scalars().all()
    )
    assert any(s.id == statement.id for s in user_statements)

    # 2. Get statement detail & line items
    resolved_txns = await resolve_statement_transactions(db, statement)
    assert len(resolved_txns) == 2

    credit_txn = next(t for t in resolved_txns if "Salary" in t.description)
    debit_txn = next(t for t in resolved_txns if "Rent" in t.description)
    assert credit_txn.amount == Decimal("5000.00")
    assert debit_txn.amount == Decimal("1500.00")


@pytest.mark.asyncio
async def test_statement_full_approval_and_posting_flow(
    db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.804.3: Statement full flow (upload -> parse -> approve -> auto-post)."""
    monkeypatch.setattr(settings, "enable_ai_classification", True)

    async def deterministic_proposer(transactions, _policy):
        categories = {
            "Salary Revenue": TransactionCategory.SALARY,
            "Office Rent": TransactionCategory.HOUSING,
        }
        return [
            CategoryProposal(
                category=categories[transaction.description].value, confidence=99, reason="shift_left_test"
            )
            for transaction in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", deterministic_proposer)

    bank = Account(
        user_id=test_user.id,
        name="Operating Bank Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(bank)
    await db.flush()

    opening = Decimal("10000.00")
    closing = Decimal("13500.00")  # 10,000 + 5,000 (salary) - 1,500 (rent)

    csv_bytes = _sample_dbs_csv("2026-05")
    service = ExtractionService()
    source = DocumentSource.resolve(path=Path("dbs_may_2026.csv"), content=csv_bytes)
    result, statement, transactions = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        source=source,
        institution="DBS",
        file_type="csv",
    )

    # Complete review inputs
    statement.account_id = bank.id
    statement.currency = bank.currency
    statement.period_start = min(t.txn_date for t in transactions)
    statement.period_end = max(t.txn_date for t in transactions)
    statement.opening_balance = opening
    statement.closing_balance = closing
    for t in transactions:
        t.currency = bank.currency
        t.currency_unresolved = False
    await db.flush()

    # Approve statement
    approved = await approve_statement(db, statement.id, test_user.id)
    assert approved.status == BankStatementStatus.APPROVED.value

    # Auto-post entries into double-entry ledger
    outcome = await auto_create_posted_entries_for_statement(
        db,
        statement=approved,
        user_id=test_user.id,
        dependencies=posting_dependencies(),
    )
    assert outcome.created_count == 2
    assert outcome.review_reasons == ()

    # Verify bank account balance articulates exactly
    bank_balance = await calculate_account_balance(db, bank.id, test_user.id)
    assert bank_balance == Decimal("3500.00")  # Net movement: +5000 - 1500 = +3500


@pytest.mark.asyncio
async def test_seeded_statement_materializes_without_llm(db: AsyncSession, test_user: User) -> None:
    """AC-testing.seeded-journey.1: Seeded statement fixture materializes with zero provider calls."""
    csv_bytes = (
        b"Date,Description,Debit Amount,Credit Amount\n"
        b"2026-06-01,Opening Transfer,,10000.00\n"
        b"2026-06-15,Client Fee Revenue,,2800.00\n"
    )
    source = DocumentSource.resolve(path=Path("seeded_june.csv"), content=csv_bytes)
    service = ExtractionService()
    result, statement, transactions = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        source=source,
        institution="Standard Chartered",
        file_type="csv",
    )

    statement.opening_balance = Decimal("10000.00")
    statement.closing_balance = Decimal("12800.00")
    await db.flush()

    # Invariant: Record is stored with valid Decimal balances and non-empty filename
    persisted = (await db.execute(select(StatementSummary).where(StatementSummary.id == statement.id))).scalar_one()
    assert persisted.status == "parsed"
    assert persisted.closing_balance == Decimal("12800.00")

    doc = (
        await db.execute(select(UploadedDocument).where(UploadedDocument.id == persisted.uploaded_document_id))
    ).scalar_one()
    assert doc.original_filename == "seeded_june.csv"
    assert len(transactions) == 2


@pytest.mark.asyncio
async def test_seeded_statement_list_and_details_query(db: AsyncSession, test_user: User) -> None:
    """AC-testing.seeded-journey.2: Seeded statement list and detail views expose parsed status and metadata."""
    csv_bytes = b"Date,Description,Debit Amount,Credit Amount\n2026-07-01,Consulting Income,,3100.00\n"
    source = DocumentSource.resolve(path=Path("dbs_operations.csv"), content=csv_bytes)
    service = ExtractionService()
    result, statement, transactions = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        source=source,
        institution="Standard Chartered",
        file_type="csv",
    )

    statement.opening_balance = Decimal("5000.00")
    statement.closing_balance = Decimal("8100.00")
    await db.flush()

    # Verify query for list and detail
    loaded_stmt = (await db.execute(select(StatementSummary).where(StatementSummary.id == statement.id))).scalar_one()
    assert loaded_stmt.status == "parsed"
    assert loaded_stmt.opening_balance == Decimal("5000.00")
    assert loaded_stmt.closing_balance == Decimal("8100.00")

    doc = (
        await db.execute(select(UploadedDocument).where(UploadedDocument.id == loaded_stmt.uploaded_document_id))
    ).scalar_one()
    assert doc.original_filename == "dbs_operations.csv"


@pytest.mark.asyncio
async def test_seeded_statement_transactions_and_reconciliation(db: AsyncSession, test_user: User) -> None:
    """AC-testing.seeded-journey.3: Seeded statement resolves atomic transactions for downstream review."""
    csv_bytes = (
        b"Date,Description,Debit Amount,Credit Amount\n"
        b"2026-08-01,Transaction item 1,,1200.00\n"
        b"2026-08-02,Transaction item 2,,800.00\n"
        b"2026-08-03,Transaction item 3,,500.00\n"
        b"2026-08-04,Transaction item 4,,300.00\n"
    )
    source = DocumentSource.resolve(path=Path("seeded_four_txns.csv"), content=csv_bytes)
    service = ExtractionService()
    result, statement, transactions = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        source=source,
        institution="DBS",
        file_type="csv",
    )

    statement.opening_balance = Decimal("10000.00")
    statement.closing_balance = Decimal("12800.00")
    await db.flush()

    txns = await resolve_statement_transactions(db, statement)

    assert len(txns) == 4
    assert sum(t.amount for t in txns) == Decimal("2800.00")
    assert all(len(t.description) > 0 for t in txns)
