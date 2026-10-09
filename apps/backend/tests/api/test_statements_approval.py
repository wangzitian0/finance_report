"""Statement approval and Stage 1 review API router tests.

Tests endpoints in src/routers/statements.py covering:
- POST /statements/{id}/approve - Stage 1 statement approval
- POST /statements/{id}/reject - Stage 1 statement rejection
- POST /statements/{id}/edit-and-approve - Unsupported legacy endpoint validation
- Auto-approve candidate validation and ledger posting
- Account mapping, fallback, and validation before posting
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.audit import (
    STATEMENT_SOURCE_TYPES,
    JournalEntrySourceType,
    SqlTraceRecordRepository,
    TraceEmitter,
    TraceResult,
)
from src.config import settings
from src.extraction import (
    BankStatementStatus,
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceProvenance,
    Stage1Status,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
    extraction_trace_policy_registry,
    persist_statement_extraction_result,
)
from src.extraction.extension import (
    statement_validation as statement_validation_mod,
)
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.extraction.extension.statement_posting import (
    try_auto_approve_high_confidence_statement,
)
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.routers import statements as statements_router
from src.schemas import StatementDecisionRequest
from src.schemas.review import (
    EditAndApproveRequest,
    ReviewedStatementEnvelopeRequest,
    Stage1ApprovalRequest,
    TransactionEditRequest,
)
from tests.api._statement_router_fixtures import (
    add_reviewed_disposition_rule,
    add_txn,
    build_statement,
    create_statement_account,
    seed_historical_source_evidence,
)
from tests.ledger._ledger_helpers import create_valid_posted_entry
from tests.statement_ingestion import posting_dependencies

pytestmark = pytest.mark.asyncio


async def test_approve_statement_stage1_success(db, test_user, monkeypatch):
    """Given a parsed statement with matching balances,
    When approve_statement_stage1 is called,
    Then it approves the statement (lines 761-771).
    """
    account = await create_statement_account(db, test_user.id, "Stage 1 Approve Account")
    statement = build_statement(test_user.id, "hash_s1_approve", 80)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = account.id
    # With no transactions, calculated_closing = opening_balance = 100.
    # Set closing_balance to match so validation passes.
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    result = await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)
    assert result.status == BankStatementStatus.APPROVED
    assert result.journal_entries_created == 0


async def test_approve_statement_stage1_creates_posted_entries(db, test_user):
    bank_account = Account(
        user_id=test_user.id,
        name="DBS Autosave",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(bank_account)
    await db.flush()

    statement = build_statement(test_user.id, "hash_s1_posted", 88)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("115.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    txn_in = await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 2),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    txn_out = await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 3),
        description="Lunch",
        amount=Decimal("5.00"),
        direction="OUT",
    )
    db.add_all([txn_in, txn_out])
    await db.flush()
    await add_reviewed_disposition_rule(
        db,
        user_id=test_user.id,
        keyword="salary",
        account_type=AccountType.INCOME,
        category="SALARY",
    )
    await add_reviewed_disposition_rule(
        db,
        user_id=test_user.id,
        keyword="lunch",
        account_type=AccountType.EXPENSE,
        category="MEALS",
    )
    bank_account_id = bank_account.id
    txn_ids = [txn_in.id, txn_out.id]
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)
    assert result.journal_entries_created == 2
    assert result.status == BankStatementStatus.APPROVED

    entries_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id.in_(txn_ids))
        .options(selectinload(JournalEntry.lines))
    )
    entries = entries_result.scalars().all()
    assert len(entries) == 2
    assert all(entry.status == JournalEntryStatus.POSTED for entry in entries)
    assert all(any(line.account_id == bank_account_id for line in entry.lines) for entry in entries)


async def test_AC_extraction_disposition_5_stage1_requires_economic_review(db, test_user, monkeypatch):
    """AC-extraction.disposition.5: source confirmation cannot imply an economic command."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    bank_account = await create_statement_account(db, test_user.id, "DBS Economic Review")
    statement = build_statement(test_user.id, "hash_s1_economic_review", 88)
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    transaction = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 2),
        description="Opaque merchant",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id,
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert exc.value.detail == "Economic review required: intent_missing"
    await db.refresh(statement)
    assert statement.status is BankStatementStatus.PARSED
    assert statement.stage1_status is Stage1Status.PENDING_REVIEW
    assert statement.validation_error == "Economic review required: intent_missing"

    entries = await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction.id))
    assert entries.scalars().all() == []


