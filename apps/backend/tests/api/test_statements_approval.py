from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
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
from src.extraction.extension import statement_validation as statement_validation_mod
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus
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


async def test_AC_extraction_statement_memo_1_approval_posts_a_row_with_a_long_description(
    client: AsyncClient, db, test_user
):
    bank_account = Account(user_id=test_user.id, name="DBS Autosave", type=AccountType.ASSET, currency="SGD")
    db.add(bank_account)
    await db.flush()
    statement = build_statement(test_user.id, "hash_long_description", 89)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("88.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id
    description = "PAYNOW " + "y" * 593
    assert len(description) == 600
    txn_out = await add_txn(
        db, statement_id, txn_date=date(2025, 1, 3), description=description, amount=Decimal("12.00"), direction="OUT"
    )
    db.add(txn_out)
    await db.flush()
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="paynow", account_type=AccountType.EXPENSE, category="TRANSFER_OUT"
    )
    txn_id = txn_out.id
    await db.commit()

    resp = await client.post(f"/statements/{statement_id}/approvals")
    assert resp.status_code == status.HTTP_200_OK, resp.text
    result = resp.json()
    assert result["journal_entries_created"] == 1
    assert result["status"] == BankStatementStatus.APPROVED.value
    entries = (
        (
            await db.execute(
                select(JournalEntry)
                .where(JournalEntry.user_id == test_user.id)
                .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
                .where(JournalEntry.source_id == txn_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert entries[0].status == JournalEntryStatus.POSTED
    assert entries[0].memo == description[:500]


async def test_AC_extraction_disposition_5_stage1_requires_economic_review(
    client: AsyncClient, db, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    bank_account = await create_statement_account(db, test_user.id, "DBS Economic Review")
    statement = build_statement(test_user.id, "hash_s1_economic_review", 88)
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    transaction = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Opaque merchant", amount=Decimal("20.00"), direction="IN"
    )
    await db.commit()

    exc = await client.post(f"/statements/{statement.id}/approvals")
    assert exc.status_code == status.HTTP_409_CONFLICT
    assert exc.json()["detail"] == "Economic review required: intent_missing"
    await db.refresh(statement)
    assert statement.status is BankStatementStatus.PARSED
    assert statement.stage1_status is Stage1Status.PENDING_REVIEW
    assert statement.validation_error == "Economic review required: intent_missing"
    entries = await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction.id))
    assert entries.scalars().all() == []


async def test_AC_extraction_reviewed_envelope_4_approval_uses_reviewed_envelope_and_disposition(
    client: AsyncClient, db, test_user
):
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
            intake_mode="csv", method=ExtractionMethod.DETERMINISTIC, provider="csv-parser", model="csv-parser@1"
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
        db, statement=statement, result=source_result, source_trace_record_id=trace_records[0].record_id
    )
    transaction = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Salary", amount=Decimal("10.00"), direction="IN"
    )
    transaction.dedup_hash = "row-1"
    account = await create_statement_account(db, user_id, "Reviewed CSV Custody")
    await db.commit()

    envelope_resp = await client.post(
        f"/statements/{statement.id}/review-envelopes",
        json={
            "source_result_digest": source_result.content_digest,
            "account_id": str(account.id),
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "100.00",
            "closing_balance": "110.00",
            "rationale": "The CSV export omits source header and balance facts.",
        },
    )
    assert envelope_resp.status_code == status.HTTP_200_OK, envelope_resp.text
    assert envelope_resp.json()["source_result_digest"] == source_result.content_digest
    statement.closing_balance = Decimal("999.00")
    await db.commit()

    exc = await client.post(f"/statements/{statement.id}/approvals")
    assert exc.status_code == status.HTTP_400_BAD_REQUEST
    assert "diverges from its current reviewed envelope" in exc.json()["detail"]

    statement.closing_balance = Decimal("110.00")
    await add_reviewed_disposition_rule(
        db, user_id=user_id, keyword="salary", account_type=AccountType.INCOME, category="SALARY"
    )
    await db.commit()
    approved_resp = await client.post(f"/statements/{statement.id}/approvals")
    assert approved_resp.status_code == status.HTTP_200_OK, approved_resp.text
    approved = approved_resp.json()
    assert approved["status"] == BankStatementStatus.APPROVED.value
    assert approved["journal_entries_created"] == 1
    entries = await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction.id))
    assert len(entries.scalars().all()) == 1


