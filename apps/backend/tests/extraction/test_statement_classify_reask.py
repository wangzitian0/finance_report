"""A user classify run with hints asks again for the rows that have a model answer (#2994, slice S4b-1 review)."""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from src.composition import compose_reviewed_disposition_dependencies
from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import ClassificationStatus, EconomicIntent, RunHints, RunState, record_correction, settle_drafts_after_posting, start_user_classify_run
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory, classification_suggestions
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import TransactionClassification
from src.extraction.orm.statement_run import StatementRun
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus, void_journal_entry
from src.reconciliation import ReviewedDispositionCommand, submit_reviewed_disposition
from tests.extraction._statement_run_helpers import _worker, make_account
from tests.extraction.test_statement_classify_run import ANSWERS, _add_coffee_rule, _answers, _install, _model_on, _rows, _run, _seed  # noqa: F401
from tests.statement_ingestion import classify_statement

HINTS = RunHints(keywords=["Grab"], note="Grab rides are transport.")
OTHER_HINTS = RunHints(keywords=["Grab"], note="Grab rides are transport, always.")
LIVE = (ClassificationStatus.DRAFT, ClassificationStatus.APPLIED)


class ReaskModel:
    def __init__(self, *failures: BaseException | None, during=None, confidence: dict[str, int] | None = None) -> None:
        self.failures, self.during, self.confidence, self.calls, self.hints = failures, during, confidence or {}, [], []

    async def __call__(self, transactions, _policy, hints=None):
        number = len(self.calls)
        self.calls.append([t.description for t in transactions])
        self.hints.append(hints)
        if self.during is not None:
            await self.during(number, transactions)
        if number < len(self.failures) and self.failures[number] is not None:
            raise self.failures[number]
        follows = hints is not None and "Grab" in hints.keywords
        return [
            CategoryProposal(category=(TransactionCategory.SHOPPING if kind == "Grab" and not follows else cat).value, confidence=self.confidence.get(kind, conf), reason="fixture")
            for t in transactions
            for kind in [t.description.split()[0]]
            for cat, conf in [ANSWERS[kind]]
        ]

    @property
    def asked(self) -> set[str]:
        return {d for call in self.calls for d in call}

    @property
    def asked_kinds(self) -> set[str]:
        return {d.split()[0] for d in self.asked}


async def _history(db, user, description: str) -> list[TransactionClassification]:
    res = await db.execute(
        select(TransactionClassification).join(AtomicTransaction, AtomicTransaction.id == TransactionClassification.atomic_txn_id)
        .where(AtomicTransaction.user_id == user.id, AtomicTransaction.description.like(f"{description}%"))
        .order_by(TransactionClassification.created_at, TransactionClassification.id).execution_options(populate_existing=True)
    )
    return list(res.scalars())


async def _answer(db, user, description: str) -> TransactionClassification:
    live = [row for row in await _history(db, user, description) if row.status in LIVE]
    assert len(live) == 1
    return live[0]


async def _live_count(db, user) -> int:
    return len([await _answer(db, user, kind) for kind in ANSWERS])


async def _reask(db, statement_id, user, monkeypatch, hints: RunHints = HINTS, model=None):
    installed = _install(monkeypatch, model or ReaskModel())
    run_id = await start_user_classify_run(db, statement_id=statement_id, user_id=user.id, hints=hints)
    await db.commit()
    await _worker(create_session_maker_from_db(db), run_id)
    return run_id, installed


async def _classified_statement(db, user, monkeypatch, rows=None, model=None):
    seeded = await _seed(db, user, rows or _rows(5))
    installed = _install(monkeypatch, model or ReaskModel())
    return seeded, await classify_statement(db, seeded.id), installed