async def test_approve_statement_stage1_auto_fill_default_categories(db, test_user, monkeypatch):
    """When auto_fill_default_categories is True, approve_statement_stage1 auto-fills
    default counter accounts and succeeds without raising 409 intent_missing.
    """
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    bank_account = await create_statement_account(db, test_user.id, "DBS Auto Fill Account")
    statement = build_statement(test_user.id, "hash_s1_auto_fill", 88)
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 2),
        description="Opaque merchant IN",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 3),
        description="Opaque merchant OUT",
        amount=Decimal("15.00"),
        direction="OUT",
    )
    # Second OUT transaction to test re-using cached/existing counter account (line 159)
    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 4),
        description="Opaque merchant OUT 2",
        amount=Decimal("5.00"),
        direction="OUT",
    )
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    assert result.status == BankStatementStatus.APPROVED
    assert result.journal_entries_created == 3
    await db.refresh(statement)
    assert statement.status is BankStatementStatus.APPROVED
    assert statement.stage1_status is Stage1Status.APPROVED
    assert statement.validation_error is None

    # Call again with 0 remaining unmatched transactions to cover line 216
    result_empty = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )
    assert result_empty.journal_entries_created == 0


async def test_enum_deserialization_case_insensitivity():
    """Verify JournalEntryStatus, ChatSessionStatus, ChatMessageRole handle case-insensitive string parsing."""
    from src.advisor.orm.chat import ChatMessageRole, ChatSessionStatus
    from src.ledger.orm.journal import JournalEntryStatus

    assert JournalEntryStatus("POSTED") == JournalEntryStatus.POSTED
    assert JournalEntryStatus("posted") == JournalEntryStatus.POSTED
    assert JournalEntryStatus._missing_("UNKNOWN_INVALID") is None

    assert ChatSessionStatus("ACTIVE") == ChatSessionStatus.ACTIVE
    assert ChatSessionStatus("active") == ChatSessionStatus.ACTIVE
    assert ChatSessionStatus._missing_("UNKNOWN_INVALID") is None

    assert ChatMessageRole("USER") == ChatMessageRole.USER
    assert ChatMessageRole("user") == ChatMessageRole.USER
    assert ChatMessageRole._missing_("UNKNOWN_INVALID") is None


