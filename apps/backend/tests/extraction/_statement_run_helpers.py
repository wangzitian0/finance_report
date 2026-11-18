from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, SqlTraceRecordRepository, TraceEmitter
from src.audit.orm import TraceRecordRow
from src.composition import compose_statement_ingestion_use_case, compose_statement_posting_dependencies
from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import (
    ActiveRunExists,
    BankStatementStatus,
    ClassificationStatus,
    DocumentSource,
    DocumentStatus,
    DocumentType,
    ExtractedTransactionRow,
    ParseJob,
    RuleType,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    Stage1Status,
    StaleRun,
    StatementIngestionStatus,
    StatementSummary,
    TransactionDirection,
    UploadedDocument,
    claim_run,
    create_run,
    effective_statement_transaction_filter,
    finish_run,
)
from src.extraction.base.result import (
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceProvenance,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
)
from src.extraction.extension import statement_classification_run, transaction_classification
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.extraction_trace import build_extraction_trace_records, extraction_trace_policy_registry
from src.extraction.extension.reviewed_statement_envelope import persist_statement_extraction_result
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.source_lifecycle import SourceIdentityCommand
from src.extraction.extension.statement_classification_run import execute_classify_run
from src.extraction.extension.transaction_classification import (
    CategoryProposal,
    ClassificationPolicy,
    TransactionCategory,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.extraction.orm.reviewed_statement_envelope import (
    ReviewedStatementEnvelope,
    StatementExtractionResultRecord,
)
from src.extraction.orm.statement_run import StatementRun
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalLine, submit_system_journal_entry
from src.reporting.extension.balance_sheet import generate_balance_sheet
from tests.factories import (
    AccountFactory,
    AtomicTransactionFactory,
    StatementSummaryFactory,
    seed_parsed_statement,
)
from tests.statement_ingestion import classify_run_for, classify_statement, parse_and_load_statement_projection, run_for

WAIT_SECONDS = 20
BACKEND_DIR = Path(__file__).resolve().parents[2]
CSV = (
    b"Statement Currency,Date,Description,Debit Amount,Credit Amount\n"
    b"SGD,2026-01-05,Salary,,5000.00\n"
    b"SGD,2026-01-20,Rent,1500.00,\n"
)
ANSWERS = {
    "Salary": (TransactionCategory.SALARY, 95),
    "Coffee": (TransactionCategory.DINING, 92),
    "Grab": (TransactionCategory.TRANSPORT, 90),
    "Rent": (TransactionCategory.HOUSING, 94),
    "Refund": (TransactionCategory.REFUND, 91),
}
EXTENDED_ANSWERS: dict[str, tuple[TransactionCategory, int]] = {
    **ANSWERS,
    "Transfer": (TransactionCategory.TRANSFER, 90),
    "Loan": (TransactionCategory.LOAN_PRINCIPAL, 90),
    "Mystery": (TransactionCategory.DINING, 40),
    "Odd": (TransactionCategory.SALARY, 95),
    "Fee": (TransactionCategory.FEES, 70),
}


class Sleeps:
    """Records the waits of the retry loop so a test does not wait."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class ScriptedService:
    """Raise the scripted error of each call, then parse with the real service."""

    def __init__(self, errors: list[BaseException | None]) -> None:
        self.errors = list(errors)
        self.calls = 0
        self.real = ExtractionService()

    async def parse_document(self, *args, **kwargs):
        self.calls += 1
        error = self.errors.pop(0) if self.errors else None
        if error is not None:
            raise error
        return await self.real.parse_document(*args, **kwargs)


class ScriptedLoader:
    """Raise the scripted storage error of each call, then return the source bytes."""

    def __init__(self, errors: list[BaseException | None]) -> None:
        self.errors = list(errors)
        self.calls = 0

    async def __call__(self, _storage_key: str) -> bytes:
        self.calls += 1
        error = self.errors.pop(0) if self.errors else None
        if error is not None:
            raise error
        return CSV


class ForbiddenService:
    async def parse_document(self, *_args, **_kwargs):
        raise AssertionError("the worker called the model for a run that it could not claim")


class ScriptedModel:
    """Model mock that answers with ANSWERS and supports Events, coroutines, or exceptions."""

    def __init__(self, *steps) -> None:
        self.steps = steps
        self.calls: list[list[str]] = []
        self.cancelled: set[int] = set()
        self._reached: dict[int, asyncio.Event] = {}

    def reached(self, number: int) -> asyncio.Event:
        return self._reached.setdefault(number, asyncio.Event())

    async def __call__(self, transactions, _policy):
        number = len(self.calls)
        self.calls.append([transaction.description for transaction in transactions])
        self.reached(number).set()
        step = self.steps[number] if number < len(self.steps) else None
        if isinstance(step, asyncio.Event):
            try:
                await asyncio.wait_for(step.wait(), timeout=WAIT_SECONDS)
            except asyncio.CancelledError:
                self.cancelled.add(number)
                raise
        elif isinstance(step, BaseException):
            raise step
        elif step is not None:
            await step()
        return [
            CategoryProposal(
                category=ANSWERS[transaction.description.split()[0]][0].value,
                confidence=ANSWERS[transaction.description.split()[0]][1],
                reason="fixture",
            )
            for transaction in transactions
        ]


class Proposer:
    """A model that records its calls and can wait, fail or refuse a kind of row."""

    def __init__(
        self,
        *,
        gate: asyncio.Event | None = None,
        error: Exception | None = None,
        refuse=frozenset(),
        answers: dict[str, tuple[TransactionCategory, int]] = ANSWERS,
        timeout_gate: bool = False,
    ):
        self.calls: list[list[str]] = []
        self.gate = gate
        self.error = error
        self.refuse = refuse
        self.answers = answers
        self.timeout_gate = timeout_gate
        self.started = asyncio.Event()

    @property
    def rows_asked(self) -> int:
        return sum(len(call) for call in self.calls)

    async def __call__(self, transactions, _policy):
        self.calls.append([transaction.description for transaction in transactions])
        self.started.set()
        if self.gate is not None:
            if self.timeout_gate:
                try:
                    await asyncio.wait_for(self.gate.wait(), timeout=WAIT_SECONDS)
                except TimeoutError:
                    raise AssertionError("the test never opened the gate") from None
            else:
                await self.gate.wait()
        if self.error is not None:
            raise self.error
        proposals: list[CategoryProposal | None] = []
        for transaction in transactions:
            kind = transaction.description.split()[0]
            category, confidence = self.answers[kind]
            proposals.append(
                None
                if kind in self.refuse
                else CategoryProposal(category=category.value, confidence=confidence, reason="fixture")
            )
        return proposals


class RecordingLogger:
    """Stands in for the module logger so cached structlog loggers cannot hide events."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def info(self, event: str, **fields) -> None:
        self.events.append({"event": event, **fields})

    warning = error = debug = info


def _use_case(db, service=None, sleeps: Sleeps | None = None, **overrides):
    use_case = compose_statement_ingestion_use_case(session_maker=create_session_maker_from_db(db))
    changes = {"sleep": sleeps or Sleeps(), **overrides}
    if service is not None:
        changes["extraction_service_factory"] = lambda: service
    return replace(use_case, **changes)


async def _statement_with_run(
    db,
    user,
    *,
    content: bytes = CSV,
    name: str = "wiring.csv",
    hints: RunHints | None = None,
    model: str | None = None,
    job_model: str | None = None,
) -> tuple[UUID, ParseJob]:
    file_hash = hashlib.sha256(content).hexdigest()
    statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=user.id,
        account_id=None,
        file_hash=file_hash,
        institution="DBS",
        status=BankStatementStatus.PARSING,
        confidence_score=None,
        balance_validated=None,
    )
    db.add(statement)
    await db.flush()
    run = await create_run(
        db,
        statement_id=statement.id,
        user_id=user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.UPLOAD,
        hints=hints or RunHints(),
        model=model,
    )
    await db.commit()
    job = ParseJob(
        statement_id=statement.id,
        run_id=run.id,
        filename=name,
        institution="DBS",
        user_id=user.id,
        account_id=None,
        file_hash=file_hash,
        storage_key=f"statements/{name}",
        model=job_model or model,
        request_id=f"req-{name}",
    )
    return statement.id, job


async def _runs(db, statement_id: UUID) -> list[StatementRun]:
    rows = await db.execute(
        select(StatementRun)
        .where(StatementRun.statement_id == statement_id)
        .order_by(StatementRun.seq)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _statement(db, statement_id: UUID) -> StatementSummary:
    return await db.scalar(
        select(StatementSummary).where(StatementSummary.id == statement_id).execution_options(populate_existing=True)
    )


async def _count(db, model, *where) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def _prefect_params(**changes) -> dict[str, str | None]:
    params = {
        "statement_id": str(uuid4()),
        "run_id": str(uuid4()),
        "filename": "x.pdf",
        "institution": None,
        "user_id": str(uuid4()),
        "account_id": None,
        "file_hash": "h",
        "storage_key": "statements/x.pdf",
        "model": None,
        "request_id": None,
    }
    return {**params, **changes}


def _worker(maker, run_id: UUID, **options):
    return execute_classify_run(
        maker, run_id=run_id, posting_dependencies=compose_statement_posting_dependencies(), **options
    )


async def _wait_until(condition, seconds: float = 10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + seconds
    while not await condition():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.02)
    return True


def install_proposer(monkeypatch, proposer):
    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    return proposer


def make_rows(
    count: int = 5,
    first_day: date = date(2026, 1, 1),
    *,
    kinds: list[str] | tuple[str, ...] = ("Salary", "Coffee", "Grab", "Rent", "Refund"),
) -> list[dict]:
    rows = []
    for index in range(count):
        kind = kinds[index % len(kinds)]
        incoming = kind in ("Salary", "Refund")
        rows.append(
            {
                "description": f"{kind} {index:03d}",
                "amount": (Decimal("2500.00") if incoming else Decimal("12.50")) + Decimal(index),
                "direction": TransactionDirection.IN if incoming else TransactionDirection.OUT,
                "date": first_day + timedelta(days=index),
            }
        )
    return rows


async def seed_classify_statement(db, user_or_id, rows=None, *, name: str = "classify.pdf"):
    uid = user_or_id.id if hasattr(user_or_id, "id") else user_or_id
    rows = make_rows() if rows is None else rows
    seeded = await seed_parsed_statement(
        db, uid, institution="DBS", original_filename=name, opening_balance=Decimal("1000.00"), transactions=rows
    )
    if rows:
        seeded.statement.period_start, seeded.statement.period_end = rows[0]["date"], rows[-1]["date"]
    await db.commit()
    return seeded


async def get_run(db, run_id) -> StatementRun:
    return await db.scalar(
        select(StatementRun).where(StatementRun.id == run_id).execution_options(populate_existing=True)
    )


async def count_user_answers(db, user_or_id) -> int:
    uid = user_or_id.id if hasattr(user_or_id, "id") else user_or_id
    return await _count(
        db,
        TransactionClassification,
        TransactionClassification.atomic_txn_id.in_(
            select(AtomicTransaction.id).where(AtomicTransaction.user_id == uid)
        ),
    )


def spy_classify_outcomes(monkeypatch) -> list[str]:
    outcomes: list[str] = []
    monkeypatch.setattr(
        statement_classification_run,
        "record_statement_classification_outcome",
        lambda *, outcome: outcomes.append(outcome),
    )
    return outcomes


async def add_coffee_rule(db, user_or_id) -> UUID:
    uid = user_or_id.id if hasattr(user_or_id, "id") else user_or_id
    account = Account(user_id=uid, name="Expense - Reviewed Coffee", type=AccountType.EXPENSE, currency="SGD")
    db.add(account)
    await db.flush()
    db.add(
        ClassificationRule(
            user_id=uid,
            created_by=uid,
            version_number=1,
            effective_date=date(2020, 1, 1),
            is_active=True,
            rule_name="coffee-rule",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["Coffee"]},
            tag_mappings={"category": "REVIEWED_COFFEE"},
            default_account_id=account.id,
        )
    )
    await db.commit()
    return account.id


def high_confidence_pdf_service(rows: list[dict]):
    opening = Decimal("1000.00")
    closing = opening + sum(
        (r["amount"] if r["direction"] is TransactionDirection.IN else -r["amount"] for r in rows), start=Decimal("0")
    )
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "DBS",
            "account_last4": "1234",
            "currency": "SGD",
            "period_start": rows[0]["date"].isoformat(),
            "period_end": rows[-1]["date"].isoformat(),
            "opening_balance": str(opening),
            "closing_balance": str(closing),
            "transactions": [
                {
                    "date": r["date"].isoformat(),
                    "description": r["description"],
                    "amount": str(r["amount"]),
                    "direction": r["direction"].value,
                    "currency": "SGD",
                }
                for r in rows
            ],
        }
    )
    buffer = BytesIO()
    page = canvas.Canvas(buffer)
    page.drawString(72, 720, f"Opening: {opening} Closing: {closing}")
    for row in rows:
        page.drawString(72, 700, f"{row['date'].isoformat()} {row['description']} {row['amount']}")
    page.showPage()
    page.save()
    return service, buffer.getvalue()


async def create_parsing_job(db, user, content: bytes, name: str = "high.pdf"):
    file_hash = hashlib.sha256(content).hexdigest()
    statement = StatementSummaryFactory.build(
        id=uuid4(), user_id=user.id, status=BankStatementStatus.PARSING, file_hash=file_hash, institution="DBS"
    )
    db.add(statement)
    await db.commit()
    job = ParseJob(
        statement_id=statement.id,
        run_id=await run_for(db, statement.id),
        filename=name,
        institution="DBS",
        user_id=user.id,
        account_id=None,
        file_hash=file_hash,
        storage_key=f"statements/{name}",
        model=None,
        request_id=f"req-{name}",
    )
    return statement.id, job


