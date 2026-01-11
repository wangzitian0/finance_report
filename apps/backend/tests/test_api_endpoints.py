"""API endpoint tests for accounts, journal entries, and reconciliation."""

from __future__ import annotations

from datetime import date, timedelta
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


async def _create_account(client: AsyncClient, name: str, account_type: str) -> dict:
    payload = {"name": name, "type": account_type, "currency": "SGD"}
    resp = await client.post("/api/accounts", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_accounts_endpoints(client: AsyncClient) -> None:
    account = await _create_account(client, "Cash", "ASSET")

    basic_list_resp = await client.get("/api/accounts")
    assert basic_list_resp.status_code == 200
    assert basic_list_resp.json()["total"] >= 1

    list_resp = await client.get("/api/accounts", params={"include_balance": "true"})
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert list_data["items"][0]["balance"] is not None

    filter_resp = await client.get("/api/accounts", params={"account_type": "ASSET"})
    assert filter_resp.status_code == 200

    get_resp = await client.get(f"/api/accounts/{account['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == account["id"]

    update_resp = await client.put(
        f"/api/accounts/{account['id']}",
        json={"name": "Cash Vault", "code": "1001", "description": "Updated"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Cash Vault"

    deactivate_resp = await client.put(
        f"/api/accounts/{account['id']}",
        json={"is_active": False},
    )
    assert deactivate_resp.status_code == 200
    assert deactivate_resp.json()["is_active"] is False

    inactive_resp = await client.get("/api/accounts", params={"is_active": "false"})
    assert inactive_resp.status_code == 200
    assert inactive_resp.json()["total"] >= 1

    missing_resp = await client.get(f"/api/accounts/{uuid4()}")
    assert missing_resp.status_code == 404

    missing_update = await client.put(
        f"/api/accounts/{uuid4()}",
        json={"name": "Missing"},
    )
    assert missing_update.status_code == 404


@pytest.mark.asyncio
async def test_journal_entry_endpoints(client: AsyncClient) -> None:
    debit_account = await _create_account(client, "Bank", "ASSET")
    credit_account = await _create_account(client, "Revenue", "INCOME")

    entry_payload = {
        "entry_date": date.today().isoformat(),
        "memo": "Test entry",
        "lines": [
            {
                "account_id": debit_account["id"],
                "direction": "DEBIT",
                "amount": "100.00",
                "currency": "SGD",
            },
            {
                "account_id": credit_account["id"],
                "direction": "CREDIT",
                "amount": "100.00",
                "currency": "SGD",
            },
        ],
    }
    create_resp = await client.post("/api/journal-entries", json=entry_payload)
    assert create_resp.status_code == 201
    entry = create_resp.json()

    older_date = date.today() - timedelta(days=10)
    older_payload = {
        "entry_date": older_date.isoformat(),
        "memo": "Older entry",
        "lines": [
            {
                "account_id": debit_account["id"],
                "direction": "DEBIT",
                "amount": "50.00",
                "currency": "SGD",
            },
            {
                "account_id": credit_account["id"],
                "direction": "CREDIT",
                "amount": "50.00",
                "currency": "SGD",
            },
        ],
    }
    older_resp = await client.post("/api/journal-entries", json=older_payload)
    assert older_resp.status_code == 201
    older_entry = older_resp.json()

    list_resp = await client.get("/api/journal-entries", params={"status_filter": "draft"})
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    start_date_resp = await client.get(
        "/api/journal-entries",
        params={"start_date": date.today().isoformat()},
    )
    assert start_date_resp.status_code == 200
    start_ids = {item["id"] for item in start_date_resp.json()["items"]}
    assert older_entry["id"] not in start_ids

    end_date_resp = await client.get(
        "/api/journal-entries",
        params={"end_date": older_date.isoformat()},
    )
    assert end_date_resp.status_code == 200
    end_ids = {item["id"] for item in end_date_resp.json()["items"]}
    assert older_entry["id"] in end_ids

    get_resp = await client.get(f"/api/journal-entries/{entry['id']}")
    assert get_resp.status_code == 200

    missing_get = await client.get(f"/api/journal-entries/{uuid4()}")
    assert missing_get.status_code == 404

    post_resp = await client.post(f"/api/journal-entries/{entry['id']}/post")
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "posted"

    void_resp = await client.post(
        f"/api/journal-entries/{entry['id']}/void",
        json={"reason": "Test void"},
    )
    assert void_resp.status_code == 200
    assert void_resp.json()["status"] == "posted"

    missing_post = await client.post(f"/api/journal-entries/{uuid4()}/post")
    assert missing_post.status_code == 400

    missing_void = await client.post(
        f"/api/journal-entries/{uuid4()}/void",
        json={"reason": "missing"},
    )
    assert missing_void.status_code == 400


@pytest.mark.asyncio
async def test_reconciliation_endpoints(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
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
        "/api/reconciliation/run",
        json={"statement_id": str(statement_run.id)},
    )
    assert run_resp.status_code == 200
    assert run_resp.json()["matches_created"] >= 0

    pending_resp = await client.get("/api/reconciliation/pending")
    assert pending_resp.status_code == 200

    accept_resp = await client.post(
        f"/api/reconciliation/matches/{match_accept.id}/accept"
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "accepted"

    reject_resp = await client.post(
        f"/api/reconciliation/matches/{match_reject.id}/reject"
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"

    batch_resp = await client.post(
        "/api/reconciliation/batch-accept",
        json={"match_ids": [str(match_batch.id)]},
    )
    assert batch_resp.status_code == 200
    assert batch_resp.json()["total"] == 1

    matches_resp = await client.get(
        "/api/reconciliation/matches",
        params={"status": "pending_review"},
    )
    assert matches_resp.status_code == 200

    matches_all_resp = await client.get("/api/reconciliation/matches")
    assert matches_all_resp.status_code == 200

    stats_resp = await client.get("/api/reconciliation/stats")
    assert stats_resp.status_code == 200

    unmatched_resp = await client.get("/api/reconciliation/unmatched")
    assert unmatched_resp.status_code == 200
    assert unmatched_resp.json()["total"] >= 1

    create_entry_resp = await client.post(
        f"/api/reconciliation/unmatched/{txn_unmatched.id}/create-entry"
    )
    assert create_entry_resp.status_code == 200

    anomalies_resp = await client.get(
        f"/api/reconciliation/transactions/{txn_unmatched.id}/anomalies"
    )
    assert anomalies_resp.status_code == 200


@pytest.mark.asyncio
async def test_reconciliation_error_paths(client: AsyncClient) -> None:
    missing_accept = await client.post(
        f"/api/reconciliation/matches/{uuid4()}/accept"
    )
    assert missing_accept.status_code == 404

    missing_reject = await client.post(
        f"/api/reconciliation/matches/{uuid4()}/reject"
    )
    assert missing_reject.status_code == 404

    missing_create_entry = await client.post(
        f"/api/reconciliation/unmatched/{uuid4()}/create-entry"
    )
    assert missing_create_entry.status_code == 404

    missing_anomalies = await client.get(
        f"/api/reconciliation/transactions/{uuid4()}/anomalies"
    )
    assert missing_anomalies.status_code == 404


@pytest.mark.asyncio
async def test_reconciliation_stats_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/reconciliation/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_transactions"] == 0
    assert data["match_rate"] == 0.0


@pytest.mark.asyncio
async def test_reconciliation_run_defaults(client: AsyncClient) -> None:
    resp = await client.post("/api/reconciliation/run", json={})
    assert resp.status_code == 200
