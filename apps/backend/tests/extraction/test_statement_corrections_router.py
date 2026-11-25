from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.config import settings
from src.ledger import JournalEntry, JournalEntryStatus
from src.platform import DomainError, ResourceNotFoundError
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.request_context import RequestContext
from src.routers import statements
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account
from tests.factories import AtomicTransactionFactory, UploadedDocumentFactory


async def _seed_stmt_txn(db, user_id, name: str, file_hash: str, *, amount: Decimal, txn_date: date, description: str):
    bank = await create_statement_account(db, user_id, name)
    statement = build_statement(user_id, file_hash, 88)
    statement.account_id, statement.opening_balance, statement.closing_balance = (
        bank.id,
        Decimal("100.00"),
        Decimal("100.00") - amount,
    )
    db.add(statement)
    await db.flush()
    txn = await add_txn(db, statement, txn_date=txn_date, description=description, amount=amount, direction="OUT")
    statement_id, txn_id = statement.id, txn.id
    await db.commit()
    return statement_id, txn_id


async def test_post_create_and_invalid_category(client: AsyncClient, db, test_user):
    document = await UploadedDocumentFactory.create_async(db, user_id=test_user.id)
    txn = await AtomicTransactionFactory.create_async(
        db, test_user.id, source_doc_id=document.id, description="Test purchase"
    )
    await db.commit()

    ok = await client.post(
        "/statements/corrections", json={"transaction_id": str(txn.id), "corrected_category": "Shopping"}
    )
    bad = await client.post(
        "/statements/corrections", json={"transaction_id": str(txn.id), "corrected_category": "Food & Dining"}
    )
    assert (ok.status_code, ok.json()["transaction_id"], ok.json()["corrected_category"], bad.status_code) == (
        201,
        str(txn.id),
        "Shopping",
        400,
    )
    assert "not a category" in bad.json()["detail"]


async def test_create_correction_returns_404_when_transaction_is_missing(monkeypatch):
    async def fail_record_correction(*_args, **_kwargs):
        raise ResourceNotFoundError("transaction not found")

    class CommitShouldNotRun:
        async def commit(self):
            raise AssertionError("commit should not run after correction lookup fails")

    monkeypatch.setattr(statements, "record_correction", fail_record_correction)
    with pytest.raises(DomainError) as exc_info:
        await statements.create_correction(
            body=statements.CorrectionRequest(transaction_id=uuid4(), corrected_category="Office Supplies"),
            ctx=RequestContext(CommitShouldNotRun(), uuid4()),
        )
    assert (exc_info.value.status_code, exc_info.value.detail) == (404, "transaction not found")