async def parsed_candidate_after_extract(db, user, *, marked: bool):
    from tests.api._statement_router_fixtures import create_statement_account

    seeded = await seed_classify_statement(db, user)
    seeded.statement.balance_validated = True
    seeded.statement.confidence_score = 95
    seeded.statement.account_last4 = "1234"
    seeded.statement.account_id = (await create_statement_account(db, user.id)).id
    extract = await create_run(
        db,
        statement_id=seeded.id,
        user_id=user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await claim_run(db, extract.id)
    await finish_run(db, extract.id, result_summary={"auto_approve_candidate": marked})
    await db.commit()
    return seeded.id, await classify_run_for(db, seeded.id, parent_run_id=extract.id)


def make_csv_bytes(rows: list[dict]) -> bytes:
    lines = ["Statement Currency,Date,Description,Debit Amount,Credit Amount"]
    for row in rows:
        incoming = row["direction"] is TransactionDirection.IN
        lines.append(
            f"SGD,{row['date'].isoformat()},{row['description']},{'' if incoming else row['amount']},{row['amount'] if incoming else ''}"
        )
    return ("\n".join(lines) + "\n").encode()


def make_parse_job(statement_id: UUID, user_id: UUID, name: str, file_hash: str, run_id: UUID) -> ParseJob:
    return ParseJob(
        statement_id=statement_id,
        run_id=run_id,
        filename=name,
        institution="DBS",
        user_id=user_id,
        account_id=None,
        file_hash=file_hash,
        storage_key=f"statements/{name}",
        model=None,
        request_id=f"req-{name}",
    )


async def ingest_csv_statement(db: AsyncSession, user_id: UUID, name: str, rows: list[dict]) -> UUID:
    content = make_csv_bytes(rows)
    file_hash = hashlib.sha256(content).hexdigest()
    statement = StatementSummaryFactory.build(
        id=uuid4(), user_id=user_id, status=BankStatementStatus.PARSING, file_hash=file_hash, institution="DBS"
    )
    statement_id = statement.id
    db.add(statement)
    await db.commit()
    outcome = await _use_case(db).execute(
        make_parse_job(statement_id, user_id, name, file_hash, await run_for(db, statement_id)), content=content
    )
    assert outcome.status is StatementIngestionStatus.COMPLETED
    db.expire(statement)
    return statement_id


async def confirm_csv_envelope(client, db: AsyncSession, user_id: UUID, statement_id: UUID, rows: list[dict]) -> None:
    review = await client.get(f"/statements/{statement_id}/review")
    assert review.status_code == 200, review.text
    bank = Account(user_id=user_id, name=f"Bank from {rows[0]['date']}", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.commit()
    closing = Decimal("1000.00") + sum(
        (r["amount"] if r["direction"] is TransactionDirection.IN else -r["amount"] for r in rows), start=Decimal("0")
    )
    response = await client.post(
        f"/statements/{statement_id}/review-envelopes",
        json={
            "source_result_digest": review.json()["source_result_digest"],
            "account_id": str(bank.id),
            "currency": "SGD",
            "period_start": rows[0]["date"].isoformat(),
            "period_end": rows[-1]["date"].isoformat(),
            "opening_balance": "1000.00",
            "closing_balance": str(closing),
            "rationale": "Checked against the original file.",
        },
    )
    assert response.status_code == 200, response.text


async def approve_statement(client, statement_id: UUID):
    review = await client.get(f"/statements/{statement_id}/review")
    assert review.status_code == 200, review.text
    return await client.post(f"/statements/{statement_id}/approvals", json={"create_account_if_missing": True})


async def user_classification_rows(db_or_maker, user_id: UUID) -> list[TransactionClassification]:
    maker = db_or_maker if callable(db_or_maker) else create_session_maker_from_db(db_or_maker)
    async with maker() as session:
        rows = await session.execute(
            select(TransactionClassification)
            .join(AtomicTransaction, AtomicTransaction.id == TransactionClassification.atomic_txn_id)
            .where(AtomicTransaction.user_id == user_id)
        )
        return list(rows.scalars())


async def classify_outcome(db, statement_id: UUID) -> str:
    run_id = await classify_statement(db, statement_id)
    run = await get_run(db, run_id)
    return run.result_summary["outcome"] if run.state is RunState.SUCCEEDED else run.error_code


async def posted_accounts_for_coffee(db, user_id: UUID) -> set:
    async with create_session_maker_from_db(db)() as session:
        coffee = (
            await session.execute(
                select(AtomicTransaction).where(
                    AtomicTransaction.user_id == user_id, AtomicTransaction.description.like("Coffee%")
                )
            )
        ).scalar_one()
        return set(
            (
                await session.execute(
                    select(JournalLine.account_id)
                    .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
                    .where(JournalEntry.source_id == coffee.id)
                )
            ).scalars()
        )


async def read_classify_state(client, db: AsyncSession, user_id: UUID) -> dict:
    balance = await client.get("/reports/balance-sheet", params={"as_of_date": "2026-03-31", "currency": "SGD"})
    assert balance.status_code == 200, balance.text
    income = await client.get(
        "/reports/income-statement", params={"start_date": "2026-01-01", "end_date": "2026-03-31", "currency": "SGD"}
    )
    assert income.status_code == 200, income.text
    cls_rows = (
        (
            await db.execute(
                select(TransactionClassification)
                .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
                .where(AtomicTransaction.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    entry_rows = (await db.execute(select(JournalEntry).where(JournalEntry.user_id == user_id))).scalars().all()
    return {
        "classifications": cls_rows,
        "journal_entries": entry_rows,
        "balance_sheet": balance.json(),
        "income_statement": income.json(),
    }


async def make_run_statement(db, user, *, status=BankStatementStatus.PARSING, created_at=None) -> StatementSummary:
    statement = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=user.id,
        account_id=None,
        file_hash=f"runs-{uuid4()}",
        institution="DBS",
        status=status,
        confidence_score=None,
        balance_validated=None,
    )
    if created_at is not None:
        statement.created_at = created_at
    db.add(statement)
    await db.commit()
    return statement


async def create_test_run(db, statement, **overrides) -> StatementRun:
    arguments = {
        "statement_id": statement.id,
        "user_id": statement.user_id,
        "kind": RunKind.EXTRACT,
        "actor_kind": RunActorKind.SYSTEM,
        "trigger": RunTrigger.UPLOAD,
        "hints": RunHints(),
    }
    run = await create_run(db, **{**arguments, **overrides})
    await db.commit()
    return run


async def claim_test_run(db, statement, **overrides) -> StatementRun:
    run = await create_test_run(db, statement, **overrides)
    run = await claim_run(db, run.id)
    await db.commit()
    return run


async def run_traces(db, statement_id: UUID, run_id: UUID) -> list[TraceRecordRow]:
    rows = await db.execute(
        select(TraceRecordRow)
        .where(TraceRecordRow.execution_id == f"statement:{statement_id}:run:{run_id}")
        .order_by(TraceRecordRow.occurred_at)
    )
    return list(rows.scalars())


async def make_result_record(db, statement) -> StatementExtractionResultRecord:
    row = StatementExtractionResultRecord(
        user_id=statement.user_id,
        statement_id=statement.id,
        content_digest="a" * 64,
        source_content_digest="b" * 64,
        schema_version="2",
        producer_version="test",
        payload={},
        source_trace_record_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    db.add(row)
    await db.commit()
    return row


def migration_db_url(name: str) -> str:
    base = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test")
    return make_url(base).set(database=name).render_as_string(hide_password=False)


def run_alembic(database_url: str, *arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": database_url, "ENVIRONMENT": "testing"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def run_create_race(maker, statement_id: UUID, user_id: UUID):
    async with maker() as session:
        try:
            run = await create_run(
                session,
                statement_id=statement_id,
                user_id=user_id,
                kind=RunKind.EXTRACT,
                actor_kind=RunActorKind.USER,
                trigger=RunTrigger.RERUN,
                hints=RunHints(),
            )
            await session.commit()
            return run
        except ActiveRunExists as exc:
            await session.rollback()
            return exc


async def run_claim_race(maker, run_id: UUID):
    async with maker() as session:
        try:
            run = await claim_run(session, run_id)
            await session.commit()
            return run
        except StaleRun as exc:
            await session.rollback()
            return exc


async def set_run_timestamps(db, run_id: UUID, **values) -> None:
    await db.execute(update(StatementRun).where(StatementRun.id == run_id).values(**values))
    await db.commit()


async def make_txn(db, user, *, direction: TransactionDirection = TransactionDirection.OUT, description: str = "ROW"):
    return await AtomicTransactionFactory.create_async(
        db, user_id=user.id, description=description, direction=direction, currency="SGD"
    )


def constant_proposer(category: str | None, confidence: int = 70):
    async def proposer(transactions, _policy):
        if category is None:
            return [None for _ in transactions]
        return [CategoryProposal(category=category, confidence=confidence, reason="test") for _ in transactions]

    return proposer


async def txn_classification(db, txn) -> TransactionClassification | None:
    return (
        await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id == txn.id))
    ).scalar_one_or_none()


async def row_account(db, row) -> Account:
    return await db.get(Account, row.account_id)


async def draft_via_review_path(db, user, txn, category: str, confidence: int) -> TransactionClassification:
    from tests.statement_ingestion import classify_transactions

    user.ai_settings = {"auto_accept_ai_suggestions": False}
    await db.flush()
    await classify_transactions(
        db,
        user.id,
        [txn],
        policy=transaction_classification.POLICY_VERSIONS[-1],
        proposer=constant_proposer(category, confidence),
    )
    user.ai_settings = {"auto_accept_ai_suggestions": True}
    await db.flush()
    row = await txn_classification(db, txn)
    assert row.status is ClassificationStatus.DRAFT
    return row


def mock_model_answers(monkeypatch, items: list[dict]) -> None:
    async def stream():
        yield json.dumps(items)

    monkeypatch.setattr("src.llm.stream_ai_json", lambda **_kwargs: stream())
    monkeypatch.setattr(settings, "ai_api_key", "test-key")


def make_classification_policy(**overrides) -> ClassificationPolicy:
    return ClassificationPolicy(
        version=overrides.pop("version", 1),
        effective_from=overrides.pop("effective_from", date(2020, 1, 1)),
        catalog=overrides.pop("catalog", tuple(TransactionCategory)),
        model_version=overrides.pop("model_version", "test-model"),
        auto_apply_threshold=overrides.pop("auto_apply_threshold", 85),
        review_threshold=overrides.pop("review_threshold", 60),
        **overrides,
    )


def stub_proposer(proposals_by_description: dict[str, CategoryProposal | None]):
    calls: list[str] = []

    async def proposer(transactions, policy):
        calls.append("call")
        return [proposals_by_description.get(t.description) for t in transactions]

    proposer.calls = calls
    return proposer


def fake_stream(content: str):
    async def gen():
        yield content

    return gen()


def mock_statement_payload(*transactions: dict, direction: str = "IN", closing: str | None = None) -> dict:
    opening = Decimal("500.00") if direction == "OUT" else Decimal("100.00")
    if closing is None:
        delta = sum(Decimal(t["amount"]) if t["direction"] == "IN" else -Decimal(t["amount"]) for t in transactions)
        closing = str(opening + delta)
    return {
        "currency": "CNY",
        "period_start": "2025-02-01",
        "period_end": "2025-02-28",
        "opening_balance": str(opening),
        "closing_balance": closing,
        "transactions": list(transactions),
    }


def mock_txn_dict(
    description: object, amount: str = "50.00", direction: str = "IN", *, absent_marker: object = None
) -> dict:
    row = {"date": "2025-02-03", "amount": amount, "direction": direction}
    if absent_marker is not None and description is absent_marker:
        return row
    return {**row, "description": description}


async def parse_mock_payload(payload: dict, *, institution: str = "CMB"):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=payload)
    return await service.parse_document(
        DocumentSource.resolve(path=Path("test.pdf"), content=b"content"), institution=institution, user_id=uuid4()
    )


async def assert_stream_extract_case(
    stream_exc, accum_val, file_content, file_type, file_url, force_model, expected, err_match
) -> None:
    service = ExtractionService()
    service.api_key = "test-key"
    if stream_exc is not None:
        with (
            patch("src.extraction.extension.service.stream_ai_json", side_effect=stream_exc),
            pytest.raises(ExtractionError, match=err_match),
        ):
            await service.extract_financial_data(file_content, "DBS", file_type, file_url=file_url)
        return
    if (
        isinstance(accum_val, str)
        and force_model is None
        and (not err_match or ("strict JSON object" in err_match and "no arrays" not in err_match))
    ):
        with patch("src.extraction.extension.service.stream_ai_json", return_value=fake_stream(accum_val)):
            if err_match:
                with pytest.raises(ExtractionError, match=err_match):
                    await service.extract_financial_data(file_content, "DBS", file_type, file_url=file_url)
            else:
                assert (
                    await service.extract_financial_data(file_content, "DBS", file_type, file_url=file_url) == expected
                )
        return
    accum_patch = (
        patch("src.extraction.extension.service.accumulate_stream", new_callable=AsyncMock, side_effect=accum_val)
        if isinstance(accum_val, Exception)
        else patch("src.extraction.extension.service.accumulate_stream", new_callable=AsyncMock, return_value=accum_val)
    )
    with patch("src.extraction.extension.service.stream_ai_json") as mock_stream, accum_patch:
        kwargs = {"file_content": file_content, "institution": "DBS", "file_type": file_type, "file_url": file_url}
        if force_model:
            kwargs["force_model"] = force_model
        if err_match:
            with pytest.raises(ExtractionError, match=err_match):
                await service.extract_financial_data(**kwargs)
        else:
            assert await service.extract_financial_data(**kwargs) == expected
            if force_model:
                assert (
                    mock_stream.call_args.kwargs.get("model") or mock_stream.call_args[1].get("model")
                ) == force_model


def integrity_payload(**changes) -> dict:
    return {
        "institution": "Synthetic Bank",
        "account_last4": "0001",
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100",
        "closing_balance": "110",
        "transactions": [
            {
                "date": "2025-01-02",
                "amount": "10",
                "direction": "IN",
                "currency": "SGD",
                "description": "Synthetic deposit",
            }
        ],
        **changes,
    }


async def integrity_parse(payload, *, db=None, user_id=None, account_id=None, source=None):
    service = ExtractionService()
    service._extract_vision_source = AsyncMock(return_value=payload)
    return await service.parse_document(
        source or DocumentSource.resolve(path=Path("synthetic.pdf"), content=b"synthetic"),
        user_id=user_id or uuid4(),
        account_id=account_id,
        db=db,
    )


async def integrity_source(db, user_id, *, account=None, currency="SGD"):
    document = UploadedDocument(
        user_id=user_id,
        file_path=f"synthetic/{uuid4()}.pdf",
        file_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        original_filename="synthetic.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    summary = StatementSummaryFactory.build(
        user_id=user_id,
        uploaded_document_id=document.id,
        file_hash=document.file_hash,
        account_id=account.id if account else None,
        currency=currency,
        institution="Synthetic Bank",
    )
    db.add(summary)
    await db.flush()
    return document, summary


async def integrity_store_result(db, summary, result):
    records = build_extraction_trace_records(
        result,
        user_id=summary.user_id,
        execution_id=f"test:{summary.id}:{result.result_id}",
        occurred_at=datetime.now(UTC),
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(records)
    return await persist_statement_extraction_result(
        db, statement=summary, result=result, source_trace_record_id=records[0].record_id
    )


async def integrity_upsert(db, user_id, document, *, currency="SGD"):
    service = DeduplicationService()
    txn_date, amount, direction = date(2025, 1, 2), Decimal("10"), TransactionDirection.IN
    description, balance_after = "Synthetic deposit", Decimal("110")
    row = ExtractedTransactionRow(
        user_id=user_id,
        txn_date=txn_date,
        amount=amount,
        direction=direction.value,
        description=description,
        reference=None,
        currency=currency,
        currency_unresolved=False,
        balance_after=balance_after,
        occurrence_index=0,
        dedup_hash=service.calculate_transaction_hash(
            user_id, txn_date, amount, direction, description, balance_after=balance_after
        ),
    )
    return await service.upsert_scoped_atomic_transaction(
        db=db, row=row, source_doc_id=document.id, source_doc_type=DocumentType.BANK_STATEMENT
    )


async def integrity_legacy_txn(db, user_id, document, currency="SGD", description="Synthetic deposit"):
    old_hash = DeduplicationService.calculate_transaction_hash(
        user_id,
        date(2025, 1, 2),
        Decimal("10"),
        TransactionDirection.IN,
        description,
        balance_after=Decimal("110"),
    )
    old = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2025, 1, 2),
        amount=Decimal("10"),
        direction=TransactionDirection.IN,
        description=description,
        currency=currency,
        balance_after=Decimal("110"),
        dedup_hash=old_hash,
        source_documents=[{"doc_id": str(document.id), "doc_type": "bank_statement"}],
    )
    db.add(old)
    await db.flush()
    return old


async def effective_txn_ids(db, user_id: UUID, scope: UUID | None = None) -> set[UUID]:
    return set(
        (
            await db.scalars(select(AtomicTransaction.id).where(effective_statement_transaction_filter(user_id, scope)))
        ).all()
    )


def custody_payload(**changes) -> dict:
    return {
        "institution": "DBS",
        "account_last4": "2468",
        "currency": "SGD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": "1000",
        "closing_balance": "1100",
        "transactions": [
            {
                "date": "2026-01-10",
                "description": "Synthetic receipt",
                "amount": "100",
                "direction": "IN",
                "currency": changes.get("currency", "SGD"),
                "balance_after": "1100",
            }
        ],
        **changes,
    }


async def custody_parse(db, uid, *, account_id=None, **changes):
    service = ExtractionService()
    service._extract_vision_source = AsyncMock(return_value=custody_payload(**changes))
    source = DocumentSource.resolve(path=Path("synthetic-custody.pdf"), content=uuid4().bytes)
    _, statement, _ = await parse_and_load_statement_projection(
        service, db=db, user_id=uid, institution=None, source=source, account_id=account_id
    )
    await db.commit()
    return statement


async def custody_history(db, uid, account, *, corrupt=False):
    source = DocumentSource.resolve(path=Path("synthetic-history.pdf"), content=uuid4().bytes)
    service = ExtractionService()
    service._extract_vision_source = AsyncMock(return_value=custody_payload())
    result = await service.parse_document(source, user_id=uid, account_id=account.id)
    document = UploadedDocument(
        user_id=uid,
        file_path=str(source.path),
        file_hash=source.content_hash,
        original_filename=source.filename,
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    summary = StatementSummary(
        user_id=uid,
        uploaded_document_id=document.id,
        file_hash=document.file_hash,
        account_id=account.id,
        institution="DBS",
        account_last4="2468",
        currency="SGD",
        status=BankStatementStatus.PARSED,
    )
    db.add(summary)
    await db.flush()
    await integrity_store_result(db, summary, result)
    if corrupt:
        summary.account_last4 = "9999"
    await db.commit()
    return summary


def lifecycle_summary(user_id: UUID, *, file_hash: str, uploaded_document_id: UUID | None = None) -> StatementSummary:
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


def lifecycle_document(user_id: UUID, *, file_hash: str) -> UploadedDocument:
    return UploadedDocument(
        user_id=user_id,
        file_path=f"statements/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="statement.pdf",
        document_type=DocumentType.BANK_STATEMENT,
        status=DocumentStatus.COMPLETED,
    )


def lifecycle_atomic(
    user_id: UUID, document_id: UUID, *, currency: str, direction: TransactionDirection, amount: str
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


def lifecycle_identity(user_id: UUID, *, file_hash: str) -> SourceIdentityCommand:
    return SourceIdentityCommand(
        user_id=user_id,
        file_path=f"statements/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="statement.pdf",
        document_type=DocumentType.BANK_STATEMENT,
        extraction_metadata={"producer": "acceptance"},
    )


def lifecycle_source_result(source_digest: str, *, with_fact: bool = True) -> StatementExtractionResult:
    facts = (
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
    )
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
        transactions=facts if with_fact else (),
        positions=(),
        confidence=Decimal("0.90"),
        balance_validated=None,
        warnings=(),
        review_reasons=("source facts require confirmation",),
        provenance=SourceProvenance(
            intake_mode="csv", method=ExtractionMethod.DETERMINISTIC, provider="acceptance", model="acceptance@1"
        ),
        statement_currency=None,
    )


async def lifecycle_history_fixture(db: AsyncSession, user_id: UUID) -> tuple[StatementSummary, UploadedDocument]:
    account = Account(user_id=user_id, name="Source history account", type=AccountType.ASSET, currency="SGD")
    document = lifecycle_document(user_id, file_hash=f"history-{uuid4().hex}")
    db.add_all([account, document])
    await db.flush()
    statement = lifecycle_summary(user_id, file_hash=document.file_hash, uploaded_document_id=document.id)
    db.add(statement)
    await db.flush()
    typed_result = lifecycle_source_result("2" * 64, with_fact=False)
    source_result = StatementExtractionResultRecord(
        user_id=user_id,
        statement_id=statement.id,
        content_digest=typed_result.content_digest,
        source_content_digest=typed_result.source_content_digest,
        schema_version=typed_result.schema_version,
        producer_version=typed_result.producer_version,
        payload=typed_result.to_payload(),
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
    db.add(lifecycle_atomic(user_id, document.id, currency="SGD", direction=TransactionDirection.IN, amount="1.00"))
    await db.flush()
    return statement, document


async def run_two_session_barrier(maker, work):
    start = asyncio.Event()
    ready = 0
    lock = asyncio.Lock()

    async def barrier() -> None:
        nonlocal ready
        async with lock:
            ready += 1
            if ready == 2:
                start.set()
        await start.wait()

    async def worker():
        async with maker() as session:
            return await work(session, barrier)

    return await asyncio.wait_for(asyncio.gather(worker(), worker()), timeout=10)


async def make_approved_statement(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    *,
    institution: str = "DBS",
    last4: str = "8888",
    currency: str = "SGD",
    opening: str,
    closing: str,
    start: date,
    end: date,
    manual_opening: str | None = None,
    uploaded_document_id: UUID | None = None,
) -> StatementSummary:
    stmt = StatementSummaryFactory.build(
        user_id=user_id,
        uploaded_document_id=uploaded_document_id,
        account_id=account_id,
        institution=institution,
        account_last4=last4,
        currency=currency,
        opening_balance=Decimal(opening),
        manual_opening_balance=Decimal(manual_opening) if manual_opening is not None else None,
        closing_balance=Decimal(closing),
        period_start=start,
        period_end=end,
        status=BankStatementStatus.APPROVED,
    )
    db.add(stmt)
    await db.flush()
    return stmt


async def post_system_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    debit_id: UUID,
    credit_id: UUID,
    amount: str,
    entry_date: date,
    memo: str,
    currency: str = "SGD",
    fx_rate: Decimal | None = None,
    operation: str = "statement-posting",
    source_type: JournalEntrySourceType | None = None,
    source_id: UUID | None = None,
) -> None:
    line_extra = {"fx_rate": fx_rate} if fx_rate is not None else {}
    kwargs = {"source_type": source_type, "source_id": source_id} if source_type is not None else {}
    await submit_system_journal_entry(
        db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=[
            {
                "account_id": debit_id,
                "direction": Direction.DEBIT,
                "amount": Decimal(amount),
                "currency": currency,
                **line_extra,
            },
            {
                "account_id": credit_id,
                "direction": Direction.CREDIT,
                "amount": Decimal(amount),
                "currency": currency,
                **line_extra,
            },
        ],
        base_currency="SGD",
        operation=operation,
        **kwargs,
    )


async def assert_bs_asset(
    db: AsyncSession, user_id: UUID, *, as_of_date: date, currency: str, account_id: UUID, expected: Decimal
) -> None:
    bs = await generate_balance_sheet(db, user_id, as_of_date=as_of_date, currency=currency)
    assert bs["is_balanced"] is True
    assert next(a["amount"] for a in bs["assets"] if a["account_id"] == account_id) == expected


async def verify_runs_migration_backfill() -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    name = f"fr_ac_2994_9_{uuid4().hex[:12]}"
    admin = create_engine(migration_db_url("postgres").replace("+asyncpg", ""), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    database_url = migration_db_url(name)
    engine = create_engine(database_url.replace("+asyncpg", ""))
    user_id, updated_at, created_at = (
        uuid4(),
        datetime(2026, 11, 10, 6, 30, tzinfo=UTC),
        datetime(2026, 11, 10, 6, 0, tzinfo=UTC),
    )
    statements = {status: [uuid4(), uuid4()] for status in ("parsing", "parsed", "uploaded")}
    try:
        run_alembic(database_url, "upgrade", "0073_stmt_gin_trace_trig_perf")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, ai_settings, created_at, updated_at) VALUES (:id, :email, 'generated-hash', CAST('{}' AS jsonb), NOW(), NOW())"
                ),
                {"id": user_id, "email": f"migration-{user_id.hex}@example.test"},
            )
            for status, ids in statements.items():
                for sid in ids:
                    conn.execute(
                        text(
                            "INSERT INTO statement_summaries (id, user_id, file_hash, institution, status, created_at, updated_at) VALUES (:id, :user_id, :file_hash, 'DBS', CAST(:status AS statement_summary_status_enum), :created_at, :updated_at)"
                        ),
                        {
                            "id": sid,
                            "user_id": user_id,
                            "file_hash": sid.hex,
                            "status": status,
                            "created_at": created_at,
                            "updated_at": updated_at,
                        },
                    )
        run_alembic(database_url, "upgrade", "0074_statement_runs")
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT statement_id, user_id, seq, kind::text, state::text, actor_kind::text, trigger::text, hints, heartbeat_at, started_at, requested_at, finished_at, parent_run_id, extraction_result_id, result_summary, error_code, error_message FROM statement_runs"
                )
            ).all()
            assert {r.statement_id for r in rows} == set(statements["parsing"]) and len(rows) == 2
            for r in rows:
                assert (
                    r.user_id,
                    r.seq,
                    r.kind,
                    r.state,
                    r.actor_kind,
                    r.trigger,
                    r.hints,
                    r.heartbeat_at,
                    r.started_at,
                    r.requested_at,
                ) == (user_id, 1, "extract", "running", "system", "backfill", {}, updated_at, updated_at, created_at)
                assert (
                    r.finished_at,
                    r.parent_run_id,
                    r.extraction_result_id,
                    r.result_summary,
                    r.error_code,
                    r.error_message,
                ) == (None, None, None, None, None, None)
            assert {
                r[0]
                for r in conn.execute(
                    text("SELECT typname FROM pg_type WHERE typtype = 'e' AND typname LIKE 'statement\\_run\\_%'")
                )
            } == {
                "statement_run_kind_enum",
                "statement_run_state_enum",
                "statement_run_actor_kind_enum",
                "statement_run_trigger_enum",
            }
        insert_run = text(
            "INSERT INTO statement_runs (id, statement_id, user_id, seq, kind, state, actor_kind, trigger, hints, requested_at) VALUES (gen_random_uuid(), :statement_id, :user_id, :seq, 'extract', :state, 'user', 'rerun', CAST('{}' AS jsonb), NOW())"
        )
        for sid, seq, state, fails in (
            (statements["parsing"][0], 2, "requested", True),
            (statements["parsed"][0], 1, "requested", False),
            (statements["parsed"][0], 1, "failed", True),
            (statements["parsed"][0], 2, "failed", False),
        ):
            if fails:
                with pytest.raises(IntegrityError), engine.begin() as conn:
                    conn.execute(insert_run, {"statement_id": sid, "user_id": user_id, "seq": seq, "state": state})
            else:
                with engine.begin() as conn:
                    conn.execute(insert_run, {"statement_id": sid, "user_id": user_id, "seq": seq, "state": state})
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM statement_summaries WHERE id = :id"), {"id": statements["parsed"][0]})
            assert (
                conn.execute(
                    text("SELECT count(*) FROM statement_runs WHERE statement_id = :id"),
                    {"id": statements["parsed"][0]},
                ).scalar_one()
                == 0
            )
        run_alembic(database_url, "downgrade", "0073_stmt_gin_trace_trig_perf")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('statement_runs')")).scalar_one() is None
            assert (
                conn.execute(
                    text("SELECT count(*) FROM pg_type WHERE typtype = 'e' AND typname LIKE 'statement\\_run\\_%'")
                ).scalar_one()
                == 0
            )
            assert conn.execute(text("SELECT count(*) FROM statement_summaries")).scalar_one() == 5
        run_alembic(database_url, "upgrade", "0074_statement_runs")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM statement_runs")).scalar_one() == 2
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


