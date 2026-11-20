from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType, TraceResult
from src.config import settings
from src.extraction import BankStatementStatus, Stage1Status
from src.extraction.extension import statement_validation as statement_validation_mod
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus
from src.schemas.extraction import BankStatementResponse, StatementReviewResponse
from tests.api._statement_router_fixtures import (
    add_reviewed_disposition_rule,
    add_statement,
    add_txn,
    approve_reviewed,
    build_statement,
    create_statement_account,
    create_statement_with_bank,
    seed_historical_source_evidence,
    seed_reviewed_envelope,
)
from tests.factories import UserFactory
from tests.ledger._ledger_helpers import create_valid_posted_entry
from tests.statement_ingestion import posting_dependencies

pytestmark = pytest.mark.asyncio


async def _add_parsed_with_salary_txn(
    db, user_id, file_hash: str, *, account_id=None, closing: str = "120.00", add_rule: bool = False, **kwargs
):
    statement = await add_statement(db, user_id, file_hash, account_id=account_id, closing=closing, **kwargs)
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 8), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    if add_rule:
        await add_reviewed_disposition_rule(
            db, user_id=user_id, keyword="salary", account_type=AccountType.INCOME, category="SALARY"
        )
    return statement, txn


async def _stmt_entries(db, user_id, txn_id=None):
    q = select(JournalEntry).where(
        JournalEntry.user_id == user_id, JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES)
    )
    if txn_id is not None:
        q = q.where(JournalEntry.source_id == txn_id).options(selectinload(JournalEntry.lines))
    return (await db.execute(q)).scalars().all()


async def test_approval_posts_a_row_with_a_long_description(client: AsyncClient, db, test_user):
    statement, _bank = await create_statement_with_bank(
        db, test_user.id, "hash_long_description", closing="88.00", confidence=89, bank_name="DBS Autosave"
    )
    description = "PAYNOW " + "y" * 593
    txn_out = await add_txn(
        db, statement.id, txn_date=date(2025, 1, 3), description=description, amount=Decimal("12.00"), direction="OUT"
    )
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="paynow", account_type=AccountType.EXPENSE, category="TRANSFER_OUT"
    )
    await db.commit()

    resp = await approve_reviewed(client, statement.id)
    assert resp.status_code == status.HTTP_200_OK and (
        resp.json()["journal_entries_created"],
        resp.json()["status"],
    ) == (1, BankStatementStatus.APPROVED.value)
    entries = await _stmt_entries(db, test_user.id, txn_out.id)
    assert len(entries) == 1 and (entries[0].status, entries[0].memo) == (JournalEntryStatus.POSTED, description[:500])


async def test_stage1_requires_economic_review(client: AsyncClient, db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, _bank = await create_statement_with_bank(
        db, test_user.id, "hash_s1_economic_review", closing="120.00", bank_name="DBS Economic Review"
    )
    transaction = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Opaque merchant", amount=Decimal("20.00"), direction="IN"
    )
    await db.commit()

    exc = await approve_reviewed(client, statement.id)
    await db.refresh(statement)
    assert (
        exc.status_code == status.HTTP_409_CONFLICT
        and exc.json()["detail"] == "Economic review required: intent_missing"
    )
    assert (statement.status, statement.stage1_status, statement.validation_error) == (
        BankStatementStatus.PARSED,
        Stage1Status.PENDING_REVIEW,
        "Economic review required: intent_missing",
    )
    assert (
        await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction.id))
    ).scalars().all() == []


async def test_approval_uses_reviewed_envelope_and_disposition(client: AsyncClient, db, test_user):
    statement = await add_statement(
        db,
        test_user.id,
        "hash_reviewed_envelope_approval",
        confidence=80,
        currency=None,
        period_start=None,
        period_end=None,
        opening_balance=None,
        closing=None,
    )
    source_result, transaction = await seed_reviewed_envelope(db, test_user.id, statement)
    account = await create_statement_account(db, test_user.id, "Reviewed CSV Custody")
    await db.commit()

    assert (
        envelope_resp := await client.post(
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
    ).status_code == status.HTTP_200_OK and envelope_resp.json()["source_result_digest"] == source_result.content_digest

    statement.closing_balance = Decimal("999.00")
    await db.commit()
    assert (
        exc := await approve_reviewed(client, statement.id)
    ).status_code == status.HTTP_400_BAD_REQUEST and "diverges from its current reviewed envelope" in exc.json()[
        "detail"
    ]

    statement.closing_balance = Decimal("110.00")
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="salary", account_type=AccountType.INCOME, category="SALARY"
    )
    await db.commit()
    assert (
        approved_resp := await approve_reviewed(client, statement.id)
    ).status_code == status.HTTP_200_OK
    assert (approved_resp.json()["status"], approved_resp.json()["journal_entries_created"]) == (
        BankStatementStatus.APPROVED.value,
        1,
    )
    assert (
        len((await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction.id))).scalars().all())
        == 1
    )