async def test_post_correction_applies_classification_and_unblocks_stage1_approval(
    client: AsyncClient, db, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement_id, txn_id = await _seed_stmt_txn(
        db,
        test_user.id,
        "DBS Modal Review",
        "hash_modal_review_2432",
        amount=Decimal("20.00"),
        txn_date=date(2025, 1, 4),
        description="Opaque merchant",
    )
    approval_body = {"create_account_if_missing": False, "auto_fill_default_categories": False}

    blocked = await client.post(f"/statements/{statement_id}/approvals", json=approval_body)
    bad_dir = await client.post(
        "/statements/corrections", json={"transaction_id": str(txn_id), "corrected_category": "SALARY"}
    )
    corr = await client.post(
        "/statements/corrections", json={"transaction_id": str(txn_id), "corrected_category": "DINING"}
    )
    review = await client.get(f"/statements/{statement_id}/review")
    approved = await client.post(f"/statements/{statement_id}/approvals", json=approval_body)
    r_txn = review.json()["transactions"][0]
    assert blocked.status_code == 409 and blocked.json()["detail"].startswith("Economic review required:")
    assert bad_dir.status_code == 400 and "does not fit" in bad_dir.json()["detail"]
    assert (
        corr.status_code,
        corr.json()["corrected_category"],
        review.status_code,
        r_txn["proposed_category"],
        r_txn["confidence_score"],
        r_txn["confidence_tier"],
        approved.status_code,
        approved.json()["journal_entries_created"],
    ) == (201, "DINING", 200, "DINING", 100, "HIGH", 200, 1)


async def test_post_correction_transfer_draft_is_posted_on_stage1_approval(
    client: AsyncClient, db, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement_id, txn_id = await _seed_stmt_txn(
        db,
        test_user.id,
        "DBS Transfer Review",
        "hash_modal_transfer_2432",
        amount=Decimal("20.00"),
        txn_date=date(2025, 1, 5),
        description="Unlabeled movement",
    )
    corr = await client.post(
        "/statements/corrections", json={"transaction_id": str(txn_id), "corrected_category": "TRANSFER"}
    )
    approved = await client.post(
        f"/statements/{statement_id}/approvals",
        json={"create_account_if_missing": False, "auto_fill_default_categories": False},
    )
    assert (corr.status_code, approved.status_code, approved.json()["journal_entries_created"]) == (201, 200, 1)


async def test_post_correction_reclassifies_posted_entry_on_approved_statement(
    client: AsyncClient, db, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    user_id = test_user.id
    statement_id, txn_id = await _seed_stmt_txn(
        db,
        user_id,
        "DBS Reclassify Test Bank",
        "hash_reclassify_posted_2423",
        amount=Decimal("30.00"),
        txn_date=date(2025, 1, 6),
        description="Business meal",
    )

    async def _entries():
        return (
            await db.scalars(
                select(JournalEntry)
                .where(JournalEntry.user_id == user_id, JournalEntry.source_id == txn_id)
                .options(selectinload(JournalEntry.lines))
            )
        ).all()

    corr1 = await client.post(
        "/statements/corrections", json={"transaction_id": str(txn_id), "corrected_category": "DINING"}
    )
    approved = await client.post(
        f"/statements/{statement_id}/approvals",
        json={"create_account_if_missing": False, "auto_fill_default_categories": False},
    )
    entries1 = await _entries()
    assert (
        corr1.status_code,
        approved.status_code,
        approved.json()["journal_entries_created"],
        len(entries1),
        entries1[0].status,
    ) == (201, 200, 1, 1, JournalEntryStatus.POSTED)
    initial_id = entries1[0].id

    corr2 = await client.post(
        "/statements/corrections", json={"transaction_id": str(txn_id), "corrected_category": "SHOPPING"}
    )
    await db.rollback()
    entries2 = await _entries()
    old_e = next(e for e in entries2 if e.id == initial_id)
    new_e = next(e for e in entries2 if e.id != initial_id)
    new_id = new_e.id
    assert (corr2.status_code, len(entries2), old_e.status, new_e.status, new_e.memo) == (
        201,
        2,
        JournalEntryStatus.VOID,
        JournalEntryStatus.POSTED,
        "Business meal",
    )

    corr3 = await client.post(
        "/statements/corrections", json={"transaction_id": str(txn_id), "corrected_category": "TRANSFER"}
    )
    await db.rollback()
    all_entries = await _entries()
    leg = next(e for e in all_entries if e.id not in (initial_id, new_id) and e.status == JournalEntryStatus.RECONCILED)
    leg_id = leg.id
    rec_matches = (
        await db.scalars(select(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == txn_id))
    ).all()
    active_match = next(m for m in rec_matches if m.status == ReconciliationStatus.ACCEPTED)
    active_match_id = active_match.id
    assert (
        corr3.status_code,
        next(e for e in all_entries if e.id == new_id).status,
        str(leg_id) in active_match.journal_entry_ids,
    ) == (201, JournalEntryStatus.VOID, True)

    corr4 = await client.post(
        "/statements/corrections", json={"transaction_id": str(txn_id), "corrected_category": "DINING"}
    )
    await db.rollback()
    entries4 = await _entries()
    refreshed_match = await db.get(ReconciliationMatch, active_match_id)
    dining_e = next(
        e for e in entries4 if e.id not in (initial_id, new_id, leg_id) and e.status == JournalEntryStatus.POSTED
    )
    assert (
        corr4.status_code,
        next(e for e in entries4 if e.id == leg_id).status,
        refreshed_match.status if refreshed_match else None,
        dining_e.memo,
    ) == (201, JournalEntryStatus.VOID, ReconciliationStatus.SUPERSEDED, "Business meal")