async def verify_reaper_threshold_case(db, test_user, mode: str) -> None:
    from src.extraction import reap_stale_runs

    now, stale_after = datetime(2026, 11, 12, 8, 0, tzinfo=UTC), timedelta(minutes=5)
    if mode == "heartbeat":
        old = await claim_test_run(db, await make_run_statement(db, test_user))
        fresh = await claim_test_run(db, await make_run_statement(db, test_user))
        at_threshold = await claim_test_run(db, await make_run_statement(db, test_user))
        never_claimed = await create_test_run(db, await make_run_statement(db, test_user))
        finished = await claim_test_run(db, await make_run_statement(db, test_user))
        await finish_run(db, finished.id)
        for run, values in (
            (old, {"heartbeat_at": now - timedelta(minutes=6)}),
            (fresh, {"heartbeat_at": now - timedelta(minutes=2)}),
            (at_threshold, {"heartbeat_at": now - stale_after}),
            (never_claimed, {"requested_at": now - timedelta(minutes=2)}),
            (finished, {"heartbeat_at": now - timedelta(hours=1)}),
        ):
            await set_run_timestamps(db, run.id, **values)
        assert await reap_stale_runs(db, stale_after=stale_after, now=now) == [old.id]
        await db.commit()
        old_row = await get_run(db, old.id)
        assert (old_row.state, old_row.error_code, old_row.finished_at) == (RunState.FAILED, "heartbeat_lost", now)
        assert (
            (await get_run(db, fresh.id)).state,
            (await get_run(db, at_threshold.id)).state,
            (await get_run(db, never_claimed.id)).state,
            (await get_run(db, finished.id)).state,
        ) == (RunState.RUNNING, RunState.RUNNING, RunState.REQUESTED, RunState.SUCCEEDED)
        assert await reap_stale_runs(db, stale_after=stale_after, now=now) == []
    else:
        unclaimed = await create_test_run(db, await make_run_statement(db, test_user))
        fresh = await create_test_run(db, await make_run_statement(db, test_user))
        at_threshold = await create_test_run(db, await make_run_statement(db, test_user))
        long_running = await claim_test_run(db, await make_run_statement(db, test_user))
        for run, values in (
            (unclaimed, {"requested_at": now - timedelta(minutes=6)}),
            (fresh, {"requested_at": now - timedelta(minutes=2)}),
            (at_threshold, {"requested_at": now - stale_after}),
            (long_running, {"requested_at": now - timedelta(hours=1), "heartbeat_at": now - timedelta(minutes=1)}),
        ):
            await set_run_timestamps(db, run.id, **values)
        assert await reap_stale_runs(db, stale_after=stale_after, now=now) == [unclaimed.id]
        await db.commit()
        reaped = await get_run(db, unclaimed.id)
        assert (reaped.state, reaped.error_code, reaped.started_at, reaped.finished_at) == (
            RunState.FAILED,
            "claim_timeout",
            None,
            now,
        )
        assert (
            (await get_run(db, fresh.id)).state,
            (await get_run(db, at_threshold.id)).state,
            (await get_run(db, long_running.id)).state,
        ) == (RunState.REQUESTED, RunState.REQUESTED, RunState.RUNNING)
        records = {r.assertion_id: r for r in await run_traces(db, unclaimed.statement_id, unclaimed.id)}
        assert set(records) == {"extract.requested", "extract.failed"}
        assert (records["extract.failed"].reason_code, records["extract.failed"].occurred_at) == (
            "run_failed.claim_timeout",
            now,
        )


