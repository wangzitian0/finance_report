from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.composition import compose_reviewed_disposition_dependencies
from src.extraction import BankStatementStatus, EconomicIntent, TransactionDirection
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import AccountType, JournalEntry
from src.platform import ResourceNotFoundError
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.reconciliation.base.errors import ReviewedDispositionError
from src.reconciliation.base.reviewed_disposition import ReviewedDispositionCommand
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.extension.review_queue import reject_match
from src.reconciliation.extension.reviewed_disposition import submit_reviewed_disposition
from src.request_context import RequestContext
from src.routers.reconciliation import list_unmatched
from tests.factories import AccountFactory, UserFactory, seed_parsed_statement


async def seed(db, user_id):
    bank = await AccountFactory.create_async(db, user_id=user_id, name="Synthetic bank")
    expense = await AccountFactory.create_async(db, user_id=user_id, name="Reviewed expense", type=AccountType.EXPENSE)
    src = await seed_parsed_statement(
        db,
        user_id,
        transactions=[
            {"description": "Synthetic expense", "amount": Decimal("100"), "direction": TransactionDirection.OUT}
        ],
    )
    src.statement.account_id, src.statement.status = bank.id, BankStatementStatus.APPROVED
    txn = src.transactions[0]
    m = ReconciliationMatch(
        atomic_txn_id=txn.id, journal_entry_ids=[], match_score=70, status=ReconciliationStatus.PENDING_REVIEW
    )
    db.add(m)
    await db.commit()
    return (
        txn.id,
        m.id,
        ReviewedDispositionCommand(
            intent=EconomicIntent.EXPENSE,
            counter_account_id=expense.id,
            category="AUDIT",
            rationale="Generated source reviewed",
        ),
    )


async def test_rejected_match_can_be_reviewed_and_active_blocks(db, test_user):
    uid, deps = test_user.id, compose_reviewed_disposition_dependencies(db)
    txn, mid, cmd = await seed(db, uid)
    with pytest.raises(ReviewedDispositionError, match="already has"):
        await submit_reviewed_disposition(
            db, transaction_id=txn, user_id=uid, command=cmd, dependencies=deps, base_currency="SGD"
        )

    await reject_match(db, str(mid), user_id=uid)
    await db.commit()
    assert txn not in {r.id for r in await SqlReconciliationRepository(db).list_pending_transactions(uid)}
    assert txn in {r.id for r in (await list_unmatched(limit=100, offset=0, ctx=RequestContext(db, uid))).items}

    entry = await submit_reviewed_disposition(
        db, transaction_id=txn, user_id=uid, command=cmd, dependencies=deps, base_currency="SGD"
    )
    await db.commit()
    assert entry.source_id == txn and (await db.get(ReconciliationMatch, mid)).status == ReconciliationStatus.REJECTED
    assert txn not in {r.id for r in (await list_unmatched(limit=100, offset=0, ctx=RequestContext(db, uid))).items}


async def test_concurrent_review_after_rejection(db_engine):
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        uid = (await UserFactory.create_async(db, email=f"recovery-{uuid4()}@example.invalid")).id
        txn, mid, cmd = await seed(db, uid)
        await reject_match(db, str(mid), user_id=uid)
        await db.commit()

    async def post():
        async with sessions() as db:
            entry = await submit_reviewed_disposition(
                db,
                transaction_id=txn,
                user_id=uid,
                command=cmd,
                dependencies=compose_reviewed_disposition_dependencies(db),
                base_currency="SGD",
            )
            await db.commit()
            return entry.id

    ids = await asyncio.gather(post(), post())
    assert ids[0] == ids[1]
    async with sessions() as db:
        assert (
            len((await db.execute(select(JournalEntry.id).where(JournalEntry.source_id == txn))).scalars().all()) == 1
        )
        assert (await db.get(ReconciliationMatch, mid)).status == ReconciliationStatus.REJECTED


@pytest.mark.parametrize("source_state", ["retired", "superseded"])
async def test_historical_source_transactions_are_not_actionable(db, test_user, source_state):
    uid = test_user.id
    txn, mid, cmd = await seed(db, uid)
    await reject_match(db, str(mid), user_id=uid)
    source = await db.scalar(select(StatementSummary).where(StatementSummary.user_id == uid))
    unreviewed = await seed_parsed_statement(db, uid)
    if source_state == "retired":
        source.status = unreviewed.statement.status = BankStatementStatus.RETIRED
    else:
        source.extraction_metadata = {
            "statement_extraction_result": {"transactions": [{"fact_id": "replacement-only", "currency": "SGD"}]}
        }
        unreviewed.statement.extraction_metadata = {"statement_extraction_result": {"transactions": []}}
    await db.commit()

    ctx = RequestContext(db, uid)
    assert txn not in {r.id for r in (await list_unmatched(limit=100, offset=0, ctx=ctx)).items}
    assert txn not in {r.id for r in (await list_unmatched(statement_id=source.id, limit=100, offset=0, ctx=ctx)).items}
    assert (await db.get(ReconciliationMatch, mid)).status == ReconciliationStatus.REJECTED
    assert {txn, *(r.id for r in unreviewed.transactions)}.isdisjoint(
        r.id for r in await SqlReconciliationRepository(db).list_pending_transactions(uid)
    )
    with pytest.raises(ResourceNotFoundError, match="Transaction not found"):
        await submit_reviewed_disposition(
            db,
            transaction_id=txn,
            user_id=uid,
            command=cmd,
            dependencies=compose_reviewed_disposition_dependencies(db),
            base_currency="SGD",
        )