async def test_AC_extraction_reviewed_envelope_4_approval_uses_reviewed_envelope_and_disposition(db, test_user):
    """AC-extraction.reviewed-envelope.4: source confirmation remains separate from economic authority."""
    user_id = test_user.id
    statement = build_statement(user_id, "hash_reviewed_envelope_approval", 80)
    statement.currency = None
    statement.period_start = None
    statement.period_end = None
    statement.opening_balance = None
    statement.closing_balance = None
    db.add(statement)
    await db.flush()

    source_result = StatementExtractionResult.create(
        producer_version="csv-parser@1",
        source_content_digest="a" * 64,
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        institution="DBS",
        account_last4="1234",
        period_start=None,
        period_end=None,
        balances=(),
        transactions=(
            ExtractedTransactionFact(
                fact_id="row-1",
                transaction_date=date(2025, 1, 2),
                description="Salary",
                amount=Decimal("10.00"),
                direction="IN",
                currency="SGD",
                balance_after=None,
                confidence=Decimal("0.95"),
            ),
        ),
        positions=(),
        confidence=Decimal("0.90"),
        balance_validated=None,
        warnings=(),
        review_reasons=("source facts require confirmation",),
        provenance=SourceProvenance(
            intake_mode="csv",
            method=ExtractionMethod.DETERMINISTIC,
            provider="csv-parser",
            model="csv-parser@1",
        ),
        statement_currency=None,
    )
    trace_records = build_extraction_trace_records(
        source_result,
        user_id=user_id,
        execution_id=f"test:{statement.id}:result:{source_result.result_id}",
        occurred_at=datetime.now(UTC),
    )
    emitter = TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry()))
    await emitter.emit_many(trace_records)
    await persist_statement_extraction_result(
        db,
        statement=statement,
        result=source_result,
        source_trace_record_id=trace_records[0].record_id,
    )
    transaction = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 2),
        description="Salary",
        amount=Decimal("10.00"),
        direction="IN",
    )
    transaction.dedup_hash = "row-1"
    account = await create_statement_account(db, user_id, "Reviewed CSV Custody")
    await db.commit()

    envelope = await statements_router.confirm_statement_review_envelope(
        statement_id=statement.id,
        request=ReviewedStatementEnvelopeRequest(
            source_result_digest=source_result.content_digest,
            account_id=account.id,
            currency="SGD",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("110.00"),
            rationale="The CSV export omits source header and balance facts.",
        ),
        db=db,
        user_id=user_id,
    )
    assert envelope.source_result_digest == source_result.content_digest

    # The projection is mutable for reporting, but cannot become a second
    # unreviewed source of truth after this version-bound confirmation.
    statement.closing_balance = Decimal("999.00")
    with pytest.raises(HTTPException, match="diverges from its current reviewed envelope") as exc:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id,
            db=db,
            user_id=user_id,
        )
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    await db.refresh(statement)

    await add_reviewed_disposition_rule(
        db,
        user_id=user_id,
        keyword="salary",
        account_type=AccountType.INCOME,
        category="SALARY",
    )
    await db.commit()
    approved = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        db=db,
        user_id=user_id,
    )
    assert approved.status is BankStatementStatus.APPROVED
    assert approved.journal_entries_created == 1
    entries = await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction.id))
    assert len(entries.scalars().all()) == 1


async def test_approve_statement_stage1_auto_maps_unique_prior_confirmed_account(db, test_user):
    """AC-extraction.6.1: Stage 1 posting may auto-map only from a unique prior confirmed statement."""
    bank_account = Account(
        user_id=test_user.id,
        name="DBS Confirmed Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(bank_account)
    await db.flush()

    prior = build_statement(test_user.id, "hash_s1_prior_confirmed", 95)
    prior.status = BankStatementStatus.APPROVED
    prior.account_id = bank_account.id
    db.add(prior)
    await db.flush()
    await seed_historical_source_evidence(db, prior)

    statement = build_statement(test_user.id, "hash_s1_auto_map", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.period_start = date(2025, 2, 1)
    statement.period_end = date(2025, 2, 28)
    statement.opening_balance = Decimal("110.00")
    statement.closing_balance = Decimal("130.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    txn = await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 2, 5),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(
        db,
        user_id=test_user.id,
        keyword="salary",
        account_type=AccountType.INCOME,
        category="SALARY",
    )
    bank_account_id = bank_account.id
    txn_id = txn.id
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)
    assert result.journal_entries_created == 1

    await db.refresh(statement)
    assert statement.account_id == bank_account_id

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn_id)
        .options(selectinload(JournalEntry.lines))
    )
    entry = entry_result.scalar_one()
    assert any(line.account_id == bank_account_id for line in entry.lines)


async def test_auto_approve_high_confidence_statement_creates_posted_entries(db, test_user):
    """AC-extraction.3.1: High-confidence, balance-valid, uniquely mapped statements auto-approve and post."""
    bank_account = await create_statement_account(db, test_user.id, "DBS Auto Approval")
    statement = build_statement(test_user.id, "hash_s1_high_confidence_auto", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(
        db,
        user_id=test_user.id,
        keyword="salary",
        account_type=AccountType.INCOME,
        category="SALARY",
    )
    txn_id = txn.id
    await db.commit()

    created_count = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
    )
    assert created_count == 1

    await db.refresh(statement)
    assert statement.status == BankStatementStatus.APPROVED

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn_id)
    )
    assert entry_result.scalar_one().status == JournalEntryStatus.POSTED