async def verify_worker_retry_reaper_and_user_start(db, db_engine, test_user) -> None:
    from src.extraction import (
        HintsNotApplicable,
        RetryableStatementIngestionError,
        StatementStatusChanged,
        fail_run,
        lock_statement_for_run,
        start_user_extract_run,
    )
    from src.extraction.extension import statement_parsing_supervisor as supervisor
    from src.statement_flow import parse_statement_flow
    from src.runtime import StorageError

    assert parse_statement_flow.retries == 0 and db_engine.sync_engine.hide_parameters is True
    c1, c2, c3, c4 = (CSV.replace(b"Salary", b"Salary" + n) for n in (b"1", b"2", b"3", b"4"))
    _, job_unclaimed = await _statement_with_run(db, test_user, content=c1, name="unclaimed.csv")
    await fail_run(db, job_unclaimed.run_id, error_code="failed_early", error_message="Done")
    await db.commit()
    assert (
        await _use_case(db, ForbiddenService()).execute(job_unclaimed, content=c1)
    ).status is StatementIngestionStatus.RUN_STALE

    sid_retry, job_retry = await _statement_with_run(db, test_user, content=c2, name="retry.csv")
    assert (
        await _use_case(
            db,
            ScriptedService([RetryableStatementIngestionError("tmp1"), RetryableStatementIngestionError("tmp2"), None]),
            sleeps=Sleeps(),
        ).execute(job_retry, content=c2)
    ).status is StatementIngestionStatus.COMPLETED
    assert [r.state for r in await _runs(db, sid_retry) if r.kind is RunKind.EXTRACT] == [
        RunState.FAILED,
        RunState.FAILED,
        RunState.SUCCEEDED,
    ]

    sid_stale, _ = await _statement_with_run(db, test_user, content=c3, name="stale.csv")
    assert (
        await supervisor.reap_stale_parsing_runs(
            create_session_maker_from_db(db), now=datetime.now(UTC) + timedelta(minutes=10)
        )
        >= 1
    )
    assert (await _statement(db, sid_stale)).status is BankStatementStatus.REJECTED

    sid_err, job_err = await _statement_with_run(db, test_user, content=c4, name="err.csv")
    assert (
        await _use_case(db, ScriptedService([ExtractionError("bad pdf")])).execute(job_err, content=c4)
    ).status is StatementIngestionStatus.SOURCE_REJECTED
    assert (await _runs(db, sid_err))[0].state is RunState.FAILED

    uid = test_user.id
    parsed_id = (await make_run_statement(db, test_user, status=BankStatementStatus.PARSED)).id
    loader = ScriptedLoader([])

    async def failing_load():
        raise StorageError("missing")

    for exc_cls, ft, hints, statuses, load_fn, expected_calls in (
        (
            HintsNotApplicable,
            "csv",
            RunHints(keywords=["x"]),
            frozenset({BankStatementStatus.PARSED}),
            lambda: loader("k"),
            0,
        ),
        (StatementStatusChanged, "pdf", RunHints(), frozenset({BankStatementStatus.REJECTED}), lambda: loader("k"), 1),
        (StorageError, "pdf", RunHints(), frozenset({BankStatementStatus.PARSED}), failing_load, 1),
    ):
        with pytest.raises(exc_cls):
            await start_user_extract_run(
                db,
                statement_id=parsed_id,
                user_id=uid,
                file_type=ft,
                hints=hints,
                model=None,
                allowed_statuses=statuses,
                strict_hints=True,
                load_content=load_fn,
            )
        await db.rollback()
        assert loader.calls == expected_calls
    assert (
        await lock_statement_for_run(db, parsed_id, uid, allowed=frozenset({BankStatementStatus.PARSED}))
        is not None
    )
    await db.rollback()
    assert isinstance(ParseJob(**{**_prefect_params(), "user_id": uid}), ParseJob)


async def verify_run_transitions_guard(db, test_user) -> None:
    from src.extraction import fail_run, heartbeat_run

    statement = await make_run_statement(db, test_user)
    run = await create_test_run(db, statement)
    with pytest.raises(StaleRun):
        await finish_run(db, run.id)
    assert await heartbeat_run(db, run.id) is False
    await claim_run(db, run.id)
    await db.commit()
    with pytest.raises(StaleRun):
        await claim_run(db, run.id)
    assert await heartbeat_run(db, run.id) is True
    for kw, match in (
        ({"error_code": "Not A Code", "error_message": "x"}, "error_code"),
        ({"error_code": "provider_timeout", "error_message": "x" * 501}, "error_message"),
    ):
        with pytest.raises(ValueError, match=match):
            await fail_run(db, run.id, **kw)
    failed = await fail_run(db, run.id, error_code="provider_timeout", error_message="x" * 500)
    await db.commit()
    assert failed.state is RunState.FAILED and failed.result_summary is None and failed.finished_at is not None
    for late in (
        lambda: claim_run(db, run.id),
        lambda: finish_run(db, run.id),
        lambda: fail_run(db, run.id, error_code="provider_timeout", error_message="again"),
        lambda: claim_run(db, uuid4()),
    ):
        with pytest.raises(StaleRun):
            await late()
    assert await heartbeat_run(db, run.id) is False
    skipped = await fail_run(
        db,
        (await create_test_run(db, statement)).id,
        error_code="dispatch_lost",
        error_message="No worker claimed the run.",
    )
    await db.commit()
    assert (skipped.state, skipped.started_at, skipped.seq) == (RunState.FAILED, None, 2)


async def verify_run_logging_digest(db, test_user, monkeypatch) -> None:
    from sqlalchemy.exc import IntegrityError
    from src.audit import canonical_json_digest
    from src.extraction import fail_run
    from src.extraction.extension import statement_runs as runs_module

    logs = RecordingLogger()
    monkeypatch.setattr(runs_module, "logger", logs)
    hints = RunHints(keywords=["zebra-keyword", "quartz-keyword"], note="needle-note-text for the model")
    run = await create_test_run(
        db, await make_run_statement(db, test_user), hints=hints, actor_kind=RunActorKind.USER, trigger=RunTrigger.RERUN
    )
    await claim_run(db, run.id)
    await finish_run(db, run.id)
    await db.commit()
    other = await claim_test_run(db, await make_run_statement(db, test_user))
    await fail_run(db, other.id, error_code="provider_timeout", error_message="The model call timed out.")
    await db.commit()
    transitions = [e for e in logs.events if e["event"] == "statement.run.transition"]
    assert [(e["run_id"], e["state"]) for e in transitions[:3]] == [
        (str(run.id), "requested"),
        (str(run.id), "running"),
        (str(run.id), "succeeded"),
    ]
    digest = canonical_json_digest(hints.model_dump(mode="json"))
    assert all(
        set(e) == {"event", "run_id", "kind", "state", "hints_digest", "hint_keyword_count"}
        and (e["kind"], e["hints_digest"], e["hint_keyword_count"]) == ("extract", digest, 2)
        for e in transitions[:3]
    )
    assert (transitions[-1]["state"], transitions[-1]["error_code"]) == ("failed", "provider_timeout")
    assert all(t not in str(logs.events) for t in ("zebra-keyword", "quartz-keyword", "needle-note-text"))
    with pytest.raises(IntegrityError) as missing:
        await create_run(
            db,
            statement_id=uuid4(),
            user_id=test_user.id,
            kind=RunKind.EXTRACT,
            actor_kind=RunActorKind.USER,
            trigger=RunTrigger.RERUN,
            hints=hints,
        )
    assert "needle-note-text" not in str(missing.value) and "zebra-keyword" not in str(missing.value)


async def verify_gated_auto_approve(client, db, test_user, monkeypatch) -> None:
    import time

    gate = asyncio.Event()
    proposer = install_proposer(monkeypatch, Proposer(gate=gate))
    rows = make_rows()
    service, content = high_confidence_pdf_service(rows)
    statement_id, job = await create_parsing_job(db, test_user, content)
    task = asyncio.create_task(_use_case(db, service).execute(job, content=content))
    try:
        await asyncio.wait_for(proposer.started.wait(), timeout=WAIT_SECONDS)
        stmt = await _statement(db, statement_id)
        extract, classify = await _runs(db, statement_id)
        assert (stmt.status, stmt.stage1_status.value) == (BankStatementStatus.PARSED, "pending_review")
        assert (extract.state, classify.kind, classify.state, extract.result_summary) == (
            RunState.SUCCEEDED,
            RunKind.CLASSIFY,
            RunState.RUNNING,
            {"auto_approve_candidate": True},
        )
        assert await _count(db, JournalEntry) == 0
        review = await client.get(f"/statements/{statement_id}/review")
        assert review.status_code == 200 and len(review.json()["transactions"]) == len(rows)
        started = time.perf_counter()
        refused = await client.post(f"/statements/{statement_id}/approvals", json={})
        assert (
            refused.status_code == 409
            and refused.json()["active_run_id"] == str(classify.id)
            and (time.perf_counter() - started) < 1.0
        )
    finally:
        gate.set()
    outcome = await asyncio.wait_for(task, timeout=WAIT_SECONDS)
    assert (outcome.status, outcome.auto_posted_count, (await _statement(db, statement_id)).status) == (
        StatementIngestionStatus.COMPLETED,
        len(rows),
        BankStatementStatus.APPROVED,
    )
    assert await _count(db, JournalEntry) >= len(rows) and proposer.rows_asked == len(rows)


async def verify_classify_reaper_paths(db, test_user, monkeypatch) -> None:
    from src.extraction import reap_stale_runs

    proposer = install_proposer(monkeypatch, Proposer())
    seeded = await seed_classify_statement(db, test_user)
    unclaimed_id = await classify_run_for(db, seeded.id)
    maker = create_session_maker_from_db(db)
    async with maker() as session:
        assert await reap_stale_runs(session, now=datetime.now(UTC) + timedelta(minutes=10)) == [unclaimed_id]
        await session.commit()
    assert await _worker(maker, unclaimed_id) == 0 and proposer.calls == []
    unclaimed = await get_run(db, unclaimed_id)
    assert (unclaimed.state, unclaimed.error_code) == (RunState.FAILED, "claim_timeout")

    active_id = await classify_run_for(db, seeded.id)
    real = Proposer()

    async def reaped_during_call(transactions, policy):
        async with maker() as other:
            assert await reap_stale_runs(other, now=datetime.now(UTC) + timedelta(minutes=10)) == [active_id]
            await other.commit()
        return await real(transactions, policy)

    install_proposer(monkeypatch, reaped_during_call)
    assert await _worker(maker, active_id) == 0
    active = await get_run(db, active_id)
    assert (active.state, active.error_code, await count_user_answers(db, test_user)) == (
        RunState.FAILED,
        "heartbeat_lost",
        0,
    )


async def verify_approve_active_or_failed_classify_run(client, db, test_user, monkeypatch) -> None:
    import time

    proposer = install_proposer(monkeypatch, Proposer())
    seeded = await seed_classify_statement(db, test_user)
    run_id = await classify_run_for(db, seeded.id)
    started = time.perf_counter()
    refused = await client.post(f"/statements/{seeded.id}/approvals", json={"create_account_if_missing": True})
    assert (
        refused.status_code == 409
        and refused.json()["active_run_id"] == str(run_id)
        and (time.perf_counter() - started) < 1.0
    )
    assert (await _count(db, JournalEntry), await _count(db, Account, Account.user_id == test_user.id)) == (0, 0)
    assert (await _statement(db, seeded.id)).status is BankStatementStatus.PARSED
    assert await _worker(create_session_maker_from_db(db), run_id) == 0
    response = await client.post(f"/statements/{seeded.id}/approvals", json={"create_account_if_missing": True})
    assert (response.status_code, response.json()["journal_entries_created"], proposer.rows_asked) == (200, 5, 5)

    before_entries, before_answers = await _count(db, JournalEntry), await count_user_answers(db, test_user)
    failing = install_proposer(monkeypatch, Proposer(error=RuntimeError("provider down")))
    seeded_fail = await seed_classify_statement(db, test_user)
    assert (await get_run(db, await classify_statement(db, seeded_fail.id))).state is RunState.FAILED
    fail_resp = await client.post(f"/statements/{seeded_fail.id}/approvals", json={"create_account_if_missing": True})
    assert fail_resp.status_code == 409 and fail_resp.json()["detail"].startswith("Economic review required:")
    assert (len(failing.calls), await _count(db, JournalEntry), await count_user_answers(db, test_user)) == (
        1,
        before_entries,
        before_answers,
    )


async def verify_phase_batches_release_connections(db, test_user, test_database_url, monkeypatch) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.database import create_app_engine

    monkeypatch.setattr(transaction_classification, "CLASSIFICATION_BATCH_SIZE", 2)
    monkeypatch.setattr(transaction_classification, "CLASSIFICATION_PARALLEL_BATCHES", 1)
    seeded = await seed_classify_statement(db, test_user, make_rows(6))
    gate = asyncio.Event()
    model = install_proposer(monkeypatch, ScriptedModel(None, gate))
    run_id = await classify_run_for(db, seeded.id)
    engine = create_app_engine(test_database_url, pool_size=4, max_overflow=0)
    worker = asyncio.create_task(_worker(async_sessionmaker(engine, expire_on_commit=False), run_id))
    try:
        await asyncio.wait_for(model.reached(1).wait(), timeout=WAIT_SECONDS)
        assert await _wait_until(lambda: asyncio.sleep(0, result=engine.pool.checkedout() == 0))
    finally:
        gate.set()
        await asyncio.wait_for(worker, timeout=WAIT_SECONDS)
        await engine.dispose()
    assert (await get_run(db, run_id)).state is RunState.SUCCEEDED


