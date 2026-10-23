"""AC-extraction.statement-classify: classify a statement once after parse, so approve waits for no model (#2637).

Staging ``v0.2.27`` took 26.35 s to approve an 80-row statement. The posting took 0.58 s. The rest was the
model call of the classification, which ran inside the approve request because nothing classified earlier.

These tests run the real ingestion use case (the code of the API task and of the Prefect flow) on a CSV or on a
PDF payload. They run the real review and approve routes. A counting fake takes the place of the model. A test
counts the rows that the fake receives, so a second call for the same row, or a call in the approve request, fails
the test.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.composition import compose_statement_ingestion_use_case
from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ParseJob,
    RuleType,
    StatementIngestionStatus,
    TransactionDirection,
)
from src.extraction.extension import transaction_classification
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.transaction_classification import (
    CategoryProposal,
    ClassificationPolicy,
    TransactionCategory,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, JournalEntry, JournalLine
from src.llm import AIStreamError
from tests.extraction.test_statement_approve_equivalence import _normalize, _rows_of, format_golden, snapshot_state
from tests.factories import StatementSummaryFactory, seed_parsed_statement

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN_PATH = FIXTURES / "statement_classify_state_golden.json"
REVIEW_PATH_GOLDEN_PATH = FIXTURES / "statement_classify_review_path_golden.json"

#: One answer for each kind of fixture row: category and confidence. The fake never refuses a row.
ANSWERS: dict[str, tuple[TransactionCategory, int]] = {
    "Salary": (TransactionCategory.SALARY, 95),
    "Coffee": (TransactionCategory.DINING, 92),
    "Grab": (TransactionCategory.TRANSPORT, 90),
    "Rent": (TransactionCategory.HOUSING, 94),
    "Refund": (TransactionCategory.REFUND, 91),
    # The kinds below leave the plain path of the gate. They are used by the equivalence tests only.
    "Transfer": (TransactionCategory.TRANSFER, 90),  # a non-P&L class: a draft and a Processing leg
    "Loan": (TransactionCategory.LOAN_PRINCIPAL, 90),  # a balance-sheet account
    "Mystery": (TransactionCategory.DINING, 40),  # below the review score: the general account, or no row
    "Odd": (TransactionCategory.SALARY, 95),  # an income class on an outgoing row: the general account
    "Fee": (TransactionCategory.FEES, 70),  # the review band: accepted, or a draft with auto-accept off
}
KINDS = ["Salary", "Coffee", "Grab", "Rent", "Refund"]
GATE_KINDS = list(ANSWERS)
#: Seconds. A wait on a gate that nobody opens would hang the run, so every wait has this bound.
WAIT_SECONDS = 20


@pytest.fixture(autouse=True)
def _automatic_path(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)
    monkeypatch.setattr(settings, "ai_api_key", "test-key")


class CountingProposer:
    """A stand-in for ``propose_categories``, the single boundary to the model.

    ``calls`` holds the descriptions of the rows of each call. ``gate`` holds back every answer until a test opens
    it. ``error`` makes every call raise. ``refuse`` names the kinds of row that get no answer.
    """

    def __init__(
        self,
        *,
        gate: asyncio.Event | None = None,
        error: Exception | None = None,
        refuse: frozenset[str] = frozenset(),
    ):
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
            try:
                await asyncio.wait_for(self.gate.wait(), timeout=WAIT_SECONDS)
            except TimeoutError:
                # Not a TimeoutError: the pass maps that one to its own deadline and would hide a missing deadline.
                raise AssertionError("the test never opened the gate") from None
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


def _install(monkeypatch, proposer: CountingProposer) -> CountingProposer:
    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    return proposer


def _rows(count: int, *, first_day: date = date(2026, 1, 1), kinds: list[str] = KINDS) -> list[dict]:
    """Rows in and out. Every description is unique, so a label names one row."""
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


def _closing(rows: list[dict], opening: Decimal = Decimal("1000.00")) -> Decimal:
    return opening + sum(
        (row["amount"] if row["direction"] is TransactionDirection.IN else -row["amount"] for row in rows),
        start=Decimal("0"),
    )


def _csv(rows: list[dict]) -> bytes:
    lines = ["Statement Currency,Date,Description,Debit Amount,Credit Amount"]
    for row in rows:
        incoming = row["direction"] is TransactionDirection.IN
        debit = "" if incoming else row["amount"]
        credit = row["amount"] if incoming else ""
        lines.append(f"SGD,{row['date'].isoformat()},{row['description']},{debit},{credit}")
    return ("\n".join(lines) + "\n").encode()


def _sessions(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Sessions on their own connections: a lock of one session does not bind another."""
    return create_session_maker_from_db(db)


def _use_case(db: AsyncSession, service: ExtractionService | None = None):
    use_case = compose_statement_ingestion_use_case(session_maker=_sessions(db))
    return replace(use_case, extraction_service_factory=lambda: service) if service is not None else use_case


def _job(statement_id: UUID, user_id: UUID, name: str, file_hash: str) -> ParseJob:
    return ParseJob(
        statement_id=statement_id,
        filename=name,
        institution="DBS",
        user_id=user_id,
        account_id=None,
        file_hash=file_hash,
        storage_key=f"statements/{name}",
        model=None,
        request_id=f"req-{name}",
    )


