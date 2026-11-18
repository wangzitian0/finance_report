from __future__ import annotations

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import TransactionDirection
from src.ledger import AccountType, Direction, post_journal_entry, submit_manual_journal_entry, validate_manual_journal_entry_for_post
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from tests.factories import AccountFactory, AtomicTransactionFactory


async def _post_manual(db: AsyncSession, uid, debit_acc, credit_acc, amount: Decimal, memo: str):
    e = await submit_manual_journal_entry(db, user_id=uid, entry_date=date.today(), memo=memo, rationale=f"Test: {memo}", lines_data=[{"account_id": debit_acc.id, "direction": Direction.DEBIT, "amount": amount, "currency": "SGD"}, {"account_id": credit_acc.id, "direction": Direction.CREDIT, "amount": amount, "currency": "SGD"}], base_currency="SGD")
    await db.refresh(e, ["lines"])
    await validate_manual_journal_entry_for_post(db, user_id=uid, entry=e, base_currency="SGD")
    return await post_journal_entry(db, e.id, uid, base_currency="SGD")


async def test_reconciliation_endpoints(client: AsyncClient, db: AsyncSession, test_user) -> None:
    uid = test_user.id
    empty = await client.get("/reconciliation/stats")
    assert empty.status_code == 200 and (empty.json()["total_transactions"], empty.json()["match_rate"]) == (0, 0.0)

    bank = await AccountFactory.create_async(db, user_id=uid, name="Bank - Main")
    inc = await AccountFactory.create_async(db, user_id=uid, name="Income", type=AccountType.INCOME)
    exp = await AccountFactory.create_async(db, user_id=uid, name="Expense", type=AccountType.EXPENSE)
    await _post_manual(db, uid, bank, inc, Decimal("1000.00"), "Salary Payment")
    await AtomicTransactionFactory.create_async(db, user_id=uid, description="Salary Payment", amount=Decimal("1000.00"), direction=TransactionDirection.IN)
    await db.commit()
    run_resp = await client.post("/reconciliation/runs", json={})
    assert run_resp.status_code == 200 and run_resp.json()["matches_created"] >= 0

    matches = []
    for desc, amt, score, bamt, create_entry in (("Coffee", "12.00", 82, 90.0, True), ("Snacks", "8.00", 70, 80.0, True), ("Lunch", "20.00", 90, 95.0, True), ("Small Charge", "9.00", 50, 40.0, False)):
        e = await _post_manual(db, uid, exp, bank, Decimal(amt), desc) if create_entry else None
        t = await AtomicTransactionFactory.create_async(db, user_id=uid, description=desc, amount=Decimal(amt), direction=TransactionDirection.OUT)
        m = ReconciliationMatch(atomic_txn_id=t.id, journal_entry_ids=[str(e.id)] if e else [], match_score=score, score_breakdown={"amount": bamt}, status=ReconciliationStatus.PENDING_REVIEW)
        db.add(m)
        matches.append(m)
    t_unm = await AtomicTransactionFactory.create_async(db, user_id=uid, description="Odd Vendor", amount=Decimal("5.00"), direction=TransactionDirection.OUT)
    await db.commit()

    assert (await client.get("/reconciliation/pending")).json()["total"] == 4
    assert (await client.patch(f"/reconciliation/matches/{matches[0].id}", json={"action": "accept"})).json()["status"] == "accepted"
    assert (await client.patch(f"/reconciliation/matches/{matches[1].id}", json={"action": "reject"})).json()["status"] == "rejected"
    assert (await client.post("/reconciliation/matches", json={"action": "accept", "match_ids": [str(matches[2].id)]})).json()["approved_count"] == 1
    assert (await client.get("/reconciliation/matches", params={"status": "pending_review"})).json()["total"] == 1
    es = next(i for i in (await client.get("/reconciliation/matches")).json()["items"] if i.get("entries"))["entries"][0]
    assert es["memo"] and es["entry_date"] and Decimal(str(es["total_amount"])) > 0 and (await client.get("/reconciliation/stats")).status_code == 200
    assert (await client.get("/reconciliation/unmatched")).json()["total"] >= 1
    assert (await client.post(f"/reconciliation/unmatched/{t_unm.id}/create-entry")).status_code == 404
    assert (await client.get(f"/reconciliation/transactions/{t_unm.id}/anomalies")).status_code == 200