async def test_approve_statement_stage1_auto_maps_unique_prior_confirmed_account(client: AsyncClient, db, test_user):
    bank_account = await create_statement_account(db, test_user.id, "DBS Confirmed Account")
    prior = await add_statement(
        db,
        test_user.id,
        "hash_s1_prior_confirmed",
        confidence=95,
        status=BankStatementStatus.APPROVED,
        account_id=bank_account.id,
    )
    await seed_historical_source_evidence(db, prior)
    statement, txn = await _add_parsed_with_salary_txn(
        db,
        test_user.id,
        "hash_s1_auto_map",
        confidence=90,
        closing="130.00",
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
        opening_balance=Decimal("110.00"),
        add_rule=True,
    )
    await db.commit()

    resp = await approve_reviewed(client, statement.id)
    assert resp.status_code == status.HTTP_200_OK and resp.json()["journal_entries_created"] == 1
    await db.refresh(statement)
    assert statement.account_id == bank_account.id
    (entry,) = await _stmt_entries(db, test_user.id, txn.id)
    assert any(line.account_id == bank_account.id for line in entry.lines)


async def test_auto_approve_high_confidence_statement_creates_posted_entries(db, test_user):
    bank_account = await create_statement_account(db, test_user.id, "DBS Auto Approval")
    statement, txn = await _add_parsed_with_salary_txn(
        db,
        test_user.id,
        "hash_s1_high_confidence_auto",
        confidence=90,
        status=BankStatementStatus.APPROVED,
        account_id=bank_account.id,
        add_rule=True,
    )
    await db.commit()

    assert (
        await try_auto_approve_high_confidence_statement(
            db, statement.id, test_user.id, dependencies=posting_dependencies()
        )
        == 1
    )
    await db.refresh(statement)
    (entry,) = await _stmt_entries(db, test_user.id, txn.id)
    assert (statement.status, entry.status) == (BankStatementStatus.APPROVED, JournalEntryStatus.POSTED)


async def test_auto_post_requires_authoritative_trace_decision(db, test_user, monkeypatch):
    bank_account = await create_statement_account(db, test_user.id, "DBS Missing Source Authority")
    statement, txn = await _add_parsed_with_salary_txn(
        db,
        test_user.id,
        "hash_s1_missing_source_authority",
        confidence=90,
        status=BankStatementStatus.APPROVED,
        account_id=bank_account.id,
        add_rule=True,
    )
    await db.commit()
    monkeypatch.setattr(
        "src.extraction.extension.statement_posting.emit_disposition_trace_records_many",
        AsyncMock(side_effect=lambda *, inputs, **_kw: [(SimpleNamespace(result=TraceResult.REVIEW),) for _ in inputs]),
    )
    assert (
        await try_auto_approve_high_confidence_statement(
            db, statement.id, test_user.id, dependencies=posting_dependencies()
        )
        == 0
    )
    await db.refresh(statement)
    assert (statement.status, statement.stage1_status) == (
        BankStatementStatus.PARSED,
        Stage1Status.PENDING_REVIEW,
    ) and "source_authority_missing" in (statement.validation_error or "")
    assert (
        await db.scalar(
            select(JournalEntry.id).where(JournalEntry.user_id == test_user.id, JournalEntry.source_id == txn.id)
        )
        is None
    )