async def verify_two_writers_keyword_rule_serialize(db, test_user) -> None:
    from src.extraction.extension.transaction_classification import ClassificationService

    seeded = await seed_classify_statement(db, test_user)
    await add_coffee_rule(db, test_user)
    coffee = next(txn for txn in seeded.transactions if txn.description.startswith("Coffee"))
    maker = create_session_maker_from_db(db)
    async with maker() as first, maker() as second:
        rows_a = await ClassificationService().apply_rules(
            first, test_user.id, [await first.get(type(coffee), coffee.id)]
        )
        task_b = asyncio.create_task(
            ClassificationService().apply_rules(second, test_user.id, [await second.get(type(coffee), coffee.id)])
        )
        done, _ = await asyncio.wait({task_b}, timeout=0.4)
        assert not done
        await first.commit()
        rows_b = await asyncio.wait_for(task_b, timeout=WAIT_SECONDS)
        await second.commit()
    assert [r.id for r in rows_a] == [r.id for r in rows_b]


async def verify_provider_no_call_at_approve(client, db, test_user, monkeypatch) -> None:
    provider_calls: list[int] = []

    def stream_ai_json(**kwargs):
        lines = [
            json.loads(line) for line in kwargs["messages"][0]["content"].splitlines() if line.startswith('{"index"')
        ]
        provider_calls.append(len(lines))
        items = [
            {
                "index": line["index"],
                "category": EXTENDED_ANSWERS[line["description"].split()[0]][0].value,
                "confidence": EXTENDED_ANSWERS[line["description"].split()[0]][1],
                "reason": "fixture",
            }
            for line in lines
        ]

        async def stream():
            yield json.dumps(items)

        return stream()

    monkeypatch.setattr("src.llm.stream_ai_json", stream_ai_json)
    rows = make_rows(8)
    statement_id = await ingest_csv_statement(db, test_user.id, "provider.csv", rows)
    assert provider_calls == [8]
    await confirm_csv_envelope(client, db, test_user.id, statement_id, rows)
    response = await approve_statement(client, statement_id)
    assert (response.status_code, response.json()["journal_entries_created"], provider_calls) == (200, 8, [8])


async def verify_shared_rows_answered_once(db, test_user, monkeypatch) -> None:
    outcomes = spy_classify_outcomes(monkeypatch)
    gate = asyncio.Event()
    proposer = install_proposer(monkeypatch, Proposer(answers=EXTENDED_ANSWERS, timeout_gate=True, gate=gate))
    first = await seed_parsed_statement(db, test_user.id, original_filename="first.pdf", transactions=make_rows(4))
    second = await seed_parsed_statement(
        db, test_user.id, original_filename="second.pdf", transactions=make_rows(4, first_day=date(2026, 2, 1))
    )
    marker = {"doc_id": str(second.document.id), "doc_type": "bank_statement"}
    for shared in first.transactions[:2]:
        shared.source_documents = [*shared.source_documents, marker]
    await db.commit()
    sessions = create_session_maker_from_db(db)
    run_ids = [await classify_run_for(db, item.id) for item in (first, second)]
    passes = [
        asyncio.create_task(
            execute_classify_run(sessions, run_id=rid, posting_dependencies=compose_statement_posting_dependencies())
        )
        for rid in run_ids
    ]
    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    while len(proposer.calls) < 2:
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.01)
    gate.set()
    await asyncio.wait_for(asyncio.gather(*passes), timeout=WAIT_SECONDS)
    stored = await user_classification_rows(sessions, test_user.id)
    assert (outcomes, len(stored), len({r.atomic_txn_id for r in stored})) == (["classified", "classified"], 8, 8)


async def verify_unresolved_currency_and_covered_rows(client, db, test_user, monkeypatch) -> None:
    proposer = install_proposer(monkeypatch, Proposer(answers=EXTENDED_ANSWERS, timeout_gate=True))
    seeded_u = await seed_classify_statement(db, test_user.id, make_rows(4), name="u.pdf")
    unresolved = seeded_u.transactions[0]
    unresolved.currency, unresolved.currency_unresolved = "XXX", True
    await db.commit()
    await classify_statement(db, seeded_u.id)
    assert proposer.rows_asked == 3 and unresolved.description not in {d for c in proposer.calls for d in c}
    assert (
        await db.scalar(
            select(func.count()).select_from(Account).where(Account.user_id == test_user.id, Account.currency == "XXX")
        )
        == 0
    )

    proposer_c = install_proposer(monkeypatch, Proposer(answers=EXTENDED_ANSWERS, timeout_gate=True))
    seeded_c = await seed_classify_statement(db, test_user.id, make_rows(4, first_day=date(2026, 2, 1)), name="c.pdf")
    bank = Account(user_id=test_user.id, name="Bank of a covered row", type=AccountType.ASSET, currency="SGD")
    expense = Account(user_id=test_user.id, name="Expense - Reviewed", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([bank, expense])
    await db.flush()
    seeded_c.statement.account_id = bank.id
    await db.commit()
    covered = seeded_c.transactions[1]
    assert (
        await client.post(
            f"/reconciliation/unmatched/{covered.id}/reviewed-dispositions",
            json={
                "intent": "expense",
                "counter_account_id": str(expense.id),
                "category": "GENERAL",
                "rationale": "Reviewed against the source.",
            },
        )
    ).status_code == 200
    await classify_statement(db, seeded_c.id)
    assert proposer_c.rows_asked == 3 and covered.description not in {d for c in proposer_c.calls for d in c}
    assert covered.id not in {r.atomic_txn_id for r in await user_classification_rows(db, test_user.id)}


async def verify_source_bytes_released_before_model(db, test_user, monkeypatch) -> None:
    import gc

    freed: list[bool] = []
    file_is_freed: list[bool] = []

    class Payload(bytes):
        def __del__(self):
            freed.append(True)

    async def probing_proposer(transactions, _policy):
        gc.collect()
        file_is_freed.append(bool(freed))
        return [
            CategoryProposal(
                category=EXTENDED_ANSWERS[t.description.split()[0]][0].value, confidence=95, reason="fixture"
            )
            for t in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", probing_proposer)
    payload = Payload(make_csv_bytes(make_rows(3)))
    file_hash = hashlib.sha256(payload).hexdigest()
    stmt = StatementSummaryFactory.build(
        id=uuid4(), user_id=test_user.id, status=BankStatementStatus.PARSING, file_hash=file_hash, institution="DBS"
    )
    db.add(stmt)
    await db.commit()
    run = _use_case(db).execute(
        make_parse_job(stmt.id, test_user.id, "release.csv", file_hash, await run_for(db, stmt.id)), content=payload
    )
    del payload
    assert (await run).status is StatementIngestionStatus.COMPLETED and file_is_freed == [True]


async def verify_reparse_preserves_history(db, test_user, monkeypatch) -> None:
    from unittest.mock import MagicMock
    from src.extraction.extension import deduplication
    from src.extraction.extension.statement_validation import resolve_statement_transactions

    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    document, summary = await integrity_source(db, test_user.id, account=account)
    source = DocumentSource.resolve(
        path=Path(document.file_path),
        content=b"synthetic",
        content_hash=document.file_hash,
        filename=document.original_filename,
    )
    checkpoint = MagicMock()
    monkeypatch.setattr(deduplication.logger, "info", checkpoint)
    first = await integrity_parse(
        integrity_payload(), db=db, user_id=test_user.id, account_id=account.id, source=source
    )
    first_record = await integrity_store_result(db, summary, first)
    old_id = (await resolve_statement_transactions(db, summary))[0].id
    changed = integrity_payload(
        closing_balance="120",
        transactions=[
            {
                "date": "2025-01-02",
                "amount": "20",
                "direction": "IN",
                "currency": "SGD",
                "description": "Synthetic corrected deposit",
            }
        ],
    )
    second = await integrity_parse(changed, db=db, user_id=test_user.id, account_id=account.id, source=source)
    await db.refresh(summary)
    second_record = await integrity_store_result(db, summary, second)
    current = await resolve_statement_transactions(db, summary)
    assert (
        await db.get(AtomicTransaction, old_id) is not None and len(current) == 1 and current[0].amount == Decimal("20")
    )
    assert current[0].id != old_id and first.result_id != second.result_id
    assert (await db.get(StatementExtractionResultRecord, first_record.id)).payload == first.to_payload()
    assert await db.get(TraceRecordRow, first_record.source_trace_record_id) is not None
    assert summary.current_extraction_result_id == second_record.id and document.file_path == str(source.path)
    completion = [c.kwargs for c in checkpoint.call_args_list if c.args == ("Dual write to Layer 2 completed",)]
    assert completion and completion[-1]["statement_summary_id"] == str(summary.id)


async def verify_posted_cannot_be_superseded(db, test_user) -> None:
    from src.extraction import EconomicIntent
    from src.extraction.extension.review_queue import create_entry_from_txn
    from src.extraction.extension.statement_validation import resolve_statement_transactions
    from src.ledger import JournalEntryStatus
    from tests.statement_ingestion import anchored_reviewed_posting_inputs

    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    document, summary = await integrity_source(db, test_user.id, account=account)
    source = DocumentSource.resolve(
        path=Path(document.file_path), content=b"synthetic", content_hash=document.file_hash
    )
    record = await integrity_store_result(
        db,
        summary,
        await integrity_parse(integrity_payload(), db=db, user_id=test_user.id, account_id=account.id, source=source),
    )
    row = (await resolve_statement_transactions(db, summary))[0]
    decision, counter, anchor, emitter = await anchored_reviewed_posting_inputs(
        db, user_id=test_user.id, transaction=row, intent=EconomicIntent.INCOME
    )
    journal = await create_entry_from_txn(
        db,
        row,
        user_id=test_user.id,
        base_currency="SGD",
        auto_post=True,
        preloaded_bank_account=account,
        disposition=decision,
        counter_account=counter,
        source_decision=anchor,
        trace_emitter=emitter,
    )
    assert journal.status is JournalEntryStatus.POSTED
    replacement = integrity_payload(
        closing_balance="120",
        transactions=[
            {
                "date": "2025-01-02",
                "amount": "20",
                "direction": "IN",
                "currency": "SGD",
                "description": "Synthetic corrected deposit",
            }
        ],
    )
    with pytest.raises(ExtractionError, match="posted.*review|review.*posted"):
        await integrity_parse(replacement, db=db, user_id=test_user.id, account_id=account.id, source=source)
    await db.refresh(summary)
    assert (
        summary.current_extraction_result_id == record.id
        and (await resolve_statement_transactions(db, summary))[0].id == row.id
    )
    assert (
        await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)) == 1
    )


async def verify_multicurrency_pdf_batches(db, test_user) -> None:
    from src.extraction.extension.statement_validation import resolve_statement_transactions

    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    output = BytesIO()
    pdf = canvas.Canvas(output)
    for page in range(6):
        pdf.drawString(72, 720, f"Synthetic statement page {page + 1}")
        pdf.showPage()
    pdf.save()
    meta = {
        "institution": "Synthetic Bank",
        "account_last4": "0001",
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100",
        "closing_balance": "110",
        "balances": [
            {"currency": "SGD", "opening": "100", "closing": "110"},
            {"currency": "USD", "opening": "200", "closing": "200"},
            {"currency": "EUR", "opening": "300", "closing": "320"},
        ],
    }
    first = integrity_payload(
        balances=[
            {"currency": "SGD", "opening": "100", "closing": "110"},
            {"currency": "USD", "opening": "200", "closing": "200"},
        ]
    )
    second = {
        "balances": [{"currency": "EUR", "opening": "300", "closing": "320"}],
        "transactions": [
            {
                "date": "2025-01-03",
                "amount": "20",
                "currency": "EUR",
                "direction": "IN",
                "description": "Synthetic EUR deposit",
            }
        ],
    }
    service = ExtractionService()
    service.api_key = "synthetic-provider-key"
    service._extract_json_with_model = AsyncMock(side_effect=[meta, first, second])
    source = DocumentSource.resolve(path=Path("synthetic/multicurrency.pdf"), content=output.getvalue())
    result = await service.parse_document(
        source, user_id=test_user.id, account_id=account.id, db=db, force_model="synthetic-vision"
    )
    summary = await db.scalar(
        select(StatementSummary).where(
            StatementSummary.file_hash == source.content_hash, StatementSummary.user_id == test_user.id
        )
    )
    assert result.balance_validated is True and {b.currency for b in result.balances} == {"SGD", "USD", "EUR"}
    assert (
        len(await resolve_statement_transactions(db, summary)) == 2
        and service._extract_json_with_model.await_count == 3
    )


async def verify_membership_excludes_ambiguous_and_superseded(db, test_user) -> None:
    from src.extraction.extension.statement_validation import resolve_statement_transactions

    a1, a2 = (
        AccountFactory.build(user_id=test_user.id, currency="SGD"),
        AccountFactory.build(user_id=test_user.id, currency="SGD"),
    )
    db.add_all([a1, a2])
    await db.flush()
    d1, s1 = await integrity_source(db, test_user.id, account=a1)
    d2, s2 = await integrity_source(db, test_user.id, account=a2)
    legacy = await integrity_legacy_txn(db, test_user.id, d1)
    legacy.source_documents = [*legacy.source_documents, {"doc_id": str(d2.id), "doc_type": "bank_statement"}]
    payload = (await integrity_parse(integrity_payload())).to_payload()
    payload["transactions"][0]["fact_id"] = legacy.dedup_hash
    for s in (s1, s2):
        s.extraction_metadata = {"statement_extraction_result": payload}
    await db.flush()
    assert all([legacy.id not in await effective_txn_ids(db, test_user.id, scope) for scope in (None, s1.id, s2.id)])

    source = DocumentSource.resolve(path=Path(d1.file_path), content=b"synthetic", content_hash=d1.file_hash)
    await integrity_store_result(
        db, s1, await integrity_parse(integrity_payload(), db=db, user_id=test_user.id, account_id=a1.id, source=source)
    )
    old_id = (await resolve_statement_transactions(db, s1))[0].id
    changed = integrity_payload(
        closing_balance="120",
        transactions=[
            {
                "date": "2025-01-02",
                "amount": "20",
                "direction": "IN",
                "currency": "SGD",
                "description": "Synthetic correction",
            }
        ],
    )
    await integrity_store_result(
        db, s1, await integrity_parse(changed, db=db, user_id=test_user.id, account_id=a1.id, source=source)
    )
    new_id = (await resolve_statement_transactions(db, s1))[0].id
    assert all(
        [
            new_id in (ids := await effective_txn_ids(db, test_user.id, scope)) and old_id not in ids
            for scope in (None, s1.id)
        ]
    )
    assert not await effective_txn_ids(db, uuid4())
    standalone = await integrity_legacy_txn(
        db, test_user.id, type("Source", (), {"id": uuid4()})(), description="Synthetic standalone"
    )
    assert standalone.id in await effective_txn_ids(db, test_user.id)


