"""A user classify run with hints asks again for the rows that have a model answer (#2994, slice S4b-1 review).

With auto-accept on, every row has an answer after the automatic run, even the fallback. A user run with hints
would otherwise find nothing to ask. It asks again for each row whose answer is a model answer and appends the new
answer: the old answer becomes history (`SUPERSEDED`), and the unique key covers only the live answers. A run with
no hints, or a run whose prompt an earlier run of the statement already used for a row, does not ask for that row.
It never touches a keyword-rule answer, a decision of the user or a row that the ledger covers.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from src.database import create_session_maker_from_db
from src.extraction import ClassificationStatus, RunHints, RunState, record_correction, start_user_classify_run
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.transaction_classification import (
    CategoryProposal,
    TransactionCategory,
    classification_suggestions,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import TransactionClassification
from src.extraction.orm.statement_run import StatementRun
from src.ledger import Account, AccountType
from tests.extraction.test_statement_classify_run import (
    ANSWERS,
    _add_coffee_rule,
    _answers,
    _install,
    _model_on,  # noqa: F401 - the autouse fixture of the sibling module
    _rows,
    _run,
    _seed,
)
from tests.extraction._statement_run_helpers import _worker
from tests.statement_ingestion import classify_statement

HINTS = RunHints(keywords=["Grab"], note="Grab rides are transport.")
OTHER_HINTS = RunHints(keywords=["Grab"], note="Grab rides are transport, always.")
LIVE = (ClassificationStatus.DRAFT, ClassificationStatus.APPLIED)


class ReaskModel:
    """A model that answers each kind by ANSWERS. It calls Grab SHOPPING, unless the hints name Grab.

    `during` is an optional coroutine function that runs inside each call: a test uses it to change the database
    while the model call is open, as another request would. `confidence` overrides the confidence of a kind.
    """

    def __init__(self, *failures: BaseException | None, during=None, confidence: dict[str, int] | None = None) -> None:
        self.failures = failures
        self.during = during
        self.confidence = confidence or {}
        self.calls: list[list[str]] = []
        self.hints: list[RunHints | None] = []

    async def __call__(self, transactions, _policy, hints=None):
        number = len(self.calls)
        self.calls.append([transaction.description for transaction in transactions])
        self.hints.append(hints)
        if self.during is not None:
            await self.during(number, transactions)
        if number < len(self.failures) and self.failures[number] is not None:
            raise self.failures[number]
        follows = hints is not None and "Grab" in hints.keywords
        proposals = []
        for transaction in transactions:
            kind = transaction.description.split()[0]
            category, confidence = ANSWERS[kind]
            if kind == "Grab" and not follows:
                category = TransactionCategory.SHOPPING
            confidence = self.confidence.get(kind, confidence)
            proposals.append(CategoryProposal(category=category.value, confidence=confidence, reason="fixture"))
        return proposals

    @property
    def asked(self) -> set[str]:
        return {description for call in self.calls for description in call}

    @property
    def asked_kinds(self) -> set[str]:
        return {description.split()[0] for description in self.asked}


async def _history(db, user, description: str) -> list[TransactionClassification]:
    """Every answer of the row with this description, oldest first, read again from the database."""
    result = await db.execute(
        select(TransactionClassification)
        .join(AtomicTransaction, AtomicTransaction.id == TransactionClassification.atomic_txn_id)
        .where(AtomicTransaction.user_id == user.id, AtomicTransaction.description.like(f"{description}%"))
        .order_by(TransactionClassification.created_at, TransactionClassification.id)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars())


async def _answer(db, user, description: str) -> TransactionClassification:
    """The one live answer of the row with this description."""
    live = [row for row in await _history(db, user, description) if row.status in LIVE]
    assert len(live) == 1, f"{description}: {len(live)} live answers"
    return live[0]


async def _live_count(db, user) -> int:
    return len([await _answer(db, user, kind) for kind in ANSWERS])


async def _user_run(db, statement_id, user, hints: RunHints = HINTS):
    run_id = await start_user_classify_run(db, statement_id=statement_id, user_id=user.id, hints=hints)
    await db.commit()
    return run_id


async def _classified_statement(db, user, monkeypatch, rows=None, model=None):
    """A parsed statement whose automatic run answered every row. Return the statement, the run id and the model."""
    seeded = await _seed(db, user, rows or _rows(5))
    model = _install(monkeypatch, model or ReaskModel())
    return seeded, await classify_statement(db, seeded.id), model


async def test_AC_extraction_2994_137_a_user_run_with_hints_asks_again_for_a_model_answer(db, test_user, monkeypatch):
    """AC-extraction.2994.137: The hints reach the model. The Grab row gets a new live answer with the new category."""
    seeded, auto_run_id, automatic = await _classified_statement(db, test_user, monkeypatch)
    before = await _answer(db, test_user, "Grab")
    before_id = before.id
    assert before.tags["category"] == "SHOPPING" and len(automatic.calls) == 1
    reasked = _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    run = await _run(db, run_id)
    after = await _answer(db, test_user, "Grab")
    assert (run.state, run.result_summary["outcome"]) == (RunState.SUCCEEDED, "classified")
    assert reasked.hints == [HINTS] and reasked.asked == {f"{kind} {i:03d}" for i, kind in enumerate(ANSWERS)}
    assert (after.tags["category"], after.id != before_id) == ("TRANSPORT", True), "the answer is a new row"
    assert await _live_count(db, test_user) == 5 and await _answers(db, test_user) == 10 and auto_run_id != run_id


async def test_AC_extraction_2994_137_a_row_with_a_keyword_rule_a_decision_or_a_posted_entry_is_not_asked_again(
    client, db, test_user, monkeypatch
):
    """AC-extraction.2994.137: A keyword-rule answer, a corrected row and a posted row stay as they are."""
    seeded = await _seed(db, test_user, _rows(5))
    await _add_coffee_rule(db, test_user)
    _install(monkeypatch, ReaskModel())
    auto_run_id = await classify_statement(db, seeded.id)
    bank = Account(user_id=test_user.id, name="Bank of a posted row", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Income - Reviewed", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, income])
    await db.flush()
    seeded.statement.account_id = bank.id
    await db.commit()
    posted = await client.post(
        f"/reconciliation/unmatched/{seeded.transactions[0].id}/reviewed-dispositions",
        json={
            "intent": "income",
            "counter_account_id": str(income.id),
            "category": "GENERAL",
            "rationale": "Reviewed.",
        },
    )
    assert posted.status_code == 200, posted.text
    rent_txn = next(txn for txn in seeded.transactions if txn.description.startswith("Rent"))
    await record_correction(db, user_id=test_user.id, transaction_id=rent_txn.id, corrected_category="utilities")
    await db.commit()
    stay = {name: (await _answer(db, test_user, name)).tags for name in ("Salary", "Coffee", "Rent")}
    reasked = _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert reasked.asked == {"Grab 002", "Refund 004"}, "only the rows with a model answer are asked again"
    for name, tags in stay.items():
        assert (await _answer(db, test_user, name)).tags == tags, name
        assert len(await _history(db, test_user, name)) == 1, f"{name} has no new answer"
    assert stay["Coffee"]["run_id"] == str(auto_run_id) and stay["Rent"]["category"] == "UTILITIES"
    assert stay["Rent"]["corrected_by_user"] is True, "the decision came from the correction service"


async def test_AC_extraction_2994_138_every_answer_that_a_run_writes_carries_its_run_id(db, test_user, monkeypatch):
    """AC-extraction.2994.138: The tags of a model answer, a re-asked answer and a rule answer name the run."""
    seeded = await _seed(db, test_user, _rows(5))
    await _add_coffee_rule(db, test_user)
    _install(monkeypatch, ReaskModel())
    auto_run_id = await classify_statement(db, seeded.id)
    for name in ("Salary", "Coffee", "Grab", "Rent", "Refund"):
        assert (await _answer(db, test_user, name)).tags["run_id"] == str(auto_run_id), name
    _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    assert (await _answer(db, test_user, "Coffee")).tags["run_id"] == str(auto_run_id), (
        "the rule row is not asked again"
    )
    for name in ("Salary", "Grab", "Rent", "Refund"):
        assert (await _answer(db, test_user, name)).tags["run_id"] == str(run_id), name
        assert [row.tags["run_id"] for row in await _history(db, test_user, name)] == [str(auto_run_id), str(run_id)]


async def test_AC_extraction_2994_139_an_automatic_run_still_asks_only_the_rows_without_an_answer(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.139: The automatic run asks nothing for answered rows and writes no answer."""
    seeded, first_run_id, _first = await _classified_statement(db, test_user, monkeypatch)
    before = {name: (await _answer(db, test_user, name)).tags for name in ("Salary", "Grab")}
    second = _install(monkeypatch, ReaskModel())

    second_run_id = await classify_statement(db, seeded.id)

    run = await _run(db, second_run_id)
    assert (run.state, run.result_summary["outcome"]) == (RunState.SUCCEEDED, "nothing_to_classify")
    assert second.calls == [] and first_run_id != second_run_id and await _answers(db, test_user) == 5
    assert {name: (await _answer(db, test_user, name)).tags for name in before} == before