async def test_auto_approve_guard_failure_preserves_uncommitted_parse_data(db, test_user):
    unsafe_account = Account(user_id=test_user.id, name="Uncommitted Expense", type=AccountType.EXPENSE, currency="SGD")
    db.add(unsafe_account)
    await db.flush()
    statement = await add_statement(
        db,
        test_user.id,
        "hash_s1_guard_failure_preserves_parse",
        confidence=90,
        status=BankStatementStatus.APPROVED,
        account_id=unsafe_account.id,
        closing="120.00",
    )
    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Uncommitted Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )

    assert (
        await try_auto_approve_high_confidence_statement(
            db, statement.id, test_user.id, dependencies=posting_dependencies()
        )
        == 0
    )
    persisted = await db.get(StatementSummary, statement.id)
    assert (persisted.status, persisted.stage1_status, persisted.validation_error) == (
        BankStatementStatus.PARSED,
        Stage1Status.PENDING_REVIEW,
        "Custody account must be a non-system asset or liability account",
    )
    assert [t.description for t in await statement_validation_mod.resolve_statement_transactions(db, persisted)] == [
        "Uncommitted Salary"
    ]


async def test_approve_statement_stage1_routes_legacy_statement_entry_to_correction_review(
    client: AsyncClient, db, test_user
):
    bank_account = await create_statement_account(db, test_user.id, "DBS Existing Entry Promotion")
    statement, txn = await _add_parsed_with_salary_txn(
        db, test_user.id, "hash_s1_existing_entry_promotion", confidence=90, account_id=bank_account.id
    )
    existing = await create_valid_posted_entry(
        db,
        test_user.id,
        entry_date=txn.txn_date,
        memo="Existing parsed entry",
        source_type=JournalEntrySourceType.AUTO_PARSED,
        source_id=txn.id,
    )
    await db.commit()

    assert (
        exc_info := await approve_reviewed(client, statement.id)
    ).status_code == status.HTTP_409_CONFLICT and "legacy_unanchored_source_entry" in exc_info.json()["detail"]
    [await db.refresh(x) for x in (existing, statement)]
    assert (
        existing.source_type,
        existing.status,
        statement.status,
        statement.stage1_status,
        len(await _stmt_entries(db, test_user.id, txn.id)),
    ) == (
        JournalEntrySourceType.AUTO_PARSED,
        JournalEntryStatus.POSTED,
        BankStatementStatus.PARSED,
        Stage1Status.PENDING_REVIEW,
        1,
    )


@pytest.mark.parametrize(
    ("scenario", "expected_detail"),
    [
        ("unmapped", "Account mapping required"),
        ("unconfirmed_prior", "Historical custody source needs review"),
        ("ambiguous_prior", "Ambiguous historical custody accounts"),
        ("period_overlap", "Statement period overlaps"),
    ],
)
async def test_approve_statement_stage1_blocks_mapping_and_period_guards(
    client: AsyncClient, db, test_user, scenario, expected_detail
):
    account_id = None
    if scenario == "unconfirmed_prior":
        await add_statement(
            db,
            test_user.id,
            "hash_prior_unconfirmed",
            confidence=95,
            account_id=(await create_statement_account(db, test_user.id, "DBS Unconfirmed Prior")).id,
        )
    elif scenario in ("ambiguous_prior", "period_overlap"):
        for idx in ("a", "b") if scenario == "ambiguous_prior" else ("p",):
            acc = await create_statement_account(db, test_user.id, f"DBS Account {idx}")
            await seed_historical_source_evidence(
                db,
                await add_statement(
                    db,
                    test_user.id,
                    f"hash_{scenario}_{idx}",
                    confidence=95,
                    status=BankStatementStatus.APPROVED,
                    account_id=acc.id,
                ),
            )
            account_id = acc.id if scenario == "period_overlap" else None

    extra = {"period_start": date(2025, 1, 15), "period_end": date(2025, 2, 15)} if scenario == "period_overlap" else {}
    statement, _ = await _add_parsed_with_salary_txn(
        db, test_user.id, f"hash_block_{scenario}", confidence=90, account_id=account_id, **extra
    )
    await db.commit()

    assert (
        exc := await approve_reviewed(client, statement.id)
    ).status_code == status.HTTP_400_BAD_REQUEST and expected_detail in exc.json()["detail"]
    assert await _stmt_entries(db, test_user.id) == []
    if scenario == "unmapped":
        assert (
            await db.execute(select(Account).where(Account.user_id == test_user.id, Account.name == "Bank - Main"))
        ).scalar_one_or_none() is None