async def test_AC_extraction_disposition_6_auto_post_requires_authoritative_trace_decision(db, test_user, monkeypatch):
    """AC-extraction.disposition.6: no source decision means review, never a ledger write."""
    bank_account = await create_statement_account(db, test_user.id, "DBS Missing Source Authority")
    statement = build_statement(test_user.id, "hash_s1_missing_source_authority", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(
        db,
        user_id=test_user.id,
        keyword="salary",
        account_type=AccountType.INCOME,
        category="SALARY",
    )
    await db.commit()

    async def emit_non_authoritative(*_args, **_kwargs):
        return (SimpleNamespace(result=TraceResult.REVIEW),)

    monkeypatch.setattr(
        "src.extraction.extension.statement_posting.emit_disposition_trace_records",
        emit_non_authoritative,
    )

    created_count = await try_auto_approve_high_confidence_statement(
        db,
        statement.id,
        test_user.id,
        dependencies=posting_dependencies(),
    )

    assert created_count == 0
    await db.refresh(statement)
    assert statement.status is BankStatementStatus.PARSED
    assert statement.stage1_status is Stage1Status.PENDING_REVIEW
    assert "source_authority_missing" in (statement.validation_error or "")
    entry_count = await db.scalar(
        select(JournalEntry.id).where(JournalEntry.user_id == test_user.id).where(JournalEntry.source_id == txn.id)
    )
    assert entry_count is None


async def test_auto_approve_high_confidence_statement_returns_zero_for_non_candidate(db, test_user):
    statement = build_statement(test_user.id, "hash_s1_high_confidence_non_candidate", 90)
    statement.status = BankStatementStatus.PARSED
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.commit()

    created_count = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
    )

    assert created_count == 0


async def test_auto_approve_high_confidence_statement_falls_back_to_pending_review_on_guard_failure(db, test_user):
    """AC-extraction.3.1: Unsafe high-confidence statements remain reviewable instead of failing parsing."""
    unsafe_account = Account(
        user_id=test_user.id,
        name="High Confidence Liability",
        type=AccountType.LIABILITY,
        currency="SGD",
    )
    db.add(unsafe_account)
    await db.flush()

    statement = build_statement(test_user.id, "hash_s1_high_confidence_guard_failure", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = unsafe_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    created_count = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
    )

    assert created_count == 0
    await db.refresh(statement)
    assert statement.status == BankStatementStatus.PARSED
    assert statement.stage1_status == Stage1Status.PENDING_REVIEW
    assert statement.validation_error == "Custody account must be a non-system asset account"


async def test_auto_approve_guard_failure_preserves_uncommitted_parse_data(db, test_user):
    """AC-extraction.3.1: Auto-approval guard fallback must not roll back parsed statement data."""
    unsafe_account = Account(
        user_id=test_user.id,
        name="Uncommitted Liability",
        type=AccountType.LIABILITY,
        currency="SGD",
    )
    db.add(unsafe_account)
    await db.flush()

    statement = build_statement(test_user.id, "hash_s1_guard_failure_preserves_parse", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = unsafe_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Uncommitted Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()

    created_count = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
    )

    assert created_count == 0

    persisted_statement = await db.get(StatementSummary, statement.id)
    assert persisted_statement is not None
    assert persisted_statement.status == BankStatementStatus.PARSED
    assert persisted_statement.stage1_status == Stage1Status.PENDING_REVIEW
    assert persisted_statement.validation_error == "Custody account must be a non-system asset account"

    persisted_txns = await statement_validation_mod.resolve_statement_transactions(db, persisted_statement)
    assert len(persisted_txns) == 1
    assert persisted_txns[0].description == "Uncommitted Salary"


