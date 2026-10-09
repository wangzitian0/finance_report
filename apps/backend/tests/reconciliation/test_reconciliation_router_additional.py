"""Additional coverage for reconciliation router helpers."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.composition import compose_reviewed_disposition_dependencies
from src.deps import PaginationParams
from src.extraction import CurrencyUnresolvedError, DocumentType, EconomicIntent, TransactionDirection, UploadedDocument
from src.extraction.extension.review_queue import create_entry_from_txn
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    ValidationError,
    post_journal_entry,
    submit_manual_journal_entry,
    validate_manual_journal_entry_for_post,
)
from src.reconciliation import (
    AmountMismatchError,
    EntryCreationError,
    ReconciliationMatch,
    ReconciliationStatus,
    ReviewedDispositionCommand,
    submit_reviewed_disposition,
)
from src.reconciliation.extension.review_queue import (
    accept_match as accept_match_service,
    batch_accept as batch_accept_service,
    reject_match as reject_match_service,
)
from src.routers import reconciliation as reconciliation_router
from src.routers.reconciliation import _load_entry_summaries
from src.schemas.reconciliation import (
    BatchAcceptRequest,
    ReconciliationRunRequest,
    ReconciliationStatusEnum,
)
from tests.factories import UserFactory


async def _create_statement(db: AsyncSession, user_id, account_id=None) -> StatementSummary:
    """Create a StatementSummary conform linked to an ODS UploadedDocument."""
    today = date.today()
    file_hash = str(uuid4())
    doc = UploadedDocument(
        user_id=user_id,
        file_path="statements/test.pdf",
        file_hash=file_hash,
        original_filename="test.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()
    statement = StatementSummary(
        user_id=user_id,
        account_id=account_id,
        uploaded_document_id=doc.id,
        file_hash=file_hash,
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
    statement: StatementSummary,
    *,
    amount: Decimal,
    status=None,
) -> AtomicTransaction:
    txn = AtomicTransaction(
        user_id=statement.user_id,
        txn_date=date.today(),
        description="Test txn",
        amount=amount,
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(statement.uploaded_document_id), "doc_type": "bank_statement"}],
    )
    db.add(txn)
    await db.flush()
    return txn


async def _seed_statement_txn(
    db: AsyncSession,
    user_id,
    amount: Decimal = Decimal("100.00"),
    account_id=None,
) -> tuple[StatementSummary, AtomicTransaction]:
    statement = await _create_statement(db, user_id, account_id=account_id)
    txn = await _create_transaction(db, statement, amount=amount)
    await db.commit()
    return statement, txn


async def _create_match_entry(
    db: AsyncSession,
    *,
    user_id,
    bank_account: Account,
    counter_account: Account,
    amount: Decimal,
    memo: str | None = None,
) -> JournalEntry:
    """Create a decision-anchored manual entry for reconciliation acceptance."""
    entry = await submit_manual_journal_entry(
        db,
        user_id=user_id,
        entry_date=date.today(),
        memo=memo or f"Reviewed candidate {uuid4()}",
        rationale=f"Test operator attested reconciliation candidate {uuid4()}",
        lines_data=[
            {
                "account_id": counter_account.id,
                "direction": Direction.DEBIT,
                "amount": amount,
                "currency": "SGD",
            },
            {
                "account_id": bank_account.id,
                "direction": Direction.CREDIT,
                "amount": amount,
                "currency": "SGD",
            },
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


def _make_match(
    txn: AtomicTransaction,
    entry_ids: list[str] | None = None,
    *,
    score: int = 80,
    breakdown: dict | None = None,
    status: ReconciliationStatus = ReconciliationStatus.PENDING_REVIEW,
) -> ReconciliationMatch:
    return ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=entry_ids or [],
        match_score=score,
        score_breakdown=breakdown or {},
        status=status,
    )


async def _seed_match(
    db: AsyncSession,
    user_id,
    amount: Decimal = Decimal("100.00"),
    score: int = 80,
    status: ReconciliationStatus = ReconciliationStatus.PENDING_REVIEW,
    entry_ids: list[str] | None = None,
) -> tuple[StatementSummary, AtomicTransaction, ReconciliationMatch]:
    statement = await _create_statement(db, user_id)
    txn = await _create_transaction(db, statement, amount=amount)
    match = _make_match(txn, entry_ids, score=score, status=status)
    db.add(match)
    await db.commit()
    return statement, txn, match


async def _create_account_pair(
    db: AsyncSession, user_id, bank_name: str = "Bank", counter_name: str = "Expense"
) -> tuple[Account, Account]:
    bank = Account(user_id=user_id, name=f"{bank_name} {uuid4().hex[:6]}", type=AccountType.ASSET, currency="SGD")
    counter = Account(
        user_id=user_id, name=f"{counter_name} {uuid4().hex[:6]}", type=AccountType.EXPENSE, currency="SGD"
    )
    db.add_all([bank, counter])
    await db.flush()
    return bank, counter


async def _create_match_with_entry(
    db: AsyncSession,
    user_id,
    *,
    statement: StatementSummary | None = None,
    txn_amount: Decimal = Decimal("100.00"),
    entry_amount: Decimal = Decimal("100.00"),
    status: ReconciliationStatus = ReconciliationStatus.PENDING_REVIEW,
    score: int = 80,
    memo: str | None = None,
) -> tuple[AtomicTransaction, JournalEntry, ReconciliationMatch]:
    bank, counter = await _create_account_pair(db, user_id)
    if statement is None:
        statement = await _create_statement(db, user_id, account_id=bank.id)
    txn = await _create_transaction(db, statement, amount=txn_amount)
    entry = await _create_match_entry(
        db, user_id=user_id, bank_account=bank, counter_account=counter, amount=entry_amount, memo=memo
    )
    match = _make_match(txn, [str(entry.id)], score=score, status=status)
    db.add(match)
    await db.commit()
    return txn, entry, match


async def test_build_match_response_includes_entries(db: AsyncSession, test_user) -> None:
    txn, entry, match = await _create_match_with_entry(db, test_user.id, score=85, memo="Test entry")
    match.score_breakdown = {"amount": 90.0, "group_total": "100.00"}
    await db.commit()

    entry_summaries = await _load_entry_summaries(db, [match], test_user.id)
    response = reconciliation_router._build_match_response(
        match,
        transaction=txn,
        entry_summaries=entry_summaries,
    )

    assert response.transaction is not None
    assert len(response.entries) == 1
    assert response.entries[0].total_amount == Decimal("100.00")
    assert response.entries[0].entry_date == entry.entry_date
    assert response.entries[0].memo == "Test entry"
    assert response.entries[0].id == entry.id
    assert response.score_breakdown == {"amount": 90.0, "group_total": "100.00"}


async def test_run_reconciliation_statement_not_found(db: AsyncSession, test_user) -> None:
    payload = ReconciliationRunRequest(statement_id=uuid4())
    with pytest.raises(HTTPException, match="Statement not found"):
        await reconciliation_router.run_reconciliation(payload, db=db, user_id=test_user.id)


async def test_run_reconciliation_maps_processing_currency_conflict_to_400(
    db: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_matching(*_args, **_kwargs):
        raise ValidationError("Processing account currency is SGD; got transfer currency USD")

    monkeypatch.setattr(reconciliation_router, "execute_matching", fail_matching)

    with pytest.raises(HTTPException) as exc_info:
        await reconciliation_router.run_reconciliation(ReconciliationRunRequest(), db=db, user_id=test_user.id)

    assert exc_info.value.status_code == 400
    assert "Processing account currency is SGD" in exc_info.value.detail


async def test_run_reconciliation_filters_unmatched(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    statement, _ = await _seed_statement_txn(db, test_user.id, amount=Decimal("5.00"))

    async def fake_execute_matching(*_args, **_kwargs):
        return [
            ReconciliationMatch(
                atomic_txn_id=uuid4(),
                journal_entry_ids=[],
                match_score=90,
                score_breakdown={},
                status=ReconciliationStatus.AUTO_ACCEPTED,
            ),
            ReconciliationMatch(
                atomic_txn_id=uuid4(),
                journal_entry_ids=[],
                match_score=70,
                score_breakdown={},
                status=ReconciliationStatus.PENDING_REVIEW,
            ),
        ]

    monkeypatch.setattr(reconciliation_router, "execute_matching", fake_execute_matching)

    response = await reconciliation_router.run_reconciliation(
        ReconciliationRunRequest(statement_id=statement.id), db=db, user_id=test_user.id
    )

    assert response.matches_created == 2
    assert response.auto_accepted == 1
    assert response.pending_review == 1
    assert response.unmatched == 1


async def test_AC10_8_3_reconciliation_run_audit_checkpoints(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-observability.8.3: Reconciliation run logs start/completion/failure replay checkpoints."""
    statement, _ = await _seed_statement_txn(db, test_user.id, amount=Decimal("5.00"))
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
        ReconciliationRunRequest(statement_id=statement_id, limit=25), db=db, user_id=test_user.id
    )

    calls = [(call.args[0], call.kwargs) for call in mock_info.call_args_list]
    started = next(kwargs for event, kwargs in calls if event == "reconciliation.run.started")
    completed = next(kwargs for event, kwargs in calls if event == "reconciliation.run.completed")

    assert response.matches_created == 1
    assert started["audit_event"] == "reconciliation.run.started"
    assert started["request_id"]
    assert started["statement_id"] == str(statement_id)
    assert started["phase"] == "matching_started"
    assert started["progress"] is None
    assert started["model_to_use"] is None
    assert started["limit"] == 25
    assert completed["audit_event"] == "reconciliation.run.completed"
    assert completed["request_id"] == started["request_id"]
    assert completed["statement_id"] == str(statement_id)
    assert completed["phase"] == "matching_completed"
    assert completed["progress"] is None
    assert completed["model_to_use"] is None
    assert completed["matches_created"] == 1
    assert completed["auto_accepted"] == 1
    assert completed["pending_review"] == 0
    assert completed["unmatched"] == 1

    async def fail_execute_matching(*_args, **_kwargs):
        raise RuntimeError("matching score service unavailable with raw details omitted")

    monkeypatch.setattr(reconciliation_router, "execute_matching", fail_execute_matching)

    with pytest.raises(RuntimeError, match="matching score service unavailable"):
        await reconciliation_router.run_reconciliation(
            ReconciliationRunRequest(statement_id=statement_id, limit=25),
            db=db,
            user_id=test_user.id,
        )

    failed = next(call.kwargs for call in mock_exception.call_args_list if call.args[0] == "reconciliation.run.failed")
    assert failed["audit_event"] == "reconciliation.run.failed"
    assert failed["statement_id"] == str(statement_id)
    assert failed["phase"] == "matching_failed"
    assert failed["progress"] is None
    assert failed["model_to_use"] is None
    assert failed["limit"] == 25
    assert failed["error_type"] == "RuntimeError"
    assert failed["safe_error_message"] == "matching score service unavailable with raw details omitted"