async def test_AC_extraction_2994_140_a_re_ask_that_fails_in_batch_2_keeps_the_answers_of_batch_1(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.140: The answers of batch 1 are appended and committed. The rows of batch 2 keep theirs."""
    monkeypatch.setattr(tc, "CLASSIFICATION_BATCH_SIZE", 2)
    monkeypatch.setattr(tc, "CLASSIFICATION_PARALLEL_BATCHES", 1)
    seeded, auto_run_id, _automatic = await _classified_statement(db, test_user, monkeypatch)
    failing = _install(monkeypatch, ReaskModel(None, RuntimeError("provider down")))
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    run = await _run(db, run_id)
    assert (run.state, run.error_code) == (RunState.FAILED, "classification_failed")
    first_batch = {call.split()[0] for call in failing.calls[0]}
    runs_of = {kind: (await _answer(db, test_user, kind)).tags["run_id"] for kind in ANSWERS}
    assert {kind for kind, owner in runs_of.items() if owner == str(run_id)} == first_batch
    assert {kind for kind, owner in runs_of.items() if owner == str(auto_run_id)} == set(ANSWERS) - first_batch
    assert run.result_summary["batches_done"] == 1 and await _live_count(db, test_user) == 5
    assert await _answers(db, test_user) == 5 + len(first_batch), "one history row for each answer of batch 1"


async def test_AC_extraction_2994_141_a_re_ask_with_a_low_confidence_answer_writes_a_fallback_in_a_new_row(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.141: The new row is a fallback with the original tags of the new proposal. The old row stays."""
    seeded, auto_run_id, _automatic = await _classified_statement(db, test_user, monkeypatch)
    before_id = (await _answer(db, test_user, "Grab")).id

    class Unsure(ReaskModel):
        async def __call__(self, transactions, _policy, hints=None):
            proposals = await super().__call__(transactions, _policy, hints)
            return [
                CategoryProposal(category=proposal.category, confidence=10, reason="unsure")
                if transaction.description.startswith("Grab")
                else proposal
                for transaction, proposal in zip(transactions, proposals, strict=True)
            ]

    _install(monkeypatch, Unsure())
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    old, row = await _history(db, test_user, "Grab")
    account = await db.scalar(select(Account.name).where(Account.id == row.account_id))
    assert (old.id, old.status, old.superseded_by_id) == (before_id, ClassificationStatus.SUPERSEDED, row.id)
    assert old.tags["category"] == "SHOPPING" and old.tags["run_id"] == str(auto_run_id)
    assert row.id != before_id and account == "General Expense (SGD)"
    assert (row.tags["category"], row.tags["original_category"], row.tags["original_confidence"]) == (
        "UNCLASSIFIED",
        "TRANSPORT",
        10,
    )
    assert (row.confidence_score, row.tags["run_id"]) == (0, str(run_id))


async def test_AC_extraction_2994_144_a_re_ask_appends_the_answer_and_keeps_the_old_answer_as_history(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.144: After two runs with other hints, both answers exist. Only the last one is live."""
    seeded, auto_run_id, _automatic = await _classified_statement(db, test_user, monkeypatch)
    _install(monkeypatch, ReaskModel())
    first_run_id = await _user_run(db, seeded.id, test_user, HINTS)
    await _worker(create_session_maker_from_db(db), first_run_id)
    _install(monkeypatch, ReaskModel())
    second_run_id = await _user_run(db, seeded.id, test_user, OTHER_HINTS)

    await _worker(create_session_maker_from_db(db), second_run_id)

    first, second, third = await _history(db, test_user, "Grab")
    assert [row.status for row in (first, second, third)] == [
        ClassificationStatus.SUPERSEDED,
        ClassificationStatus.SUPERSEDED,
        ClassificationStatus.APPLIED,
    ]
    assert (first.superseded_by_id, second.superseded_by_id, third.superseded_by_id) == (second.id, third.id, None)
    owners = [first.tags["run_id"], second.tags["run_id"], third.tags["run_id"]]
    assert owners == [str(auto_run_id), str(first_run_id), str(second_run_id)]
    runs = await db.execute(select(StatementRun).where(StatementRun.id.in_([first_run_id, second_run_id])))
    hints_of = {str(run.id): run.hints for run in runs.scalars()}
    assert hints_of[owners[1]] == HINTS.model_dump(mode="json")
    assert hints_of[owners[2]] == OTHER_HINTS.model_dump(mode="json"), "the run id leads to the hints of the answer"
    suggestion = (await classification_suggestions(db, [third.atomic_txn_id]))[third.atomic_txn_id]
    assert (suggestion.classification_id, suggestion.category) == (third.id, "TRANSPORT"), "readers see the live answer"
    assert await _live_count(db, test_user) == 5


@pytest.mark.parametrize("strip_run_ids", [False, True], ids=["answers_of_a_run", "answers_without_a_run_id"])
async def test_AC_extraction_2994_149_a_user_run_with_no_hints_asks_only_the_rows_without_an_answer(
    db, test_user, monkeypatch, strip_run_ids
):
    """AC-extraction.2994.149: With no hints the prompt equals the automatic prompt. The run asks nothing again."""
    seeded, _auto_run_id, _automatic = await _classified_statement(db, test_user, monkeypatch)
    if strip_run_ids:  # the answers that an earlier release wrote have no run id: only the empty hints protect them
        await db.execute(
            update(TransactionClassification).values(tags=TransactionClassification.tags.op("-")("run_id"))
        )
        await db.commit()
    quiet = _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user, RunHints())

    await _worker(create_session_maker_from_db(db), run_id)

    run = await _run(db, run_id)
    assert (run.state, run.result_summary["outcome"]) == (RunState.SUCCEEDED, "nothing_to_classify")
    assert quiet.calls == [] and await _answers(db, test_user) == 5


async def test_AC_extraction_2994_150_a_run_that_failed_resumes_and_skips_the_rows_that_it_answered(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.150: A run with the same hints skips the rows of the failed run. Other hints ask every row."""
    monkeypatch.setattr(tc, "CLASSIFICATION_BATCH_SIZE", 2)
    monkeypatch.setattr(tc, "CLASSIFICATION_PARALLEL_BATCHES", 1)
    seeded, _auto_run_id, _automatic = await _classified_statement(db, test_user, monkeypatch)
    failing = _install(monkeypatch, ReaskModel(None, RuntimeError("provider down")))
    failed_run_id = await _user_run(db, seeded.id, test_user, HINTS)
    await _worker(create_session_maker_from_db(db), failed_run_id)
    assert (await _run(db, failed_run_id)).state is RunState.FAILED
    answered = {call.split()[0] for call in failing.calls[0]}
    resumed = _install(monkeypatch, ReaskModel())
    resume_id = await _user_run(db, seeded.id, test_user, HINTS)

    await _worker(create_session_maker_from_db(db), resume_id)

    assert (await _run(db, resume_id)).state is RunState.SUCCEEDED
    assert resumed.asked_kinds == set(ANSWERS) - answered, "only the rest is asked"
    owners = {kind: (await _answer(db, test_user, kind)).tags["run_id"] for kind in answered}
    assert owners == {kind: str(failed_run_id) for kind in answered}, "the answers of the failed run stay live"
    other = _install(monkeypatch, ReaskModel())
    other_id = await _user_run(db, seeded.id, test_user, OTHER_HINTS)

    await _worker(create_session_maker_from_db(db), other_id)

    assert other.asked_kinds == set(ANSWERS), "other hints ask every row"


async def test_AC_extraction_3057_superseded_row_for_current_policy_does_not_block_classify(db, test_user, monkeypatch):
    """#3057: An orphaned SUPERSEDED row under the current policy version must not skip automatic classification."""
    seeded, _auto_run_id, _automatic = await _classified_statement(db, test_user, monkeypatch)
    grab_answer = await _answer(db, test_user, "Grab")
    grab_answer.status = ClassificationStatus.SUPERSEDED
    await db.commit()

    rerun = _install(monkeypatch, ReaskModel())
    second_run_id = await classify_statement(db, seeded.id)

    assert (await _run(db, second_run_id)).state is RunState.SUCCEEDED
    assert rerun.asked_kinds == {"Grab"}, "the superseded row has no live answer and must be classified"
    live_grab = await _answer(db, test_user, "Grab")
    assert live_grab.status in (ClassificationStatus.APPLIED, ClassificationStatus.DRAFT)
    assert live_grab.tags["run_id"] == str(second_run_id)


async def test_void_entry_allows_reask_and_settlement_skips_covered(db, test_user, monkeypatch):
    from src.composition import compose_reviewed_disposition_dependencies
    from src.config import settings
    from src.extraction import EconomicIntent, settle_drafts_after_posting
    from src.ledger import JournalEntry, JournalEntryStatus, void_journal_entry
    from src.reconciliation import ReviewedDispositionCommand, submit_reviewed_disposition

    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    seeded, _auto_run_id, _ = await _classified_statement(
        db, test_user, monkeypatch, model=ReaskModel(confidence={"Grab": 75})
    )
    grab_txn = next(t for t in seeded.transactions if t.description.startswith("Grab"))
    draft = await _answer(db, test_user, "Grab")
    bank = Account(user_id=test_user.id, name="Bank void test", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    seeded.statement.account_id = bank.id
    await db.flush()
    await submit_reviewed_disposition(
        db,
        transaction_id=grab_txn.id,
        user_id=test_user.id,
        command=ReviewedDispositionCommand(
            intent=EconomicIntent.EXPENSE,
            counter_account_id=draft.account_id,
            category="GENERAL",
            rationale="Posted before voiding.",
        ),
        dependencies=compose_reviewed_disposition_dependencies(db),
        base_currency="SGD",
    )
    posted_entry = await db.scalar(select(JournalEntry).where(JournalEntry.source_id == grab_txn.id))
    assert posted_entry is not None
    await void_journal_entry(db, posted_entry.id, "Voided before re-ask", test_user.id)
    await settle_drafts_after_posting(db, grab_txn.id, accepted_id=None)
    await db.commit()
    assert posted_entry.status is JournalEntryStatus.VOID

    reasked = _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)
    await _worker(create_session_maker_from_db(db), run_id)
    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert "Grab" in reasked.asked_kinds