async def test_AC_extraction_2994_137_a_user_run_with_hints_asks_again_for_a_model_answer(db, test_user, monkeypatch):
    seeded, auto_run_id, automatic = await _classified_statement(db, test_user, monkeypatch)
    before = await _answer(db, test_user, "Grab")
    before_id = before.id
    assert before.tags["category"] == "SHOPPING" and len(automatic.calls) == 1
    run_id, reasked = await _reask(db, seeded.id, test_user, monkeypatch)
    run, after = await _run(db, run_id), await _answer(db, test_user, "Grab")
    assert (run.state, run.result_summary["outcome"], reasked.hints, reasked.asked, after.tags["category"], after.id != before_id, await _live_count(db, test_user), await _answers(db, test_user), auto_run_id != run_id) == (
        RunState.SUCCEEDED, "classified", [HINTS], {f"{k} {i:03d}" for i, k in enumerate(ANSWERS)}, "TRANSPORT", True, 5, 10, True
    )


async def test_AC_extraction_2994_137_a_row_with_a_keyword_rule_a_decision_or_a_posted_entry_is_not_asked_again(client, db, test_user, monkeypatch):
    seeded = await _seed(db, test_user, _rows(5))
    await _add_coffee_rule(db, test_user)
    _install(monkeypatch, ReaskModel())
    auto_run_id = await classify_statement(db, seeded.id)
    bank, income = await make_account(db, test_user.id, name="Bank of a posted row", type=AccountType.ASSET), await make_account(db, test_user.id, name="Income - Reviewed", type=AccountType.INCOME)
    seeded.statement.account_id = bank.id
    await db.commit()
    posted = await client.post(f"/reconciliation/unmatched/{seeded.transactions[0].id}/reviewed-dispositions", json={"intent": "income", "counter_account_id": str(income.id), "category": "GENERAL", "rationale": "Reviewed."})
    assert posted.status_code == 200, posted.text
    await record_correction(db, user_id=test_user.id, transaction_id=next(t for t in seeded.transactions if t.description.startswith("Rent")).id, corrected_category="utilities")
    await db.commit()
    stay = {name: (await _answer(db, test_user, name)).tags for name in ("Salary", "Coffee", "Rent")}
    run_id, reasked = await _reask(db, seeded.id, test_user, monkeypatch)
    assert ((await _run(db, run_id)).state, reasked.asked, stay["Coffee"]["run_id"], stay["Rent"]["category"], stay["Rent"]["corrected_by_user"]) == (RunState.SUCCEEDED, {"Grab 002", "Refund 004"}, str(auto_run_id), "UTILITIES", True)
    assert [(await _answer(db, test_user, n)).tags == tags and len(await _history(db, test_user, n)) == 1 for n, tags in stay.items()] == [True] * len(stay)


async def test_AC_extraction_2994_138_every_answer_that_a_run_writes_carries_its_run_id(db, test_user, monkeypatch):
    seeded = await _seed(db, test_user, _rows(5))
    await _add_coffee_rule(db, test_user)
    _install(monkeypatch, ReaskModel())
    auto_run_id = await classify_statement(db, seeded.id)
    assert [(await _answer(db, test_user, name)).tags["run_id"] for name in ANSWERS] == [str(auto_run_id)] * len(ANSWERS)
    run_id, _ = await _reask(db, seeded.id, test_user, monkeypatch)
    assert (await _answer(db, test_user, "Coffee")).tags["run_id"] == str(auto_run_id)
    for name in ("Salary", "Grab", "Rent", "Refund"):
        assert (await _answer(db, test_user, name)).tags["run_id"] == str(run_id) and [r.tags["run_id"] for r in await _history(db, test_user, name)] == [str(auto_run_id), str(run_id)]


async def test_AC_extraction_2994_139_an_automatic_run_still_asks_only_the_rows_without_an_answer(db, test_user, monkeypatch):
    seeded, first_run_id, _ = await _classified_statement(db, test_user, monkeypatch)
    before = {name: (await _answer(db, test_user, name)).tags for name in ("Salary", "Grab")}
    second = _install(monkeypatch, ReaskModel())
    second_run_id = await classify_statement(db, seeded.id)
    run = await _run(db, second_run_id)
    assert (run.state, run.result_summary["outcome"], second.calls, first_run_id != second_run_id, await _answers(db, test_user), {n: (await _answer(db, test_user, n)).tags for n in before}) == (RunState.SUCCEEDED, "nothing_to_classify", [], True, 5, before)


