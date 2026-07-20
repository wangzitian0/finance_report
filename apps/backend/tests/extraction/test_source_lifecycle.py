"""Acceptance proofs for #1970's extraction-owned source lifecycle."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import get_type_hints
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction import DocumentStatus, DocumentType, UploadedDocument
from src.extraction.base.result import (
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceProvenance,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
)
from src.extraction.extension.deduplication import dual_write_layer2
from src.extraction.extension.reviewed_statement_envelope import persist_statement_extraction_result
from src.extraction.extension.source_lifecycle import (
    RetireStatementCommand,
    SourceIdentityCommand,
    resolve_source_identity,
    retire_statement,
)
from src.extraction.extension.statement_validation import (
    _raise_if_balance_chain_invalid,
    validate_balance_chain,
)
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.extraction.orm.reviewed_statement_envelope import (
    ReviewedStatementEnvelope,
    StatementExtractionResultRecord,
)
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from src.routers import statements as statements_router
from src.routers.reconciliation import run_reconciliation
from src.routers.review import get_review_conflicts, run_stage2_checks
from src.schemas.reconciliation import ReconciliationRunRequest


def _summary(
    user_id: UUID,
    *,
    file_hash: str,
    uploaded_document_id: UUID | None = None,
) -> StatementSummary:
    return StatementSummary(
        user_id=user_id,
        uploaded_document_id=uploaded_document_id,
        file_hash=file_hash,
        institution="Example Bank",
        currency="SGD",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.PARSED,
        stage1_status=Stage1Status.PENDING_REVIEW,
    )


def _document(user_id: UUID, *, file_hash: str) -> UploadedDocument:
    return UploadedDocument(
        user_id=user_id,
        file_path=f"statements/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="statement.pdf",
        document_type=DocumentType.BANK_STATEMENT,
        status=DocumentStatus.COMPLETED,
    )


def _atomic(
    user_id: UUID,
    document_id: UUID,
    *,
    currency: str,
    direction: TransactionDirection,
    amount: str,
) -> AtomicTransaction:
    return AtomicTransaction(
        user_id=user_id,
        txn_date=date(2026, 6, 15),
        description=f"{currency} movement {uuid4().hex}",
        amount=Decimal(amount),
        direction=direction,
        currency=currency,
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(document_id), "doc_type": "bank_statement"}],
    )


@pytest.mark.asyncio
async def test_AC_extraction_source_lifecycle_1_approval_is_per_currency(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-extraction.source-lifecycle.1: cross-currency cancellation cannot approve."""
    document = _document(test_user.id, file_hash="per-currency-approval")
    db.add(document)
    await db.flush()
    statement = _summary(
        test_user.id,
        file_hash=document.file_hash,
        uploaded_document_id=document.id,
    )
    statement.currency_balances = [
        {"currency": "SGD", "opening": "0.00", "closing": "0.00"},
        {"currency": "USD", "opening": "0.00", "closing": "0.00"},
    ]
    db.add(statement)
    db.add_all(
        [
            _atomic(
                test_user.id,
                document.id,
                currency="SGD",
                direction=TransactionDirection.IN,
                amount="10.00",
            ),
            _atomic(
                test_user.id,
                document.id,
                currency="USD",
                direction=TransactionDirection.OUT,
                amount="10.00",
            ),
        ]
    )
    await db.flush()

    result = await validate_balance_chain(db, statement.id)

    assert result["balance_valid"] is False
    assert {row["currency"] for row in result["per_currency"]} == {"SGD", "USD"}
    assert all(row["closing_match"] is False for row in result["per_currency"])
    with pytest.raises(ValueError, match="currency"):
        _raise_if_balance_chain_invalid(result)


def _identity(user_id: UUID, *, file_hash: str) -> SourceIdentityCommand:
    return SourceIdentityCommand(
        user_id=user_id,
        file_path=f"statements/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="statement.pdf",
        document_type=DocumentType.BANK_STATEMENT,
        extraction_metadata={"producer": "acceptance"},
    )


def _source_result(source_digest: str) -> StatementExtractionResult:
    return StatementExtractionResult.create(
        producer_version="acceptance@1",
        source_content_digest=source_digest,
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        institution="Example Bank",
        account_last4="1234",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        balances=(),
        transactions=(
            ExtractedTransactionFact(
                fact_id="row-1",
                transaction_date=date(2026, 6, 15),
                description="typed source fact",
                amount=Decimal("1.00"),
                direction="IN",
                currency="SGD",
                balance_after=None,
                confidence=Decimal("0.90"),
            ),
        ),
        positions=(),
        confidence=Decimal("0.90"),
        balance_validated=None,
        warnings=(),
        review_reasons=("source facts require confirmation",),
        provenance=SourceProvenance(
            intake_mode="csv",
            method=ExtractionMethod.DETERMINISTIC,
            provider="acceptance",
            model="acceptance@1",
        ),
        statement_currency=None,
    )