async def verify_identity_rejection_case(db, test_user, failure: str) -> None:
    from src.extraction.extension.transaction_identity import (
        TransactionIdentityReviewRequired,
        resolve_transaction_identity,
        source_custody_scope,
        versioned_transaction_hash,
    )
    from src.extraction.orm.layer2 import AtomicTransactionIdentity
    from tests.factories import UserFactory

    account = await AccountFactory.create_async(db, user_id=test_user.id, currency="SGD")
    document, summary = await integrity_source(db, test_user.id, account=account)
    old = await integrity_legacy_txn(db, test_user.id, document)
    original = (old.id, old.dedup_hash)
    if failure in {"foreign_document", "changed_account", "missing_account"}:
        uid = (await UserFactory.create_async(db)).id if failure == "foreign_document" else test_user.id
        if failure == "missing_account":
            summary.account_id = None
            await db.flush()
        with pytest.raises((ValueError, TransactionIdentityReviewRequired)):
            await source_custody_scope(db, user_id=uid, document_id=document.id, account_id=uuid4())
    else:
        if failure == "malformed_lineage":
            old.source_documents = [{"doc_id": "invalid"}]
        elif failure == "currency_conflict":
            summary.currency = "USD"
        elif failure == "missing_custody":
            summary.account_id = None
        if failure == "inconsistent_alias":
            db.add(
                AtomicTransactionIdentity(
                    user_id=test_user.id,
                    identity_version="v2",
                    identity_hash=versioned_transaction_hash(old.dedup_hash, "SGD", f"account:{account.id}"),
                    legacy_hash=old.dedup_hash,
                    atomic_txn_id=old.id,
                    currency="USD",
                    custody_scope=f"account:{account.id}",
                )
            )
        await db.flush()
        if failure == "different_currency":
            assert (
                await resolve_transaction_identity(
                    db,
                    user_id=test_user.id,
                    legacy_hash=old.dedup_hash,
                    currency="USD",
                    custody_scope=f"account:{account.id}",
                )
            )[1] is None
        else:
            with pytest.raises(TransactionIdentityReviewRequired):
                await resolve_transaction_identity(
                    db,
                    user_id=test_user.id,
                    legacy_hash=old.dedup_hash,
                    currency="SGD",
                    custody_scope=f"account:{account.id}",
                )
    assert (old.id, old.dedup_hash) == original


async def verify_concurrent_first_custody_imports(db_engine) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.extraction.orm.bank_custody_binding import BankCustodyBinding
    from tests.factories import UserFactory

    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        uid = (await UserFactory.create_async(db, email=f"custody-race-{uuid4()}@example.invalid")).id
        await db.execute(
            text(
                "CREATE FUNCTION custody_test_delay() RETURNS trigger AS $$ BEGIN PERFORM pg_sleep(0.1); RETURN NEW; END; $$ LANGUAGE plpgsql"
            )
        )
        await db.execute(
            text(
                "CREATE TRIGGER custody_test_delay BEFORE INSERT ON accounts FOR EACH ROW EXECUTE FUNCTION custody_test_delay()"
            )
        )
        await db.commit()

    async def first():
        async with sessions() as db:
            return (await custody_parse(db, uid)).account_id

    try:
        ids = await asyncio.gather(first(), first())
        assert ids[0] == ids[1]
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Account).where(Account.user_id == uid)) == 1
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    db.add(
                        BankCustodyBinding(
                            user_id=uid, institution="DBS", account_last4="2468", currency="SGD", account_id=ids[0]
                        )
                    )
                    await db.flush()
    finally:
        async with sessions() as db:
            await db.execute(text("DROP TRIGGER custody_test_delay ON accounts"))
            await db.execute(text("DROP FUNCTION custody_test_delay()"))
            await db.commit()


async def verify_real_custody_migration(db, test_user) -> None:
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from src.extraction.extension.custody_binding import resolve_bank_custody
    from src.extraction.orm.bank_custody_binding import BankCustodyBinding

    await db.execute(text("DROP TABLE bank_custody_bindings"))
    spec = importlib.util.spec_from_file_location(
        "custody_migration", BACKEND_DIR / "migrations/versions/0062_bank_custody.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    await db.run_sync(
        lambda s: (
            setattr(migration, "op", Operations(MigrationContext.configure(s.connection()))),
            migration.upgrade(),
        )
    )
    allocation = await resolve_bank_custody(
        db, user_id=test_user.id, institution="DBS", account_last4="2468", currency="SGD"
    )
    await db.commit()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                BankCustodyBinding(
                    user_id=test_user.id,
                    institution="DBS",
                    account_last4="2468",
                    currency="SGD",
                    account_id=allocation.account.id,
                )
            )
            await db.flush()
    for stmt, tid in (
        ("DELETE FROM accounts WHERE id = :id", allocation.account.id),
        ("DELETE FROM users WHERE id = :id", test_user.id),
    ):
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(text(stmt), {"id": tid})
    assert await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")) == 1
    with pytest.raises(RuntimeError, match="verified pre-upgrade backup"):
        migration.downgrade()


async def verify_historical_custody_adoption_case(db, test_user, condition: str) -> None:
    from sqlalchemy.exc import IntegrityError
    from tests.factories import UserFactory

    owner = (
        await UserFactory.create_async(db, email=f"custody-foreign-{uuid4()}@example.invalid")
        if condition == "foreign"
        else test_user
    )
    account = AccountFactory.build(user_id=owner.id, name="Renamed historical account", currency="SGD")
    db.add(account)
    await db.flush()
    if condition == "foreign":
        with pytest.raises(IntegrityError, match="cross-user account"):
            async with db.begin_nested():
                await custody_history(db, test_user.id, account)
        return
    await custody_history(db, test_user.id, account, corrupt=condition in {"source_mismatch", "source_original"})
    if condition == "ambiguous":
        second = AccountFactory.build(user_id=test_user.id, currency="SGD")
        db.add(second)
        await db.flush()
        await custody_history(db, test_user.id, second)
    if condition == "unique":
        assert (await custody_parse(db, test_user.id)).account_id == account.id
    else:
        with pytest.raises(ExtractionError, match="[Hh]istorical|[Aa]mbiguous"):
            await custody_parse(db, test_user.id, account_last4="9999" if condition == "source_mismatch" else "2468")


async def verify_invalid_custody_evidence_case(db, test_user, failure: str) -> None:
    from src.extraction.extension.custody_binding import resolve_bank_custody

    account = await AccountFactory.create_async(db, user_id=test_user.id, currency="SGD")
    summary = await custody_history(db, test_user.id, account)
    if failure == "missing_document":
        summary.uploaded_document_id = None
    elif failure == "brokerage_document":
        (await db.get(UploadedDocument, summary.uploaded_document_id)).document_type = DocumentType.BROKERAGE_STATEMENT
    elif failure in {"invalid_payload", "source_digest", "payload_digest"}:
        orig = await db.get(StatementExtractionResultRecord, summary.current_extraction_result_id)
        rep = StatementExtractionResultRecord(
            user_id=test_user.id,
            statement_id=summary.id,
            content_digest="a" * 64,
            source_content_digest="b" * 64 if failure == "source_digest" else orig.source_content_digest,
            schema_version=orig.schema_version,
            producer_version=orig.producer_version,
            payload={} if failure == "invalid_payload" else orig.payload,
            source_trace_record_id=orig.source_trace_record_id,
            created_at=datetime.now(UTC),
        )
        db.add(rep)
        await db.flush()
        summary.current_extraction_result_id = rep.id
    elif failure == "archived_account":
        account.is_active = False
    await db.flush()
    explicit = (
        await AccountFactory.create_async(db, user_id=test_user.id, currency="SGD")
        if failure == "explicit_conflict"
        else None
    )
    with pytest.raises(ExtractionError):
        await resolve_bank_custody(
            db,
            user_id=test_user.id,
            institution="" if failure == "missing_identity" else "DBS",
            account_last4="2468",
            currency="SGD",
            account_id=explicit.id if explicit else None,
        )


async def verify_reconcile_chain_out_of_order(db, test_user) -> None:
    from src.extraction.base.types import RetireStatementCommand
    from src.extraction.extension.source_lifecycle import retire_statement
    from src.extraction.extension.statement_posting import (
        reconcile_account_statement_chain,
        try_auto_post_statement_opening_balance,
    )
    from src.ledger import calculate_account_balance
    from src.ledger.extension.account_service import get_or_create_unexplained_gap_equity_account

    account, income = (
        Account(user_id=test_user.id, name="DBS Multiplier", type=AccountType.ASSET, currency="SGD"),
        Account(user_id=test_user.id, name="Salary Income", type=AccountType.INCOME, currency="SGD"),
    )
    db.add_all([account, income])
    await db.flush()
    stmt_jun = await make_approved_statement(
        db,
        test_user.id,
        account.id,
        opening="15000.00",
        closing="18000.00",
        start=date(2025, 6, 1),
        end=date(2025, 6, 30),
    )
    await post_system_entry(
        db,
        test_user.id,
        debit_id=account.id,
        credit_id=income.id,
        amount="3000.00",
        entry_date=date(2025, 6, 15),
        memo="June salary",
        operation="test-june-txn",
    )
    await try_auto_post_statement_opening_balance(db, stmt_jun, test_user.id, base_currency="SGD")
    await assert_bs_asset(
        db,
        test_user.id,
        as_of_date=date(2025, 6, 30),
        currency="SGD",
        account_id=account.id,
        expected=Decimal("18000.00"),
    )
    stmt_jan = await make_approved_statement(
        db,
        test_user.id,
        account.id,
        opening="10000.00",
        closing="12000.00",
        start=date(2025, 1, 1),
        end=date(2025, 1, 31),
    )
    await post_system_entry(
        db,
        test_user.id,
        debit_id=account.id,
        credit_id=income.id,
        amount="2000.00",
        entry_date=date(2025, 1, 15),
        memo="Jan salary",
        operation="test-jan-txn",
    )
    await try_auto_post_statement_opening_balance(db, stmt_jan, test_user.id, base_currency="SGD")
    for anchor_date, expected in (
        (date(2025, 1, 1), Decimal("10000.00")),
        (date(2025, 1, 31), Decimal("12000.00")),
        (date(2025, 6, 1), Decimal("15000.00")),
        (date(2025, 6, 30), Decimal("18000.00")),
    ):
        await assert_bs_asset(
            db, test_user.id, as_of_date=anchor_date, currency="SGD", account_id=account.id, expected=expected
        )
    gap_equity = await get_or_create_unexplained_gap_equity_account(db, test_user.id, "SGD")
    assert await calculate_account_balance(db, gap_equity.id, test_user.id) == Decimal("3000.00")
    stmt_feb = await make_approved_statement(
        db,
        test_user.id,
        account.id,
        opening="12000.00",
        closing="13200.00",
        start=date(2025, 2, 1),
        end=date(2025, 2, 28),
    )
    await post_system_entry(
        db,
        test_user.id,
        debit_id=account.id,
        credit_id=income.id,
        amount="1200.00",
        entry_date=date(2025, 2, 15),
        memo="Feb salary",
        operation="test-feb-txn",
    )
    await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=account.id, base_currency="SGD")
    assert await calculate_account_balance(db, gap_equity.id, test_user.id) == Decimal("1800.00")
    await assert_bs_asset(
        db,
        test_user.id,
        as_of_date=date(2025, 2, 28),
        currency="SGD",
        account_id=account.id,
        expected=Decimal("13200.00"),
    )
    await assert_bs_asset(
        db,
        test_user.id,
        as_of_date=date(2025, 6, 30),
        currency="SGD",
        account_id=account.id,
        expected=Decimal("18000.00"),
    )
    await retire_statement(
        db, RetireStatementCommand(statement_id=stmt_feb.id, user_id=test_user.id), base_currency="SGD"
    )
    await assert_bs_asset(
        db,
        test_user.id,
        as_of_date=date(2025, 6, 1),
        currency="SGD",
        account_id=account.id,
        expected=Decimal("15000.00"),
    )
    assert await calculate_account_balance(db, account.id, test_user.id) == Decimal("18000.00")


async def verify_reconcile_chain_retirement_and_fx(db, test_user) -> None:
    from src.extraction.extension.statement_posting import (
        reconcile_account_statement_chain,
        release_statement_ledger_effects,
    )
    from src.pricing import PricingError

    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=uuid4(), base_currency="SGD")
        is False
    )
    usd_acc, sgd_acc = (
        Account(user_id=test_user.id, name="USD Custody", type=AccountType.ASSET, currency="USD"),
        Account(user_id=test_user.id, name="SGD Custody", type=AccountType.ASSET, currency="SGD"),
    )
    db.add_all([usd_acc, sgd_acc])
    await db.flush()
    await make_approved_statement(
        db,
        test_user.id,
        usd_acc.id,
        last4="1234",
        currency="USD",
        opening="1000.00",
        closing="1000.00",
        start=date(2025, 1, 1),
        end=date(2025, 1, 31),
    )
    await make_approved_statement(
        db,
        test_user.id,
        usd_acc.id,
        last4="1234",
        currency="USD",
        opening="1500.00",
        closing="1500.00",
        start=date(2025, 3, 1),
        end=date(2025, 3, 31),
    )
    deps_fail = replace(
        compose_statement_posting_dependencies(),
        fx_rate_provider=AsyncMock(side_effect=[Decimal("1.35"), ValueError("No plug FX")]),
        fx_rate_error=ValueError,
    )
    with pytest.raises(ValueError, match="FX rate required for cross-period gap plug in USD"):
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=usd_acc.id, dependencies=deps_fail)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.pricing.get_exchange_rate", AsyncMock(side_effect=PricingError("No rate")))
        with pytest.raises(ValueError, match="FX rate required for cross-period gap plug in USD"):
            await reconcile_account_statement_chain(
                db, user_id=test_user.id, account_id=usd_acc.id, dependencies=None, base_currency="SGD"
            )
    deps_ok = replace(
        compose_statement_posting_dependencies(),
        fx_rate_provider=AsyncMock(return_value=Decimal("1.35")),
        fx_rate_error=ValueError,
    )
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=usd_acc.id, dependencies=deps_ok)
        is True
    )
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=usd_acc.id, dependencies=deps_ok)
        is False
    )
    s_jan = await make_approved_statement(
        db,
        test_user.id,
        sgd_acc.id,
        last4="5678",
        opening="1000.00",
        closing="1000.00",
        start=date(2025, 1, 1),
        end=date(2025, 1, 31),
    )
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=sgd_acc.id, base_currency="SGD")
        is True
    )
    s_jan.status = BankStatementStatus.RETIRED
    s_mar = await make_approved_statement(
        db,
        test_user.id,
        sgd_acc.id,
        last4="5678",
        opening="1500.00",
        closing="1500.00",
        start=date(2025, 3, 1),
        end=date(2025, 3, 31),
    )
    s_may = await make_approved_statement(
        db,
        test_user.id,
        sgd_acc.id,
        last4="5678",
        opening="2000.00",
        closing="2000.00",
        start=date(2025, 5, 1),
        end=date(2025, 5, 31),
    )
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=sgd_acc.id, base_currency="SGD")
        is True
    )
    s_mar.status = s_may.status = BankStatementStatus.RETIRED
    await db.flush()
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=sgd_acc.id, base_currency="SGD")
        is True
    )
    assert (
        await release_statement_ledger_effects(
            db, s_mar, test_user.id, was_approved=True, reason="Statement retired", dependencies=None
        )
        == 0
    )


