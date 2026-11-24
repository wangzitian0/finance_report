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

from src import statement_flow
from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.audit.orm.trace_record import TraceRecordRow
from src.composition import compose_financial_trace_emitter, compose_statement_posting_dependencies
from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
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
    TransactionDirection,
)
from src.extraction.extension import statement_pipeline
from src.extraction.extension.disposition_trace import emit_disposition_trace_records
from src.extraction.extension.extraction_trace import extraction_trace_policy_registry
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing import RetryableStatementIngestionError
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.ledger import JournalEntry, JournalEntryStatus
from tests.factories import StatementSummaryFactory
from tests.statement_ingestion import classify_statement_rows, run_for

_async_val = lambda val: (lambda *_a, **_kw: asyncio.sleep(0, result=val))


async def _fx_rate(_db, _base, _quote, _date, *, lazy_load=False):
    raise AssertionError("base-currency test must not request FX")


def _posting_dependencies() -> StatementPostingDependencies:
    return StatementPostingDependencies(
        transfer_exclusions=_async_val(set()),
        fx_rate_provider=_fx_rate,
        fx_rate_error=RuntimeError,
        trace_emitter_factory=compose_financial_trace_emitter,
        disposition_mode=DispositionMode.ENFORCE,
        base_currency_resolver=_async_val("SGD"),
    )


def _job(*, statement_id=None, user_id=None, file_hash: str = "statement-ingestion-ac", run_id=None) -> ParseJob:
    return ParseJob(
        statement_id=statement_id or uuid4(),
        run_id=run_id or uuid4(),
        filename="statement.pdf",
        institution="DBS",
        user_id=user_id or uuid4(),
        account_id=None,
        file_hash=file_hash,
        storage_key="uploads/statement.pdf",
        model=None,
        request_id="req-1913",
    )


def _make_use_case(
    db, service, *, content_loader=_async_val(b"stored-content"), trace_emitter_factory=lambda _db: None
):
    return StatementIngestionUseCase(
        session_maker=create_session_maker_from_db(db),
        content_loader=content_loader,
        extraction_service_factory=lambda: service,
        posting_dependencies=_posting_dependencies(),
        brokerage_router=_async_val(None),
        trace_emitter_factory=trace_emitter_factory,
        clock=lambda: 0.0,
        sleep=_async_val(None),
    )


def _interest_service(last4: str, month: str) -> ExtractionService:
    svc = ExtractionService()
    svc.extract_financial_data = AsyncMock(
        return_value={
            "institution": "DBS",
            "account_last4": last4,
            "currency": "SGD",
            "period_start": f"{month}-01",
            "period_end": f"{month}-30",
            "opening_balance": "100.00",
            "closing_balance": "110.00",
            "transactions": [
                {
                    "date": f"{month}-15",
                    "description": "Interest",
                    "amount": "10.00",
                    "direction": "IN",
                    "currency": "SGD",
                    "balance_after": "110.00",
                }
            ],
        }
    )
    return svc


def _interest_pdf(tag: str) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    for idx, line in enumerate(
        (
            tag,
            "Opening Balance 100.00",
            "Interest 10.00",
            "Closing Balance 110.00",
        )
    ):
        page.insert_text((72, 72 + 16 * idx), line)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_statement_disposition_mode_and_composition_guards(monkeypatch):
    monkeypatch.setattr(settings, "statement_disposition_mode", "observe")
    assert compose_statement_posting_dependencies().disposition_mode is DispositionMode.OBSERVE
    with pytest.raises(StatementIngestionConfigurationError, match="content_loader"):
        StatementIngestionUseCase(
            session_maker=object(),
            content_loader=None,
            extraction_service_factory=ExtractionService,
            posting_dependencies=_posting_dependencies(),
            brokerage_router=_async_val(None),
            trace_emitter_factory=lambda _db: None,
            clock=lambda: 0.0,
        )


async def test_AC_extraction_1913_4_api_and_prefect_use_same_composed_use_case(monkeypatch):
    calls: list[tuple[ParseJob, bytes | None]] = []

    class FakeUseCase:
        async def execute(self, job: ParseJob, *, content: bytes | None = None):
            calls.append((job, content))

    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", None)
    monkeypatch.setattr(statement_pipeline, "run_with_async_parse_tracking", lambda awaitable, **_context: awaitable)
    monkeypatch.setattr(statement_flow, "run_with_async_parse_tracking", lambda awaitable, **_context: awaitable)
    job = _job()
    task = await statement_pipeline.submit_parse_pipeline(
        job=job, content=b"api-content", use_case_factory=lambda: FakeUseCase()
    )
    assert isinstance(task, asyncio.Task)
    await task
    await statement_flow.parse_statement_flow.fn(
        job=job.to_prefect_params(), use_case_factory=lambda **_kwargs: FakeUseCase()
    )
    assert calls == [(job, b"api-content"), (job, None)]


async def test_AC_extraction_1913_6_application_error_does_not_reject_source(db, test_user):
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
    service.parse_documents = AsyncMock(side_effect=RuntimeError("composition unavailable"))
    with pytest.raises(RetryableStatementIngestionError, match="composition unavailable"):
        await _make_use_case(db, service).execute(
            _job(statement_id=statement.id, user_id=test_user.id, run_id=await run_for(db, statement.id)),
            content=b"content",
        )
    await db.refresh(statement)
    assert (statement.status, statement.validation_error) == (BankStatementStatus.PARSING, None)


