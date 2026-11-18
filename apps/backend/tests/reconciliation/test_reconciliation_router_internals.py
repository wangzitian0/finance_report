from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from src.audit.orm import TraceRecordRow
from src.composition import compose_reviewed_disposition_dependencies
from src.extraction import BankStatementStatus, CurrencyUnresolvedError, DispositionPolicy, EconomicIntent
from src.extraction.extension.review_queue import create_entry_from_txn
from src.identity import User
from src.ledger import JournalEntry
from src.reconciliation import (
    AmountMismatchError,
    ReconciliationMatch,
    ReconciliationStatus,
    ReviewedDispositionCommand,
    ReviewedDispositionDependencies,
    submit_reviewed_disposition,
)
from src.reconciliation.extension import review_queue
from src.reconciliation.extension.review_queue import (
    accept_match as accept_match_service,
    batch_decide_matches as batch_decide_service,
    reject_match as reject_match_service,
)
from src.request_context import RequestContext
from src.routers import reconciliation as reconciliation_router
from src.routers.reconciliation import _load_entry_summaries
from src.schemas.reconciliation import (
    ReconciliationMatchBatchRequest,
    ReconciliationRunRequest,
    ReviewedDispositionRequest,
)
from tests.api.test_reconciliation_router import (
    _seed_expense_setup,
    _seed_router_match,
    _seed_router_txns,
    create_anchored_match_entry,
    create_test_match,
    create_test_statement,
    create_test_transaction,
)
from tests.factories import UserFactory


async def test_AC_reconciliation_review_queue_15_scopes_statement_in_sql(db, db_engine, test_user: User) -> None:
    statement = await create_test_statement(db, test_user)
    db.add(create_test_transaction(db, statement))
    await db.commit()
    executed_statements: list[str] = []

    def capture_sql(_conn, _cursor, statement_text, _parameters, _context, _executemany):
        executed_statements.append(statement_text)

    event.listen(db_engine.sync_engine, "before_cursor_execute", capture_sql)
    try:
        response = await reconciliation_router.list_unmatched(
            statement_id=statement.id, limit=100, offset=0, ctx=RequestContext(db, test_user.id)
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", capture_sql)
    assert response.total == 1
    assert len(executed_statements) == 3
    assert sum("source_documents" in statement_text for statement_text in executed_statements) == 2


async def test_reviewed_disposition_rolls_back_its_decision_when_posting_fails(db, test_user: User, monkeypatch) -> None:
    _, _, transaction, expense = await _seed_expense_setup(db, test_user, expense_name="Expense - Fault Injection")
    transaction_id = transaction.id

    async def fail_after_decision(*_args, **_kwargs):
        raise RuntimeError("journal posting fault")

    monkeypatch.setattr("src.reconciliation.extension.reviewed_disposition.create_entry_from_txn", fail_after_decision)
    with pytest.raises(RuntimeError, match="journal posting fault"):
        await reconciliation_router.submit_unmatched_reviewed_disposition(
            transaction_id,
            ReviewedDispositionRequest(
                intent="expense",
                counter_account_id=expense.id,
                category="DINING",
                rationale="A deterministic posting fault tests transaction rollback.",
            ),
            ctx=RequestContext(db, test_user.id),
        )
    await db.rollback()
    traces = await db.execute(select(TraceRecordRow).where(TraceRecordRow.target_id == str(transaction_id)))
    entries = await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction_id))
    assert traces.scalars().all() == []
    assert entries.scalars().all() == []


async def test_reviewed_disposition_rolls_back_when_trace_append_fails(db, test_user: User, monkeypatch) -> None:
    _, _, transaction, expense = await _seed_expense_setup(db, test_user, expense_name="Expense - Trace Fault")
    transaction_id = transaction.id

    class FailingRepository:
        async def current_decision(self, *_args):
            return None

    class FailingEmitter:
        repository = FailingRepository()

        async def emit_many(self, _records):
            raise RuntimeError("trace append fault")

    dependencies = ReviewedDispositionDependencies(
        trace_emitter=FailingEmitter(), disposition_policy=DispositionPolicy()
    )
    monkeypatch.setattr(reconciliation_router, "compose_reviewed_disposition_dependencies", lambda _db: dependencies)
    with pytest.raises(RuntimeError, match="trace append fault"):
        await reconciliation_router.submit_unmatched_reviewed_disposition(
            transaction_id,
            ReviewedDispositionRequest(
                intent="expense",
                counter_account_id=expense.id,
                category="DINING",
                rationale="Trace failure must abort posting.",
            ),
            ctx=RequestContext(db, test_user.id),
        )
    await db.rollback()
    traces = await db.execute(select(TraceRecordRow).where(TraceRecordRow.target_id == str(transaction_id)))
    entries = await db.execute(select(JournalEntry).where(JournalEntry.source_id == transaction_id))
    assert traces.scalars().all() == []
    assert entries.scalars().all() == []


