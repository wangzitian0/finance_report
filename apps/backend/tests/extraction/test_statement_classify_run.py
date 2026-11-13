"""Classification is a run with a state; the approve only posts (#2994, slice S3).

The extract run ends and creates a `classify` run in the same transaction. The same worker task claims that
run, asks the model for the rows without an answer, and ends the run. A high-confidence statement is
auto-approved by the transaction that ends the classify run. No lock guards the classification: the active-run index
and a 409 with `active_run_id` replace it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import func, select

from src.audit.orm import TraceRecordRow
from src.composition import compose_statement_posting_dependencies
from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import (
    ActiveRunExists,
    BankStatementStatus,
    ExtractionError,
    ParseJob,
    RuleType,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    StatementIngestionStatus,
    StatementSummary,
    TransactionDirection,
    claim_run,
    create_run,
    finish_run,
    reap_stale_runs,
)
from src.extraction.extension import statement_classification_run, statement_parsing, transaction_classification
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_classification_run import execute_classify_run
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.extraction.orm.statement_run import StatementRun
from src.ledger import Account, AccountType, JournalEntry
from tests.extraction.test_statement_run_wiring import (
    CSV,
    ScriptedService,
    Sleeps,
    _runs,
    _statement,
    _statement_with_run,
    _use_case,
)
from tests.factories import StatementSummaryFactory, seed_parsed_statement
from tests.statement_ingestion import classify_run_for, classify_statement, run_for

WAIT_SECONDS = 20
ANSWERS = {
    "Salary": (TransactionCategory.SALARY, 95),
    "Coffee": (TransactionCategory.DINING, 92),
    "Grab": (TransactionCategory.TRANSPORT, 90),
    "Rent": (TransactionCategory.HOUSING, 94),
    "Refund": (TransactionCategory.REFUND, 91),
}
KINDS = list(ANSWERS)


@pytest.fixture(autouse=True)
def _model_on(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)
    monkeypatch.setattr(settings, "ai_api_key", "test-key")


class Proposer:
    """A model that records its calls and can wait, fail or refuse a kind of row."""

    def __init__(self, *, gate: asyncio.Event | None = None, error: Exception | None = None, refuse=frozenset()):
        self.calls: list[list[str]] = []
        self.gate = gate
        self.error = error
        self.refuse = refuse
        self.started = asyncio.Event()

    @property
    def rows_asked(self) -> int:
        return sum(len(call) for call in self.calls)

    async def __call__(self, transactions, _policy):
        self.calls.append([transaction.description for transaction in transactions])
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        proposals: list[CategoryProposal | None] = []
        for transaction in transactions:
            kind = transaction.description.split()[0]
            category, confidence = ANSWERS[kind]
            proposals.append(
                None
                if kind in self.refuse
                else CategoryProposal(category=category.value, confidence=confidence, reason="fixture")
            )
        return proposals


def _install(monkeypatch, proposer: Proposer) -> Proposer:
    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    return proposer


def _rows(count: int = 5, first_day: date = date(2026, 1, 1)) -> list[dict]:
    rows = []
    for index in range(count):
        kind = KINDS[index % len(KINDS)]
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


async def _seed(db, user, rows=None):
    rows = rows or _rows()
    seeded = await seed_parsed_statement(
        db,
        user.id,
        institution="DBS",
        original_filename="classify.pdf",
        opening_balance=Decimal("1000.00"),
        transactions=rows,
    )
    seeded.statement.period_start, seeded.statement.period_end = rows[0]["date"], rows[-1]["date"]
    await db.commit()
    return seeded


async def _run(db, run_id) -> StatementRun:
    return await db.scalar(
        select(StatementRun).where(StatementRun.id == run_id).execution_options(populate_existing=True)
    )


async def _count(db, model, *where) -> int:
    return int(await db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


async def _answers(db, user) -> int:
    from src.extraction.orm.layer2 import AtomicTransaction

    return await _count(
        db,
        TransactionClassification,
        TransactionClassification.atomic_txn_id.in_(
            select(AtomicTransaction.id).where(AtomicTransaction.user_id == user.id)
        ),
    )


def _spy_outcomes(monkeypatch) -> list[str]:
    outcomes: list[str] = []
    monkeypatch.setattr(
        statement_classification_run,
        "record_statement_classification_outcome",
        lambda *, outcome: outcomes.append(outcome),
    )
    return outcomes


def _high_confidence(rows: list[dict]):
    """A PDF payload that the parse scores as an auto-approve candidate: balanced, with an account."""
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


async def _parsing_job(db, user, content: bytes, name: str = "high.pdf"):
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


# --- The extract run creates the classify run, and the same task executes it -------------------------


async def test_AC_extraction_2994_88_a_successful_extract_run_creates_the_classify_run_in_its_transaction(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.88: The extract run and the new classify run commit together, and the same task gets the run id."""
    statement_id, job = await _statement_with_run(db, test_user)
    received: list = []

    async def spy(session_maker, *, run_id, posting_dependencies, **_options):
        received.append(run_id)
        return 0

    monkeypatch.setattr(statement_parsing, "execute_classify_run", spy)

    outcome = await _use_case(db).execute(job, content=CSV)

    extract, classify = await _runs(db, statement_id)
    assert outcome.status is StatementIngestionStatus.COMPLETED
    assert (extract.kind, extract.state) == (RunKind.EXTRACT, RunState.SUCCEEDED)
    assert (classify.kind, classify.state, classify.seq) == (RunKind.CLASSIFY, RunState.REQUESTED, 2)
    assert (classify.actor_kind, classify.trigger) == (RunActorKind.SYSTEM, RunTrigger.AUTO_CLASSIFY)
    assert classify.parent_run_id == extract.id
    assert classify.hints == {"keywords": [], "note": None}
    assert classify.model is None
    assert received == [classify.id], "the same worker task executes the run: no second dispatch"
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSED


