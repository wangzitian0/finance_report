from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from uuid import UUID, uuid4

from sqlalchemy import func, select

from src.composition import compose_statement_ingestion_use_case, compose_statement_posting_dependencies
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ParseJob,
    RunActorKind,
    RunHints,
    RunKind,
    RunTrigger,
    StatementSummary,
    create_run,
)
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_classification_run import execute_classify_run
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.statement_run import StatementRun
from tests.factories import StatementSummaryFactory

WAIT_SECONDS = 20
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
    return await db.scalar(select(func.count()).select_from(model).where(*where))


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