def test_legacy_unmatched_create_entry_helper_removed() -> None:
    assert not hasattr(reconciliation_router, "create_entry")


async def test_load_transactions_enforces_user_isolation(db, test_user: User) -> None:
    other_user_id = uuid4()
    _, transaction, match = await _seed_router_match(db, test_user)
    loaded_owner = await reconciliation_router._load_transactions(db, [match], user_id=test_user.id)
    assert transaction.id in loaded_owner
    loaded_other = await reconciliation_router._load_transactions(db, [match], user_id=other_user_id)
    assert transaction.id not in loaded_other


async def test_build_match_response_includes_entries(db, test_user: User) -> None:
    account, _, transaction, expense = await _seed_expense_setup(db, test_user)
    entry = await create_anchored_match_entry(
        db,
        user_id=test_user.id,
        bank_account=account,
        counter_account=expense,
        entry_date=transaction.txn_date,
        memo="Test entry",
        amount=transaction.amount,
    )
    match = create_test_match(
        db,
        transaction,
        match_score=85,
        journal_entry_ids=[str(entry.id)],
        score_breakdown={"amount": 90.0, "group_total": "100.00"},
    )
    db.add(match)
    await db.commit()
    entry_summaries = await _load_entry_summaries(db, [match], test_user.id)
    response = reconciliation_router._build_match_response(
        match, transaction=transaction, entry_summaries=entry_summaries
    )
    assert response.transaction is not None
    assert len(response.entries) == 1
    assert response.entries[0].total_amount == Decimal("100.00")
    assert response.entries[0].entry_date == entry.entry_date
    assert response.entries[0].memo == "Test entry"
    assert response.entries[0].id == entry.id
    assert response.score_breakdown == {"amount": 90.0, "group_total": "100.00"}