async def test_approve_statement_stage1_auto_maps_unique_prior_confirmed_account(client: AsyncClient, db, test_user):
    bank_account = Account(user_id=test_user.id, name="DBS Confirmed Account", type=AccountType.ASSET, currency="SGD")
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
        db, statement_id, txn_date=date(2025, 2, 5), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="salary", account_type=AccountType.INCOME, category="SALARY"
    )
    bank_account_id = bank_account.id
    txn_id = txn.id
    await db.commit()

    resp = await client.post(f"/statements/{statement_id}/approvals")
    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert resp.json()["journal_entries_created"] == 1
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
    bank_account = await create_statement_account(db, test_user.id, "DBS Auto Approval")
    statement = build_statement(test_user.id, "hash_s1_high_confidence_auto", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 8), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="salary", account_type=AccountType.INCOME, category="SALARY"
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
    bank_account = await create_statement_account(db, test_user.id, "DBS Missing Source Authority")
    statement = build_statement(test_user.id, "hash_s1_missing_source_authority", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 8), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="salary", account_type=AccountType.INCOME, category="SALARY"
    )
    await db.commit()

    async def emit_non_authoritative(*, inputs, **_kwargs):
        return [(SimpleNamespace(result=TraceResult.REVIEW),) for _ in inputs]

    monkeypatch.setattr(
        "src.extraction.extension.statement_posting.emit_disposition_trace_records_many", emit_non_authoritative
    )
    created_count = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
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


async def test_auto_approve_guard_failure_preserves_uncommitted_parse_data(db, test_user):
    unsafe_account = Account(
        user_id=test_user.id, name="Uncommitted Expense", type=AccountType.EXPENSE, currency="SGD"
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
    assert persisted_statement.validation_error == "Custody account must be a non-system asset or liability account"
    persisted_txns = await statement_validation_mod.resolve_statement_transactions(db, persisted_statement)
    assert len(persisted_txns) == 1
    assert persisted_txns[0].description == "Uncommitted Salary"


async def test_approve_statement_stage1_routes_legacy_statement_entry_to_correction_review(
    client: AsyncClient, db, test_user
):
    bank_account = await create_statement_account(db, test_user.id, "DBS Existing Entry Promotion")
    statement = build_statement(test_user.id, "hash_s1_existing_entry_promotion", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 8), description="Salary", amount=Decimal("20.00"), direction="IN"
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
    await db.commit()

    exc_info = await client.post(f"/statements/{statement.id}/approvals")
    assert exc_info.status_code == status.HTTP_409_CONFLICT
    assert "legacy_unanchored_source_entry" in exc_info.json()["detail"]
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


async def test_approve_statement_stage1_blocks_prior_unconfirmed_account_mapping(client: AsyncClient, db, test_user):
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
        db, statement, txn_date=date(2025, 1, 8), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    await db.commit()

    exc = await client.post(f"/statements/{statement.id}/approvals")
    assert exc.status_code == status.HTTP_400_BAD_REQUEST
    assert "Historical custody source needs review" in exc.json()["detail"]


async def test_approve_statement_stage1_blocks_overlapping_statement_period_before_posting(
    client: AsyncClient, db, test_user
):
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
        db, statement, txn_date=date(2025, 1, 20), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    await db.commit()

    exc = await client.post(f"/statements/{statement.id}/approvals")
    assert exc.status_code == status.HTTP_400_BAD_REQUEST
    assert "Statement period overlaps" in exc.json()["detail"]
    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
    )
    assert entry_result.scalars().all() == []


async def test_statement_summary_rejects_a_period_that_ends_before_it_starts(db, test_user):
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