async def verify_manual_override_and_lifecycle_guards(db, test_user) -> None:
    from src.extraction.extension.statement_posting import reconcile_account_statement_chain
    from src.extraction.extension.statement_workflow import reject_statement_workflow
    from src.ledger import calculate_account_balance, list_opening_positions
    from src.ledger.extension.account_service import get_or_create_unexplained_gap_equity_account

    acc = Account(user_id=test_user.id, name="OCBC 360", type=AccountType.ASSET, currency="SGD")
    db.add(acc)
    await db.flush()
    stmt_manual = await make_approved_statement(
        db,
        test_user.id,
        acc.id,
        institution="OCBC",
        last4="1111",
        opening="2000.00",
        manual_opening="2500.00",
        closing="2500.00",
        start=date(2025, 1, 1),
        end=date(2025, 1, 31),
    )
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=acc.id, base_currency="SGD")
        is True
    )
    assert await calculate_account_balance(db, acc.id, test_user.id) == Decimal("2500.00")
    await reject_statement_workflow(
        db, stmt_manual.id, test_user.id, reason="Dormant statement rejected", base_currency="SGD"
    )
    assert (
        await calculate_account_balance(db, acc.id, test_user.id) == Decimal("0.00")
        and len(await list_opening_positions(db, user_id=test_user.id, as_of=date.max)) == 0
    )
    stmt_mar = await make_approved_statement(
        db,
        test_user.id,
        acc.id,
        institution="OCBC",
        last4="1111",
        opening="4000.00",
        closing="4000.00",
        start=date(2025, 3, 1),
        end=date(2025, 3, 31),
    )
    await make_approved_statement(
        db,
        test_user.id,
        acc.id,
        institution="OCBC",
        last4="1111",
        opening="5000.00",
        closing="5000.00",
        start=date(2025, 6, 1),
        end=date(2025, 6, 30),
    )
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=acc.id, base_currency="SGD")
        is True
    )
    gap_eq = await get_or_create_unexplained_gap_equity_account(db, test_user.id, "SGD")
    assert await calculate_account_balance(db, gap_eq.id, test_user.id) == Decimal("1000.00")
    stmt_mar.status = BankStatementStatus.RETIRED
    await db.flush()
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=acc.id, base_currency="SGD")
        is True
    )
    assert (
        await calculate_account_balance(db, gap_eq.id, test_user.id),
        await calculate_account_balance(db, acc.id, test_user.id),
    ) == (Decimal("0.00"), Decimal("5000.00"))


async def verify_foreign_currency_opening_and_retire(db, test_user) -> None:
    from src.extraction.base.types import RetireStatementCommand
    from src.extraction.extension.source_lifecycle import retire_statement
    from src.extraction.extension.statement_posting import reconcile_account_statement_chain
    from src.ledger import calculate_account_balance
    from src.ledger.extension.account_service import (
        get_or_create_opening_balance_equity_account,
        get_or_create_unexplained_gap_equity_account,
    )
    from src.pricing import FxRate

    db.add_all(
        [
            FxRate(base_currency=b, quote_currency=q, rate=Decimal(r), rate_date=d, source="test")
            for b, q, r, d in (
                ("CNY", "SGD", "0.188304", date(2024, 1, 1)),
                ("CNY", "SGD", "0.190000", date(2024, 2, 1)),
                ("CNY", "SGD", "0.192490", date(2024, 2, 28)),
                ("SGD", "CNY", "5.195075", date(2024, 2, 28)),
                ("CNY", "SGD", "0.195000", date(2024, 3, 1)),
                ("CNY", "SGD", "0.195000", date(2024, 3, 31)),
            )
        ]
    )
    cny_bank, cny_exp = (
        Account(user_id=test_user.id, name="CMB Savings", type=AccountType.ASSET, currency="CNY"),
        Account(user_id=test_user.id, name="CNY Dining", type=AccountType.EXPENSE, currency="CNY"),
    )
    doc_jan, doc_mar = (
        UploadedDocument(
            user_id=test_user.id,
            file_path=f"statements/{n}.pdf",
            file_hash=f"{n}_hash_2851",
            original_filename=f"{n}.pdf",
            document_type=DocumentType.BANK_STATEMENT,
            status=DocumentStatus.COMPLETED,
        )
        for n in ("cmb_jan", "cmb_mar")
    )
    db.add_all([cny_bank, cny_exp, doc_jan, doc_mar])
    await db.flush()
    stmt_jan = await make_approved_statement(
        db,
        test_user.id,
        cny_bank.id,
        uploaded_document_id=doc_jan.id,
        institution="CMB",
        currency="CNY",
        opening="38500.00",
        closing="38000.00",
        start=date(2024, 1, 1),
        end=date(2024, 2, 28),
    )
    await make_approved_statement(
        db,
        test_user.id,
        cny_bank.id,
        uploaded_document_id=doc_mar.id,
        institution="CMB",
        currency="CNY",
        opening="40000.00",
        closing="40000.00",
        start=date(2024, 3, 1),
        end=date(2024, 3, 31),
    )
    txn_jan = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date(2024, 2, 1),
        amount=Decimal("500.00"),
        direction="OUT",
        description="Hotpot Dinner",
        currency="CNY",
        dedup_hash="cmb_jan_txn_2851",
        source_documents=[{"doc_id": str(doc_jan.id), "doc_type": "bank_statement"}],
    )
    db.add(txn_jan)
    await db.flush()
    await post_system_entry(
        db,
        test_user.id,
        debit_id=cny_exp.id,
        credit_id=cny_bank.id,
        amount="500.00",
        entry_date=date(2024, 2, 1),
        memo="Hotpot Dinner",
        currency="CNY",
        fx_rate=Decimal("0.190000"),
        source_type=JournalEntrySourceType.AUTO_PARSED,
        source_id=txn_jan.id,
    )
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=cny_bank.id, base_currency="SGD")
        is True
    )
    obe = await get_or_create_opening_balance_equity_account(db, test_user.id, "CNY", match_currency=True)
    assert (obe.currency, await calculate_account_balance(db, obe.id, test_user.id)) == ("CNY", Decimal("38500.00"))
    bs_cny = await generate_balance_sheet(
        db, test_user.id, as_of_date=date(2024, 2, 28), currency="CNY", base_currency="SGD"
    )
    assert (
        bs_cny["is_balanced"],
        bs_cny["total_assets"],
        bs_cny["total_equity"],
        bs_cny["net_income"],
        bs_cny["unrealized_fx_gain_loss"],
        bs_cny["cta_adjustment"],
        [line["name"] for line in bs_cny["equity"]],
    ) == (
        True,
        Decimal("38000.00"),
        Decimal("38500.00"),
        Decimal("-500.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        ["Opening Balance Equity"],
    )
    assert (
        await retire_statement(
            db, RetireStatementCommand(statement_id=stmt_jan.id, user_id=test_user.id), base_currency="SGD"
        )
    ).status == BankStatementStatus.RETIRED
    gap_eq = await get_or_create_unexplained_gap_equity_account(db, test_user.id, "CNY")
    assert (
        await calculate_account_balance(db, gap_eq.id, test_user.id),
        await calculate_account_balance(db, cny_bank.id, test_user.id),
    ) == (Decimal("0.00"), Decimal("40000.00"))
    bs_mar = await generate_balance_sheet(
        db, test_user.id, as_of_date=date(2024, 3, 31), currency="CNY", base_currency="SGD"
    )
    assert (
        bs_mar["is_balanced"],
        bs_mar["total_assets"],
        bs_mar["total_equity"],
        [line["name"] for line in bs_mar["equity"]],
    ) == (True, Decimal("40000.00"), Decimal("40000.00"), ["Opening Balance Equity"])


async def verify_two_sessions_share_identity_and_result(db, db_engine, test_user) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.extraction.extension.source_lifecycle import resolve_source_identity

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    command = lifecycle_identity(test_user.id, file_hash="concurrent-source-identity")

    async def id_work(session, barrier):
        await barrier()
        doc, created = await resolve_source_identity(session, command)
        await session.commit()
        return doc.id, created

    first, second = await run_two_session_barrier(maker, id_work)
    assert first[0] == second[0] and sorted((first[1], second[1])) == [False, True]
    async with maker() as v:
        assert (
            await v.scalar(
                select(func.count())
                .select_from(UploadedDocument)
                .where(UploadedDocument.user_id == test_user.id, UploadedDocument.file_hash == command.file_hash)
            )
            == 1
        )
    statement = lifecycle_summary(test_user.id, file_hash="concurrent-result-identity")
    db.add(statement)
    await db.commit()
    result = lifecycle_source_result("4" * 64)

    async def res_work(session, barrier):
        owned = await session.get(StatementSummary, statement.id)
        assert owned is not None
        await barrier()
        rec = await persist_statement_extraction_result(
            session, statement=owned, result=result, source_trace_record_id=uuid4()
        )
        await session.commit()
        return rec.id

    rids = await run_two_session_barrier(maker, res_work)
    assert rids[0] == rids[1]
    async with maker() as v:
        assert (
            await v.scalar(
                select(func.count())
                .select_from(StatementExtractionResultRecord)
                .where(
                    StatementExtractionResultRecord.statement_id == statement.id,
                    StatementExtractionResultRecord.content_digest == result.content_digest,
                )
            )
            == 1
        )


async def verify_failure_and_retry_convergence(db, db_engine, test_user, monkeypatch) -> None:
    from fastapi import UploadFile
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from src.extraction import get_known_storage_paths
    from src.extraction.extension.source_lifecycle import RetireStatementCommand, retire_statement
    from src.platform import DomainError
    from src.request_context import RequestContext
    from src.routers import statements as statements_router
    from src.runtime import StorageError
    from src.runtime.extension import storage_sweep

    statement, _ = await lifecycle_history_fixture(db, test_user.id)
    await db.commit()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    cmd = RetireStatementCommand(statement_id=statement.id, user_id=test_user.id)
    async with maker() as failed:
        await retire_statement(failed, cmd, base_currency="SGD")
        await failed.flush()
        await failed.rollback()
    async with maker() as verification:
        assert (await verification.get(StatementSummary, statement.id)).status is BankStatementStatus.PARSED
    for _ in range(2):
        async with maker() as s:
            await retire_statement(s, cmd, base_currency="SGD")
            await s.commit()
    async with maker() as v:
        assert (
            await v.scalar(
                select(func.count()).select_from(StatementSummary).where(StatementSummary.id == statement.id)
            )
            == 1
        )

    class FailingThenRecoveringStorage:
        def __init__(self) -> None:
            self.keys, self.delete_attempts = set(), 0

        def upload_bytes(self, *, key: str, **_kwargs) -> None:
            self.keys.add(key)

        def delete_object(self, key: str) -> None:
            self.delete_attempts += 1
            if self.delete_attempts == 1:
                raise StorageError("immediate cleanup unavailable")
            self.keys.remove(key)

    storage = FailingThenRecoveringStorage()
    monkeypatch.setattr(statements_router, "StorageService", lambda: storage)
    orig_commit = db.commit
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("database commit unavailable")))
    upload = UploadFile(filename="failure-convergence.pdf", file=BytesIO(b"source bytes"))
    with pytest.raises(DomainError) as exc:
        await statements_router.upload_statement(
            file=upload, institution="Example Bank", model=None, ctx=RequestContext(db, test_user.id)
        )
    await upload.close()
    assert (exc.value.status_code, storage.delete_attempts, len(storage.keys)) == (500, 1, 1)
    orphan_key = next(iter(storage.keys))
    monkeypatch.setattr(db, "commit", orig_commit)
    assert (
        await db.scalar(
            select(func.count()).select_from(UploadedDocument).where(UploadedDocument.file_path == orphan_key)
        )
        == 0
    )

    class SessionCtx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(storage_sweep, "StorageService", lambda: storage)
    monkeypatch.setattr(
        storage_sweep, "_list_storage_keys", lambda _s: [(orphan_key, datetime.now(UTC) - timedelta(hours=2))]
    )
    monkeypatch.setattr(storage_sweep.settings, "s3_bucket", "acceptance")
    monkeypatch.setattr(storage_sweep.settings, "storage_sweep_grace_period_hours", 1)
    assert (
        await storage_sweep.sweep_orphaned_storage_objects(
            sessionmaker=lambda: SessionCtx(), known_paths_provider=get_known_storage_paths
        )
        == 1
    )
    assert storage.keys == set()


async def verify_counterfactual_404_matrix(db, test_user) -> None:
    from src.extraction.extension.source_lifecycle import RetireStatementCommand, retire_statement
    from src.extraction.extension.statement_validation import _raise_if_balance_chain_invalid, validate_balance_chain
    from src.platform import DomainError
    from src.request_context import RequestContext
    from src.routers import statements as statements_router
    from src.routers.reconciliation import run_reconciliation, run_stage2_checks
    from src.routers.statements import get_review_conflicts
    from src.schemas.reconciliation import ConsistencyCheckRunRequest, ReconciliationRunRequest

    document = lifecycle_document(test_user.id, file_hash="orphan-currency-counterfactual")
    db.add(document)
    await db.flush()
    statement = lifecycle_summary(test_user.id, file_hash=document.file_hash, uploaded_document_id=document.id)
    statement.currency_balances = [{"currency": "SGD", "opening": "0.00", "closing": "0.00"}]
    db.add(statement)
    db.add(
        lifecycle_atomic(test_user.id, document.id, currency="USD", direction=TransactionDirection.IN, amount="1.00")
    )
    await db.flush()
    validation = await validate_balance_chain(db, statement.id)
    assert next(r for r in validation["per_currency"] if r["currency"] == "USD")["declared_balance"] is False
    with pytest.raises(ValueError, match="currency"):
        _raise_if_balance_chain_invalid(validation)
    await retire_statement(
        db, RetireStatementCommand(statement_id=statement.id, user_id=test_user.id), base_currency="SGD"
    )
    await db.commit()
    ctx = RequestContext(db, test_user.id)
    for call in (
        statements_router.get_statement(statement.id, ctx),
        get_review_conflicts(statement.id, ctx),
        run_stage2_checks(ConsistencyCheckRunRequest(statement_id=statement.id), ctx),
        run_reconciliation(ReconciliationRunRequest(statement_id=statement.id), ctx=ctx),
    ):
        with pytest.raises(DomainError) as exc:
            await call
        assert exc.value.status_code == 404