async def test_AC_extraction_2994_140_a_re_ask_that_fails_in_batch_2_keeps_the_answers_of_batch_1(db, test_user, monkeypatch):
    monkeypatch.setattr(tc, "CLASSIFICATION_BATCH_SIZE", 2)
    monkeypatch.setattr(tc, "CLASSIFICATION_PARALLEL_BATCHES", 1)
    seeded, auto_run_id, _ = await _classified_statement(db, test_user, monkeypatch)
    run_id, failing = await _reask(db, seeded.id, test_user, monkeypatch, model=ReaskModel(None, RuntimeError("provider down")))
    run, first_batch = await _run(db, run_id), {call.split()[0] for call in failing.calls[0]}
    runs_of = {kind: (await _answer(db, test_user, kind)).tags["run_id"] for kind in ANSWERS}
    assert (run.state, run.error_code, {k for k, o in runs_of.items() if o == str(run_id)}, {k for k, o in runs_of.items() if o == str(auto_run_id)}, run.result_summary["batches_done"], await _live_count(db, test_user), await _answers(db, test_user)) == (
        RunState.FAILED, "classification_failed", first_batch, set(ANSWERS) - first_batch, 1, 5, 5 + len(first_batch),
    )


async def test_AC_extraction_2994_141_a_re_ask_with_a_low_confidence_answer_writes_a_fallback_in_a_new_row(db, test_user, monkeypatch):
    seeded, auto_run_id, _ = await _classified_statement(db, test_user, monkeypatch)
    before_id = (await _answer(db, test_user, "Grab")).id

    class Unsure(ReaskModel):
        async def __call__(self, transactions, _policy, hints=None):
            return [CategoryProposal(category=p.category, confidence=10, reason="unsure") if t.description.startswith("Grab") else p for t, p in zip(transactions, await super().__call__(transactions, _policy, hints), strict=True)]

    run_id, _ = await _reask(db, seeded.id, test_user, monkeypatch, model=Unsure())
    old, row = await _history(db, test_user, "Grab")
    account = await db.scalar(select(Account.name).where(Account.id == row.account_id))
    assert (old.id, old.status, old.superseded_by_id, old.tags["category"], old.tags["run_id"], row.id != before_id, account, row.tags["category"], row.tags["original_category"], row.tags["original_confidence"], row.confidence_score, row.tags["run_id"]) == (
        before_id, ClassificationStatus.SUPERSEDED, row.id, "SHOPPING", str(auto_run_id), True, "General Expense (SGD)", "UNCLASSIFIED", "TRANSPORT", 10, 0, str(run_id)
    )


async def test_AC_extraction_2994_144_a_re_ask_appends_the_answer_and_keeps_the_old_answer_as_history(db, test_user, monkeypatch):
    seeded, auto_run_id, _ = await _classified_statement(db, test_user, monkeypatch)
    first_run_id, _ = await _reask(db, seeded.id, test_user, monkeypatch, HINTS)
    second_run_id, _ = await _reask(db, seeded.id, test_user, monkeypatch, OTHER_HINTS)
    first, second, third = await _history(db, test_user, "Grab")
    owners = [first.tags["run_id"], second.tags["run_id"], third.tags["run_id"]]
    hints_of = {str(r.id): r.hints for r in (await db.execute(select(StatementRun).where(StatementRun.id.in_([first_run_id, second_run_id])))).scalars()}
    suggestion = (await classification_suggestions(db, [third.atomic_txn_id]))[third.atomic_txn_id]
    assert ([r.status for r in (first, second, third)], (first.superseded_by_id, second.superseded_by_id, third.superseded_by_id), owners, hints_of[owners[1]], hints_of[owners[2]], suggestion.classification_id, suggestion.category, await _live_count(db, test_user)) == (
        [ClassificationStatus.SUPERSEDED, ClassificationStatus.SUPERSEDED, ClassificationStatus.APPLIED], (second.id, third.id, None), [str(auto_run_id), str(first_run_id), str(second_run_id)], HINTS.model_dump(mode="json"), OTHER_HINTS.model_dump(mode="json"), third.id, "TRANSPORT", 5
    )


