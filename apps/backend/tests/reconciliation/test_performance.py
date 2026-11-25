from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reconciliation import DEFAULT_CONFIG, execute_matching, score_single
from tests.factories import AccountFactory


def _atomic(uid, d: date, desc: str, amt: Decimal, direction: str) -> AtomicTransaction:
    return AtomicTransaction(user_id=uid, txn_date=d, description=desc, amount=amt, direction=TransactionDirection(direction), currency="SGD", dedup_hash=uuid4().hex + uuid4().hex, source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}])


def _entry(db: AsyncSession, uid, debit_acc, credit_acc, amt: Decimal, d: date, memo: str) -> JournalEntry:
    e = JournalEntry(user_id=uid, entry_date=d, memo=memo, source_type=JournalEntrySourceType.MANUAL, status=JournalEntryStatus.POSTED, lines=[JournalLine(account_id=debit_acc.id, direction=Direction.DEBIT, amount=amt, currency="SGD"), JournalLine(account_id=credit_acc.id, direction=Direction.CREDIT, amount=amt, currency="SGD")])
    db.add(e)
    return e


async def test_high_confidence_matches_and_parallel_matching(db: AsyncSession, test_user):
    uid = test_user.id
    bank, income = await AccountFactory.create_async(db, user_id=uid, name="Bank Acc"), await AccountFactory.create_async(db, user_id=uid, name="Inc Acc", type=AccountType.INCOME)
    for i in range(10):
        d, amt, memo = date(2024, 1, 15) + timedelta(days=i), Decimal("100.00") + Decimal(str(i * 10)), f"Exact Match Test {i}"
        _entry(db, uid, bank, income, amt, d, memo)
        db.add(_atomic(uid, d, memo, amt, "IN"))
    await db.commit()
    assert sum(1 for m in await execute_matching(db, user_id=uid, currency="SGD") if m.match_score >= 85) >= 8

    db.add_all([_atomic(uid, date(2024, 1, i + 1), f"Stmt{i} Txn{j}", Decimal(str(100 + i * 10 + j)), "IN") for i in range(3) for j in range(5)])
    await db.commit()
    results = [await execute_matching(db, user_id=uid, currency="SGD") for _ in range(3)]
    assert len(results) == 3 and all(isinstance(r, list) for r in results)


@pytest.mark.parametrize(
    ("acc_type", "entry_date", "memo", "entry_amt", "txn_date", "txn_desc", "txn_amt", "direction", "min_score", "max_score"),
    [
        (AccountType.EXPENSE, date(2024, 1, 5), "Monthly Rent Payment to Landlord", "2000.00", date(2023, 12, 20), "Coffee Shop Purchase", "5.50", "OUT", 0, 59),
        (AccountType.INCOME, date(2024, 1, 25), "January Salary from Employer Inc", "5000.00", date(2024, 1, 25), "EMPLOYER INC SALARY JAN", "5000.00", "IN", 60, 100),
        (AccountType.INCOME, date(2024, 2, 1), "Monthly Subscription", "99.00", date(2024, 1, 31), "Monthly Subscription", "99.00", "IN", 70, 100),
        (AccountType.EXPENSE, date(2024, 1, 15), "Client Dinner Expense", "150.00", date(2024, 1, 12), "CLIENT DINNER", "150.00", "OUT", 65, 100),
    ],
)
async def test_score_single_bands(db: AsyncSession, test_user, acc_type, entry_date, memo, entry_amt, txn_date, txn_desc, txn_amt, direction, min_score, max_score):
    uid = test_user.id
    bank, other = await AccountFactory.create_async(db, user_id=uid, name=f"B-{memo[:8]}"), await AccountFactory.create_async(db, user_id=uid, name=f"O-{memo[:8]}", type=acc_type)
    debit, credit = (bank, other) if direction == "IN" else (other, bank)
    entry = _entry(db, uid, debit, credit, Decimal(entry_amt), entry_date, memo)
    txn = _atomic(uid, txn_date, txn_desc, Decimal(txn_amt), direction)
    db.add(txn)
    await db.commit()
    await db.refresh(entry, ["lines"])
    assert min_score <= (await score_single(db, txn, [entry], DEFAULT_CONFIG, user_id=uid)).score <= max_score