async def test_approve_statement_stage1_routes_legacy_statement_entry_to_correction_review(db, test_user):
    bank_account = await create_statement_account(db, test_user.id, "DBS Existing Entry Promotion")
    statement = build_statement(test_user.id, "hash_s1_existing_entry_promotion", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()

    existing_entry = await create_valid_posted_entry(
        db,
        test_user.id,
        entry_date=txn.txn_date,
        memo="Existing parsed entry",
        source_type=JournalEntrySourceType.AUTO_PARSED,
        source_id=txn.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=test_user.id)

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "legacy_unanchored_source_entry" in exc_info.value.detail
    await db.refresh(existing_entry)
    assert existing_entry.source_type == JournalEntrySourceType.AUTO_PARSED
    assert existing_entry.status == JournalEntryStatus.POSTED
    await db.refresh(statement)
    assert statement.status == BankStatementStatus.PARSED
    assert statement.stage1_status == Stage1Status.PENDING_REVIEW

    entries_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert len(entries_result.scalars().all()) == 1


async def test_approve_statement_stage1_blocks_prior_unconfirmed_account_mapping(db, test_user):
    """AC-extraction.6.5: Stage 1 posting cannot auto-map from an unconfirmed prior statement."""
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Unconfirmed Prior")

    prior = build_statement(user_id, "hash_s1_prior_unconfirmed", 95)
    prior.status = BankStatementStatus.PARSED
    prior.account_id = bank_account.id
    db.add(prior)
    await db.flush()

    statement = build_statement(user_id, "hash_s1_unconfirmed_prior_target", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Historical custody source needs review" in str(exc.value.detail)


async def test_approve_statement_stage1_blocks_overlapping_statement_period_before_posting(db, test_user):
    """AC-extraction.6.6: Stage 1 posting blocks duplicate or overlapping account/currency periods."""
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Period Guard")

    prior = build_statement(user_id, "hash_s1_prior_period", 95)
    prior.status = BankStatementStatus.APPROVED
    prior.account_id = bank_account.id
    prior.period_start = date(2025, 1, 1)
    prior.period_end = date(2025, 1, 31)
    db.add(prior)
    await db.flush()
    await seed_historical_source_evidence(db, prior)

    statement = build_statement(user_id, "hash_s1_period_overlap", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.period_start = date(2025, 1, 15)
    statement.period_end = date(2025, 2, 15)
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 20),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Statement period overlaps" in str(exc.value.detail)

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
    )
    assert entry_result.scalars().all() == []


async def test_approve_statement_stage1_blocks_missing_statement_period_before_posting(db, test_user):
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Missing Period Guard")

    statement = build_statement(user_id, "hash_s1_missing_period", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.period_start = None
    statement.period_end = date(2025, 1, 31)
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 20),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Statement period required" in str(exc.value.detail)


async def test_approve_statement_stage1_blocks_invalid_statement_period_before_posting(db, test_user):
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Invalid Period Guard")

    statement = build_statement(user_id, "hash_s1_invalid_period", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.period_start = date(2025, 2, 1)
    statement.period_end = date(2025, 1, 31)
    statement.closing_balance = Decimal("120.00")
    with pytest.raises(IntegrityError, match="ck_statement_summaries_period_order"):
        db.add(statement)
        await db.flush()


async def test_approve_statement_stage1_blocks_missing_statement_currency_before_posting(db, test_user):
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Missing Currency Guard")

    statement = build_statement(user_id, "hash_s1_missing_currency", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.currency = ""
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 20),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Statement currency required" in str(exc.value.detail)


async def test_approve_statement_stage1_does_not_create_account_without_source_currency(db, test_user):
    """Explicit account confirmation cannot manufacture a statement currency."""
    user_id = test_user.id
    existing_account_ids = {
        account.id for account in (await db.execute(select(Account).where(Account.user_id == user_id))).scalars()
    }
    statement = build_statement(user_id, "hash_s1_missing_currency_account", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.currency = ""
    db.add(statement)
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id,
            db=db,
            user_id=user_id,
            request=Stage1ApprovalRequest(create_account_if_missing=True),
        )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Statement currency required" in str(exc.value.detail)
    account_ids = {
        account.id for account in (await db.execute(select(Account).where(Account.user_id == user_id))).scalars()
    }
    assert account_ids == existing_account_ids


async def test_approve_statement_stage1_blocks_unmapped_account_without_fallback(db, test_user):
    """AC-extraction.6.2: Stage 1 posting blocks first uploads without an explicit account mapping."""
    user_id = test_user.id
    statement = build_statement(user_id, "hash_s1_unmapped", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 6),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Account mapping required" in str(exc.value.detail)

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
    )
    assert entry_result.scalars().all() == []

    fallback_result = await db.execute(
        select(Account).where(Account.user_id == user_id).where(Account.name == "Bank - Main")
    )
    assert fallback_result.scalar_one_or_none() is None


async def test_approve_statement_stage1_blocks_missing_account_metadata(db, test_user):
    """AC-extraction.6.2: Stage 1 posting blocks unmapped statements with incomplete account metadata."""
    user_id = test_user.id
    statement = build_statement(user_id, "hash_s1_missing_account_metadata", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.account_last4 = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 6),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "metadata is missing" in str(exc.value.detail)


async def test_approve_statement_stage1_blocks_invalid_explicit_account_mapping(db, test_user):
    """AC-extraction.6.2: Stage 1 posting blocks stale statement account references."""
    user_id = test_user.id

    statement = build_statement(user_id, "hash_s1_invalid_account_mapping", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = uuid4()
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    try:
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        await db.flush()
        statement_id = statement.id
        await add_txn(
            db,
            statement_id,
            txn_date=date(2025, 1, 6),
            description="Salary",
            amount=Decimal("20.00"),
            direction="IN",
        )
    finally:
        await db.execute(text("SET LOCAL session_replication_role = DEFAULT"))
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Custody account must be owned" in str(exc.value.detail)


@pytest.mark.parametrize(
    ("account_type", "account_currency", "is_active", "expected_detail"),
    [
        (AccountType.LIABILITY, "SGD", True, "Custody account must be a non-system asset account"),
        (AccountType.ASSET, "USD", True, "Custody account currency does not match the source"),
        (AccountType.ASSET, "SGD", False, "Custody account is archived; an active account is required"),
    ],
)
async def test_approve_statement_stage1_blocks_unsafe_explicit_account_mapping(
    db,
    test_user,
    account_type,
    account_currency,
    is_active,
    expected_detail,
):
    """AC-extraction.6.2: Explicit statement accounts must be active ASSET accounts in the statement currency."""
    user_id = test_user.id
    account = Account(
        user_id=user_id,
        name="Unsafe Explicit Account",
        type=account_type,
        currency=account_currency,
        is_active=is_active,
    )
    db.add(account)
    await db.flush()

    statement = build_statement(user_id, f"hash_s1_unsafe_explicit_{account_type}_{account_currency}_{is_active}", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = account.id
    statement.currency = "SGD"
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 6),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert expected_detail == str(exc.value.detail)


async def test_approve_statement_stage1_creates_account_with_explicit_confirmation(db, test_user):
    """AC-extraction.6.4: First upload approval can explicitly create and bind a statement account."""
    user_id = test_user.id
    statement = build_statement(user_id, "hash_s1_confirm_create_account", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.account_last4 = "9876"
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    txn = await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 6),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(
        db,
        user_id=user_id,
        keyword="salary",
        account_type=AccountType.INCOME,
        category="SALARY",
    )
    txn_id = txn.id
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement_id,
        db=db,
        user_id=user_id,
        request=Stage1ApprovalRequest(create_account_if_missing=True),
    )

    assert result.journal_entries_created == 1
    await db.refresh(statement)
    assert statement.account_id is not None

    account = await db.get(Account, statement.account_id)
    assert account is not None
    assert account.name == "DBS ••9876"
    assert account.type == AccountType.ASSET
    assert account.currency == "SGD"
    assert account.code == "AUTO-BANK"

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn_id)
        .options(selectinload(JournalEntry.lines))
    )
    entry = entry_result.scalar_one()
    assert any(line.account_id == account.id for line in entry.lines)

    fallback_result = await db.execute(
        select(Account).where(Account.user_id == user_id).where(Account.name == "Bank - Main")
    )
    assert fallback_result.scalar_one_or_none() is None


