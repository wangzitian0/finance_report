"""AC-reconciliation.rejection-recovery: rejected evidence is not a workflow tombstone."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.composition import compose_reviewed_disposition_dependencies
from src.extraction import EconomicIntent, TransactionDirection
from src.ledger import Account, AccountType, JournalEntry
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.reconciliation.base.errors import ReviewedDispositionError
from src.reconciliation.base.reviewed_disposition import ReviewedDispositionCommand
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.extension.review_queue import reject_match
from src.reconciliation.extension.reviewed_disposition import submit_reviewed_disposition
from src.routers.reconciliation import list_unmatched
from tests.factories import UserFactory, seed_parsed_statement


async def seed(db, user):
    bank = Account(user_id=user.id, name="Synthetic bank", type=AccountType.ASSET, currency="SGD")
    expense = Account(user_id=user.id, name="Reviewed expense", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([bank, expense])
    await db.flush()
    source = await seed_parsed_statement(
        db,
        user.id,
        transactions=[
            {"description": "Synthetic expense", "amount": Decimal("100"), "direction": TransactionDirection.OUT}
        ],
    )
    source.statement.account_id = bank.id
    txn = source.transactions[0]
    match = ReconciliationMatch(
        atomic_txn_id=txn.id, journal_entry_ids=[], match_score=70, status=ReconciliationStatus.PENDING_REVIEW
    )
    db.add(match)
    await db.commit()
    command = ReviewedDispositionCommand(
        intent=EconomicIntent.EXPENSE,
        counter_account_id=expense.id,
        category="AUDIT",
        rationale="Generated source reviewed",
    )
    return txn.id, match.id, command


async def test_rejected_match_can_be_reviewed(db, test_user):
    """AC-reconciliation.rejection-recovery.1: recover without deleting rejected history."""
    txn, mid, command = await seed(db, test_user)
    await reject_match(db, str(mid), user_id=test_user.id)
    await db.commit()
    queue = await list_unmatched(db=db, user_id=test_user.id, limit=100, offset=0)
    assert txn in {row.id for row in queue.items}
    entry = await submit_reviewed_disposition(
        db,
        transaction_id=txn,
        user_id=test_user.id,
        command=command,
        dependencies=compose_reviewed_disposition_dependencies(db),
    )
    await db.commit()
    assert entry.source_id == txn
    assert (await db.get(ReconciliationMatch, mid)).status == ReconciliationStatus.REJECTED
    queue = await list_unmatched(db=db, user_id=test_user.id, limit=100, offset=0)
    assert txn not in {row.id for row in queue.items}


async def test_active_match_blocks_and_rerun_honors_rejection(db, test_user):
    """AC-reconciliation.rejection-recovery.2: retries cannot undo a human rejection."""
    txn, mid, command = await seed(db, test_user)
    with pytest.raises(ReviewedDispositionError, match="already has"):
        await submit_reviewed_disposition(
            db,
            transaction_id=txn,
            user_id=test_user.id,
            command=command,
            dependencies=compose_reviewed_disposition_dependencies(db),
        )
    await reject_match(db, str(mid), user_id=test_user.id)
    await db.commit()
    pending = await SqlReconciliationRepository(db).list_pending_transactions(test_user.id)
    assert txn not in {row.id for row in pending}


async def test_concurrent_review_after_rejection(db_engine):
    """AC-reconciliation.rejection-recovery.3: separate sessions create only one command."""
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        user = await UserFactory.create_async(db, email=f"recovery-{uuid4()}@example.invalid")
        uid = user.id
        txn, mid, command = await seed(db, user)
        await reject_match(db, str(mid), user_id=uid)
        await db.commit()

    async def post():
        async with sessions() as db:
            entry = await submit_reviewed_disposition(
                db,
                transaction_id=txn,
                user_id=uid,
                command=command,
                dependencies=compose_reviewed_disposition_dependencies(db),
            )
            await db.commit()
            return entry.id

    ids = await asyncio.gather(post(), post())
    assert ids[0] == ids[1]
    async with sessions() as db:
        entries = (await db.execute(select(JournalEntry.id).where(JournalEntry.source_id == txn))).scalars().all()
        assert len(entries) == 1
        assert (await db.get(ReconciliationMatch, mid)).status == ReconciliationStatus.REJECTED


@pytest.mark.parametrize("source_state", ["retired", "superseded"])
async def test_historical_source_transactions_are_not_actionable(db, test_user, source_state):
    """AC-reconciliation.rejection-recovery.4: immutable history is never a new action."""
    from src.extraction import BankStatementStatus
    from src.extraction.orm.statement_summary import StatementSummary

    txn, mid, command = await seed(db, test_user)
    await reject_match(db, str(mid), user_id=test_user.id)
    source = await db.scalar(select(StatementSummary).where(StatementSummary.user_id == test_user.id))
    if source_state == "retired":
        source.status = BankStatementStatus.RETIRED
    else:
        source.extraction_metadata = {
            "statement_extraction_result": {"transactions": [{"fact_id": "replacement-only", "currency": "SGD"}]}
        }
    await db.commit()
    queue = await list_unmatched(db=db, user_id=test_user.id, limit=100, offset=0)
    assert txn not in {row.id for row in queue.items}
    scoped = await list_unmatched(db=db, user_id=test_user.id, statement_id=source.id, limit=100, offset=0)
    assert txn not in {row.id for row in scoped.items}
    # Remove no evidence: the history row remains queryable for audit.
    assert (await db.get(ReconciliationMatch, mid)).status == ReconciliationStatus.REJECTED
    unreviewed = await seed_parsed_statement(db, test_user.id)
    unreviewed.statement.status = (
        BankStatementStatus.RETIRED if source_state == "retired" else BankStatementStatus.PARSED
    )
    if source_state == "superseded":
        unreviewed.statement.extraction_metadata = {"statement_extraction_result": {"transactions": []}}
    await db.commit()
    pending = await SqlReconciliationRepository(db).list_pending_transactions(test_user.id)
    assert {txn, *(row.id for row in unreviewed.transactions)}.isdisjoint(row.id for row in pending)
    with pytest.raises(LookupError, match="Transaction not found"):
        await submit_reviewed_disposition(
            db,
            transaction_id=txn,
            user_id=test_user.id,
            command=command,
            dependencies=compose_reviewed_disposition_dependencies(db),
        )