async def test_AC_extraction_2994_88_a_failed_classify_insert_leaves_no_succeeded_extract_run(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.88: The classify run insert is part of the final transaction of the extract run."""
    statement_id, job = await _statement_with_run(db, test_user)
    real_create_run = statement_parsing.create_run

    async def create_run_that_fails_for_classify(session, **kwargs):
        if kwargs["kind"] is RunKind.CLASSIFY:
            raise RuntimeError("the classify run insert failed")
        return await real_create_run(session, **kwargs)

    monkeypatch.setattr(statement_parsing, "create_run", create_run_that_fails_for_classify)

    with pytest.raises(Exception, match="finalization"):
        await _use_case(db, sleeps=Sleeps()).execute(job, content=CSV)

    runs = await _runs(db, statement_id)
    assert {run.kind for run in runs} == {RunKind.EXTRACT}
    assert RunState.SUCCEEDED not in {run.state for run in runs}, "a succeeded extract run needs its classify run"
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSING


async def test_AC_extraction_2994_89_a_failed_extract_run_creates_no_classify_run(db, test_user, monkeypatch):
    """AC-extraction.2994.89: A source rejection fails the extract run and no classify run exists."""
    statement_id, job = await _statement_with_run(db, test_user)
    called: list = []

    async def spy(*_args, **_kwargs):
        called.append(True)
        return 0

    monkeypatch.setattr(statement_parsing, "execute_classify_run", spy)

    outcome = await _use_case(db, ScriptedService([ExtractionError("unreadable")])).execute(job, content=CSV)

    assert outcome.status is StatementIngestionStatus.SOURCE_REJECTED
    assert [(run.kind, run.state) for run in await _runs(db, statement_id)] == [(RunKind.EXTRACT, RunState.FAILED)]
    assert called == []


# --- The classify run: success, timeout, failure, model off, reaper ------------------------------------


async def test_AC_extraction_2994_90_a_classify_run_ends_with_counts_and_no_row_text(db, test_user, monkeypatch):
    """AC-extraction.2994.90: The summary holds counts only: no description, no amount."""
    outcomes = _spy_outcomes(monkeypatch)
    proposer = _install(monkeypatch, Proposer())
    seeded = await _seed(db, test_user)

    run_id = await classify_statement(db, seeded.id)

    run = await _run(db, run_id)
    assert (run.kind, run.state) == (RunKind.CLASSIFY, RunState.SUCCEEDED)
    assert run.started_at is not None and run.heartbeat_at is not None and run.finished_at is not None
    assert run.error_code is None
    assert run.result_summary["outcome"] == "classified"
    assert run.result_summary["total"] == 5
    assert run.result_summary["by_disposition"] == {"applied": 5}
    assert run.result_summary["by_category"]["SALARY"] == 1
    flat = json.dumps(run.result_summary)
    for row in _rows():
        assert row["description"] not in flat and str(row["amount"]) not in flat
    assert proposer.rows_asked == 5
    assert await _answers(db, test_user) == 5
    assert outcomes == ["classified"]
    records = await db.execute(
        select(TraceRecordRow.assertion_id)
        .where(TraceRecordRow.execution_id == f"statement:{seeded.id}:run:{run_id}")
        .order_by(TraceRecordRow.occurred_at)
    )
    assert list(records.scalars()) == ["classify.requested", "classify.running", "classify.succeeded"]


async def test_AC_extraction_2994_91_a_classify_run_that_passes_its_deadline_fails_with_a_timeout_code(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.91: The run fails with classification_timeout. A call that never returned writes nothing."""
    outcomes = _spy_outcomes(monkeypatch)
    hung = _install(monkeypatch, Proposer(gate=asyncio.Event()))
    seeded = await _seed(db, test_user)
    run_id = await classify_run_for(db, seeded.id)

    posted = await asyncio.wait_for(
        execute_classify_run(
            create_session_maker_from_db(db),
            run_id=run_id,
            posting_dependencies=compose_statement_posting_dependencies(),
            deadline_seconds=0.3,
        ),
        timeout=WAIT_SECONDS,
    )

    run = await _run(db, run_id)
    assert posted == 0
    assert (run.state, run.error_code) == (RunState.FAILED, "classification_timeout")
    assert hung.rows_asked == 5
    assert await _answers(db, test_user) == 0
    assert (await _statement(db, seeded.id)).status is BankStatementStatus.PARSED
    assert outcomes == ["timed_out"]


@pytest.mark.parametrize(
    "error", [RuntimeError("secret Salary 000 owner@example.com 2500.00"), TimeoutError("connect")]
)
async def test_AC_extraction_2994_92_any_other_error_fails_the_run_with_a_code_and_no_row_text(
    db, test_user, monkeypatch, error
):
    """AC-extraction.2994.92: The failure keeps its code. A driver timeout is a failure, not the deadline."""
    outcomes = _spy_outcomes(monkeypatch)
    _install(monkeypatch, Proposer(error=error))
    seeded = await _seed(db, test_user)

    run_id = await classify_statement(db, seeded.id)

    run = await _run(db, run_id)
    assert (run.state, run.error_code) == (RunState.FAILED, "classification_failed")
    assert run.error_message and len(run.error_message) <= 500
    for secret in ("Salary", "owner@example.com", "2500.00"):
        assert secret not in run.error_message
    assert await _answers(db, test_user) == 0
    assert (await _statement(db, seeded.id)).status is BankStatementStatus.PARSED
    assert outcomes == ["failed"]


async def test_AC_extraction_2994_93_a_classify_run_with_the_model_off_succeeds_with_a_skipped_summary(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.93: The model off is not a failure. The run succeeds, the model is not asked."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    outcomes = _spy_outcomes(monkeypatch)
    proposer = _install(monkeypatch, Proposer(error=AssertionError("the model was asked")))
    seeded = await _seed(db, test_user)

    run_id = await classify_statement(db, seeded.id)

    run = await _run(db, run_id)
    assert run.state is RunState.SUCCEEDED
    assert run.result_summary["outcome"] == "skipped_disabled"
    assert proposer.calls == []
    assert outcomes == ["skipped_disabled"]


async def test_AC_extraction_2994_93_a_run_with_a_refused_row_ends_partial_and_a_statement_without_rows_ends_empty(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.93: A row without a usable answer gives partial. A statement without rows gives nothing_to_classify."""
    outcomes = _spy_outcomes(monkeypatch)
    _install(monkeypatch, Proposer(refuse=frozenset({"Coffee"})))
    seeded = await _seed(db, test_user)
    empty = await seed_parsed_statement(db, test_user.id, original_filename="empty.pdf", transactions=[])

    partial_id = await classify_statement(db, seeded.id)
    empty_id = await classify_statement(db, empty.statement.id)

    assert (await _run(db, partial_id)).result_summary["outcome"] == "partial"
    assert (await _run(db, empty_id)).result_summary["outcome"] == "nothing_to_classify"
    assert (await _run(db, empty_id)).state is RunState.SUCCEEDED
    assert outcomes == ["partial", "nothing_to_classify"]


async def test_AC_extraction_2994_94_a_statement_that_left_parsed_is_skipped_and_the_run_still_ends(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.94: A run that finds a statement outside PARSED asks no model and ends succeeded."""
    outcomes = _spy_outcomes(monkeypatch)
    proposer = _install(monkeypatch, Proposer())
    seeded = await _seed(db, test_user)
    seeded.statement.status = BankStatementStatus.RETIRED
    await db.commit()

    run_id = await classify_statement(db, seeded.id)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert (await _run(db, run_id)).result_summary["outcome"] == "skipped_state"
    assert proposer.calls == [] and outcomes == ["skipped_state"]


async def test_AC_extraction_2994_95_the_reaper_fails_a_classify_run_that_no_worker_claimed(db, test_user, monkeypatch):
    """AC-extraction.2994.95: A requested classify run fails with claim_timeout, and a late worker cannot claim it."""
    proposer = _install(monkeypatch, Proposer())
    seeded = await _seed(db, test_user)
    run_id = await classify_run_for(db, seeded.id)
    maker = create_session_maker_from_db(db)

    async with maker() as session:
        reaped = await reap_stale_runs(session, now=datetime.now(UTC) + timedelta(minutes=10))
        await session.commit()
    posted = await execute_classify_run(
        maker, run_id=run_id, posting_dependencies=compose_statement_posting_dependencies()
    )

    run = await _run(db, run_id)
    assert reaped == [run_id]
    assert (run.state, run.error_code) == (RunState.FAILED, "claim_timeout")
    assert posted == 0 and proposer.calls == []


async def test_AC_extraction_2994_95_a_finish_after_the_reaper_failed_the_classify_run_discards_the_answers(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.95: The reaper fails the run during the model call: the batch is not written."""
    seeded = await _seed(db, test_user)
    run_id = await classify_run_for(db, seeded.id)
    maker = create_session_maker_from_db(db)
    real = Proposer()

    async def reaped_during_the_call(transactions, policy):
        async with maker() as other_session:
            assert await reap_stale_runs(other_session, now=datetime.now(UTC) + timedelta(minutes=10)) == [run_id]
            await other_session.commit()
        return await real(transactions, policy)

    _install(monkeypatch, reaped_during_the_call)

    posted = await execute_classify_run(
        maker, run_id=run_id, posting_dependencies=compose_statement_posting_dependencies()
    )

    run = await _run(db, run_id)
    assert posted == 0
    assert (run.state, run.error_code) == (RunState.FAILED, "heartbeat_lost")
    assert await _answers(db, test_user) == 0


# --- Keyword rules answer in the run ---------------------------------------------------------------------


async def _add_coffee_rule(db, user) -> None:
    account = Account(user_id=user.id, name="Expense - Reviewed Coffee", type=AccountType.EXPENSE, currency="SGD")
    db.add(account)
    await db.flush()
    db.add(
        ClassificationRule(
            user_id=user.id,
            created_by=user.id,
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


async def test_AC_extraction_2994_97_the_classify_run_answers_a_keyword_rule_row_without_the_model_and_approve_posts(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.97: The run applies the keyword rule: no model call for the row, and the approve posts all rows."""
    proposer = _install(monkeypatch, Proposer())
    seeded = await _seed(db, test_user)
    await _add_coffee_rule(db, test_user)

    run_id = await classify_statement(db, seeded.id)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert not any(description.startswith("Coffee") for call in proposer.calls for description in call)
    assert proposer.rows_asked == 4
    rule_answers = await _count(
        db,
        TransactionClassification,
        TransactionClassification.rule_version_id.in_(
            select(ClassificationRule.id).where(ClassificationRule.rule_type == RuleType.KEYWORD_MATCH)
        ),
    )
    assert rule_answers == 1, "the row of the keyword rule has its answer from the rule"
    response = await client.post(f"/statements/{seeded.id}/review/approve", json={"create_account_if_missing": True})
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 5
    assert proposer.rows_asked == 4, "the approve asks no model"


# --- Approve only posts ----------------------------------------------------------------------------------


async def test_AC_extraction_2994_98_approve_with_an_active_classify_run_gives_409_at_once_and_writes_nothing(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.98: Approve refuses an active classify run in under 1 s with the run id. After the run it posts."""
    proposer = _install(monkeypatch, Proposer())
    seeded = await _seed(db, test_user)
    seeded_id = seeded.id
    run_id = await classify_run_for(db, seeded_id)

    started = time.perf_counter()
    refused = await client.post(f"/statements/{seeded_id}/review/approve", json={"create_account_if_missing": True})
    elapsed = time.perf_counter() - started

    assert refused.status_code == 409, refused.text
    assert refused.json()["active_run_id"] == str(run_id)
    assert elapsed < 1.0, f"the 409 took {elapsed:.2f} s"
    assert await _count(db, JournalEntry) == 0
    assert await _count(db, Account, Account.user_id == test_user.id) == 0, "the refused approve created no account"
    assert (await _statement(db, seeded_id)).status is BankStatementStatus.PARSED

    posted = await execute_classify_run(
        create_session_maker_from_db(db), run_id=run_id, posting_dependencies=compose_statement_posting_dependencies()
    )
    assert posted == 0
    response = await client.post(f"/statements/{seeded_id}/review/approve", json={"create_account_if_missing": True})
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 5
    assert proposer.rows_asked == 5, "the approve asks no row"


async def test_AC_extraction_2994_98_approve_of_rows_after_a_failed_classify_run_goes_to_economic_review(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.98: The failed run leaves no answer. The approve asks no model and posts nothing wrong."""
    failing = _install(monkeypatch, Proposer(error=RuntimeError("provider down")))
    seeded = await _seed(db, test_user)
    run_id = await classify_statement(db, seeded.id)
    assert (await _run(db, run_id)).state is RunState.FAILED

    response = await client.post(f"/statements/{seeded.id}/review/approve", json={"create_account_if_missing": True})

    assert response.status_code == 409, response.text
    assert response.json()["detail"].startswith("Economic review required:")
    assert len(failing.calls) == 1, "only the classify run asked the model"
    assert await _count(db, JournalEntry) == 0
    assert await _answers(db, test_user) == 0
    assert (await _statement(db, seeded.id)).status is BankStatementStatus.PARSED


# --- Auto-approve follows a succeeded classify run -----------------------------------------------------


async def test_AC_extraction_2994_99_a_high_confidence_statement_is_approved_only_after_the_classify_run_succeeded(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.99: PARSED with visible rows while the run runs; APPROVED with entries once the run succeeded."""
    gate = asyncio.Event()
    proposer = _install(monkeypatch, Proposer(gate=gate))
    rows = _rows()
    service, content = _high_confidence(rows)
    statement_id, job = await _parsing_job(db, test_user, content)

    task = asyncio.create_task(_use_case(db, service).execute(job, content=content))
    try:
        await asyncio.wait_for(proposer.started.wait(), timeout=WAIT_SECONDS)
        statement = await _statement(db, statement_id)
        extract, classify = await _runs(db, statement_id)
        assert statement.status is BankStatementStatus.PARSED, "APPROVED only when the entries are posted"
        assert statement.stage1_status.value == "pending_review"
        assert (extract.state, classify.kind, classify.state) == (
            RunState.SUCCEEDED,
            RunKind.CLASSIFY,
            RunState.RUNNING,
        )
        assert extract.result_summary == {"auto_approve_candidate": True}
        assert await _count(db, JournalEntry) == 0
        review = await client.get(f"/statements/{statement_id}/review")
        assert review.status_code == 200, review.text
        assert len(review.json()["transactions"]) == len(rows), "the rows are visible while the classify run is active"
        started = time.perf_counter()
        refused = await client.post(f"/statements/{statement_id}/review/approve", json={})
        assert refused.status_code == 409 and refused.json()["active_run_id"] == str(classify.id)
        assert time.perf_counter() - started < 1.0
    finally:
        gate.set()
    outcome = await asyncio.wait_for(task, timeout=WAIT_SECONDS)

    assert outcome.status is StatementIngestionStatus.COMPLETED
    assert outcome.auto_posted_count == len(rows)
    assert (await _statement(db, statement_id)).status is BankStatementStatus.APPROVED
    assert await _count(db, JournalEntry) >= len(rows)
    assert proposer.rows_asked == len(rows), "one model call for each row, in the classify run"


async def test_AC_extraction_2994_99_a_high_confidence_statement_stays_parsed_when_the_classify_run_fails(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.99: A failed classify run posts nothing and leaves the statement PARSED with no review notice."""
    _install(monkeypatch, Proposer(error=RuntimeError("provider down")))
    service, content = _high_confidence(_rows())
    statement_id, job = await _parsing_job(db, test_user, content)

    outcome = await _use_case(db, service).execute(job, content=content)

    statement = await _statement(db, statement_id)
    assert outcome.status is StatementIngestionStatus.COMPLETED and outcome.auto_posted_count == 0
    assert statement.status is BankStatementStatus.PARSED
    assert statement.validation_error is None
    assert await _count(db, JournalEntry) == 0
    assert [(run.kind, run.state) for run in await _runs(db, statement_id)] == [
        (RunKind.EXTRACT, RunState.SUCCEEDED),
        (RunKind.CLASSIFY, RunState.FAILED),
    ]


async def test_AC_extraction_2994_99_a_low_confidence_statement_is_never_auto_approved(db, test_user, monkeypatch):
    """AC-extraction.2994.99: Only the candidate that the parse marked is approved: a CSV without balances stays PARSED."""
    _install(monkeypatch, Proposer())
    statement_id, job = await _statement_with_run(db, test_user)

    outcome = await _use_case(db).execute(job, content=CSV)

    extract, classify = await _runs(db, statement_id)
    assert extract.result_summary == {"auto_approve_candidate": False}
    assert classify.state is RunState.SUCCEEDED
    assert outcome.auto_posted_count == 0
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSED
    assert await _count(db, JournalEntry) == 0


async def _parsed_candidate_after_an_extract_run(db, user, *, marked: bool):
    """A PARSED statement with a high score and a classify run whose extract run marked it, or did not."""
    from tests.api._statement_router_fixtures import create_statement_account

    seeded = await _seed(db, user)
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


async def test_AC_extraction_2994_99_the_mark_of_the_parse_decides_not_the_score(db, test_user, monkeypatch):
    """AC-extraction.2994.99: A PARSED statement with a high score and no mark (a position snapshot) is not approved."""
    _install(monkeypatch, Proposer())
    statement_id, run_id = await _parsed_candidate_after_an_extract_run(db, test_user, marked=False)

    posted = await execute_classify_run(
        create_session_maker_from_db(db), run_id=run_id, posting_dependencies=compose_statement_posting_dependencies()
    )

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert posted == 0
    assert (await _statement(db, statement_id)).status is BankStatementStatus.PARSED
    assert await _count(db, JournalEntry) == 0


async def test_AC_extraction_2994_99_a_marked_statement_is_approved_at_the_end_of_its_run(db, test_user, monkeypatch):
    """AC-extraction.2994.99: The same statement with the mark is approved and posted when its run succeeds."""
    _install(monkeypatch, Proposer())
    statement_id, run_id = await _parsed_candidate_after_an_extract_run(db, test_user, marked=True)

    posted = await execute_classify_run(
        create_session_maker_from_db(db), run_id=run_id, posting_dependencies=compose_statement_posting_dependencies()
    )

    assert posted == 5
    assert (await _statement(db, statement_id)).status is BankStatementStatus.APPROVED
    assert await _count(db, JournalEntry) >= 5


async def test_AC_extraction_2994_99_the_auto_approve_leaves_a_statement_that_a_user_approved_first(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.99: The user approve wins the race: the auto-approve posts nothing more and keeps the review time."""
    from src.extraction.extension.statement_posting import auto_approve_parsed_candidate

    _install(monkeypatch, Proposer())
    statement_id, run_id = await _parsed_candidate_after_an_extract_run(db, test_user, marked=False)
    maker = create_session_maker_from_db(db)
    await execute_classify_run(maker, run_id=run_id, posting_dependencies=compose_statement_posting_dependencies())
    response = await client.post(f"/statements/{statement_id}/review/approve", json={})
    assert response.status_code == 200, response.text
    approved = await _statement(db, statement_id)
    reviewed_at, entries = approved.stage1_reviewed_at, await _count(db, JournalEntry)
    assert approved.status is BankStatementStatus.APPROVED

    # The end of the run reaches the auto-approve after the user approve committed.
    async with maker() as session:
        posted = await auto_approve_parsed_candidate(
            session, statement_id, test_user.id, dependencies=compose_statement_posting_dependencies()
        )
        await session.commit()

    assert posted == 0
    assert (await _statement(db, statement_id)).stage1_reviewed_at == reviewed_at
    assert await _count(db, JournalEntry) == entries


async def test_AC_extraction_2994_99_a_candidate_with_a_refused_row_waits_in_the_economic_review_until_the_next_run(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.99: A partial run leaves the candidate PARSED with the notice. The next run answers the row."""
    _install(monkeypatch, Proposer(refuse=frozenset({"Refund"})))
    rows = _rows()
    service, content = _high_confidence(rows)
    statement_id, job = await _parsing_job(db, test_user, content)

    outcome = await _use_case(db, service).execute(job, content=content)

    statement = await _statement(db, statement_id)
    assert outcome.auto_posted_count == 0
    assert statement.status is BankStatementStatus.PARSED
    assert (statement.validation_error or "").startswith("Economic review required:")
    assert await _count(db, JournalEntry) == 0
    healthy = _install(monkeypatch, Proposer())
    await classify_statement(db, statement_id)
    assert healthy.rows_asked == 1, "the next run asks only the row without an answer"
    response = await client.post(f"/statements/{statement_id}/review/approve", json={})
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == len(rows)
    assert healthy.rows_asked == 1


async def test_AC_extraction_2994_99_a_candidate_with_the_model_off_goes_to_economic_review(db, test_user, monkeypatch):
    """AC-extraction.2994.99: Rows without an answer stay PARSED with the review notice, as the model-off case did before."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    service, content = _high_confidence(_rows())
    statement_id, job = await _parsing_job(db, test_user, content)

    outcome = await _use_case(db, service).execute(job, content=content)

    statement = await _statement(db, statement_id)
    assert outcome.auto_posted_count == 0
    assert statement.status is BankStatementStatus.PARSED
    assert (statement.validation_error or "").startswith("Economic review required:")
    assert await _count(db, JournalEntry) == 0


# --- The other callers of the classification -----------------------------------------------------------


async def test_AC_extraction_2994_101_the_one_click_fill_refuses_a_statement_with_an_active_run(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.101: The fill asks no model while a run is active. It raises ActiveRunExists with the run id."""
    from src.composition import auto_fill_default_statement_dispositions

    proposer = _install(monkeypatch, Proposer())
    seeded = await _seed(db, test_user)
    run_id = await classify_run_for(db, seeded.id)

    with pytest.raises(ActiveRunExists) as caught:
        await auto_fill_default_statement_dispositions(db, seeded.statement, test_user.id)

    assert caught.value.active_run_id == run_id
    assert proposer.calls == []


async def test_AC_extraction_2994_101_the_one_click_fill_still_works_without_an_active_run(db, test_user, monkeypatch):
    """AC-extraction.2994.101: Without an active run the fill classifies its rows itself, without a lock."""
    proposer = _install(monkeypatch, Proposer())
    seeded = await _seed(db, test_user)

    from src.composition import auto_fill_default_statement_dispositions

    await auto_fill_default_statement_dispositions(db, seeded.statement, test_user.id)

    assert proposer.rows_asked == 5


async def test_AC_extraction_2994_101_the_approve_route_with_the_fill_option_gives_409_while_a_run_is_active(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.101: The fill option of the approve route cannot start a classification during a run."""
    proposer = _install(monkeypatch, Proposer())
    seeded = await _seed(db, test_user)
    run_id = await classify_run_for(db, seeded.id)

    response = await client.post(
        f"/statements/{seeded.id}/review/approve",
        json={"create_account_if_missing": True, "auto_fill_default_categories": True},
    )

    assert response.status_code == 409, response.text
    assert response.json()["active_run_id"] == str(run_id)
    assert proposer.calls == []


async def test_AC_extraction_2994_101_the_backfill_skips_a_statement_with_an_active_run_and_counts_it(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.101: The backfill leaves the rows of a statement with an active run and reports the skip."""
    proposer = _install(monkeypatch, Proposer())
    busy = await _seed(db, test_user, _rows(3, first_day=date(2026, 1, 1)))
    free = await _seed(db, test_user, _rows(4, first_day=date(2026, 2, 1)))
    await classify_run_for(db, busy.id)

    response = await client.post("/classifications/backfill")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["classified"], body["candidates"], body["skipped_statements"]) == (4, 4, 1)
    asked = {description for call in proposer.calls for description in call}
    assert asked == {transaction.description for transaction in free.transactions}
    assert await _answers(db, test_user) == 4
    assert busy.statement.id != free.statement.id


# --- Interleavings with real sessions: the routes are in tests/api/test_statement_classify_run_routes.py -----


async def _active_classify_run(db, user, monkeypatch, proposer):
    """Start a classify run that waits in the model call. Return the statement id, the run id and the worker task."""
    seeded = await _seed(db, user)
    run_id = await classify_run_for(db, seeded.id)
    worker = asyncio.create_task(
        execute_classify_run(
            create_session_maker_from_db(db),
            run_id=run_id,
            posting_dependencies=compose_statement_posting_dependencies(),
        )
    )
    await asyncio.wait_for(proposer.started.wait(), timeout=WAIT_SECONDS)
    return seeded.id, run_id, worker


# --- The flag and the lock are gone ---------------------------------------------------------------------


def test_AC_extraction_2994_103_the_review_response_has_no_classification_flag(openapi_schema):
    """AC-extraction.2994.103: The review payload carries no preclassification_in_progress. The runs list shows the state."""
    from src.schemas.review import StatementReviewResponse

    assert "preclassification_in_progress" not in StatementReviewResponse.model_fields
    assert (
        "preclassification_in_progress"
        not in openapi_schema["components"]["schemas"]["StatementReviewResponse"]["properties"]
    )


def test_AC_extraction_2994_104_no_advisory_lock_guards_the_classification():
    """AC-extraction.2994.104: The lock functions, the wait constants and the busy error do not exist."""
    import src.extraction as package

    for name in (
        "lock_statement_classification",
        "try_lock_statement_classification",
        "is_statement_classification_running",
        "classify_statement_by_effective_policy",
        "StatementClassificationBusy",
    ):
        assert not hasattr(package, name), name
        assert not hasattr(transaction_classification, name), name
    for name in ("CLASSIFICATION_LOCK_WAIT_SECONDS", "_LOCK_POLL_SECONDS", "_statement_lock_key"):
        assert not hasattr(transaction_classification, name), name