async def test_AC10_8_3_reconciliation_run_audit_checkpoints(db, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    statement, _ = await _seed_router_txns(db, test_user, count=1)
    statement_id = statement.id

    async def fake_execute_matching(*_args, **_kwargs):
        return [
            ReconciliationMatch(
                atomic_txn_id=uuid4(),
                journal_entry_ids=[],
                match_score=90,
                score_breakdown={},
                status=ReconciliationStatus.AUTO_ACCEPTED,
            )
        ]

    mock_info = MagicMock()
    mock_exception = MagicMock()
    monkeypatch.setattr(reconciliation_router, "execute_matching", fake_execute_matching)
    monkeypatch.setattr(reconciliation_router.logger, "info", mock_info)
    monkeypatch.setattr(reconciliation_router.logger, "exception", mock_exception)
    response = await reconciliation_router.run_reconciliation(
        ReconciliationRunRequest(statement_id=statement_id, limit=25), ctx=RequestContext(db, test_user.id)
    )
    calls = [(call.args[0], call.kwargs) for call in mock_info.call_args_list]
    started = next(kwargs for event_name, kwargs in calls if event_name == "reconciliation.run.started")
    completed = next(kwargs for event_name, kwargs in calls if event_name == "reconciliation.run.completed")
    assert response.matches_created == 1
    assert started["audit_event"] == "reconciliation.run.started"
    assert started["request_id"]
    assert started["statement_id"] == str(statement_id)
    assert started["phase"] == "matching_started"
    assert started["limit"] == 25
    assert completed["audit_event"] == "reconciliation.run.completed"
    assert completed["request_id"] == started["request_id"]
    assert completed["matches_created"] == 1
    assert completed["auto_accepted"] == 1
    assert completed["pending_review"] == 0
    assert completed["unmatched"] == 1

    async def fail_execute_matching(*_args, **_kwargs):
        raise RuntimeError("matching score service unavailable with raw details omitted")

    monkeypatch.setattr(reconciliation_router, "execute_matching", fail_execute_matching)
    with pytest.raises(RuntimeError, match="matching score service unavailable"):
        await reconciliation_router.run_reconciliation(
            ReconciliationRunRequest(statement_id=statement_id, limit=25), ctx=RequestContext(db, test_user.id)
        )
    failed = next(call.kwargs for call in mock_exception.call_args_list if call.args[0] == "reconciliation.run.failed")
    assert failed["audit_event"] == "reconciliation.run.failed"
    assert failed["statement_id"] == str(statement_id)
    assert failed["phase"] == "matching_failed"
    assert failed["error_type"] == "RuntimeError"


async def test_load_entry_summaries_edge_cases(db, test_user: User) -> None:
    assert await _load_entry_summaries(db, [], test_user.id) == {}
    bad_match = ReconciliationMatch(
        atomic_txn_id=uuid4(),
        journal_entry_ids=["not-a-uuid", "also-invalid"],
        match_score=80,
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    assert await _load_entry_summaries(db, [bad_match], test_user.id) == {}


async def test_accept_reject_tolerance_and_batch_guards(db, test_user: User) -> None:
    _, _, rejected_match = await _seed_router_match(db, test_user, status=ReconciliationStatus.REJECTED, score=60)
    assert (await reject_match_service(db, str(rejected_match.id), user_id=test_user.id)).status == ReconciliationStatus.REJECTED
    account, statement, txn_tol, expense = await _seed_expense_setup(db, test_user)
    entry_tol = await create_anchored_match_entry(
        db,
        user_id=test_user.id,
        bank_account=account,
        counter_account=expense,
        entry_date=txn_tol.txn_date,
        memo="Tol",
        amount=Decimal("99.95"),
    )
    match_tol = create_test_match(db, txn_tol, journal_entry_ids=[str(entry_tol.id)], match_score=85)
    txn_bad = create_test_transaction(db, statement, amount=Decimal("100.00"))
    entry_bad = await create_anchored_match_entry(
        db,
        user_id=test_user.id,
        bank_account=account,
        counter_account=expense,
        entry_date=txn_bad.txn_date,
        memo="Bad",
        amount=Decimal("50.00"),
    )
    match_bad = create_test_match(db, txn_bad, journal_entry_ids=[str(entry_bad.id)], match_score=80)
    txn_low = create_test_transaction(db, statement, amount=Decimal("50.00"))
    match_low = create_test_match(db, txn_low, match_score=60)
    db.add_all([txn_bad, txn_low, match_tol, match_bad, match_low])
    await db.commit()
    assert (await accept_match_service(db, match_tol.id, user_id=test_user.id)).status == ReconciliationStatus.ACCEPTED
    with pytest.raises(AmountMismatchError, match="Amount mismatch"):
        await accept_match_service(db, match_bad.id, user_id=test_user.id)
    assert (
        await batch_decide_service(db, user_id=test_user.id, action="accept", match_ids=[match_low.id], min_score=75)
    ).approved_count == 0
    await db.refresh(match_low)
    assert match_low.status == ReconciliationStatus.PENDING_REVIEW


async def test_batch_accept_router_preserves_currency_unresolved_error(db, test_user: User, monkeypatch) -> None:
    error = CurrencyUnresolvedError("Currency must be resolved")

    async def fail_batch(*args, **kwargs):
        raise error

    monkeypatch.setattr(review_queue, "accept_pending_matches", fail_batch)
    with pytest.raises(CurrencyUnresolvedError) as exc_info:
        await reconciliation_router.batch_update_matches(
            ReconciliationMatchBatchRequest(action="accept", match_ids=[uuid4()]),
            ctx=RequestContext(db, test_user.id),
        )
    assert exc_info.value is error


async def test_reviewed_disposition_uses_statement_account_and_rejects_foreign_txn(db, test_user: User) -> None:
    bank, _, txn, expense = await _seed_expense_setup(db, test_user)
    entry = await submit_reviewed_disposition(
        db,
        transaction_id=txn.id,
        user_id=test_user.id,
        command=ReviewedDispositionCommand(
            intent=EconomicIntent.EXPENSE,
            counter_account_id=expense.id,
            category="GENERAL",
            rationale="Reviewed source transaction.",
        ),
        dependencies=compose_reviewed_disposition_dependencies(db),
        base_currency="SGD",
    )
    assert entry is not None
    assert bank.id in [line.account_id for line in entry.lines]
    other_user = await UserFactory.create_async(db)
    _, (other_txn,) = await _seed_router_txns(db, other_user, count=1)
    with pytest.raises(ValueError, match="Transaction does not belong to user"):
        await create_entry_from_txn(db, other_txn, user_id=test_user.id, base_currency="SGD")