def test_AC_extraction_1913_7_fresh_worker_composes_without_main():
    script = "import sys\nfrom src.composition import compose_statement_ingestion_use_case\ncase = compose_statement_ingestion_use_case()\nassert case.posting_dependencies.transfer_exclusions is not None and case.posting_dependencies.fx_rate_provider is not None and 'src.main' not in sys.modules\n"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


async def test_AC_extraction_1913_8_retry_does_not_duplicate_financial_effects(db, test_user, monkeypatch):
    content = _interest_pdf("retry-idempotent")
    await _interest_service("1913", "2026-06").parse_document(
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
    monkeypatch.setattr("src.config.settings.enable_ai_classification", True)
    monkeypatch.setattr(
        "src.extraction.extension.transaction_classification.propose_categories",
        lambda txns, _p: asyncio.sleep(
            0,
            result=[
                CategoryProposal(
                    category=TransactionCategory.INTEREST.value,
                    confidence=95,
                    reason="deterministic idempotency fixture",
                )
                for _ in txns
            ],
        ),
    )
    deps = _posting_dependencies()
    await classify_statement_rows(db, statement)
    first = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id, dependencies=deps)
    second = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id, dependencies=deps)
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
    assert (first, second, len(entries)) == (1, 0, 1)


async def test_AC_extraction_ingestion_trace_1_is_atomic_with_statement_facts(db, test_user, monkeypatch):
    # The model abstains for every row: the rows stay without an answer and the statement waits for the economic review.
    # (With no model configured the classify run fails instead: that case has tests of its own.)
    monkeypatch.setattr(
        "src.extraction.extension.transaction_classification.propose_categories",
        lambda txns, _p: asyncio.sleep(0, result=[None] * len(txns)),
    )
    content = _interest_pdf("atomic-trace-statement")
    fail_content = _interest_pdf("trace-failure")
    file_hash = hashlib.sha256(content).hexdigest()
    statement = StatementSummaryFactory.build(
        id=uuid4(), user_id=test_user.id, status=BankStatementStatus.PARSING, file_hash=file_hash, institution="DBS"
    )
    second_statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash=hashlib.sha256(fail_content).hexdigest(),
        institution="DBS",
    )
    db.add_all([statement, second_statement])
    await db.commit()
    service = _interest_service("1914", "2026-07")
    use_case = _make_use_case(
        db,
        service,
        trace_emitter_factory=lambda s: TraceEmitter(SqlTraceRecordRepository(s, extraction_trace_policy_registry())),
    )
    tenant_rows_q = select(TraceRecordRow).where(
        TraceRecordRow.scope_id == str(test_user.id), TraceRecordRow.target_kind != "statement_run"
    )
    before = len((await db.execute(tenant_rows_q)).scalars().all())
    outcome = await use_case.execute(
        _job(
            statement_id=statement.id, user_id=test_user.id, file_hash=file_hash, run_id=await run_for(db, statement.id)
        ),
        content=content,
    )
    await db.refresh(statement)
    assert (
        outcome.status.value,
        len((await db.execute(tenant_rows_q)).scalars().all()),
        statement.status,
        statement.validation_error,
    ) == ("completed", before + 8, BankStatementStatus.PARSED, "Economic review required: intent_missing")

    class FailingEmitter:
        async def emit_many(self, _records):
            raise RuntimeError("trace repository unavailable")

    failing = _make_use_case(db, service, trace_emitter_factory=lambda _s: FailingEmitter())
    with pytest.raises(RetryableStatementIngestionError, match="trace repository unavailable"):
        await failing.execute(
            _job(
                statement_id=second_statement.id,
                user_id=test_user.id,
                file_hash=second_statement.file_hash,
                run_id=await run_for(db, second_statement.id),
            ),
            content=fail_content,
        )
    await db.refresh(second_statement)
    assert (second_statement.status, len((await db.execute(tenant_rows_q)).scalars().all())) == (
        BankStatementStatus.PARSING,
        before + 8,
    )


async def test_AC_extraction_ingestion_trace_2_retries_are_idempotent_and_changes_supersede(db, test_user):
    txn = StatementTransaction(
        transaction_id=uuid4(),
        transaction_date=date(2026, 7, 1),
        amount=Decimal("10.00"),
        currency="SGD",
        direction=TransactionDirection.IN,
        description="Recorded credit",
    )
    counter_id, policy, emitter = (
        uuid4(),
        DispositionPolicy(),
        TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())),
    )

    async def emit(category: str):
        intent = IntentProposal(
            schema_version="1",
            policy_version="intent-v1",
            origin=IntentProposalOrigin.REVIEWED_RULE,
            intent=EconomicIntent.INCOME,
            category=category,
            confidence=Decimal("0.95"),
            evidence=("recorded-description",),
        )
        return await emit_disposition_trace_records(
            emitter=emitter,
            user_id=test_user.id,
            execution_id=f"statement:stable:txn:{txn.transaction_id}",
            occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
            transaction=txn,
            proposal=intent,
            decision=policy.decide(txn, proposal=intent, context=DispositionContext(counter_account_id=counter_id)),
        )

    first, retry, corrected = await emit("SALARY"), await emit("SALARY"), await emit("DIVIDEND")
    assert (
        retry == first,
        len(list((await db.execute(select(TraceRecordRow))).scalars())),
        corrected[2].supersedes_id,
        corrected[3].supersedes_id,
    ) == (True, 7, first[2].record_id, first[3].record_id)