async def test_list_matches_filters_by_status(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    txn_pending = await _create_transaction(db, statement, amount=Decimal("8.00"))
    txn_accept = await _create_transaction(db, statement, amount=Decimal("9.00"))
    db.add_all(
        [
            _make_match(txn_pending, score=70, status=ReconciliationStatus.PENDING_REVIEW),
            _make_match(txn_accept, score=90, status=ReconciliationStatus.ACCEPTED),
        ]
    )
    await db.commit()

    response = await reconciliation_router.list_matches(
        status_filter=ReconciliationStatusEnum.PENDING_REVIEW,
        limit=50,
        offset=0,
        db=db,
        user_id=test_user.id,
    )

    assert response.total == 1
    assert response.items[0].status == ReconciliationStatusEnum.PENDING_REVIEW


async def test_load_entry_summaries_empty(db: AsyncSession, test_user) -> None:
    """Test _load_entry_summaries with empty input."""
    result = await _load_entry_summaries(db, [], test_user.id)
    assert result == {}


async def test_load_entry_summaries_invalid_uuid(db: AsyncSession, test_user) -> None:
    """Test _load_entry_summaries with invalid UUID strings."""
    match = ReconciliationMatch(
        atomic_txn_id=uuid4(),
        journal_entry_ids=["not-a-uuid"],
        match_score=80,
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    result = await _load_entry_summaries(db, [match], test_user.id)
    assert result == {}


async def test_reconciliation_stats_bucket_distribution(db: AsyncSession, test_user) -> None:
    statement = await _create_statement(db, test_user.id)
    matches = [
        _make_match(
            await _create_transaction(db, statement, amount=Decimal(str(10 + i))),
            score=score,
            status=ReconciliationStatus.AUTO_ACCEPTED if score >= 80 else ReconciliationStatus.PENDING_REVIEW,
        )
        for i, score in enumerate([55, 70, 85, 95])
    ]
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


async def test_pending_review_queue_returns_items(db: AsyncSession, test_user) -> None:
    await _seed_match(db, test_user.id, amount=Decimal("6.00"), score=80)

    response = await reconciliation_router.pending_review_queue(limit=50, offset=0, db=db, user_id=test_user.id)

    assert response.total == 1
    assert response.items[0].status == ReconciliationStatusEnum.PENDING_REVIEW


async def test_accept_reject_batch_accept(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.review-queue.2: [AC4.3.3] Test batch accept functionality."""
    _, _, match_accept = await _create_match_with_entry(
        db, test_user.id, txn_amount=Decimal("7.00"), entry_amount=Decimal("7.00"), score=85
    )
    _, _, match_reject = await _create_match_with_entry(
        db, test_user.id, txn_amount=Decimal("8.00"), entry_amount=Decimal("8.00"), score=75
    )
    _, _, match_batch = await _create_match_with_entry(
        db, test_user.id, txn_amount=Decimal("9.00"), entry_amount=Decimal("9.00"), score=90
    )

    accepted = await reconciliation_router.accept_match(match_id=str(match_accept.id), db=db, user_id=test_user.id)
    rejected = await reconciliation_router.reject_match(match_id=str(match_reject.id), db=db, user_id=test_user.id)
    batch = await reconciliation_router.batch_accept(
        payload=BatchAcceptRequest(match_ids=[str(match_batch.id)]),
        db=db,
        user_id=test_user.id,
    )

    assert accepted.status == ReconciliationStatusEnum.ACCEPTED
    assert rejected.status == ReconciliationStatusEnum.REJECTED
    assert batch.total == 1


async def test_list_unmatched_has_no_raw_entry_creator(db: AsyncSession, test_user) -> None:
    await _seed_statement_txn(db, test_user.id, amount=Decimal("4.00"))

    unmatched = await reconciliation_router.list_unmatched(limit=50, offset=0, db=db, user_id=test_user.id)
    assert unmatched.total == 1

    assert not hasattr(reconciliation_router, "create_entry")


async def test_unmatched_exclusions_are_tenant_scoped(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.review-queue.12: another tenant cannot hide this user's source facts."""
    statement = await _create_statement(db, test_user.id)
    source_collision = await _create_transaction(db, statement, amount=Decimal("4.00"))
    visible_transaction = await _create_transaction(db, statement, amount=Decimal("5.00"))
    other_user = await UserFactory.create_async(db)
    _, other_transaction = await _seed_statement_txn(db, other_user.id, amount=Decimal("6.00"))
    db.add_all(
        [
            JournalEntry(
                user_id=other_user.id,
                entry_date=date.today(),
                memo="Foreign source-id collision",
                source_type=JournalEntrySourceType.AUTO_PARSED,
                source_id=source_collision.id,
                status=JournalEntryStatus.DRAFT,
            ),
            ReconciliationMatch(
                atomic_txn_id=other_transaction.id,
                journal_entry_ids=[],
                match_score=Decimal("80"),
                score_breakdown={},
                status=ReconciliationStatus.PENDING_REVIEW,
            ),
        ]
    )
    await db.commit()

    unmatched = await reconciliation_router.list_unmatched(limit=50, offset=0, db=db, user_id=test_user.id)

    assert unmatched.total == 2
    assert {item.id for item in unmatched.items} == {source_collision.id, visible_transaction.id}


async def test_list_anomalies_returns_list(db: AsyncSession, test_user) -> None:
    _, txn = await _seed_statement_txn(db, test_user.id, amount=Decimal("10.00"))

    anomalies = await reconciliation_router.list_anomalies(
        txn_id=str(txn.id), db=db, user_id=test_user.id, pagination=PaginationParams()
    )
    assert isinstance(anomalies, list)


async def test_accept_match_already_accepted_is_idempotent(db: AsyncSession, test_user) -> None:
    """Accepting an already-accepted match should return it unchanged (idempotent)."""
    _, _, match = await _seed_match(
        db, test_user.id, amount=Decimal("15.00"), score=90, status=ReconciliationStatus.ACCEPTED
    )

    result = await accept_match_service(db, match.id, user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED


async def test_reject_match_already_rejected_is_idempotent(db: AsyncSession, test_user) -> None:
    """Rejecting an already-rejected match should return it unchanged (idempotent)."""
    _, _, match = await _seed_match(
        db, test_user.id, amount=Decimal("16.00"), score=60, status=ReconciliationStatus.REJECTED
    )

    result = await reject_match_service(db, str(match.id), user_id=test_user.id)
    assert result.status == ReconciliationStatus.REJECTED


async def test_build_match_response_with_invalid_uuid_in_entry_ids(db: AsyncSession, test_user) -> None:
    """Invalid UUIDs in journal_entry_ids should be gracefully skipped."""
    _, _, match = await _seed_match(
        db, test_user.id, amount=Decimal("20.00"), score=75, entry_ids=["not-a-valid-uuid", "also-invalid"]
    )

    entry_summaries = await _load_entry_summaries(db, [match], test_user.id)
    assert entry_summaries == {}


async def test_accept_match_amount_mismatch_raises(db: AsyncSession, test_user) -> None:
    """Accept match should raise ValueError when entry amounts don't match transaction."""
    _, _, match = await _create_match_with_entry(
        db, test_user.id, txn_amount=Decimal("100.00"), entry_amount=Decimal("50.00")
    )
    with pytest.raises(AmountMismatchError, match="Amount mismatch"):
        await accept_match_service(db, match.id, user_id=test_user.id)


async def test_accept_match_amount_within_tolerance(db: AsyncSession, test_user) -> None:
    """Accept match should succeed when amounts match within tolerance."""
    _, _, match = await _create_match_with_entry(
        db, test_user.id, txn_amount=Decimal("100.00"), entry_amount=Decimal("99.95"), score=85
    )
    result = await accept_match_service(db, match.id, user_id=test_user.id)
    assert result.status == ReconciliationStatus.ACCEPTED


async def test_accept_match_amount_check_cannot_be_bypassed(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.review-hardening.2: mismatched amounts always raise (#1864)."""
    _, _, match = await _create_match_with_entry(
        db, test_user.id, txn_amount=Decimal("100.00"), entry_amount=Decimal("50.00")
    )
    with pytest.raises(AmountMismatchError, match="Amount mismatch"):
        await accept_match_service(db, match.id, user_id=test_user.id)


async def test_batch_accept_skips_low_score_matches(db: AsyncSession, test_user) -> None:
    """batch_accept should skip matches below min_score threshold."""
    _, _, match = await _seed_match(db, test_user.id, amount=Decimal("50.00"), score=60)

    accepted = await batch_accept_service(db, user_id=test_user.id, match_ids=[str(match.id)], min_score=75)
    assert len(accepted) == 0
    await db.refresh(match)
    assert match.status == ReconciliationStatus.PENDING_REVIEW


async def test_batch_accept_router_maps_entry_creation_error_to_400(db, test_user, monkeypatch) -> None:
    """AC-reconciliation.signature-surgery.4: batch and single accept share typed status mapping."""

    async def fail_batch(*args, **kwargs):
        raise EntryCreationError("Account mapping required before posting")

    monkeypatch.setattr(reconciliation_router, "batch_accept_service", fail_batch)

    with pytest.raises(HTTPException) as exc_info:
        await reconciliation_router.batch_accept(
            BatchAcceptRequest(match_ids=[str(uuid4())]),
            db=db,
            user_id=test_user.id,
        )

    assert exc_info.value.status_code == 400


async def test_batch_accept_router_preserves_currency_unresolved_error(db, test_user, monkeypatch) -> None:
    """AC12.40.4: the global handler remains the sole owner of the structured 409."""
    error = CurrencyUnresolvedError("Currency must be resolved")

    async def fail_batch(*args, **kwargs):
        raise error

    monkeypatch.setattr(reconciliation_router, "batch_accept_service", fail_batch)

    with pytest.raises(CurrencyUnresolvedError) as exc_info:
        await reconciliation_router.batch_accept(
            BatchAcceptRequest(match_ids=[str(uuid4())]),
            db=db,
            user_id=test_user.id,
        )

    assert exc_info.value is error


async def test_reviewed_disposition_uses_statement_account(db: AsyncSession, test_user) -> None:
    """A reviewed statement posting uses the source statement's linked account."""
    bank_account, expense_account = await _create_account_pair(db, test_user.id, "Linked Bank", "Reviewed Expense")
    statement = await _create_statement(db, test_user.id, account_id=bank_account.id)
    txn = await _create_transaction(db, statement, amount=Decimal("100.00"))

    entry = await submit_reviewed_disposition(
        db,
        transaction_id=txn.id,
        user_id=test_user.id,
        command=ReviewedDispositionCommand(
            intent=EconomicIntent.EXPENSE,
            counter_account_id=expense_account.id,
            category="GENERAL",
            rationale="Reviewed source transaction.",
        ),
        dependencies=compose_reviewed_disposition_dependencies(db),
    )

    assert entry is not None
    assert bank_account.id in [line.account_id for line in entry.lines]


async def test_create_entry_from_txn_rejects_other_user_transaction(db: AsyncSession, test_user) -> None:
    """create_entry_from_txn should reject transactions from other users."""
    other_user_id = (await UserFactory.create_async(db)).id
    _, txn = await _seed_statement_txn(db, other_user_id, amount=Decimal("50.00"))

    with pytest.raises(ValueError, match="Transaction does not belong to user"):
        await create_entry_from_txn(db, txn, user_id=test_user.id)
