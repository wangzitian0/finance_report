"""Unit tests for SqlReconciliationRepository (the port's SQLAlchemy adapter)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.models.layer2 import AtomicTransaction
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.reconciliation.extension.repository import SqlReconciliationRepository
from tests.ledger._ledger_helpers import create_valid_posted_entry


def _atomic_txn(*, owner_id, **kwargs) -> AtomicTransaction:
    kwargs.setdefault("currency", "SGD")
    kwargs.setdefault("dedup_hash", uuid4().hex + uuid4().hex)
    kwargs.setdefault("source_documents", [{"doc_id": str(uuid4()), "doc_type": "bank_statement"}])
    return AtomicTransaction(user_id=owner_id, **kwargs)


async def test_list_pending_transactions_excludes_matched_and_other_users(db: AsyncSession, test_user) -> None:
    other_user = User(email=f"repo-test-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()
    other_user_id = other_user.id
    pending = _atomic_txn(
        owner_id=test_user.id,
        txn_date=date(2024, 1, 1),
        description="Pending",
        amount=Decimal("10.00"),
        direction="OUT",
    )
    matched = _atomic_txn(
        owner_id=test_user.id,
        txn_date=date(2024, 1, 2),
        description="Already matched",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    other_users_txn = _atomic_txn(
        owner_id=other_user_id,
        txn_date=date(2024, 1, 3),
        description="Someone else's txn",
        amount=Decimal("30.00"),
        direction="OUT",
    )
    db.add_all([pending, matched, other_users_txn])
    await db.flush()
    db.add(
        ReconciliationMatch(
            atomic_txn_id=matched.id,
            journal_entry_ids=[str(uuid4())],
            match_score=90,
            status=ReconciliationStatus.AUTO_ACCEPTED,
        )
    )
    await db.commit()

    repo = SqlReconciliationRepository(db)
    results = await repo.list_pending_transactions(test_user.id)

    assert [txn.id for txn in results] == [pending.id]


async def test_list_pending_transactions_limit_zero_returns_no_rows(db: AsyncSession, test_user) -> None:
    txn = _atomic_txn(
        owner_id=test_user.id,
        txn_date=date(2024, 1, 1),
        description="Pending",
        amount=Decimal("10.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()

    repo = SqlReconciliationRepository(db)
    assert await repo.list_pending_transactions(test_user.id, limit=0) == []
    assert len(await repo.list_pending_transactions(test_user.id, limit=1)) == 1


async def test_list_journal_candidates_filters_by_date_range_and_excludes_void(db: AsyncSession, test_user) -> None:
    in_range = await create_valid_posted_entry(db, test_user.id, entry_date=date(2024, 1, 15), memo="In range")
    out_of_range = await create_valid_posted_entry(db, test_user.id, entry_date=date(2024, 3, 1), memo="Out of range")

    repo = SqlReconciliationRepository(db)
    results = await repo.list_journal_candidates(
        user_id=test_user.id,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )

    result_ids = {entry.id for entry in results}
    assert in_range.id in result_ids
    assert out_of_range.id not in result_ids


async def test_get_active_match_excludes_superseded(db: AsyncSession, test_user) -> None:
    txn = _atomic_txn(
        owner_id=test_user.id,
        txn_date=date(2024, 1, 1),
        description="Txn",
        amount=Decimal("10.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.flush()

    repo = SqlReconciliationRepository(db)
    assert await repo.get_active_match(txn.id) is None

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(uuid4())],
        match_score=85,
        status=ReconciliationStatus.AUTO_ACCEPTED,
    )
    db.add(match)
    await db.commit()

    active = await repo.get_active_match(txn.id)
    assert active is not None
    assert active.id == match.id

    match.status = ReconciliationStatus.SUPERSEDED
    await db.commit()
    assert await repo.get_active_match(txn.id) is None


async def test_add_match_persists_the_record(db: AsyncSession, test_user) -> None:
    txn = _atomic_txn(
        owner_id=test_user.id,
        txn_date=date(2024, 1, 1),
        description="Txn",
        amount=Decimal("10.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.flush()

    repo = SqlReconciliationRepository(db)
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(uuid4())],
        match_score=75,
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    await repo.add_match(match)
    await db.commit()

    active = await repo.get_active_match(txn.id)
    assert active is not None
    assert active.match_score == 75