async def test_approve_statement_stage1_blocks_ambiguous_account_mapping(db, test_user):
    """AC-extraction.6.3: Stage 1 posting blocks ambiguous statement-account metadata matches."""
    user_id = test_user.id
    first_account = Account(
        user_id=user_id,
        name="DBS Account A",
        type=AccountType.ASSET,
        currency="SGD",
    )
    second_account = Account(
        user_id=user_id,
        name="DBS Account B",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add_all([first_account, second_account])
    await db.flush()

    first_prior = build_statement(user_id, "hash_s1_ambiguous_prior_a", 95)
    first_prior.status = BankStatementStatus.APPROVED
    first_prior.account_id = first_account.id
    second_prior = build_statement(user_id, "hash_s1_ambiguous_prior_b", 95)
    second_prior.status = BankStatementStatus.APPROVED
    second_prior.account_id = second_account.id
    db.add_all([first_prior, second_prior])
    await db.flush()
    await seed_historical_source_evidence(db, first_prior)
    await seed_historical_source_evidence(db, second_prior)

    statement = build_statement(user_id, "hash_s1_ambiguous", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 7),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Ambiguous historical custody accounts" in str(exc.value.detail)


async def test_approve_statement_stage1_keeps_transfer_detection_priority(db, test_user):
    bank_account = await create_statement_account(db, test_user.id, "Transfer Priority Account")
    statement = build_statement(test_user.id, "hash_s1_transfer_priority", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("90.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 4),
        description="Transfer out",
        amount=Decimal("10.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.flush()

    transfer_entry = await create_valid_posted_entry(
        db,
        test_user.id,
        entry_date=date(2025, 1, 4),
        memo="Transfer OUT via processing account",
        source_type=JournalEntrySourceType.SYSTEM,
    )

    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[str(transfer_entry.id)],
            status=ReconciliationStatus.AUTO_ACCEPTED,
            match_score=100,
        )
    )
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=test_user.id)
    assert result.journal_entries_created == 0

    generated_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert generated_result.scalar_one_or_none() is None


async def test_approve_statement_stage1_ignores_rejected_matches_for_skip_logic(db, test_user):
    account = await create_statement_account(db, test_user.id, "DBS Rejected Match")
    statement = build_statement(test_user.id, "hash_s1_rejected_match", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = account.id
    statement.closing_balance = Decimal("90.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 4),
        description="Payment",
        amount=Decimal("10.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.flush()

    stale_entry = await create_valid_posted_entry(
        db,
        test_user.id,
        entry_date=date(2025, 1, 4),
        memo="Stale candidate",
        source_type=JournalEntrySourceType.SYSTEM,
    )
    await add_reviewed_disposition_rule(
        db,
        user_id=test_user.id,
        keyword="payment",
        account_type=AccountType.EXPENSE,
        category="BILLS",
    )

    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[str(stale_entry.id)],
            status=ReconciliationStatus.REJECTED,
            match_score=100,
        )
    )
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=test_user.id)
    assert result.journal_entries_created == 1

    generated_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    generated = generated_result.scalar_one_or_none()
    assert generated is not None


async def test_approve_statement_stage1_balance_mismatch(db, test_user):
    """Given a statement where closing balance doesn't match calculations,
    When approve_statement_stage1 is called,
    Then it raises 400 (lines 764-765).
    """
    account = await create_statement_account(db, test_user.id, "Balance Mismatch Account")
    statement = build_statement(test_user.id, "hash_s1_mismatch", 80)
    statement.account_id = account.id
    statement.closing_balance = Decimal("999.99")  # Wrong closing balance
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)
    assert exc.value.status_code == 400
    assert "Balance mismatch" in exc.value.detail


