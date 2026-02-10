"""AC2.10.1 - AC2.10.1: Reconciliation API Endpoint Tests

These tests validate reconciliation API endpoints including running reconciliation,
pending review queue, accepting/rejecting matches, batch operations,
and statistics queries.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountEvent,
    AccountType,
    BankTransactionStatus,
    ConfidenceLevel,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
    Statement,
)


@pytest.mark.asyncio
async def test_reconciliation_endpoints(client: AsyncClient, db: AsyncSession, test_user) -> None:
    session = db
    statement_run = Statement(
        user_id=test_user.id,
        account_id=None,
        file_path="statements/run.pdf",
        file_hash="hash_run",
        original_filename="run.pdf",
        institution="Test Bank",
        account_last4="1234",
        currency="SGD",
        period_start=date.today(),
        period_end=date.today(),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )
    statement_review = Statement(
        user_id=test_user.id,
        account_id=None,
        file_path="statements/review.pdf",
        file_hash="hash_review",
        original_filename="review.pdf",
        institution="Test Bank",
        account_last4="5678",
        currency="SGD",
        period_start=date.today(),
        period_end=date.today(),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )
    bank_account = Account(
        user_id=test_user.id,
        name="Bank - Main",
        type=AccountType.ASSET,
        currency="SGD",
    )
    income_account = Account(
        user_id=test_user.id,
        name="Income - Salary",
        type=AccountType.INCOME,
        currency="SGD",
    )
    expense_account = Account(
        user_id=test_user.id,
        name="Expense - Misc",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    session.add_all(
        [
            statement_run,
            statement_review,
            bank_account,
            income_account,
            expense_account,
        ]
    )
    await session.flush()

    entry_run = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Salary Payment",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry_accept = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Coffee",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry_reject = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Snacks",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry_batch = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Lunch",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    session.add_all([entry_run, entry_accept, entry_reject, entry_batch])
    await session.flush()

    session.add_all(
        [
            JournalLine(
                journal_entry_id=entry_run.id,
                account_id=bank_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_run.id,
                account_id=income_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_accept.id,
                account_id=expense_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("12.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_accept.id,
                account_id=bank_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("12.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_reject.id,
                account_id=expense_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("8.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_reject.id,
                account_id=bank_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("8.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_batch.id,
                account_id=expense_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("20.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_batch.id,
                account_id=bank_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("20.00"),
                currency="SGD",
            ),
        ]
    )

    txn_run = AccountEvent(
        statement_id=statement_run.id,
        txn_date=date.today(),
        description="Salary Payment",
        amount=Decimal("1000.00"),
        direction="IN",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    txn_accept = AccountEvent(
        statement_id=statement_review.id,
        txn_date=date.today(),
        description="Coffee",
        amount=Decimal("12.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    txn_reject = AccountEvent(
        statement_id=statement_review.id,
        txn_date=date.today(),
        description="Snacks",
        amount=Decimal("8.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    txn_batch = AccountEvent(
        statement_id=statement_review.id,
        txn_date=date.today(),
        description="Lunch",
        amount=Decimal("20.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.HIGH,
    )
    txn_unmatched = AccountEvent(
        statement_id=statement_review.id,
        txn_date=date.today(),
        description="Odd Vendor",
        amount=Decimal("5.00"),
        direction="OUT",
        status=BankTransactionStatus.UNMATCHED,
        confidence=ConfidenceLevel.MEDIUM,
    )
    txn_low = AccountEvent(
        statement_id=statement_review.id,
        txn_date=date.today(),
        description="Small Charge",
        amount=Decimal("9.00"),
        direction="OUT",
        status=BankTransactionStatus.PENDING,
        confidence=ConfidenceLevel.MEDIUM,
    )
    session.add_all([txn_run, txn_accept, txn_reject, txn_batch, txn_unmatched, txn_low])
    await session.flush()

    match_accept = ReconciliationMatch(
        bank_txn_id=txn_accept.id,
        journal_entry_ids=[str(entry_accept.id)],
        match_score=82,
        score_breakdown={"amount": 90.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_reject = ReconciliationMatch(
        bank_txn_id=txn_reject.id,
        journal_entry_ids=[str(entry_reject.id)],
        match_score=70,
        score_breakdown={"amount": 80.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_batch = ReconciliationMatch(
        bank_txn_id=txn_batch.id,
        journal_entry_ids=[str(entry_batch.id)],
        match_score=90,
        score_breakdown={"amount": 95.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_low = ReconciliationMatch(
        bank_txn_id=txn_low.id,
        journal_entry_ids=[],
        match_score=50,
        score_breakdown={"amount": 40.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    session.add_all([match_accept, match_reject, match_batch, match_low])
    await session.commit()

    run_resp = await client.post(
        "/reconciliation/run",
        json={"statement_id": str(statement_run.id)},
    )
    assert run_resp.status_code == 200
    assert run_resp.json()["matches_created"] >= 0

    pending_resp = await client.get("/reconciliation/pending")
    assert pending_resp.status_code == 200
    pending_data = pending_resp.json()
    assert pending_data["total"] == 4

    accept_resp = await client.post(f"/reconciliation/matches/{match_accept.id}/accept")
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "accepted"

    reject_resp = await client.post(f"/reconciliation/matches/{match_reject.id}/reject")
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"

    batch_resp = await client.post(
        "/reconciliation/batch-accept",
        json={"match_ids": [str(match_batch.id)]},
    )
    assert batch_resp.status_code == 200
    assert batch_resp.json()["total"] == 1

    matches_resp = await client.get(
        "/reconciliation/matches",
        params={"status": "pending_review"},
    )
    assert matches_resp.status_code == 200
    matches_data = matches_resp.json()
    assert matches_data["total"] == 1

    matches_all_resp = await client.get("/reconciliation/matches")
    assert matches_all_resp.status_code == 200
    matches_all_data = matches_all_resp.json()
    entries_item = next(
        (item for item in matches_all_data["items"] if item.get("entries")),
        None,
    )
    assert entries_item is not None
    entry_summary = entries_item["entries"][0]
    assert entry_summary["memo"]
    assert entry_summary["entry_date"]
    assert Decimal(str(entry_summary["total_amount"])) > 0

    stats_resp = await client.get("/reconciliation/stats")
    assert stats_resp.status_code == 200

    unmatched_resp = await client.get("/reconciliation/unmatched")
    assert unmatched_resp.status_code == 200
    assert unmatched_resp.json()["total"] >= 1

    create_entry_resp = await client.post(f"/reconciliation/unmatched/{txn_unmatched.id}/create-entry")
    assert create_entry_resp.status_code == 200

    anomalies_resp = await client.get(f"/reconciliation/transactions/{txn_unmatched.id}/anomalies")
    assert anomalies_resp.status_code == 200


@pytest.mark.asyncio
async def test_reconciliation_error_paths(client: AsyncClient) -> None:
    missing_accept = await client.post(f"/reconciliation/matches/{uuid4()}/accept")
    assert missing_accept.status_code == 404

    missing_reject = await client.post(f"/reconciliation/matches/{uuid4()}/reject")
    assert missing_reject.status_code == 404

    missing_create_entry = await client.post(f"/reconciliation/unmatched/{uuid4()}/create-entry")
    assert missing_create_entry.status_code == 404

    missing_anomalies = await client.get(f"/reconciliation/transactions/{uuid4()}/anomalies")
    assert missing_anomalies.status_code == 404


@pytest.mark.asyncio
async def test_reconciliation_stats_empty(client: AsyncClient) -> None:
    resp = await client.get("/reconciliation/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_transactions"] == 0
    assert data["match_rate"] == 0.0


@pytest.mark.asyncio
async def test_reconciliation_run_defaults(client: AsyncClient) -> None:
    resp = await client.post("/reconciliation/run", json={})
    assert resp.status_code == 200
