"""Additional coverage for reconciliation router helpers."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    ConfidenceLevel,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
)
from src.routers import reconciliation as reconciliation_router
from src.schemas.reconciliation import (
    BatchAcceptRequest,
    ReconciliationRunRequest,
    ReconciliationStatusEnum,
)


async def _create_statement(db: AsyncSession, user_id) -> BankStatement:
    today = date.today()
    statement = BankStatement(
        user_id=user_id,
        account_id=None,
        file_path="statements/test.pdf",
        file_hash=str(uuid4()),
        original_filename="test.pdf",
        institution="Test Bank",
        account_last4="1234",
        currency="SGD",
        period_start=today,
        period_end=today,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
    )
    db.add(statement)
    await db.flush()
    return statement


async def _create_transaction(
    db: AsyncSession,
    statement_id,
    *,
    amount: Decimal,
    status: BankStatementTransactionStatus,
) -> BankStatementTransaction:
    txn = BankStatementTransaction(
        statement_id=statement_id,
        txn_date=date.today(),
        description="Test txn",
        amount=amount,
        direction="OUT",
        status=status,
        confidence=ConfidenceLevel.HIGH,
    )
    db.add(txn)
    await db.flush()
    return txn


@pytest.mark.asyncio
async def test_build_match_response_includes_entries(db: AsyncSession, test_user) -> None:
    asset = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    income = Account(
        user_id=test_user.id, name="Income", type=AccountType.INCOME, currency="SGD"
    )
    db.add_all([asset, income])
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Test entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=asset.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("100.00"), status=BankStatementTransactionStatus.PENDING
    )
    match = ReconciliationMatch(
        bank_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=85,
        score_breakdown={"amount": 90.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)

    response = await reconciliation_router._build_match_response(db, match, test_user.id)

    assert response.transaction is not None
    assert len(response.entries) == 1
    assert response.entries[0].total_amount == Decimal("100.00")


@pytest.mark.asyncio
async def test_run_reconciliation_statement_not_found(db: AsyncSession, test_user) -> None:
    payload = ReconciliationRunRequest(statement_id=uuid4())
    with pytest.raises(HTTPException, match="Statement not found"):
        await reconciliation_router.run_reconciliation(payload, db, test_user.id)


@pytest.mark.asyncio
async def test_run_reconciliation_filters_unmatched(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    statement = await _create_statement(db, test_user.id)
    await _create_transaction(
        db, statement.id, amount=Decimal("5.00"), status=BankStatementTransactionStatus.UNMATCHED
    )
    await db.commit()

    async def fake_execute_matching(*_args, **_kwargs):
        return [
            ReconciliationMatch(
                bank_txn_id=uuid4(),
                journal_entry_ids=[],
                match_score=90,
                score_breakdown={},
                status=ReconciliationStatus.AUTO_ACCEPTED,
            ),
            ReconciliationMatch(
                bank_txn_id=uuid4(),
                journal_entry_ids=[],
                match_score=70,
                score_breakdown={},
                status=ReconciliationStatus.PENDING_REVIEW,
            ),
        ]

    monkeypatch.setattr(reconciliation_router, "execute_matching", fake_execute_matching)

    response = await reconciliation_router.run_reconciliation(
        ReconciliationRunRequest(statement_id=statement.id), db, test_user.id
    )

    assert response.matches_created == 2
    assert response.auto_accepted == 1
    assert response.pending_review == 1
    assert response.unmatched == 1


@pytest.mark.asyncio
async def test_list_matches_filters_by_status(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn_pending = await _create_transaction(
        db, statement.id, amount=Decimal("8.00"), status=BankStatementTransactionStatus.PENDING
    )
    txn_accept = await _create_transaction(
        db, statement.id, amount=Decimal("9.00"), status=BankStatementTransactionStatus.PENDING
    )
    db.add_all(
        [
            ReconciliationMatch(
                bank_txn_id=txn_pending.id,
                journal_entry_ids=[],
                match_score=70,
                score_breakdown={},
                status=ReconciliationStatus.PENDING_REVIEW,
            ),
            ReconciliationMatch(
                bank_txn_id=txn_accept.id,
                journal_entry_ids=[],
                match_score=90,
                score_breakdown={},
                status=ReconciliationStatus.ACCEPTED,
            ),
        ]
    )
    await db.commit()

    response = await reconciliation_router.list_matches(
        status=ReconciliationStatusEnum.PENDING_REVIEW,
        limit=50,
        offset=0,
        db=db,
        user_id=test_user.id,
    )

    assert response.total == 1
    assert response.items[0].status == ReconciliationStatusEnum.PENDING_REVIEW


@pytest.mark.asyncio
async def test_reconciliation_stats_bucket_distribution(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn_scores = [
        (Decimal("10.00"), BankStatementTransactionStatus.MATCHED, 55),
        (Decimal("11.00"), BankStatementTransactionStatus.MATCHED, 70),
        (Decimal("12.00"), BankStatementTransactionStatus.UNMATCHED, 85),
        (Decimal("13.00"), BankStatementTransactionStatus.UNMATCHED, 95),
    ]
    matches = []
    for amount, status, score in txn_scores:
        txn = await _create_transaction(db, statement.id, amount=amount, status=status)
        matches.append(
            ReconciliationMatch(
                bank_txn_id=txn.id,
                journal_entry_ids=[],
                match_score=score,
                score_breakdown={},
                status=(
                    ReconciliationStatus.PENDING_REVIEW
                    if score < 90
                    else ReconciliationStatus.AUTO_ACCEPTED
                ),
            )
        )
    db.add_all(matches)
    await db.commit()

    stats = await reconciliation_router.reconciliation_stats(db=db, user_id=test_user.id)

    assert stats.total_transactions == 4
    assert stats.matched_transactions == 2
    assert stats.match_rate == 50.0
    assert stats.score_distribution["0-59"] == 1
    assert stats.score_distribution["60-79"] == 1
    assert stats.score_distribution["80-89"] == 1
    assert stats.score_distribution["90-100"] == 1


@pytest.mark.asyncio
async def test_pending_review_queue_returns_items(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("6.00"), status=BankStatementTransactionStatus.PENDING
    )
    db.add(
        ReconciliationMatch(
            bank_txn_id=txn.id,
            journal_entry_ids=[],
            match_score=80,
            score_breakdown={},
            status=ReconciliationStatus.PENDING_REVIEW,
        )
    )
    await db.commit()

    response = await reconciliation_router.pending_review_queue(
        limit=50, offset=0, db=db, user_id=test_user.id
    )

    assert response.total == 1
    assert response.items[0].status == ReconciliationStatusEnum.PENDING_REVIEW


@pytest.mark.asyncio
async def test_accept_reject_batch_accept(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn_accept = await _create_transaction(
        db, statement.id, amount=Decimal("7.00"), status=BankStatementTransactionStatus.PENDING
    )
    txn_reject = await _create_transaction(
        db, statement.id, amount=Decimal("8.00"), status=BankStatementTransactionStatus.PENDING
    )
    txn_batch = await _create_transaction(
        db, statement.id, amount=Decimal("9.00"), status=BankStatementTransactionStatus.PENDING
    )
    match_accept = ReconciliationMatch(
        bank_txn_id=txn_accept.id,
        journal_entry_ids=[],
        match_score=85,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_reject = ReconciliationMatch(
        bank_txn_id=txn_reject.id,
        journal_entry_ids=[],
        match_score=75,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    match_batch = ReconciliationMatch(
        bank_txn_id=txn_batch.id,
        journal_entry_ids=[],
        match_score=90,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add_all([match_accept, match_reject, match_batch])
    await db.commit()

    accepted = await reconciliation_router.accept_match(str(match_accept.id), db, test_user.id)
    rejected = await reconciliation_router.reject_match(str(match_reject.id), db, test_user.id)
    batch = await reconciliation_router.batch_accept(
        payload=BatchAcceptRequest(match_ids=[str(match_batch.id)]),
        db=db,
        user_id=test_user.id,
    )

    assert accepted.status == ReconciliationStatusEnum.ACCEPTED
    assert rejected.status == ReconciliationStatusEnum.REJECTED
    assert batch.total == 1


@pytest.mark.asyncio
async def test_list_unmatched_and_create_entry(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("4.00"), status=BankStatementTransactionStatus.UNMATCHED
    )
    await db.commit()

    unmatched = await reconciliation_router.list_unmatched(
        limit=50, offset=0, db=db, user_id=test_user.id
    )
    assert unmatched.total == 1

    entry = await reconciliation_router.create_entry(str(txn.id), db, test_user.id)
    assert entry.total_amount == Decimal("4.00")


@pytest.mark.asyncio
async def test_list_anomalies_returns_list(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn = await _create_transaction(
        db, statement.id, amount=Decimal("10.00"), status=BankStatementTransactionStatus.PENDING
    )
    await db.commit()

    anomalies = await reconciliation_router.list_anomalies(str(txn.id), db, test_user.id)
    assert isinstance(anomalies, list)