async def test_approve_statement_stage1_authorizes_before_balance_validation(db, test_user, monkeypatch):
    """AC16.18.1: Stage 1 approval must not validate another user's statement."""
    other_user = User(email="stage1-other@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()

    statement = build_statement(other_user.id, "hash_s1_other_user", 80)
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    validation = AsyncMock(side_effect=AssertionError("validation should not run before authorization"))
    monkeypatch.setattr(statement_validation_mod, "validate_balance_chain", validation)

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)

    assert exc.value.status_code == 404
    assert "Statement not found" in exc.value.detail
    validation.assert_not_awaited()


async def test_reject_statement_stage1_success(db, test_user, monkeypatch):
    """Given a parsed statement,
    When reject_statement_stage1 is called,
    Then it rejects the statement (lines 782-792).
    """
    statement = build_statement(test_user.id, "hash_s1_reject", 80)
    statement.status = BankStatementStatus.PARSED
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    queue_reparse = AsyncMock()
    monkeypatch.setattr(statements_router, "_queue_statement_reparse", queue_reparse)

    result = await statements_router.reject_statement_stage1(
        statement_id=statement_id,
        decision=StatementDecisionRequest(notes="Bad data"),
        db=db,
        user_id=test_user.id,
    )

    assert result.status == BankStatementStatus.REJECTED
    queue_reparse.assert_awaited_once()