@pytest.mark.asyncio
async def test_AC_extraction_source_lifecycle_2_two_sessions_share_source_identity(
    db: AsyncSession,
    db_engine,
    test_user,
) -> None:
    """AC-extraction.source-lifecycle.2: workers select one source and result."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    command = _identity(test_user.id, file_hash="concurrent-source-identity")
    start = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def worker() -> tuple[UUID, bool]:
        nonlocal ready
        async with maker() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            document, created = await resolve_source_identity(session, command)
            await session.commit()
            return document.id, created

    first, second = await asyncio.wait_for(asyncio.gather(worker(), worker()), timeout=10)
    assert first[0] == second[0]
    assert sorted((first[1], second[1])) == [False, True]

    async with maker() as verification:
        count = await verification.scalar(
            select(func.count())
            .select_from(UploadedDocument)
            .where(
                UploadedDocument.user_id == test_user.id,
                UploadedDocument.file_hash == command.file_hash,
            )
        )
        assert count == 1

    statement = _summary(test_user.id, file_hash="concurrent-result-identity")
    db.add(statement)
    await db.commit()
    result = _source_result("4" * 64)
    result_start = asyncio.Event()
    result_ready = 0
    result_ready_lock = asyncio.Lock()

    async def result_worker() -> UUID:
        nonlocal result_ready
        async with maker() as session:
            owned_statement = await session.get(StatementSummary, statement.id)
            assert owned_statement is not None
            async with result_ready_lock:
                result_ready += 1
                if result_ready == 2:
                    result_start.set()
            await result_start.wait()
            record = await persist_statement_extraction_result(
                session,
                statement=owned_statement,
                result=result,
                source_trace_record_id=uuid4(),
            )
            await session.commit()
            return record.id

    result_ids = await asyncio.wait_for(asyncio.gather(result_worker(), result_worker()), timeout=10)
    assert result_ids[0] == result_ids[1]
    async with maker() as verification:
        result_count = await verification.scalar(
            select(func.count())
            .select_from(StatementExtractionResultRecord)
            .where(
                StatementExtractionResultRecord.statement_id == statement.id,
                StatementExtractionResultRecord.content_digest == result.content_digest,
            )
        )
        assert result_count == 1


@pytest.mark.asyncio
async def test_AC_extraction_source_lifecycle_3_conflict_preserves_outer_session(
    db_engine,
    test_user,
) -> None:
    """AC-extraction.source-lifecycle.3: duplicate recovery does not poison commit."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    command = _identity(test_user.id, file_hash="recoverable-source-conflict")
    async with maker() as winner_session:
        winner, created = await resolve_source_identity(winner_session, command)
        assert created is True
        await winner_session.commit()

    async with maker() as loser_session:
        observed, created = await resolve_source_identity(loser_session, command)
        assert created is False
        assert observed.id == winner.id
        summary = _summary(test_user.id, file_hash="outer-session-still-usable")
        loser_session.add(summary)
        await loser_session.commit()
        assert summary.id is not None