async def test_approve_statement_stage1_blocks_unmapped_account_without_fallback(client: AsyncClient, db, test_user):
    user_id = test_user.id
    statement = build_statement(user_id, "hash_s1_unmapped", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id
    await add_txn(
        db, statement_id, txn_date=date(2025, 1, 6), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    await db.commit()

    exc = await client.post(f"/statements/{statement_id}/approvals")
    assert exc.status_code == status.HTTP_400_BAD_REQUEST
    assert "Account mapping required" in exc.json()["detail"]
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


@pytest.mark.parametrize(
    ("account_type", "account_currency", "is_active", "expected_detail"),
    [
        (AccountType.EXPENSE, "SGD", True, "Custody account must be a non-system asset or liability account"),
        (AccountType.ASSET, "USD", True, "Custody account currency does not match the source"),
        (AccountType.ASSET, "SGD", False, "Custody account is archived; an active account is required"),
    ],
)
async def test_approve_statement_stage1_blocks_unsafe_explicit_account_mapping(
    client: AsyncClient, db, test_user, account_type, account_currency, is_active, expected_detail
):
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
        db, statement_id, txn_date=date(2025, 1, 6), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    await db.commit()

    exc = await client.post(f"/statements/{statement_id}/approvals")
    assert exc.status_code == status.HTTP_400_BAD_REQUEST
    assert expected_detail == exc.json()["detail"]


async def test_approve_statement_stage1_creates_account_with_explicit_confirmation(client: AsyncClient, db, test_user):
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
        db, statement_id, txn_date=date(2025, 1, 6), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    db.add(txn)
    await db.flush()
    await add_reviewed_disposition_rule(
        db, user_id=user_id, keyword="salary", account_type=AccountType.INCOME, category="SALARY"
    )
    txn_id = txn.id
    await db.commit()

    resp = await client.post(f"/statements/{statement_id}/approvals", json={"create_account_if_missing": True})
    assert resp.status_code == status.HTTP_200_OK, resp.text
    assert resp.json()["journal_entries_created"] == 1
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


async def test_approve_statement_stage1_blocks_ambiguous_account_mapping(client: AsyncClient, db, test_user):
    user_id = test_user.id
    first_account = Account(user_id=user_id, name="DBS Account A", type=AccountType.ASSET, currency="SGD")
    second_account = Account(user_id=user_id, name="DBS Account B", type=AccountType.ASSET, currency="SGD")
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
        db, statement_id, txn_date=date(2025, 1, 7), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    await db.commit()

    exc = await client.post(f"/statements/{statement_id}/approvals")
    assert exc.status_code == status.HTTP_400_BAD_REQUEST
    assert "Ambiguous historical custody accounts" in exc.json()["detail"]


async def test_approve_statement_stage1_authorizes_before_balance_validation(
    client: AsyncClient, db, test_user, monkeypatch
):
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

    exc = await client.post(f"/statements/{statement_id}/approvals")
    assert exc.status_code == 404
    assert "Statement not found" in exc.json()["detail"]
    validation.assert_not_awaited()


async def test_AC_extraction_2822_2_approve_binds_explicit_account_id(client: AsyncClient, db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    selected_account = await create_statement_account(db, test_user.id, "User Selected Custody Account")
    statement = build_statement(test_user.id, "hash_explicit_account_2822", 88)
    statement.account_id = None
    statement.account_last4 = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    await add_txn(
        db, statement, txn_date=date(2025, 1, 5), description="Salary credit", amount=Decimal("20.00"), direction="IN"
    )
    await db.commit()

    resp = await client.post(
        f"/statements/{statement.id}/approvals",
        json={"account_id": str(selected_account.id), "auto_fill_default_categories": True},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    approved = resp.json()
    assert approved["status"] == BankStatementStatus.APPROVED.value
    assert approved["account_id"] == str(selected_account.id)
    assert approved["journal_entries_created"] == 1


async def test_AC_extraction_2826_1_review_response_inherits_bank_statement_response(client: AsyncClient, db, test_user):
    from src.schemas.extraction import BankStatementResponse
    from src.schemas.extraction import StatementReviewResponse

    assert issubclass(StatementReviewResponse, BankStatementResponse)
    statement = build_statement(test_user.id, "hash_review_inherits_2826", 85)
    statement.extraction_metadata = {
        "brokerage_import_failure": {
            "reason": "Brokerage import failed: missing instrument symbol",
            "request_id": "req-2826",
            "recorded_at": "2026-03-01T00:00:00Z",
        }
    }
    db.add(statement)
    await db.commit()

    resp = await client.get(f"/statements/{statement.id}/review")
    assert resp.status_code == status.HTTP_200_OK, resp.text
    review = resp.json()
    assert review["brokerage_import_failed"] is True
    assert review["brokerage_import_failure_reason"] == "Brokerage import failed: missing instrument symbol"