async def test_statement_summary_rejects_a_period_that_ends_before_it_starts(db, test_user):
    bank_account = await create_statement_account(db, test_user.id, "DBS Invalid Period Guard")
    statement = build_statement(test_user.id, "hash_s1_invalid_period", 90)
    statement.account_id, statement.period_start, statement.period_end, statement.closing_balance = (
        bank_account.id,
        date(2025, 2, 1),
        date(2025, 1, 31),
        Decimal("120.00"),
    )
    with pytest.raises(IntegrityError, match="ck_statement_summaries_period_order"):
        db.add(statement)
        await db.flush()


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
    account = Account(
        user_id=test_user.id,
        name="Unsafe Explicit Account",
        type=account_type,
        currency=account_currency,
        is_active=is_active,
    )
    db.add(account)
    await db.flush()
    statement, _ = await _add_parsed_with_salary_txn(
        db,
        test_user.id,
        f"hash_s1_unsafe_{account_type}_{account_currency}_{is_active}",
        confidence=90,
        account_id=account.id,
    )
    await db.commit()

    assert (
        exc := await approve_reviewed(client, statement.id)
    ).status_code == status.HTTP_400_BAD_REQUEST and exc.json()["detail"] == expected_detail


async def test_approve_statement_stage1_creates_account_with_explicit_confirmation(client: AsyncClient, db, test_user):
    statement, txn = await _add_parsed_with_salary_txn(
        db, test_user.id, "hash_s1_confirm_create_account", confidence=90, account_last4="9876", add_rule=True
    )
    await db.commit()

    assert (
        resp := await approve_reviewed(client, statement.id, {"create_account_if_missing": True})
    ).status_code == status.HTTP_200_OK and resp.json()["journal_entries_created"] == 1
    await db.refresh(statement)
    account = await db.get(Account, statement.account_id)
    (entry,) = await _stmt_entries(db, test_user.id, txn.id)
    assert account is not None and (account.name, account.type, account.currency, account.code) == (
        "DBS ••9876",
        AccountType.ASSET,
        "SGD",
        "AUTO-BANK",
    )
    assert (
        any(line.account_id == account.id for line in entry.lines)
        and (
            await db.execute(select(Account).where(Account.user_id == test_user.id, Account.name == "Bank - Main"))
        ).scalar_one_or_none()
        is None
    )


async def test_approve_statement_stage1_authorizes_before_balance_validation(
    client: AsyncClient, db, test_user, monkeypatch
):
    other_user = await UserFactory.create_async(db)
    statement = await add_statement(db, other_user.id, "hash_s1_other_user", confidence=80)
    await db.commit()
    validation = AsyncMock(side_effect=AssertionError("validation should not run before authorization"))
    monkeypatch.setattr(statement_validation_mod, "validate_balance_chain", validation)
    assert (
        exc := await approve_reviewed(client, statement.id)
    ).status_code == 404 and "Statement not found" in exc.json()["detail"]
    validation.assert_not_awaited()


async def test_approve_binds_explicit_account_id(client: AsyncClient, db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    selected_account = await create_statement_account(db, test_user.id, "User Selected Custody Account")
    statement, _ = await _add_parsed_with_salary_txn(db, test_user.id, "hash_explicit_account_2822", account_last4=None)
    await db.commit()

    approved = (
        resp := await client.post(
            f"/statements/{statement.id}/approvals",
            json={"account_id": str(selected_account.id), "auto_fill_default_categories": True},
        )
    ).json()
    assert resp.status_code == status.HTTP_200_OK and (
        approved["status"],
        approved["account_id"],
        approved["journal_entries_created"],
    ) == (BankStatementStatus.APPROVED.value, str(selected_account.id), 1)


async def test_review_response_inherits_bank_statement_response(client: AsyncClient, db, test_user):
    assert issubclass(StatementReviewResponse, BankStatementResponse)
    statement = await add_statement(
        db,
        test_user.id,
        "hash_review_inherits_2826",
        confidence=85,
        extraction_metadata={
            "brokerage_import_failure": {
                "reason": "Brokerage import failed: missing instrument symbol",
                "request_id": "req-2826",
                "recorded_at": "2026-03-01T00:00:00Z",
            }
        },
    )
    await db.commit()
    review = (resp := await client.get(f"/statements/{statement.id}/review")).json()
    assert resp.status_code == status.HTTP_200_OK and (
        review["brokerage_import_failed"],
        review["brokerage_import_failure_reason"],
    ) == (True, "Brokerage import failed: missing instrument symbol")
