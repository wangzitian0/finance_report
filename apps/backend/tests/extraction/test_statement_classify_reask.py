"""A user classify run asks again for the rows that have only a model answer (#2994, slice S4b-1 review).

With auto-accept on, every row has an answer after the automatic run, even the fallback. A user run with hints
would otherwise find nothing to ask. It asks again for each row whose answer is a model answer, and it changes that
answer in place: the unique key allows one answer for each row and policy version. It never touches a keyword-rule
answer, a decision of the user or a row that a posted entry covers.
"""

from __future__ import annotations

from sqlalchemy import select, update

from src.database import create_session_maker_from_db
from src.extraction import RunHints, RunState, start_user_classify_run
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
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
from tests.extraction.test_statement_classify_run_phases import _worker
from tests.statement_ingestion import classify_statement

HINTS = RunHints(keywords=["Grab"], note="Grab rides are transport.")


class ReaskModel:
    """A model that answers each kind by ANSWERS. It calls Grab SHOPPING, unless the hints name Grab."""

    def __init__(self, *failures: BaseException | None) -> None:
        self.failures = failures
        self.calls: list[list[str]] = []
        self.hints: list[RunHints | None] = []

    async def __call__(self, transactions, _policy, hints=None):
        number = len(self.calls)
        self.calls.append([transaction.description for transaction in transactions])
        self.hints.append(hints)
        if number < len(self.failures) and self.failures[number] is not None:
            raise self.failures[number]
        follows = hints is not None and "Grab" in hints.keywords
        proposals = []
        for transaction in transactions:
            kind = transaction.description.split()[0]
            category, confidence = ANSWERS[kind]
            if kind == "Grab" and not follows:
                category = TransactionCategory.SHOPPING
            proposals.append(CategoryProposal(category=category.value, confidence=confidence, reason="fixture"))
        return proposals

    @property
    def asked(self) -> set[str]:
        return {description for call in self.calls for description in call}


async def _answer(db, user, description: str) -> TransactionClassification:
    """The one model or rule answer of the row with this description, read again from the database."""
    result = await db.execute(
        select(TransactionClassification)
        .join(AtomicTransaction, AtomicTransaction.id == TransactionClassification.atomic_txn_id)
        .where(AtomicTransaction.user_id == user.id, AtomicTransaction.description.like(f"{description}%"))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _user_run(db, statement_id, user, hints: RunHints = HINTS):
    run_id = await start_user_classify_run(db, statement_id=statement_id, user_id=user.id, hints=hints)
    await db.commit()
    return run_id


async def _classified_statement(db, user, monkeypatch, rows=None, model=None):
    """A parsed statement whose automatic run answered every row. Return the statement, the run id and the model."""
    seeded = await _seed(db, user, rows or _rows(5))
    model = _install(monkeypatch, model or ReaskModel())
    return seeded, await classify_statement(db, seeded.id), model


async def test_AC_extraction_2994_137_a_user_run_asks_again_for_a_model_answer_and_changes_it_in_place(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.137: The hints reach the model. The category of the Grab row changes in the same row."""
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
    assert (after.id, after.tags["category"]) == (before_id, "TRANSPORT"), "one answer for the row, changed in place"
    assert await _answers(db, test_user) == 5 and auto_run_id != run_id


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
        f"/reconciliation/unmatched/{seeded.transactions[0].id}/reviewed-disposition",
        json={"intent": "income", "counter_account_id": str(income.id), "category": "GENERAL", "rationale": "Reviewed."},
    )
    assert posted.status_code == 200, posted.text
    rent = await _answer(db, test_user, "Rent")
    await db.execute(
        update(TransactionClassification)
        .where(TransactionClassification.id == rent.id)
        .values(tags={**rent.tags, "category": "UTILITIES", "corrected_by_user": True})
    )
    await db.commit()
    stay = {name: (await _answer(db, test_user, name)).tags for name in ("Salary", "Coffee", "Rent")}
    reasked = _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    assert reasked.asked == {"Grab 002", "Refund 004"}, "only the rows with a model answer are asked again"
    for name, tags in stay.items():
        assert (await _answer(db, test_user, name)).tags == tags, name
    assert stay["Coffee"]["run_id"] == str(auto_run_id) and stay["Rent"]["category"] == "UTILITIES"


async def test_AC_extraction_2994_138_every_answer_that_a_run_writes_or_changes_carries_its_run_id(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.138: The tags of an inserted answer, a changed answer and a rule answer name the run."""
    seeded = await _seed(db, test_user, _rows(5))
    await _add_coffee_rule(db, test_user)
    _install(monkeypatch, ReaskModel())
    auto_run_id = await classify_statement(db, seeded.id)
    for name in ("Salary", "Coffee", "Grab", "Rent", "Refund"):
        assert (await _answer(db, test_user, name)).tags["run_id"] == str(auto_run_id), name
    _install(monkeypatch, ReaskModel())
    run_id = await _user_run(db, seeded.id, test_user)

    await _worker(create_session_maker_from_db(db), run_id)

    assert (await _answer(db, test_user, "Coffee")).tags["run_id"] == str(auto_run_id), "the rule row is not changed"
    for name in ("Salary", "Grab", "Rent", "Refund"):
        assert (await _answer(db, test_user, name)).tags["run_id"] == str(run_id), name


async def test_AC_extraction_2994_139_an_automatic_run_still_asks_only_the_rows_without_an_answer(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.139: The automatic run asks nothing for answered rows and changes no answer."""
    seeded, first_run_id, _first = await _classified_statement(db, test_user, monkeypatch)
    before = {name: (await _answer(db, test_user, name)).tags for name in ("Salary", "Grab")}
    second = _install(monkeypatch, ReaskModel())

    second_run_id = await classify_statement(db, seeded.id)

    run = await _run(db, second_run_id)
    assert (run.state, run.result_summary["outcome"]) == (RunState.SUCCEEDED, "nothing_to_classify")
    assert second.calls == [] and first_run_id != second_run_id
    assert {name: (await _answer(db, test_user, name)).tags for name in before} == before


async def test_AC_extraction_2994_140_a_re_ask_that_fails_in_batch_2_keeps_the_changes_of_batch_1(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.140: The answers of batch 1 are changed and committed. The rows of batch 2 keep their answers."""
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
    assert run.result_summary["batches_done"] == 1 and await _answers(db, test_user) == 5


async def test_AC_extraction_2994_141_a_re_ask_keeps_the_original_answer_semantics_of_a_fallback(
    db, test_user, monkeypatch
):
    """AC-extraction.2994.141: A low-confidence re-ask becomes a fallback in the same row, with the original answer kept."""
    seeded, _auto_run_id, _automatic = await _classified_statement(db, test_user, monkeypatch)
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

    row = await _answer(db, test_user, "Grab")
    account = await db.scalar(select(Account.name).where(Account.id == row.account_id))
    assert row.id == before_id and account == "General Expense (SGD)"
    assert (row.tags["category"], row.tags["original_category"], row.tags["original_confidence"]) == (
        "UNCLASSIFIED",
        "TRANSPORT",
        10,
    )
    assert (row.confidence_score, row.tags["run_id"]) == (0, str(run_id))
    rules = await db.scalar(select(ClassificationRule.id).where(ClassificationRule.rule_name == tc.POLICY_RULE_NAME).limit(1))
    assert rules is not None
