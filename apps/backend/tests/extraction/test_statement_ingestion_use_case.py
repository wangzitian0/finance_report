"""AC-extraction.1913.4-.8: explicit statement-ingestion application boundary."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.audit.orm.trace_record import TraceRecordRow
from src.composition import compose_statement_posting_dependencies
from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import (
    DispositionContext,
    DispositionMode,
    DispositionPolicy,
    DocumentSource,
    EconomicIntent,
    IntentProposal,
    IntentProposalOrigin,
    ParseJob,
    StatementIngestionConfigurationError,
    StatementIngestionUseCase,
    StatementPostingDependencies,
    StatementSummary,
    StatementTransaction,
)
from src.extraction.extension import statement_flow, statement_pipeline
from src.extraction.extension.disposition_trace import emit_disposition_trace_records
from src.extraction.extension.extraction_trace import extraction_trace_policy_registry
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing import RetryableStatementIngestionError
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer2 import TransactionDirection
from src.extraction.orm.statement_enums import BankStatementStatus
from src.ledger import JournalEntry, JournalEntryStatus
from tests.factories import StatementSummaryFactory


async def _no_transfers(_db, _txn_ids):
    return set()


def test_statement_disposition_mode_is_resolved_once_at_composition(monkeypatch):
    """The rollout mode is typed configuration, not a posting-path flag."""
    monkeypatch.setattr(settings, "statement_disposition_mode", "observe")

    dependencies = compose_statement_posting_dependencies()

    assert dependencies.disposition_mode is DispositionMode.OBSERVE


async def _fx_rate(_db, _base, _quote, _date, *, lazy_load=False):
    raise AssertionError("base-currency test must not request FX")


async def _content_loader(_storage_key: str) -> bytes:
    return b"stored-content"


async def _brokerage_router(**_kwargs) -> None:
    return None


def _posting_dependencies() -> StatementPostingDependencies:
    return StatementPostingDependencies(
        transfer_exclusions=_no_transfers,
        fx_rate_provider=_fx_rate,
        fx_rate_error=RuntimeError,
        trace_emitter_factory=lambda db: TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())),
        disposition_mode=DispositionMode.ENFORCE,
    )


def _job(*, statement_id=None, user_id=None, file_hash="statement-ingestion-ac") -> ParseJob:
    return ParseJob(
        statement_id=statement_id or uuid4(),
        filename="statement.pdf",
        institution="DBS",
        user_id=user_id or uuid4(),
        account_id=None,
        file_hash=file_hash,
        storage_key="uploads/statement.pdf",
        model=None,
        request_id="req-1913",
    )


async def test_AC_extraction_1913_4_api_and_prefect_use_same_composed_use_case(monkeypatch):
    """AC-extraction.1913.4: both transports execute one composed use case."""
    calls: list[tuple[ParseJob, bytes | None]] = []

    class FakeUseCase:
        async def execute(self, job: ParseJob, *, content: bytes | None = None):
            calls.append((job, content))

    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", None)
    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", lambda **_kwargs: FakeUseCase())
    monkeypatch.setattr(statement_flow, "compose_statement_ingestion_use_case", lambda **_kwargs: FakeUseCase())
    monkeypatch.setattr(statement_pipeline, "create_session_maker_from_db", lambda _db: object())
    monkeypatch.setattr(statement_pipeline, "run_with_async_parse_tracking", lambda awaitable, **_context: awaitable)
    monkeypatch.setattr(statement_flow, "run_with_async_parse_tracking", lambda awaitable, **_context: awaitable)

    job = _job()
    task = await statement_pipeline.submit_parse_pipeline(job=job, content=b"api-content", db=object())
    assert isinstance(task, asyncio.Task)
    await task
    await statement_flow.parse_statement_flow.fn(job=job.to_prefect_params())

    assert calls == [(job, b"api-content"), (job, None)]


def test_AC_extraction_1913_5_incomplete_composition_fails_before_job():
    """AC-extraction.1913.5: required ports are constructor requirements."""
    with pytest.raises(StatementIngestionConfigurationError, match="content_loader"):
        StatementIngestionUseCase(
            session_maker=object(),
            content_loader=None,
            extraction_service_factory=ExtractionService,
            posting_dependencies=_posting_dependencies(),
            brokerage_router=_brokerage_router,
            trace_emitter_factory=lambda _db: None,
            clock=lambda: 0.0,
        )


async def test_AC_extraction_1913_6_application_error_does_not_reject_source(db, test_user):
    """AC-extraction.1913.6: application failures remain retryable source-neutral errors."""
    statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash="statement-ingestion-retryable",
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    service = ExtractionService()
    service.parse_document = AsyncMock(side_effect=RuntimeError("composition unavailable"))
    use_case = StatementIngestionUseCase(
        session_maker=create_session_maker_from_db(db),
        content_loader=_content_loader,
        extraction_service_factory=lambda: service,
        posting_dependencies=_posting_dependencies(),
        brokerage_router=_brokerage_router,
        trace_emitter_factory=lambda _db: None,
        clock=lambda: 0.0,
    )

    with pytest.raises(RetryableStatementIngestionError, match="composition unavailable"):
        await use_case.execute(_job(statement_id=statement.id, user_id=test_user.id), content=b"content")

    await db.refresh(statement)
    assert statement.status == BankStatementStatus.PARSING
    assert statement.validation_error is None


def test_AC_extraction_1913_7_fresh_worker_composes_without_main():
    """AC-extraction.1913.7: a worker composes without API startup side effects."""
    backend_root = Path(__file__).resolve().parents[2]
    script = """
