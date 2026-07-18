"""AC4.3.1, AC4.3.8: Reconciliation API Endpoint Tests

These tests validate reconciliation API endpoints including running reconciliation,
pending review queue, accepting/rejecting matches, batch operations,
and statistics queries.

Fixtures are built natively on Layer 2: pending transactions are
``AtomicTransaction`` rows, and matches are keyed on ``atomic_txn_id``. A
transaction is "unmatched" when it has no ``ReconciliationMatch`` row.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    post_journal_entry,
    submit_manual_journal_entry,
    validate_manual_journal_entry_for_post,
)
from src.reconciliation import ReconciliationMatch, ReconciliationStatus


def _atomic(user_id, *, description, amount, direction=TransactionDirection.OUT):
    return AtomicTransaction(
        user_id=user_id,
        txn_date=date.today(),
        description=description,
        amount=amount,
        direction=direction,
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}],
    )


async def _post_manual_entry(
    db: AsyncSession,
    *,
    user_id,
    entry_date: date,
    memo: str,
    debit_account: Account,
    credit_account: Account,
    amount: Decimal,
) -> JournalEntry:
    entry = await submit_manual_journal_entry(
        db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        rationale=f"Test operator attested reconciliation candidate: {memo}",
        lines_data=[
            {"account_id": debit_account.id, "direction": Direction.DEBIT, "amount": amount, "currency": "SGD"},
            {"account_id": credit_account.id, "direction": Direction.CREDIT, "amount": amount, "currency": "SGD"},
        ],
        base_currency="SGD",
    )
    await db.refresh(entry, ["lines"])
    await validate_manual_journal_entry_for_post(
        db,
        user_id=user_id,
        entry=entry,
        base_currency="SGD",
    )
    return await post_journal_entry(db, entry.id, user_id, base_currency="SGD")


async def test_reconciliation_endpoints(client: AsyncClient, db: AsyncSession, test_user) -> None:
    session = db
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
    session.add_all([bank_account, income_account, expense_account])
    await session.flush()

    await _post_manual_entry(
        session,
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Salary Payment",
        debit_account=bank_account,
        credit_account=income_account,
        amount=Decimal("1000.00"),
    )
    entry_accept = await _post_manual_entry(
        session,
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Coffee",
        debit_account=expense_account,
        credit_account=bank_account,
        amount=Decimal("12.00"),
    )
    entry_reject = await _post_manual_entry(
        session,
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Snacks",
        debit_account=expense_account,
        credit_account=bank_account,
        amount=Decimal("8.00"),
    )
    entry_batch = await _post_manual_entry(
        session,
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Lunch",
        debit_account=expense_account,
        credit_account=bank_account,
        amount=Decimal("20.00"),
    )

    # txn_run is the only pending atomic transaction when /run executes, so the
    # engine auto-accepts it against entry_run without touching the other rows.
    txn_run = _atomic(
        test_user.id, description="Salary Payment", amount=Decimal("1000.00"), direction=TransactionDirection.IN
    )
    session.add(txn_run)
    await session.commit()

    run_resp = await client.post(
        "/reconciliation/runs",
        json={},
    )
    assert run_resp.status_code == 200
    assert run_resp.json()["matches_created"] >= 0

    # Now seed the pre-matched review queue and one genuinely unmatched transaction.
    txn_accept = _atomic(test_user.id, description="Coffee", amount=Decimal("12.00"))
    txn_reject = _atomic(test_user.id, description="Snacks", amount=Decimal("8.00"))
    txn_batch = _atomic(test_user.id, description="Lunch", amount=Decimal("20.00"))
    txn_unmatched = _atomic(test_user.id, description="Odd Vendor", amount=Decimal("5.00"))
    txn_low = _atomic(test_user.id, description="Small Charge", amount=Decimal("9.00"))
    session.add_all([txn_accept, txn_reject, txn_batch, txn_unmatched, txn_low])
    await session.flush()

    match_accept = ReconciliationMatch(
        atomic_txn_id=txn_accept.id,
        journal_entry_ids=[str(entry_accept.id)],
        match_score=82,
        score_breakdown={"amount": 90.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_reject = ReconciliationMatch(
        atomic_txn_id=txn_reject.id,
        journal_entry_ids=[str(entry_reject.id)],
        match_score=70,
        score_breakdown={"amount": 80.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_batch = ReconciliationMatch(
        atomic_txn_id=txn_batch.id,
        journal_entry_ids=[str(entry_batch.id)],
        match_score=90,
        score_breakdown={"amount": 95.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_low = ReconciliationMatch(
        atomic_txn_id=txn_low.id,
        journal_entry_ids=[],
        match_score=50,
        score_breakdown={"amount": 40.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    session.add_all([match_accept, match_reject, match_batch, match_low])
    await session.commit()

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
    assert create_entry_resp.status_code == 404

    anomalies_resp = await client.get(f"/reconciliation/transactions/{txn_unmatched.id}/anomalies")
    assert anomalies_resp.status_code == 200


async def test_reconciliation_error_paths(client: AsyncClient) -> None:
    missing_accept = await client.post(f"/reconciliation/matches/{uuid4()}/accept")
    assert missing_accept.status_code == 404

    missing_reject = await client.post(f"/reconciliation/matches/{uuid4()}/reject")
    assert missing_reject.status_code == 404

    missing_create_entry = await client.post(f"/reconciliation/unmatched/{uuid4()}/create-entry")
    assert missing_create_entry.status_code == 404

    missing_anomalies = await client.get(f"/reconciliation/transactions/{uuid4()}/anomalies")
    assert missing_anomalies.status_code == 404


async def test_reconciliation_stats_empty(client: AsyncClient) -> None:
    resp = await client.get("/reconciliation/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_transactions"] == 0
    assert data["match_rate"] == 0.0


async def test_reconciliation_run_defaults(client: AsyncClient) -> None:
    resp = await client.post("/reconciliation/runs", json={})
    assert resp.status_code == 200