def verify_no_classify_writer_uninvoked(backend_src: Path, module_path: Path) -> None:
    import ast

    seam_mod = "src.extraction.extension.transaction_classification"
    seams = (
        "plan_classification",
        "write_rule_answers",
        "ask_model",
        "write_answers",
        "settle_drafts",
        "apply_user_transaction_correction",
    )
    external_calls: set[str] = set()
    model_callers: dict[str, set[str]] = {}
    for path in backend_src.rglob("*.py"):
        text_src = path.read_text(encoding="utf-8")
        if path != module_path and any(s in text_src for s in seams):
            tree = ast.parse(text_src)
            aliases = {
                a.asname or a.name: a.name
                for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module in (seam_mod, "src.extraction")
                for a in n.names
                if a.name in seams
            }
            mods = {
                (a.asname or a.name).split(".")[0]
                for n in ast.walk(tree)
                if isinstance(n, ast.Import)
                for a in n.names
                if a.name == seam_mod
            }
            for n in ast.walk(tree):
                if isinstance(n, ast.Call):
                    if isinstance(n.func, ast.Name) and n.func.id in aliases:
                        external_calls.add(aliases[n.func.id])
                    elif (
                        isinstance(n.func, ast.Attribute)
                        and n.func.attr in seams
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id in mods
                    ):
                        external_calls.add(n.func.attr)
        if any(name in text_src for name in ("ask_model", "propose_categories", "_propose_batch")):
            for n in ast.walk(ast.parse(text_src)):
                if isinstance(n, ast.Call):
                    called = (
                        n.func.id
                        if isinstance(n.func, ast.Name)
                        else n.func.attr
                        if isinstance(n.func, ast.Attribute)
                        else None
                    )
                    if called in ("ask_model", "propose_categories", "_propose_batch"):
                        model_callers.setdefault(path.name, set()).add(called)
    assert not [w for w in seams if w not in external_calls]
    assert model_callers == {
        "statement_classification_run.py": {"ask_model"},
        "transaction_classification.py": {"propose_categories", "_propose_batch"},
    }


async def verify_existing_and_rejected_drafts(db, test_user) -> None:
    from tests.statement_ingestion import classify_transactions

    v2 = transaction_classification.POLICY_VERSIONS[-1]
    txn = await make_txn(db, test_user)
    row = await draft_via_review_path(db, test_user, txn, "DINING", 70)
    elsewhere = await make_txn(db, test_user)
    elsewhere_draft = await draft_via_review_path(db, test_user, elsewhere, "DINING", 70)
    assert "auto_accepted" not in row.tags
    await classify_transactions(db, test_user.id, [txn], policy=v2, proposer=constant_proposer("DINING", 70))
    await db.refresh(row)
    await db.refresh(elsewhere_draft)
    assert (row.status, row.tags["auto_accepted"], elsewhere_draft.status) == (
        ClassificationStatus.APPLIED,
        True,
        ClassificationStatus.DRAFT,
    )

    rejected = await make_txn(db, test_user)
    await classify_transactions(db, test_user.id, [rejected], policy=v2, proposer=constant_proposer("DINING", 70))
    rej_row = await txn_classification(db, rejected)
    rej_row.status, rej_row.tags = ClassificationStatus.SUPERSEDED, {**rej_row.tags, "rejected_by_user": True}
    await db.flush()
    await classify_transactions(db, test_user.id, [rejected], policy=v2, proposer=constant_proposer("DINING", 70))
    await db.refresh(rej_row)
    assert rej_row.status is ClassificationStatus.SUPERSEDED


async def verify_classified_rows_not_asked_again(db, test_user) -> None:
    from tests.statement_ingestion import classify_transactions

    v2 = transaction_classification.POLICY_VERSIONS[-1]
    answered, unanswered = (
        await make_txn(db, test_user, description="ANSWERED"),
        await make_txn(db, test_user, description="UNANSWERED"),
    )
    asked: list[list[str]] = []

    async def first_pass(transactions, _policy):
        asked.append([t.description for t in transactions])
        return [
            CategoryProposal(category="DINING", confidence=80) if t.description == "ANSWERED" else None
            for t in transactions
        ]

    async def retry(transactions, _policy):
        asked.append([t.description for t in transactions])
        return [CategoryProposal(category="GROCERIES", confidence=80) for _ in transactions]

    await classify_transactions(db, test_user.id, [answered, unanswered], policy=v2, proposer=first_pass)
    outcomes = await classify_transactions(db, test_user.id, [answered, unanswered], policy=v2, proposer=retry)
    assert asked == [["ANSWERED", "UNANSWERED"], ["UNANSWERED"]] and [o.disposition for o in outcomes] == [
        "already_classified",
        "applied",
    ]
    assert (
        (await row_account(db, await txn_classification(db, answered))).name,
        (await row_account(db, await txn_classification(db, unanswered))).name,
    ) == ("Expense - Dining", "Expense - Groceries")

    async def must_not_run(_transactions, _policy):
        raise AssertionError("the model must not be asked for a row that has its row")

    assert [
        o.disposition
        for o in await classify_transactions(db, test_user.id, [answered], policy=v2, proposer=must_not_run)
    ] == ["already_classified"]


async def verify_batch_scale_0_to_1(db, test_user, monkeypatch) -> None:
    from tests.statement_ingestion import classify_transactions

    txns = [await make_txn(db, test_user, description=f"ROW {c}") for c in "ABCD"]
    mock_model_answers(
        monkeypatch,
        [
            {"index": 0, "category": "DINING", "confidence": 0.9},
            {"index": 1, "category": "GROCERIES", "confidence": 1.0},
            {"index": 2, "category": "TRANSPORT", "confidence": "0.58"},
            {"index": 3, "category": "SHOPPING", "confidence": 0.895},
        ],
    )
    await classify_transactions(db, test_user.id, txns, policy=transaction_classification.POLICY_VERSIONS[-1])
    rows = [await txn_classification(db, t) for t in txns]
    assert (rows[0].confidence_score, rows[1].confidence_score, rows[3].confidence_score) == (90, 100, 89)
    assert (
        (await row_account(db, rows[1])).name,
        (await row_account(db, rows[2])).name,
        rows[2].tags["original_confidence"],
    ) == ("Expense - Groceries", "General Expense (SGD)", 58)


async def verify_handle_parse_failure_lineage(db, test_user) -> None:
    from src.extraction.extension.statement_parsing import handle_parse_failure

    statement = await StatementSummaryFactory.create_async(db, user_id=test_user.id, status=BankStatementStatus.PARSING)
    await db.commit()
    await handle_parse_failure(
        statement,
        db,
        job=ParseJob(
            statement_id=statement.id,
            run_id=await run_for(db, statement.id),
            filename="futu-2506.pdf",
            institution=statement.institution,
            user_id=test_user.id,
            account_id=statement.account_id,
            file_hash=statement.file_hash,
            storage_key=f"statements/{statement.id}/abc123.pdf",
            model=None,
        ),
        message="Extraction failed (json_parse): AI response must be a strict JSON object.",
    )
    doc = (
        await db.execute(
            select(UploadedDocument).where(
                UploadedDocument.user_id == test_user.id, UploadedDocument.file_hash == statement.file_hash
            )
        )
    ).scalar_one()
    refreshed = await db.get(StatementSummary, statement.id)
    assert (doc.status, doc.original_filename, doc.file_path) == (
        DocumentStatus.FAILED,
        "futu-2506.pdf",
        f"statements/{statement.id}/abc123.pdf",
    )
    assert (refreshed.status, refreshed.uploaded_document_id) == (BankStatementStatus.REJECTED, doc.id)


async def verify_parse_background_storage_error(db, test_user, monkeypatch) -> None:
    from src.runtime import StorageError
    from tests.statement_ingestion import execute_statement_ingestion as parse_statement_background

    sid = uuid4()
    statement = StatementSummaryFactory.build(
        id=sid, user_id=test_user.id, status=BankStatementStatus.PARSING, file_hash="h_storage_err", institution="DBS"
    )
    db.add(statement)
    await db.commit()

    async def mock_threadpool(func, *args, **kwargs):
        if "generate_presigned_url" in str(func):
            raise StorageError("Presigned fail")
        return func(*args, **kwargs)

    monkeypatch.setattr("fastapi.concurrency.run_in_threadpool", mock_threadpool)
    monkeypatch.setattr(
        "src.extraction.extension.service.ExtractionService.parse_document",
        AsyncMock(side_effect=ExtractionError("API key not configured")),
    )
    await parse_statement_background(
        job=ParseJob(
            statement_id=sid,
            run_id=await run_for(db, sid),
            filename="f.pdf",
            institution="DBS",
            user_id=test_user.id,
            account_id=None,
            file_hash="h_storage_err",
            storage_key="p",
            model=None,
        ),
        content=b"content",
        session_maker=create_session_maker_from_db(db),
    )
    await db.refresh(statement)
    assert (
        statement.status == BankStatementStatus.REJECTED
        and statement.validation_error
        and ("api key" in statement.validation_error.lower() or "configured" in statement.validation_error.lower())
    )


async def verify_dual_write_non_fatal(db, test_user) -> None:
    from src.extraction.extension.deduplication import dual_write_layer2

    txn_date, amount, direction, description = date(2025, 1, 1), Decimal("1.00"), TransactionDirection.IN, "txn"
    txn = ExtractedTransactionRow(
        user_id=test_user.id,
        txn_date=txn_date,
        amount=amount,
        direction=direction.value,
        description=description,
        reference=None,
        currency="SGD",
        currency_unresolved=False,
        balance_after=None,
        occurrence_index=0,
        dedup_hash=DeduplicationService.calculate_transaction_hash(
            test_user.id, txn_date, amount, direction, description
        ),
    )
    for _ in range(2):
        stmt = StatementSummaryFactory.build(
            user_id=test_user.id, file_hash="abc123", institution="DBS", currency="SGD"
        )
        await dual_write_layer2(
            db=db,
            user_id=test_user.id,
            statement=stmt,
            transactions=[txn],
            file_path=Path("statement.pdf"),
            original_filename="statement.pdf",
        )
        await db.commit()
    rows = (
        (
            await db.execute(
                select(UploadedDocument).where(
                    UploadedDocument.user_id == test_user.id, UploadedDocument.file_hash == "abc123"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def verify_failed_run_leaves_rows_to_review(client, db, test_user, monkeypatch, failure: str, label: str) -> None:
    from src.llm import AIStreamError

    outcomes = spy_classify_outcomes(monkeypatch)
    failing = Proposer(
        answers=EXTENDED_ANSWERS,
        timeout_gate=True,
        error={"unexpected-error": RuntimeError("unexpected failure"), "driver-timeout": TimeoutError("connect")}.get(
            failure
        ),
    )
    provider_calls: list[int] = []
    if failure == "provider-error":
        monkeypatch.setattr(
            "src.llm.stream_ai_json",
            lambda **_kw: (provider_calls.append(1), (_ for _ in ()).throw(AIStreamError("provider down")))[1],
        )
    else:
        install_proposer(monkeypatch, failing)
    rows = make_rows(6)
    statement_id = await ingest_csv_statement(db, test_user.id, "fails.csv", rows)
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSED and (
        len(provider_calls) if failure == "provider-error" else failing.rows_asked
    ) >= 1
    assert (await user_classification_rows(db, test_user.id), outcomes) == ([], [label])
    healthy = install_proposer(monkeypatch, Proposer(answers=EXTENDED_ANSWERS, timeout_gate=True))
    await confirm_csv_envelope(client, db, test_user.id, statement_id, rows)
    response = await approve_statement(client, statement_id)
    assert (
        response.status_code == 409
        and response.json()["detail"].startswith("Economic review required:")
        and healthy.rows_asked == 0
    )


async def verify_each_row_gets_own_date_policy(db, test_user, monkeypatch) -> None:
    from tests.statement_ingestion import earlier_policy

    second, first, cutover = transaction_classification.POLICY_VERSIONS[-1], earlier_policy(), date(2026, 1, 6)
    monkeypatch.setattr(
        transaction_classification,
        "POLICY_VERSIONS",
        (
            ClassificationPolicy(**{**first.model_dump(), "effective_from": date.min}),
            ClassificationPolicy(**{**second.model_dump(), "effective_from": cutover}),
        ),
    )
    proposer = install_proposer(monkeypatch, Proposer(answers=EXTENDED_ANSWERS, timeout_gate=True))
    seeded = await seed_classify_statement(db, test_user.id, make_rows(10), name="seeded.pdf")
    await classify_statement(db, seeded.id)
    stored = (
        await db.execute(
            select(AtomicTransaction.txn_date, ClassificationRule.version_number)
            .join(TransactionClassification, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
            .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
            .where(AtomicTransaction.user_id == test_user.id)
        )
    ).all()
    assert (
        len(stored) == 10
        and {v for _d, v in stored} == {1, 2}
        and len(proposer.calls) == 2
        and all(v == (1 if d < cutover else 2) for d, v in stored)
    )


async def verify_state_after_parse_classify_approve(client, db, test_user, monkeypatch) -> None:
    gate_kinds = list(EXTENDED_ANSWERS)
    proposer = install_proposer(monkeypatch, Proposer(answers=EXTENDED_ANSWERS, timeout_gate=True))
    for name, rows in (
        ("classify_equivalence_jan.csv", make_rows(len(gate_kinds), kinds=gate_kinds)),
        ("classify_equivalence_feb.csv", make_rows(5, first_day=date(2026, 2, 10))),
    ):
        sid = await ingest_csv_statement(db, test_user.id, name, rows)
        await confirm_csv_envelope(client, db, test_user.id, sid, rows)
        resp = await approve_statement(client, sid)
        assert (resp.status_code, resp.json()["journal_entries_created"]) == (200, len(rows))
    state = await read_classify_state(client, db, test_user.id)
    assert len(state["classifications"]) == len(gate_kinds) + 5 and all(
        r.status == "applied" for r in state["classifications"]
    )
    assert (
        len(state["journal_entries"]) >= len(gate_kinds) + 5
        and Decimal(state["income_statement"]["total_income"]) > 0
        and Decimal(state["balance_sheet"]["total_assets"]) != 0
        and proposer.rows_asked == len(gate_kinds) + 5
    )