import sys
from src.composition import compose_statement_ingestion_use_case
case = compose_statement_ingestion_use_case()
assert case.posting_dependencies.transfer_exclusions is not None
assert case.posting_dependencies.fx_rate_provider is not None
assert 'src.main' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_AC_extraction_1913_8_retry_does_not_duplicate_financial_effects(db, test_user, monkeypatch):
    """AC-extraction.1913.8: finalizing twice cannot duplicate financial effects."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "DBS",
            "account_last4": "1913",
            "currency": "SGD",
            "period_start": "2026-06-01",
            "period_end": "2026-06-30",
            "opening_balance": "100.00",
            "closing_balance": "110.00",
            "transactions": [
                {
                    "date": "2026-06-15",
                    "description": "Interest",
                    "amount": "10.00",
                    "direction": "IN",
                    "currency": "SGD",
                    "balance_after": "110.00",
                }
            ],
        }
    )
    content = b"%PDF-1.7"
    await service.parse_document(
        DocumentSource.resolve(
            path=Path("retry-idempotent.pdf"),
            content=content,
            content_hash=hashlib.sha256(content).hexdigest(),
            filename="retry-idempotent.pdf",
        ),
        institution="DBS",
        user_id=test_user.id,
        db=db,
    )
    await db.flush()
    statement = (
        await db.execute(select(StatementSummary).where(StatementSummary.user_id == test_user.id))
    ).scalar_one()

    async def propose_income(transactions, _policy):
        return [
            CategoryProposal(
                category=TransactionCategory.INTEREST.value,
                confidence=95,
                reason="deterministic idempotency fixture",
            )
            for _transaction in transactions
        ]

    monkeypatch.setattr("src.config.settings.enable_ai_classification", True)
    monkeypatch.setattr(
        "src.extraction.extension.transaction_classification.propose_categories",
        propose_income,
    )
    dependencies = _posting_dependencies()
    first = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id, dependencies=dependencies)
    second = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id, dependencies=dependencies)

    entries = list(
        (
            await db.execute(
                select(JournalEntry).where(
                    JournalEntry.user_id == test_user.id,
                    JournalEntry.status == JournalEntryStatus.POSTED,
                    JournalEntry.source_id.is_not(None),
                )
            )
        ).scalars()
    )
    assert first == 1
    assert second == 0
    assert len(entries) == 1


async def test_AC_extraction_ingestion_trace_1_is_atomic_with_statement_facts(db, test_user):
    """AC-extraction.ingestion-trace.1: trace failure rolls back statement facts and effects."""
    content = b"atomic-trace-statement"
    file_hash = hashlib.sha256(content).hexdigest()
    statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash=file_hash,
        institution="DBS",
    )
    db.add(statement)
    await db.commit()

    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "DBS",
            "account_last4": "1914",
            "currency": "SGD",
            "period_start": "2026-07-01",
            "period_end": "2026-07-31",
            "opening_balance": "100.00",
            "closing_balance": "110.00",
            "transactions": [
                {
                    "date": "2026-07-15",
                    "description": "Interest",
                    "amount": "10.00",
                    "direction": "IN",
                    "currency": "SGD",
                    "balance_after": "110.00",
                }
            ],
        }
    )

    use_case = StatementIngestionUseCase(
        session_maker=create_session_maker_from_db(db),
        content_loader=_content_loader,
        extraction_service_factory=lambda: service,
        posting_dependencies=_posting_dependencies(),
        brokerage_router=_brokerage_router,
        trace_emitter_factory=lambda session: TraceEmitter(
            SqlTraceRecordRepository(session, extraction_trace_policy_registry())
        ),
        clock=lambda: 0.0,
    )
    tenant_trace_rows = select(TraceRecordRow).where(TraceRecordRow.scope_id == str(test_user.id))
    before = len((await db.execute(tenant_trace_rows)).scalars().all())

    outcome = await use_case.execute(
        _job(statement_id=statement.id, user_id=test_user.id, file_hash=file_hash),
        content=content,
    )
    assert outcome.status.value == "completed"
    assert len((await db.execute(tenant_trace_rows)).scalars().all()) == before + 8
    await db.refresh(statement)
    assert statement.status is BankStatementStatus.PARSED
    assert statement.validation_error == "Economic review required: intent_missing"

    second_statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash=hashlib.sha256(b"trace-failure").hexdigest(),
        institution="DBS",
    )
    db.add(second_statement)
    await db.commit()

    class FailingEmitter:
        async def emit_many(self, _records):
            raise RuntimeError("trace repository unavailable")

    failing = StatementIngestionUseCase(
        session_maker=create_session_maker_from_db(db),
        content_loader=_content_loader,
        extraction_service_factory=lambda: service,
        posting_dependencies=_posting_dependencies(),
        brokerage_router=_brokerage_router,
        trace_emitter_factory=lambda _session: FailingEmitter(),
        clock=lambda: 0.0,
    )
    with pytest.raises(RetryableStatementIngestionError, match="trace repository unavailable"):
        await failing.execute(
            _job(
                statement_id=second_statement.id,
                user_id=test_user.id,
                file_hash=second_statement.file_hash,
            ),
            content=b"trace-failure",
        )
    await db.refresh(second_statement)
    assert second_statement.status is BankStatementStatus.PARSING
    assert len((await db.execute(tenant_trace_rows)).scalars().all()) == before + 8


async def test_AC_extraction_ingestion_trace_2_retries_are_idempotent_and_changes_supersede(db, test_user):
    """AC-extraction.ingestion-trace.2: retries deduplicate and corrections supersede."""
    transaction = StatementTransaction(
        transaction_id=uuid4(),
        transaction_date=date(2026, 7, 1),
        amount=Decimal("10.00"),
        currency="SGD",
        direction=TransactionDirection.IN,
        description="Recorded credit",
    )
    counter_account_id = uuid4()
    policy = DispositionPolicy()
    emitter = TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry()))

    def proposal(category: str) -> IntentProposal:
        return IntentProposal(
            schema_version="1",
            policy_version="intent-v1",
            origin=IntentProposalOrigin.REVIEWED_RULE,
            intent=EconomicIntent.INCOME,
            category=category,
            confidence=Decimal("0.95"),
            evidence=("recorded-description",),
        )

    async def emit(category: str):
        intent = proposal(category)
        decision = policy.decide(
            transaction,
            proposal=intent,
            context=DispositionContext(counter_account_id=counter_account_id),
        )
        return await emit_disposition_trace_records(
            emitter=emitter,
            user_id=test_user.id,
            execution_id=f"statement:stable:txn:{transaction.transaction_id}",
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
            transaction=transaction,
            proposal=intent,
            decision=decision,
        )

    first = await emit("SALARY")
    retry = await emit("SALARY")
    corrected = await emit("DIVIDEND")

    rows = list((await db.execute(select(TraceRecordRow))).scalars())
    assert retry == first
    assert len(rows) == 7
    assert corrected[2].supersedes_id == first[2].record_id
    assert corrected[3].supersedes_id == first[3].record_id