async def test_reject_statement_stage1_not_found(db, test_user):
    """Given a non-existent statement,
    When reject_statement_stage1 is called,
    Then it raises 400 (ValueError from service).
    """
    with pytest.raises(HTTPException) as exc:
        await statements_router.reject_statement_stage1(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            decision=StatementDecisionRequest(notes="Bad"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 400


async def test_edit_and_approve_statement_is_unsupported(db, test_user):
    """Editing parsed transactions is unsupported: Layer-2 atomic facts are write-once.

    Reviewers must reject and re-parse instead, so the endpoint now returns 400.
    """

    account = await create_statement_account(db, test_user.id, "DBS Edit Approve")
    statement = build_statement(test_user.id, "hash_edit_approve", 80)
    statement.account_id = account.id
    db.add(statement)
    await db.commit()
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Test Txn",
        amount=Decimal("10.00"),
        direction="IN",
    )
    await db.commit()
    await db.refresh(txn)
    txn_id = txn.id
    statement_id = statement.id
    edit_req = EditAndApproveRequest(
        edits=[
            TransactionEditRequest(
                txn_id=txn_id,
                amount=Decimal("10.00"),
                description="Test Txn",
                txn_date=date(2025, 1, 15),
                direction="IN",
            )
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await statements_router.edit_and_approve_statement(
            statement_id=statement_id, request=edit_req, db=db, user_id=test_user.id
        )
    assert exc.value.status_code == 400
    assert "unsupported" in exc.value.detail.lower()


async def test_edit_and_approve_statement_balance_invalid(db, test_user):
    """Given a statement where edits result in balance mismatch,
    When edit_and_approve_statement is called,
    Then it raises 400 (lines 807-808).
    """

    statement = build_statement(test_user.id, "hash_edit_bad", 80)
    db.add(statement)
    await db.commit()
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Test Txn",
        amount=Decimal("10.00"),
        direction="IN",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    statement_id = statement.id
    # Change amount to something that breaks the balance
    edit_req = EditAndApproveRequest(
        edits=[
            TransactionEditRequest(
                txn_id=txn.id,
                amount=Decimal("99999.00"),
                description="Test Txn",
                txn_date=date(2025, 1, 15),
                direction="IN",
            )
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await statements_router.edit_and_approve_statement(
            statement_id=statement_id, request=edit_req, db=db, user_id=test_user.id
        )
    assert exc.value.status_code == 400