async def _new_parsing_statement(db: AsyncSession, user_id: UUID, file_hash: str) -> UUID:
    statement = StatementSummaryFactory.build(
        id=uuid4(), user_id=user_id, status=BankStatementStatus.PARSING, file_hash=file_hash, institution="DBS"
    )
    db.add(statement)
    await db.commit()
    return statement.id


async def _ingest_csv(db: AsyncSession, user_id: UUID, name: str, rows: list[dict]) -> UUID:
    """Run the ingestion use case on a CSV, as the upload task does."""
    content = _csv(rows)
    file_hash = hashlib.sha256(content).hexdigest()
    statement_id = await _new_parsing_statement(db, user_id, file_hash)
    outcome = await _use_case(db).execute(_job(statement_id, user_id, name, file_hash), content=content)
    assert outcome.status is StatementIngestionStatus.COMPLETED
    return statement_id


async def _confirm_csv_envelope(client, db: AsyncSession, user_id: UUID, statement_id: UUID, rows: list[dict]) -> None:
    """The review of the user: read the source result, then confirm the bank account and the balances."""
    review = await client.get(f"/statements/{statement_id}/review")
    assert review.status_code == 200, review.text
    bank = Account(user_id=user_id, name=f"Bank from {rows[0]['date']}", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.commit()
    response = await client.post(
        f"/statements/{statement_id}/review/envelope",
        json={
            "source_result_digest": review.json()["source_result_digest"],
            "account_id": str(bank.id),
            "currency": "SGD",
            "period_start": rows[0]["date"].isoformat(),
            "period_end": rows[-1]["date"].isoformat(),
            "opening_balance": "1000.00",
            "closing_balance": str(_closing(rows)),
            "rationale": "Checked against the original file.",
        },
    )
    assert response.status_code == 200, response.text


async def _seed(db: AsyncSession, user_id: UUID, rows: list[dict], *, name: str = "seeded.pdf"):
    """A parsed statement that the database already holds, with no provider call and no reviewed answer."""
    seeded = await seed_parsed_statement(
        db, user_id, institution="DBS", original_filename=name, opening_balance=Decimal("1000.00"), transactions=rows
    )
    if rows:
        seeded.statement.period_start = rows[0]["date"]
        seeded.statement.period_end = rows[-1]["date"]
    await db.commit()
    return seeded


async def _approve(client, statement_id: UUID):
    """The route that the user calls. The reads that the review page makes come first."""
    review = await client.get(f"/statements/{statement_id}/review")
    assert review.status_code == 200, review.text
    return await client.post(f"/statements/{statement_id}/review/approve", json={"create_account_if_missing": True})


async def _status_of(sessions, statement_id: UUID) -> BankStatementStatus:
    async with sessions() as session:
        return (await session.get(StatementSummary, statement_id)).status


async def _classification_rows(sessions, user_id: UUID) -> list[TransactionClassification]:
    async with sessions() as session:
        rows = await session.execute(
            select(TransactionClassification)
            .join(AtomicTransaction, AtomicTransaction.id == TransactionClassification.atomic_txn_id)
            .where(AtomicTransaction.user_id == user_id)
        )
        return list(rows.scalars())


def _spy_outcomes(monkeypatch) -> list[str]:
    from src.extraction.extension import statement_preclassification

    outcomes: list[str] = []
    monkeypatch.setattr(
        statement_preclassification,
        "record_statement_classification_outcome",
        lambda *, outcome: outcomes.append(outcome),
    )
    return outcomes


# ---------------------------------------------------------------------------------------------------------
# AC-extraction.statement-classify.1: the parse classifies, the approve asks no model
# ---------------------------------------------------------------------------------------------------------


async def test_AC_extraction_statement_classify_1_parse_classifies_and_approve_makes_zero_model_calls(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.1: after the ingestion each row has one answer, and approve asks no model.

    On main the ingestion asks nothing and the approve asks for every row, so both counts fail there.
    """
    proposer = _install(monkeypatch, CountingProposer())
    rows = _rows(12)

    statement_id = await _ingest_csv(db, test_user.id, "jan.csv", rows)

    assert await _status_of(_sessions(db), statement_id) is BankStatementStatus.PARSED
    assert proposer.rows_asked == 12, "the ingestion asks the model once for each row"
    assert len(await _classification_rows(_sessions(db), test_user.id)) == 12

    await _confirm_csv_envelope(client, db, test_user.id, statement_id, rows)
    response = await _approve(client, statement_id)

    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 12
    assert proposer.rows_asked == 12, "the approve asks the model for no row"
    assert len(proposer.calls) == 1


async def test_AC_extraction_statement_classify_1_the_provider_gets_no_call_at_approve(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.1: the same, counted at the provider call ``stream_ai_json``."""
    provider_calls: list[int] = []

    def stream_ai_json(**kwargs):
        content = kwargs["messages"][0]["content"]
        lines = [json.loads(line) for line in content.splitlines() if line.startswith('{"index"')]
        provider_calls.append(len(lines))
        items = [
            {
                "index": line["index"],
                "category": ANSWERS[line["description"].split()[0]][0].value,
                "confidence": ANSWERS[line["description"].split()[0]][1],
                "reason": "fixture",
            }
            for line in lines
        ]

        async def stream():
            yield json.dumps(items)

        return stream()

    monkeypatch.setattr("src.llm.stream_ai_json", stream_ai_json)
    rows = _rows(8)

    statement_id = await _ingest_csv(db, test_user.id, "provider.csv", rows)
    assert provider_calls == [8]

    await _confirm_csv_envelope(client, db, test_user.id, statement_id, rows)
    response = await _approve(client, statement_id)

    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 8
    assert provider_calls == [8]


async def test_AC_extraction_statement_classify_1_a_pdf_payload_is_classified_after_parse_too(
    db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.1: the PDF path runs the same phase as the CSV path."""
    proposer = _install(monkeypatch, CountingProposer())
    rows = _rows(3)
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "DBS",
            "currency": "SGD",
            "transactions": [
                {
                    "date": row["date"].isoformat(),
                    "description": row["description"],
                    "amount": str(row["amount"]),
                    "direction": row["direction"].value,
                    "currency": "SGD",
                }
                for row in rows
            ],
        }
    )
    content = b"%PDF-1.7 classify after parse"
    file_hash = hashlib.sha256(content).hexdigest()
    statement_id = await _new_parsing_statement(db, test_user.id, file_hash)

    outcome = await _use_case(db, service).execute(
        _job(statement_id, test_user.id, "jan.pdf", file_hash), content=content
    )

    assert outcome.status is StatementIngestionStatus.COMPLETED
    assert await _status_of(_sessions(db), statement_id) is BankStatementStatus.PARSED
    assert proposer.rows_asked == 3
    assert len(await _classification_rows(_sessions(db), test_user.id)) == 3


# ---------------------------------------------------------------------------------------------------------
# AC-extraction.statement-classify.2: the phase fails soft
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "label"),
    [
        # The model code turns a provider error into "no answer" for each row: the pass ends with partial.
        ("provider-error", "partial"),
        ("unexpected-error", "failed"),
        # A TimeoutError of the driver is a failure, not the deadline of the pass.
        ("driver-timeout", "failed"),
    ],
)
async def test_AC_extraction_statement_classify_2_a_failed_phase_leaves_the_rows_to_the_approve(
    client, db, test_user, monkeypatch, failure, label
):
    """AC-extraction.statement-classify.2: a failure leaves no row and no failed ingestion; approve works as before."""
    outcomes = _spy_outcomes(monkeypatch)
    failing = CountingProposer(
        error={"unexpected-error": RuntimeError("unexpected failure"), "driver-timeout": TimeoutError("connect")}.get(
            failure
        )
    )
    provider_calls: list[int] = []
    if failure == "provider-error":

        def stream_ai_json(**_kwargs):
            provider_calls.append(1)
            raise AIStreamError("provider down")

        monkeypatch.setattr("src.llm.stream_ai_json", stream_ai_json)
    else:
        _install(monkeypatch, failing)
    rows = _rows(6)

    statement_id = await _ingest_csv(db, test_user.id, "fails.csv", rows)  # asserts COMPLETED

    assert await _status_of(_sessions(db), statement_id) is BankStatementStatus.PARSED
    assert (len(provider_calls) if failure == "provider-error" else failing.rows_asked) >= 1, "the model was asked"
    assert await _classification_rows(_sessions(db), test_user.id) == []
    assert outcomes == [label]

    healthy = _install(monkeypatch, CountingProposer())
    await _confirm_csv_envelope(client, db, test_user.id, statement_id, rows)
    response = await _approve(client, statement_id)

    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 6
    assert healthy.rows_asked == 6, "the approve asks for the rows that have no answer"


async def test_AC_extraction_statement_classify_2_a_phase_that_runs_past_its_deadline_is_stopped(
    db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.2: a hung model ends at the deadline, writes nothing and frees the lock."""
    from src.extraction.extension import statement_preclassification
    from src.extraction.extension.transaction_classification import try_lock_statement_classification

    outcomes = _spy_outcomes(monkeypatch)
    monkeypatch.setattr(statement_preclassification, "CLASSIFICATION_PHASE_DEADLINE_SECONDS", 3.0)
    hung = _install(monkeypatch, CountingProposer(gate=asyncio.Event()))  # the gate never opens
    seeded = await _seed(db, test_user.id, _rows(4))
    sessions = _sessions(db)

    result = await statement_preclassification.classify_parsed_statement(
        sessions, statement_id=seeded.id, user_id=test_user.id
    )

    assert result is statement_preclassification.StatementClassificationPhase.TIMED_OUT
    assert hung.rows_asked == 4
    assert await _classification_rows(sessions, test_user.id) == []
    assert outcomes == ["timed_out"]
    async with sessions() as probe:
        assert await try_lock_statement_classification(probe, seeded.id), "the deadline released the lock"
        await probe.rollback()


# ---------------------------------------------------------------------------------------------------------
# AC-extraction.statement-classify.3: one answer for a row, whoever asks first
# ---------------------------------------------------------------------------------------------------------


async def test_AC_extraction_statement_classify_3_approve_waits_for_a_running_phase_and_asks_no_second_time(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.3: approve during the phase waits, then posts from the rows of the phase.

    Without the lock the approve would not see the rows of the phase (they are not committed), ask the model for the
    same rows, and fail on the unique key of the classification table.
    """
    from src.extraction.extension import statement_preclassification

    attempts: list[bool] = []
    real_try_lock = transaction_classification.try_lock_statement_classification

    async def counting_try_lock(session, statement_id):
        acquired = await real_try_lock(session, statement_id)
        attempts.append(acquired)
        return acquired

    monkeypatch.setattr(transaction_classification, "try_lock_statement_classification", counting_try_lock)
    monkeypatch.setattr(transaction_classification, "_LOCK_POLL_SECONDS", 0.01)
    gate = asyncio.Event()
    proposer = _install(monkeypatch, CountingProposer(gate=gate))
    seeded = await _seed(db, test_user.id, _rows(10))
    sessions = _sessions(db)

    phase = asyncio.create_task(
        statement_preclassification.classify_parsed_statement(sessions, statement_id=seeded.id, user_id=test_user.id)
    )
    await asyncio.wait_for(proposer.started.wait(), timeout=WAIT_SECONDS)  # the phase holds the lock now
    attempts.clear()
    approve = asyncio.create_task(_approve(client, seeded.id))
    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    while attempts.count(False) < 3:  # the approve polled the lock and found it held
        assert asyncio.get_running_loop().time() < deadline, "the approve never asked for the lock"
        await asyncio.sleep(0.01)

    assert not approve.done()
    assert len(proposer.calls) == 1, "only the phase asks the model while it runs"

    gate.set()
    result = await asyncio.wait_for(phase, timeout=WAIT_SECONDS)
    response = await asyncio.wait_for(approve, timeout=WAIT_SECONDS)

    assert result is statement_preclassification.StatementClassificationPhase.CLASSIFIED
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 10
    assert proposer.rows_asked == 10, "no row was asked twice"
    stored = await _classification_rows(sessions, test_user.id)
    assert len(stored) == 10
    assert len({row.atomic_txn_id for row in stored}) == 10


async def test_AC_extraction_statement_classify_3_the_phase_skips_when_an_approval_holds_the_lock(
    db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.3: a phase that finds the lock held leaves the rows to the holder."""
    from src.extraction.extension import statement_preclassification
    from src.extraction.extension.transaction_classification import try_lock_statement_classification

    outcomes = _spy_outcomes(monkeypatch)
    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(4))
    sessions = _sessions(db)

    async with sessions() as holder:
        assert await try_lock_statement_classification(holder, seeded.id)
        result = await asyncio.wait_for(
            statement_preclassification.classify_parsed_statement(
                sessions, statement_id=seeded.id, user_id=test_user.id
            ),
            timeout=WAIT_SECONDS,
        )
        await holder.rollback()

    assert result is statement_preclassification.StatementClassificationPhase.SKIPPED_LOCKED
    assert proposer.calls == []
    assert outcomes == ["skipped_locked"]


async def test_AC_extraction_statement_classify_3_an_approval_that_cannot_get_the_lock_in_time_answers_409(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.3: past the wait limit the approve answers 409 and asks no model."""
    from src.extraction.extension.transaction_classification import try_lock_statement_classification

    monkeypatch.setattr(transaction_classification, "CLASSIFICATION_LOCK_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(transaction_classification, "_LOCK_POLL_SECONDS", 0.01)
    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(4))
    sessions = _sessions(db)

    async with sessions() as holder:
        assert await try_lock_statement_classification(holder, seeded.id)
        response = await asyncio.wait_for(_approve(client, seeded.id), timeout=WAIT_SECONDS)
        await holder.rollback()

    assert response.status_code == 409, response.text
    assert "still running" in response.json()["detail"]
    assert proposer.calls == []
    assert await _status_of(sessions, seeded.id) is BankStatementStatus.PARSED, "the stopped approve changed nothing"


async def test_AC_extraction_statement_classify_3_a_second_phase_asks_no_row_that_has_an_answer(
    db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.3: a row with an answer of the current policy is not asked again."""
    from src.extraction.extension import statement_preclassification

    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(6))
    sessions = _sessions(db)

    first = await statement_preclassification.classify_parsed_statement(
        sessions, statement_id=seeded.id, user_id=test_user.id
    )
    second = await statement_preclassification.classify_parsed_statement(
        sessions, statement_id=seeded.id, user_id=test_user.id
    )

    assert first is statement_preclassification.StatementClassificationPhase.CLASSIFIED
    assert second is statement_preclassification.StatementClassificationPhase.NOTHING_TO_CLASSIFY
    assert proposer.rows_asked == 6
    assert len(await _classification_rows(sessions, test_user.id)) == 6


async def test_AC_extraction_statement_classify_3_the_approve_asks_only_for_the_rows_without_an_answer(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.3: a partial pass leaves the missing rows to the approve, and no other row."""
    from src.extraction.extension import statement_preclassification

    outcomes = _spy_outcomes(monkeypatch)
    partial = _install(monkeypatch, CountingProposer(refuse=frozenset({"Coffee"})))
    rows = _rows(10)
    seeded = await _seed(db, test_user.id, rows)
    sessions = _sessions(db)

    result = await statement_preclassification.classify_parsed_statement(
        sessions, statement_id=seeded.id, user_id=test_user.id
    )

    assert result is statement_preclassification.StatementClassificationPhase.PARTIAL
    assert outcomes == ["partial"]
    assert partial.rows_asked == 10
    assert len(await _classification_rows(sessions, test_user.id)) == 8, "the two Coffee rows have no answer"

    healthy = _install(monkeypatch, CountingProposer())
    response = await _approve(client, seeded.id)

    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 10
    assert sorted(description for call in healthy.calls for description in call) == ["Coffee 001", "Coffee 006"]


async def test_AC_extraction_statement_classify_3_the_one_click_fill_takes_the_same_lock(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.3: the fill of the default categories waits for the lock like the approve."""
    from src.extraction.extension.transaction_classification import try_lock_statement_classification

    monkeypatch.setattr(transaction_classification, "CLASSIFICATION_LOCK_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(transaction_classification, "_LOCK_POLL_SECONDS", 0.01)
    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(4))
    sessions = _sessions(db)

    async with sessions() as holder:
        assert await try_lock_statement_classification(holder, seeded.id)
        response = await asyncio.wait_for(
            client.post(
                f"/statements/{seeded.id}/review/approve",
                json={"create_account_if_missing": True, "auto_fill_default_categories": True},
            ),
            timeout=WAIT_SECONDS,
        )
        await holder.rollback()

    assert response.status_code == 409, response.text
    assert proposer.calls == []


async def test_AC_extraction_statement_classify_6_the_source_bytes_are_released_before_the_model_is_asked(
    db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.6: the pass holds no copy of the uploaded file (the memory limit of #2595)."""
    freed: list[bool] = []

    class Payload(bytes):  # a bytes object that tells when the interpreter frees it
        def __del__(self):
            freed.append(True)

    file_is_freed_when_asked: list[bool] = []

    async def probing_proposer(transactions, _policy):
        gc.collect()
        file_is_freed_when_asked.append(bool(freed))
        return [
            CategoryProposal(category=ANSWERS[t.description.split()[0]][0].value, confidence=95, reason="fixture")
            for t in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", probing_proposer)
    payload = Payload(_csv(_rows(3)))
    file_hash = hashlib.sha256(payload).hexdigest()
    statement_id = await _new_parsing_statement(db, test_user.id, file_hash)
    run = _use_case(db).execute(_job(statement_id, test_user.id, "release.csv", file_hash), content=payload)
    del payload  # the test keeps no copy either

    outcome = await run

    assert outcome.status is StatementIngestionStatus.COMPLETED
    assert file_is_freed_when_asked == [True], "the file bytes are still alive when the model is asked"


async def test_AC_extraction_statement_classify_3_two_statements_that_share_rows_answer_each_row_once(
    db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.3: a row shared by two statements gets one answer, and no pass fails.

    Dedup adds the document of a second upload to the rows that it shares with the first. The two passes take two
    locks, so both ask the model for the shared rows. The second writer must see the rows of the first.
    """
    from src.extraction.extension import statement_preclassification

    outcomes = _spy_outcomes(monkeypatch)
    gate = asyncio.Event()
    proposer = _install(monkeypatch, CountingProposer(gate=gate))
    first = await seed_parsed_statement(db, test_user.id, original_filename="first.pdf", transactions=_rows(4))
    second = await seed_parsed_statement(
        db, test_user.id, original_filename="second.pdf", transactions=_rows(4, first_day=date(2026, 2, 1))
    )
    marker = {"doc_id": str(second.document.id), "doc_type": "bank_statement"}
    for shared in first.transactions[:2]:
        shared.source_documents = [*shared.source_documents, marker]
    await db.commit()
    sessions = _sessions(db)

    passes = [
        asyncio.create_task(
            statement_preclassification.classify_parsed_statement(sessions, statement_id=item.id, user_id=test_user.id)
        )
        for item in (first, second)
    ]
    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    while len(proposer.calls) < 2:  # both passes read "no answer" for the shared rows before any pass writes
        assert asyncio.get_running_loop().time() < deadline, "a pass never asked the model"
        await asyncio.sleep(0.01)
    gate.set()
    results = await asyncio.wait_for(asyncio.gather(*passes), timeout=WAIT_SECONDS)

    classified = statement_preclassification.StatementClassificationPhase.CLASSIFIED
    assert results == [classified, classified], outcomes
    stored = await _classification_rows(sessions, test_user.id)
    assert len(stored) == 8, "four rows of the first statement and four own rows of the second"
    assert len({row.atomic_txn_id for row in stored}) == 8


async def test_AC_extraction_statement_classify_3_an_approve_that_waits_holds_no_row_lock_of_the_statement(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.3: the approve takes the classification lock before the statement row.

    A poll is invisible to the deadlock detector of the database. An approve that held the row while it polled could
    form a cycle with a request that holds the classification lock and wants the row.
    """
    attempts: list[bool] = []
    real_try_lock = transaction_classification.try_lock_statement_classification

    async def counting_try_lock(session, statement_id):
        acquired = await real_try_lock(session, statement_id)
        attempts.append(acquired)
        return acquired

    monkeypatch.setattr(transaction_classification, "try_lock_statement_classification", counting_try_lock)
    monkeypatch.setattr(transaction_classification, "_LOCK_POLL_SECONDS", 0.01)
    _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(4))
    sessions = _sessions(db)

    async with sessions() as holder:
        assert await real_try_lock(holder, seeded.id)
        approve = asyncio.create_task(_approve(client, seeded.id))
        deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
        while attempts.count(False) < 3:
            assert asyncio.get_running_loop().time() < deadline, "the approve never asked for the lock"
            await asyncio.sleep(0.01)
        async with sessions() as probe:
            # NOWAIT raises when the approve holds the row.
            row = await probe.execute(
                select(StatementSummary.id).where(StatementSummary.id == seeded.id).with_for_update(nowait=True)
            )
            assert row.scalar_one() == seeded.id
            await probe.rollback()
        await holder.rollback()

    response = await asyncio.wait_for(approve, timeout=WAIT_SECONDS)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("setting", ["enable_ai_classification", "auto_accept_ai_suggestions"])
async def test_AC_extraction_statement_classify_3_a_setting_turned_off_after_the_phase_does_not_undo_its_rows(
    client, db, test_user, monkeypatch, setting
):
    """AC-extraction.statement-classify.3: the rows of the pass stay as stored when a user changes a setting later.

    This pins the difference from main that the readme states: main reads the setting at the approval.
    """
    from src.extraction.extension import statement_preclassification

    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(8))
    sessions = _sessions(db)
    await statement_preclassification.classify_parsed_statement(sessions, statement_id=seeded.id, user_id=test_user.id)
    assert proposer.rows_asked == 8

    monkeypatch.setattr(settings, setting, False)
    response = await _approve(client, seeded.id)

    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 8
    assert proposer.rows_asked == 8, "the approve asks no row, and it does not drop a stored row"


# ---------------------------------------------------------------------------------------------------------
# AC-extraction.statement-classify.4: what gets classified does not change
# ---------------------------------------------------------------------------------------------------------


async def test_AC_extraction_statement_classify_4_each_row_gets_the_policy_of_its_own_date(db, test_user, monkeypatch):
    """AC-extraction.statement-classify.4: the policy in effect on the date of a row classifies it, as at approve."""
    from src.extraction.extension import statement_preclassification

    first, second = transaction_classification.POLICY_VERSIONS
    cutover = date(2026, 1, 6)
    registry = (
        ClassificationPolicy(**{**first.model_dump(), "effective_from": date.min}),
        ClassificationPolicy(**{**second.model_dump(), "effective_from": cutover}),
    )
    monkeypatch.setattr(transaction_classification, "POLICY_VERSIONS", registry)
    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(10))
    sessions = _sessions(db)

    await statement_preclassification.classify_parsed_statement(sessions, statement_id=seeded.id, user_id=test_user.id)

    async with sessions() as session:
        stored = (
            await session.execute(
                select(AtomicTransaction.txn_date, ClassificationRule.version_number)
                .join(TransactionClassification, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
                .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
                .where(AtomicTransaction.user_id == test_user.id)
            )
        ).all()
    assert len(stored) == 10
    assert {version for _date, version in stored} == {1, 2}, "the fixture spans both policies"
    for txn_date, version in stored:
        assert version == (1 if txn_date < cutover else 2)
    assert len(proposer.calls) == 2, "one call for each policy version"


async def _add_coffee_rule(db: AsyncSession, user_id: UUID) -> UUID:
    account = Account(user_id=user_id, name="Expense - Reviewed Coffee", type=AccountType.EXPENSE, currency="SGD")
    db.add(account)
    await db.flush()
    db.add(
        ClassificationRule(
            user_id=user_id,
            created_by=user_id,
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


async def test_AC_extraction_statement_classify_4_a_rule_made_after_the_phase_wins_at_approve(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.4: the rules pre-pass runs at approve, and a reviewed rule beats a model row."""
    proposer = _install(monkeypatch, CountingProposer())
    rows = _rows(5)
    statement_id = await _ingest_csv(db, test_user.id, "rule_after.csv", rows)
    assert proposer.rows_asked == 5
    await _confirm_csv_envelope(client, db, test_user.id, statement_id, rows)
    rule_account_id = await _add_coffee_rule(db, test_user.id)

    response = await _approve(client, statement_id)

    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 5
    assert proposer.rows_asked == 5, "the approve asks no model"
    async with _sessions(db)() as session:
        coffee = (
            await session.execute(
                select(AtomicTransaction).where(
                    AtomicTransaction.user_id == test_user.id, AtomicTransaction.description.like("Coffee%")
                )
            )
        ).scalar_one()
        posted_accounts = set(
            (
                await session.execute(
                    select(JournalLine.account_id)
                    .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
                    .where(JournalEntry.source_id == coffee.id)
                )
            ).scalars()
        )
    assert rule_account_id in posted_accounts, "the entry posts to the account of the reviewed rule"


async def test_AC_extraction_statement_classify_4_the_phase_writes_no_rule_row_and_asks_no_row_of_a_rule(
    db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.4: a rule that matches at parse keeps its row for the approve to write.

    The approve writes the rule row, as on main, so a rule that a user changes between parse and approve does not
    apply from a stale row. The model is not asked for a row that a rule matches, as on main.
    """
    from src.extraction.extension import statement_preclassification

    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(5))
    await _add_coffee_rule(db, test_user.id)
    sessions = _sessions(db)

    await statement_preclassification.classify_parsed_statement(sessions, statement_id=seeded.id, user_id=test_user.id)

    assert not any(description.startswith("Coffee") for call in proposer.calls for description in call)
    assert proposer.rows_asked == 4
    async with sessions() as session:
        rule_rows = await session.scalar(
            select(func.count())
            .select_from(TransactionClassification)
            .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
            .where(ClassificationRule.rule_type == RuleType.KEYWORD_MATCH, ClassificationRule.user_id == test_user.id)
        )
    assert rule_rows == 0


async def test_AC_extraction_statement_classify_4_a_row_with_an_unresolved_currency_waits_for_the_approve(
    db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.4: the account of an answer follows the currency, so the phase leaves the row.

    A row with the placeholder currency would get an account in that placeholder currency. The reviewer sets the
    currency later, and the approve then classifies the row under the right currency, as on main.
    """
    from src.extraction.extension import statement_preclassification

    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(4))
    unresolved = seeded.transactions[0]
    unresolved.currency = "XXX"
    unresolved.currency_unresolved = True
    await db.commit()
    sessions = _sessions(db)

    await statement_preclassification.classify_parsed_statement(sessions, statement_id=seeded.id, user_id=test_user.id)

    assert proposer.rows_asked == 3
    assert unresolved.description not in {description for call in proposer.calls for description in call}
    async with sessions() as session:
        accounts_in_placeholder = await session.scalar(
            select(func.count()).select_from(Account).where(Account.user_id == test_user.id, Account.currency == "XXX")
        )
    assert accounts_in_placeholder == 0


async def test_AC_extraction_statement_classify_4_a_row_that_an_entry_covers_is_left_alone(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.4: the approval skips a row that has an entry, and so does the pass."""
    from src.extraction.extension import statement_preclassification

    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(4))
    bank = Account(user_id=test_user.id, name="Bank of a covered row", type=AccountType.ASSET, currency="SGD")
    expense = Account(user_id=test_user.id, name="Expense - Reviewed", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([bank, expense])
    await db.flush()
    seeded.statement.account_id = bank.id
    await db.commit()
    covered = seeded.transactions[1]  # "Coffee 001", an outgoing row
    posted = await client.post(
        f"/reconciliation/unmatched/{covered.id}/reviewed-disposition",
        json={
            "intent": "expense",
            "counter_account_id": str(expense.id),
            "category": "GENERAL",
            "rationale": "Reviewed against the source.",
        },
    )
    assert posted.status_code == 200, posted.text
    sessions = _sessions(db)

    await statement_preclassification.classify_parsed_statement(sessions, statement_id=seeded.id, user_id=test_user.id)

    assert proposer.rows_asked == 3
    assert covered.description not in {description for call in proposer.calls for description in call}
    assert covered.id not in {row.atomic_txn_id for row in await _classification_rows(sessions, test_user.id)}


@pytest.mark.parametrize(
    ("state", "label"),
    [("approved", "SKIPPED_STATE"), ("rejected", "SKIPPED_STATE"), ("ai-off", "SKIPPED_DISABLED")],
)
async def test_AC_extraction_statement_classify_4_the_phase_leaves_a_statement_that_approve_does_not_classify(
    db, test_user, monkeypatch, state, label
):
    """AC-extraction.statement-classify.4: only a parsed statement of a user with the model on is classified."""
    from src.extraction.extension import statement_preclassification

    proposer = _install(monkeypatch, CountingProposer())
    seeded = await _seed(db, test_user.id, _rows(4))
    if state == "approved":
        bank = Account(
            user_id=test_user.id, name="Bank of an approved statement", type=AccountType.ASSET, currency="SGD"
        )
        db.add(bank)
        await db.flush()
        seeded.statement.account_id = bank.id
        seeded.statement.status = BankStatementStatus.APPROVED
    elif state == "rejected":
        seeded.statement.status = BankStatementStatus.REJECTED
    else:
        monkeypatch.setattr(settings, "enable_ai_classification", False)
    await db.commit()
    sessions = _sessions(db)

    result = await statement_preclassification.classify_parsed_statement(
        sessions, statement_id=seeded.id, user_id=test_user.id
    )

    assert result is statement_preclassification.StatementClassificationPhase[label]
    assert proposer.calls == []
    assert await _classification_rows(sessions, test_user.id) == []


async def test_AC_extraction_statement_classify_4_a_statement_without_rows_or_with_unresolvable_rows_is_left_alone(
    db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.4: the approval raises the error of unresolvable rows, so the pass leaves them."""
    from src.extraction.extension import statement_preclassification

    proposer = _install(monkeypatch, CountingProposer())
    empty = await _seed(db, test_user.id, [])
    seeded = await _seed(db, test_user.id, _rows(3))
    sessions = _sessions(db)

    empty_result = await statement_preclassification.classify_parsed_statement(
        sessions, statement_id=empty.id, user_id=test_user.id
    )

    async def unresolvable(_session, _statement):
        raise ValueError("Current source transaction identity requires review")

    monkeypatch.setattr(statement_preclassification, "resolve_statement_transactions", unresolvable)
    unresolvable_result = await statement_preclassification.classify_parsed_statement(
        sessions, statement_id=seeded.id, user_id=test_user.id
    )

    assert empty_result is statement_preclassification.StatementClassificationPhase.NOTHING_TO_CLASSIFY
    assert unresolvable_result is statement_preclassification.StatementClassificationPhase.SKIPPED_STATE
    assert proposer.calls == []


# ---------------------------------------------------------------------------------------------------------
# AC-extraction.statement-classify.5: the written state equals the state of main
# ---------------------------------------------------------------------------------------------------------


async def _read_state(client, db: AsyncSession) -> dict:
    """Every table that holds rows, with identifiers labelled by meaning, and the two reports."""
    balance = await client.get("/reports/balance-sheet", params={"as_of_date": "2026-03-31", "currency": "SGD"})
    assert balance.status_code == 200, balance.text
    income = await client.get(
        "/reports/income-statement",
        params={"start_date": "2026-01-01", "end_date": "2026-03-31", "currency": "SGD"},
    )
    assert income.status_code == 200, income.text
    tokens = {str(row["id"]): f"account:{row['name']}" for row in await _rows_of(db, "accounts")}
    return {
        "tables": await snapshot_state(db),
        "reports": {
            "balance_sheet": _normalize(balance.json(), tokens),
            "income_statement": _normalize(income.json(), tokens),
        },
    }


async def build_classified_state(client, db: AsyncSession, user_id: UUID) -> dict:
    """Ingest, review and approve two CSV statements with the fake model, then read every table and the reports.

    The first statement has one row of each kind, so the state covers the gate: applied rows, a non-P&L draft with
    its Processing leg, a balance-sheet account, the review band, a score below it and a class that contradicts the
    direction of its row.
    """
    january = _rows(len(GATE_KINDS), first_day=date(2026, 1, 1), kinds=GATE_KINDS)
    february = _rows(5, first_day=date(2026, 2, 10))
    for name, rows in (("classify_equivalence_jan.csv", january), ("classify_equivalence_feb.csv", february)):
        statement_id = await _ingest_csv(db, user_id, name, rows)
        await _confirm_csv_envelope(client, db, user_id, statement_id, rows)
        response = await _approve(client, statement_id)
        assert response.status_code == 200, response.text
        assert response.json()["journal_entries_created"] == len(rows)
    return await _read_state(client, db)


async def build_review_path_state(client, db: AsyncSession, user_id: UUID) -> dict:
    """Ingest, review and approve one CSV statement for a user with auto-accept off.

    Rows with a score from 60 to 84 stay drafts, and a row below 60 gets no row. The approve then answers 409, and
    the state holds what the attempt wrote.
    """
    rows = _rows(6, kinds=["Salary", "Coffee", "Fee", "Mystery", "Transfer", "Grab"])
    statement_id = await _ingest_csv(db, user_id, "classify_review_path.csv", rows)
    await _confirm_csv_envelope(client, db, user_id, statement_id, rows)
    response = await _approve(client, statement_id)
    assert response.status_code == 409, response.text
    return await _read_state(client, db)


async def test_AC_extraction_statement_classify_5_state_after_parse_classify_approve_equals_main(
    client, db, test_user, monkeypatch
):
    """AC-extraction.statement-classify.5: classifications, entries, trace graph and reports equal the state of main.

    The golden file holds the state that ``main`` at ``d213429b2`` wrote for the same fixture and the same fake
    model: there the ingestion asked nothing and the approve asked for every row. Here the ingestion asks and the
    approve asks nothing, and every table holds the same rows.
    """
    proposer = _install(monkeypatch, CountingProposer())

    state = await build_classified_state(client, db, test_user.id)

    # The fixture covers what the golden must hold. An empty golden would pass a broken change.
    assert len(state["tables"]["transaction_classification"]) == len(GATE_KINDS) + 5
    assert len(state["tables"]["journal_entries"]) >= len(GATE_KINDS) + 5
    assert state["reports"]["income_statement"]
    assert proposer.rows_asked == len(GATE_KINDS) + 5
    assert state == json.loads(GOLDEN_PATH.read_text())


async def test_AC_extraction_statement_classify_5_review_path_state_equals_main(client, db, test_user, monkeypatch):
    """AC-extraction.statement-classify.5: with auto-accept off the drafts, the tail and the 409 equal the state of main.

    On main the approve asks for the six rows and writes the drafts. Here the pass writes them, and the approve asks
    again only for the row that got no row.
    """
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    proposer = _install(monkeypatch, CountingProposer())

    state = await build_review_path_state(client, db, test_user.id)

    stored = state["tables"]["transaction_classification"]
    assert {row["status"] for row in stored} == {"applied", "draft"}, "the fixture holds applied rows and drafts"
    assert len(stored) == 5, "the row below the review score has no row"
    assert proposer.rows_asked == 6 + 1, "the pass asks for six rows, the approve for the one without a row"
    assert state == json.loads(REVIEW_PATH_GOLDEN_PATH.read_text())


async def test_AC_extraction_statement_classify_5_the_goldens_have_one_row_to_a_line():
    """AC-extraction.statement-classify.5: one row to a line, so that a review reads a change as a line diff."""
    for path in (GOLDEN_PATH, REVIEW_PATH_GOLDEN_PATH):
        text_of_golden = path.read_text()
        assert text_of_golden == format_golden(json.loads(text_of_golden)), path.name