async def _history_fixture(db: AsyncSession, user_id: UUID) -> tuple[StatementSummary, UploadedDocument]:
    account = Account(
        user_id=user_id,
        name="Source history account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    document = _document(user_id, file_hash=f"history-{uuid4().hex}")
    db.add_all([account, document])
    await db.flush()
    statement = _summary(user_id, file_hash=document.file_hash, uploaded_document_id=document.id)
    db.add(statement)
    await db.flush()
    source_result = StatementExtractionResultRecord(
        user_id=user_id,
        statement_id=statement.id,
        content_digest="1" * 64,
        source_content_digest="2" * 64,
        schema_version="2",
        producer_version="acceptance",
        payload={"kind": "source-result"},
        source_trace_record_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    db.add(source_result)
    await db.flush()
    statement.current_extraction_result_id = source_result.id
    db.add(
        ReviewedStatementEnvelope(
            user_id=user_id,
            statement_id=statement.id,
            source_result_id=source_result.id,
            account_id=account.id,
            currency="SGD",
            period_start=statement.period_start,
            period_end=statement.period_end,
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("0.00"),
            rationale="Confirmed from source",
            command_digest="3" * 64,
            review_trace_record_id=uuid4(),
            supersedes_id=None,
            created_at=datetime.now(UTC),
        )
    )
    db.add(
        _atomic(
            user_id,
            document.id,
            currency="SGD",
            direction=TransactionDirection.IN,
            amount="1.00",
        )
    )
    await db.flush()
    return statement, document


@pytest.mark.asyncio
async def test_AC_extraction_source_lifecycle_4_retire_preserves_history(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-extraction.source-lifecycle.4: removal preserves every source fact."""
    statement, document = await _history_fixture(db, test_user.id)
    before = {
        model: await db.scalar(select(func.count()).select_from(model))
        for model in (
            StatementExtractionResultRecord,
            ReviewedStatementEnvelope,
            AtomicTransaction,
            UploadedDocument,
        )
    }

    retired = await retire_statement(
        db,
        RetireStatementCommand(statement_id=statement.id, user_id=test_user.id),
    )
    repeated = await retire_statement(
        db,
        RetireStatementCommand(statement_id=statement.id, user_id=test_user.id),
    )
    await db.commit()

    assert retired.id == repeated.id == statement.id
    assert retired.status is BankStatementStatus.RETIRED
    await db.refresh(document)
    assert document.status is DocumentStatus.RETIRED
    after = {model: await db.scalar(select(func.count()).select_from(model)) for model in before}
    assert after == before


@pytest.mark.asyncio
async def test_AC_extraction_source_lifecycle_5_retire_does_not_delete_storage(
    db: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-extraction.source-lifecycle.5: storage outage cannot split retirement."""
    statement, _ = await _history_fixture(db, test_user.id)
    await db.commit()

    class UnavailableStorage:
        def __init__(self) -> None:
            raise RuntimeError("object storage unavailable")

    monkeypatch.setattr(statements_router, "StorageService", UnavailableStorage)
    await statements_router.delete_statement(statement.id, db, test_user.id)

    persisted = await db.get(StatementSummary, statement.id)
    assert persisted is not None
    assert persisted.status is BankStatementStatus.RETIRED


@pytest.mark.asyncio
async def test_AC_extraction_source_lifecycle_6_failure_and_retry_converge(
    db: AsyncSession,
    db_engine,
    test_user,
) -> None:
    """AC-extraction.source-lifecycle.6: rollback and retry keep one state."""
    statement, _ = await _history_fixture(db, test_user.id)
    await db.commit()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as failed:
        await retire_statement(
            failed,
            RetireStatementCommand(statement_id=statement.id, user_id=test_user.id),
        )
        await failed.flush()
        await failed.rollback()

    async with maker() as verification:
        current = await verification.get(StatementSummary, statement.id)
        assert current is not None
        assert current.status is BankStatementStatus.PARSED

    async with maker() as retry:
        await retire_statement(
            retry,
            RetireStatementCommand(statement_id=statement.id, user_id=test_user.id),
        )
        await retry.commit()

    async with maker() as repeated:
        await retire_statement(
            repeated,
            RetireStatementCommand(statement_id=statement.id, user_id=test_user.id),
        )
        await repeated.commit()
        count = await repeated.scalar(
            select(func.count()).select_from(StatementSummary).where(StatementSummary.id == statement.id)
        )
        assert count == 1


def test_AC_extraction_source_lifecycle_7_boundary_is_typed() -> None:
    """AC-extraction.source-lifecycle.7: lifecycle inputs are typed values."""
    identity_hints = get_type_hints(SourceIdentityCommand)
    retire_hints = get_type_hints(RetireStatementCommand)
    assert identity_hints["user_id"] is UUID
    assert identity_hints["document_type"] is DocumentType
    assert retire_hints["statement_id"] is UUID
    assert retire_hints["user_id"] is UUID
    signature = inspect.signature(dual_write_layer2)
    assert "ExtractedTransactionRow" in str(signature.parameters["transactions"].annotation)
    assert "dict" not in str(signature.parameters["transactions"].annotation)


def test_AC_extraction_source_lifecycle_8_ordinary_api_has_no_purge_path() -> None:
    """AC-extraction.source-lifecycle.8: DELETE is retirement, never purge."""
    source = inspect.getsource(statements_router.delete_statement)
    assert "retire_statement(" in source
    assert "delete_object" not in source
    assert "db.delete" not in source
    assert "purge" not in source.casefold()


@pytest.mark.asyncio
async def test_AC_extraction_source_lifecycle_10_counterfactual_matrix_is_locked(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-extraction.source-lifecycle.10: undeclared currency and retired reads fail closed."""
    document = _document(test_user.id, file_hash="orphan-currency-counterfactual")
    db.add(document)
    await db.flush()
    statement = _summary(test_user.id, file_hash=document.file_hash, uploaded_document_id=document.id)
    statement.currency_balances = [{"currency": "SGD", "opening": "0.00", "closing": "0.00"}]
    db.add(statement)
    db.add(
        _atomic(
            test_user.id,
            document.id,
            currency="USD",
            direction=TransactionDirection.IN,
            amount="1.00",
        )
    )
    await db.flush()
    validation = await validate_balance_chain(db, statement.id)
    orphan = next(row for row in validation["per_currency"] if row["currency"] == "USD")
    assert orphan["declared_balance"] is False
    with pytest.raises(ValueError, match="currency"):
        _raise_if_balance_chain_invalid(validation)

    await retire_statement(db, RetireStatementCommand(statement_id=statement.id, user_id=test_user.id))
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await statements_router.get_statement(statement.id, db, test_user.id)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await get_review_conflicts(statement.id, db, test_user.id)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await run_stage2_checks(statement.id, db, test_user.id)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await run_reconciliation(
            ReconciliationRunRequest(statement_id=statement.id),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 404