@pytest.mark.parametrize("strip_run_ids", [False, True], ids=["answers_of_a_run", "answers_without_a_run_id"])
async def test_AC_extraction_2994_149_a_user_run_with_no_hints_asks_only_the_rows_without_an_answer(db, test_user, monkeypatch, strip_run_ids):
    seeded, _, _ = await _classified_statement(db, test_user, monkeypatch)
    if strip_run_ids:
        await db.execute(update(TransactionClassification).values(tags=TransactionClassification.tags.op("-")("run_id")))
        await db.commit()
    run_id, quiet = await _reask(db, seeded.id, test_user, monkeypatch, RunHints())
    run = await _run(db, run_id)
    assert (run.state, run.result_summary["outcome"], quiet.calls, await _answers(db, test_user)) == (RunState.SUCCEEDED, "nothing_to_classify", [], 5)


async def test_AC_extraction_2994_150_a_run_that_failed_resumes_and_skips_the_rows_that_it_answered(db, test_user, monkeypatch):
    monkeypatch.setattr(tc, "CLASSIFICATION_BATCH_SIZE", 2)
    monkeypatch.setattr(tc, "CLASSIFICATION_PARALLEL_BATCHES", 1)
    seeded, _, _ = await _classified_statement(db, test_user, monkeypatch)
    failed_run_id, failing = await _reask(db, seeded.id, test_user, monkeypatch, HINTS, ReaskModel(None, RuntimeError("provider down")))
    assert (await _run(db, failed_run_id)).state is RunState.FAILED
    answered = {call.split()[0] for call in failing.calls[0]}
    resume_id, resumed = await _reask(db, seeded.id, test_user, monkeypatch, HINTS)
    assert ((await _run(db, resume_id)).state, resumed.asked_kinds, {k: (await _answer(db, test_user, k)).tags["run_id"] for k in answered}) == (RunState.SUCCEEDED, set(ANSWERS) - answered, {k: str(failed_run_id) for k in answered})
    _, other = await _reask(db, seeded.id, test_user, monkeypatch, OTHER_HINTS)
    assert other.asked_kinds == set(ANSWERS)


async def test_AC_extraction_3057_superseded_row_for_current_policy_does_not_block_classify(db, test_user, monkeypatch):
    seeded, _, _ = await _classified_statement(db, test_user, monkeypatch)
    (await _answer(db, test_user, "Grab")).status = ClassificationStatus.SUPERSEDED
    await db.commit()
    rerun = _install(monkeypatch, ReaskModel())
    second_run_id = await classify_statement(db, seeded.id)
    live_grab = await _answer(db, test_user, "Grab")
    assert ((await _run(db, second_run_id)).state, rerun.asked_kinds, live_grab.status in LIVE, live_grab.tags["run_id"]) == (RunState.SUCCEEDED, {"Grab"}, True, str(second_run_id))


async def test_void_entry_allows_reask_and_settlement_skips_covered(db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", False)
    seeded, _, _ = await _classified_statement(db, test_user, monkeypatch, model=ReaskModel(confidence={"Grab": 75}))
    grab_txn, draft, bank = next(t for t in seeded.transactions if t.description.startswith("Grab")), await _answer(db, test_user, "Grab"), await make_account(db, test_user.id, name="Bank void test", type=AccountType.ASSET)
    seeded.statement.account_id = bank.id
    await db.flush()
    await submit_reviewed_disposition(db, transaction_id=grab_txn.id, user_id=test_user.id, command=ReviewedDispositionCommand(intent=EconomicIntent.EXPENSE, counter_account_id=draft.account_id, category="GENERAL", rationale="Posted before voiding."), dependencies=compose_reviewed_disposition_dependencies(db), base_currency="SGD")
    posted_entry = await db.scalar(select(JournalEntry).where(JournalEntry.source_id == grab_txn.id))
    assert posted_entry is not None
    await void_journal_entry(db, posted_entry.id, "Voided before re-ask", test_user.id)
    await settle_drafts_after_posting(db, grab_txn.id, accepted_id=None)
    await db.commit()
    run_id, reasked = await _reask(db, seeded.id, test_user, monkeypatch)
    assert (posted_entry.status, (await _run(db, run_id)).state, "Grab" in reasked.asked_kinds) == (JournalEntryStatus.VOID, RunState.SUCCEEDED, True)
