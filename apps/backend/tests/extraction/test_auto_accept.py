"""AC-extraction.auto-accept: the system decides every row that the model answered, so a statement posts without a click.

The owner rule of #2405: the user uploads, the system produces the base tables and the default three
statements. The review band (a score from 60 to 84), the Other classes and the rows that the model could not
place no longer wait for a person. The model answered them, so the system accepts the suggestion or uses the
general account of the direction. A row that the model did not answer (an outage, an unreadable answer) writes
nothing, so a later pass can still classify it.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from src.config import settings
from src.extraction import ClassificationStatus, TransactionDirection
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.transaction_classification import (
    CategoryProposal,
    classify_transactions,
)
from src.extraction.orm.layer3 import TransactionClassification
from src.ledger import Account, AccountType
from tests.factories import AtomicTransactionFactory

pytestmark = pytest.mark.asyncio

V2 = tc.POLICY_VERSIONS[1]


@pytest.fixture(autouse=True)
def _automatic_path(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)


async def _txn(db, user, *, direction: TransactionDirection = TransactionDirection.OUT, description: str = "ROW"):
    return await AtomicTransactionFactory.create_async(
        db, user_id=user.id, description=description, direction=direction, currency="SGD"
    )


def _answer(category: str | None, confidence: int = 70):
    async def proposer(transactions, _policy):
        if category is None:
            return [None for _ in transactions]
        return [CategoryProposal(category=category, confidence=confidence, reason="test") for _ in transactions]

    return proposer


async def _row(db, txn) -> TransactionClassification | None:
    return (
        await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id == txn.id))
    ).scalar_one_or_none()


async def _account(db, row) -> Account:
    return await db.get(Account, row.account_id)


async def test_AC_extraction_auto_accept_2_a_review_band_proposal_is_applied(db, test_user):
    """AC-extraction.auto-accept.2: a score of 70 is below 85, and the system accepts it."""
    txn = await _txn(db, test_user)

    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("DINING", 70))

    row = await _row(db, txn)
    assert row.status is ClassificationStatus.APPLIED
    assert (await _account(db, row)).name == "Expense - Dining"
    assert outcomes[0].disposition == "applied"


async def test_AC_extraction_auto_accept_2_other_income_is_applied_to_the_other_account(db, test_user):
    """AC-extraction.auto-accept.2: "Other" no longer waits for a person when the user accepts suggestions."""
    txn = await _txn(db, test_user, direction=TransactionDirection.IN)

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("OTHER_INCOME", 72))

    row = await _row(db, txn)
    assert row.status is ClassificationStatus.APPLIED
    assert (await _account(db, row)).name == "Income - Other"


@pytest.mark.parametrize(
    ("category", "confidence", "reason"),
    [
        ("DINING", 40, "below the review score"),
        ("DINING", 0, "an explicit zero: the model says that it cannot place the row"),
        ("SALARY", 95, "an income category for money out"),
    ],
)
async def test_AC_extraction_auto_accept_3_a_row_that_the_model_cannot_place_gets_the_general_account(
    db, test_user, category, confidence, reason
):
    """AC-extraction.auto-accept.3: the model answered but the answer is unusable. The general account takes the row."""
    txn = await _txn(db, test_user)

    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, confidence))

    row = await _row(db, txn)
    assert row.status is ClassificationStatus.APPLIED, reason
    assert (await _account(db, row)).name == "General Expense (SGD)"
    assert (await _account(db, row)).type is AccountType.EXPENSE
    assert row.tags["category"] == "UNCLASSIFIED"
    assert row.confidence_score == 0
    # The record keeps what the model said, so a reader can tell a guess from a missing answer.
    assert row.tags["original_category"] == category
    assert row.tags["original_confidence"] == confidence
    assert outcomes[0].disposition == "fallback"


async def test_AC_extraction_auto_accept_3_money_in_falls_back_to_general_income(db, test_user):
    """AC-extraction.auto-accept.3: the fallback follows the direction of the row."""
    txn = await _txn(db, test_user, direction=TransactionDirection.IN)

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("DINING", 90))

    row = await _row(db, txn)
    assert (await _account(db, row)).name == "General Income (SGD)"
    assert (await _account(db, row)).type is AccountType.INCOME


async def test_AC_extraction_auto_accept_4_no_answer_writes_nothing(db, test_user):
    """AC-extraction.auto-accept.4: an outage must not turn a whole statement into general entries.

    A row without an answer gets no row. The next pass, after the provider is back, classifies it.
    """
    txn = await _txn(db, test_user)

    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(None))

    assert await _row(db, txn) is None
    assert outcomes[0].disposition == "no_proposal"
    retried = await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("GROCERIES", 91))
    assert retried[0].disposition == "applied"
    assert (await _account(db, await _row(db, txn))).name == "Expense - Groceries"


@pytest.mark.parametrize(
    ("category", "direction", "intent", "account_name", "account_type"),
    [
        ("LOAN_PRINCIPAL", TransactionDirection.OUT, "loan_principal", "Loans Payable (SGD)", AccountType.LIABILITY),
        ("LOAN_PRINCIPAL", TransactionDirection.IN, "loan_principal", "Loans Payable (SGD)", AccountType.LIABILITY),
        (
            "INVESTMENT_TRADE",
            TransactionDirection.OUT,
            "investment_purchase",
            "Investments (SGD)",
            AccountType.ASSET,
        ),
        ("INVESTMENT_TRADE", TransactionDirection.IN, "investment_sale", "Investments (SGD)", AccountType.ASSET),
    ],
)
async def test_AC_extraction_auto_accept_5_a_loan_or_a_trade_is_applied_with_an_explicit_intent(
    db, test_user, category, direction, intent, account_name, account_type
):
    """AC-extraction.auto-accept.5: the row is a balance-sheet movement, booked to a default balance-sheet account."""
    txn = await _txn(db, test_user, direction=direction)

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, 66))

    row = await _row(db, txn)
    account = await _account(db, row)
    assert row.status is ClassificationStatus.APPLIED
    assert (account.name, account.type) == (account_name, account_type)
    assert row.tags["intent"] == intent
    assert row.tags["category"] == category


@pytest.mark.parametrize("category", ["TRANSFER", "CARD_REPAYMENT"])
async def test_AC_extraction_auto_accept_5_a_transfer_stays_a_draft_for_the_leg(db, test_user, category):
    """AC-extraction.auto-accept.5: a transfer posts as a Processing leg. The draft records the class for it."""
    txn = await _txn(db, test_user)

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, 88))

    row = await _row(db, txn)
    assert row.status is ClassificationStatus.DRAFT
    assert row.account_id is None
    assert row.tags["category"] == category


async def test_AC_extraction_auto_accept_6_existing_drafts_are_promoted(db, test_user):
    """AC-extraction.auto-accept.6: turning the setting on also settles the drafts that the review path left.

    The first pass runs with the setting off, so no row holds the tag yet. Only the promotion can add it.
    """
    txn = await _txn(db, test_user)
    row = await _draft_from_the_review_path(db, test_user, txn, "DINING", 70)
    assert "auto_accepted" not in row.tags

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("DINING", 70))

    await db.refresh(row)
    assert row.status is ClassificationStatus.APPLIED
    assert row.tags["auto_accepted"] is True


async def test_AC_extraction_auto_accept_6_a_rejected_draft_is_not_promoted(db, test_user):
    """AC-extraction.auto-accept.6: a decision of the user outranks the setting."""
    txn = await _txn(db, test_user)
    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("DINING", 70))
    row = await _row(db, txn)
    row.status = ClassificationStatus.SUPERSEDED
    row.tags = {**row.tags, "rejected_by_user": True}
    await db.flush()

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("DINING", 70))

    await db.refresh(row)
    assert row.status is ClassificationStatus.SUPERSEDED


async def test_AC_extraction_auto_accept_1_a_user_who_turned_it_off_keeps_the_review_path(db, test_user):
    """AC-extraction.auto-accept.1: the rollback path. Off means the old thresholds and the draft rows."""
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}
    await db.flush()
    review = await _txn(db, test_user)
    other = await _txn(db, test_user, direction=TransactionDirection.IN)
    tail = await _txn(db, test_user)

    async def proposer(transactions, _policy):
        answers = {review.id: ("DINING", 70), other.id: ("OTHER_INCOME", 95), tail.id: ("DINING", 40)}
        return [CategoryProposal(category=answers[t.id][0], confidence=answers[t.id][1]) for t in transactions]

    outcomes = await classify_transactions(db, test_user.id, [review, other, tail], policy=V2, proposer=proposer)

    assert {outcome.disposition for outcome in outcomes} == {"review", "tail"}
    assert (await _row(db, review)).status is ClassificationStatus.DRAFT
    assert (await _row(db, other)).status is ClassificationStatus.DRAFT
    assert await _row(db, tail) is None


async def _draft_from_the_review_path(db, user, txn, category: str, confidence: int) -> TransactionClassification:
    """Write the row as the review path writes it: the user setting is off while the model answers."""
    user.ai_settings = {"auto_accept_ai_suggestions": False}
    await db.flush()
    await classify_transactions(db, user.id, [txn], policy=V2, proposer=_answer(category, confidence))
    user.ai_settings = {"auto_accept_ai_suggestions": True}
    await db.flush()
    row = await _row(db, txn)
    assert row.status is ClassificationStatus.DRAFT
    return row


@pytest.mark.parametrize(
    ("category", "direction", "intent", "account_name"),
    [
        ("LOAN_PRINCIPAL", TransactionDirection.OUT, "loan_principal", "Loans Payable (SGD)"),
        ("INVESTMENT_TRADE", TransactionDirection.IN, "investment_sale", "Investments (SGD)"),
    ],
)
async def test_AC_extraction_auto_accept_6_a_loan_or_a_trade_draft_gets_its_account_and_its_intent(
    db, test_user, category, direction, intent, account_name
):
    """AC-extraction.auto-accept.6: the review path stores a loan or a trade without an account. Promotion adds both."""
    txn = await _txn(db, test_user, direction=direction)
    draft = await _draft_from_the_review_path(db, test_user, txn, category, 70)
    assert draft.account_id is None

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, 70))

    await db.refresh(draft)
    assert draft.status is ClassificationStatus.APPLIED
    assert (await _account(db, draft)).name == account_name
    assert draft.tags["intent"] == intent
    assert draft.tags["category"] == category


@pytest.mark.parametrize("category", ["TRANSFER", "CARD_REPAYMENT"])
async def test_AC_extraction_auto_accept_6_a_transfer_draft_stays_a_draft(db, test_user, category):
    """AC-extraction.auto-accept.6: a transfer has no account to apply. Its Processing leg posts it."""
    txn = await _txn(db, test_user)
    draft = await _draft_from_the_review_path(db, test_user, txn, category, 80)

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, 80))

    await db.refresh(draft)
    assert draft.status is ClassificationStatus.DRAFT
    assert draft.account_id is None


async def test_AC_extraction_auto_accept_6_a_draft_against_the_direction_goes_to_the_general_account(db, test_user):
    """AC-extraction.auto-accept.6: a salary draft on money out cannot post. The general account takes the row."""
    txn = await _txn(db, test_user, direction=TransactionDirection.OUT)
    draft = await _draft_from_the_review_path(db, test_user, txn, "SALARY", 70)
    assert (await _account(db, draft)).name == "Income - Salary"

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("SALARY", 70))

    await db.refresh(draft)
    assert draft.status is ClassificationStatus.APPLIED
    assert (await _account(db, draft)).name == "General Expense (SGD)"
    assert draft.tags["category"] == "UNCLASSIFIED"
    assert draft.tags["original_category"] == "SALARY"
    assert draft.confidence_score == 0


async def test_AC_extraction_auto_accept_6_promotion_touches_only_the_rows_of_the_call(db, test_user):
    """AC-extraction.auto-accept.6: a pass for one statement does not settle the drafts of another statement."""
    in_call = await _txn(db, test_user)
    elsewhere = await _txn(db, test_user)
    in_call_draft = await _draft_from_the_review_path(db, test_user, in_call, "DINING", 70)
    elsewhere_draft = await _draft_from_the_review_path(db, test_user, elsewhere, "DINING", 70)

    await classify_transactions(db, test_user.id, [in_call], policy=V2, proposer=_answer("DINING", 70))

    await db.refresh(in_call_draft)
    await db.refresh(elsewhere_draft)
    assert in_call_draft.status is ClassificationStatus.APPLIED
    assert elsewhere_draft.status is ClassificationStatus.DRAFT


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"auto_accept_ai_suggestions": False}, False),
        ({"enable_ai_classification": False}, False),
        ({"enable_ai_classification": False, "auto_accept_ai_suggestions": True}, False),
        ({"enable_ai_classification": True, "auto_accept_ai_suggestions": True}, True),
    ],
)
async def test_AC_extraction_auto_accept_1_the_setting_needs_ai_classification(db, test_user, overrides, expected):
    """AC-extraction.auto-accept.1: with AI classification off there is nothing to accept, whatever the setting says."""
    from src.extraction.extension.ai_settings import auto_accept_enabled

    test_user.ai_settings = overrides
    await db.flush()

    assert await auto_accept_enabled(db, test_user.id) is expected


async def test_AC_extraction_auto_accept_1_the_process_default_of_classification_applies_without_an_override(
    db, test_user, monkeypatch
):
    """AC-extraction.auto-accept.1: a user without an override follows the process default of AI classification."""
    from src.extraction.extension.ai_settings import auto_accept_enabled, classification_enabled

    monkeypatch.setattr(settings, "enable_ai_classification", False)

    assert await classification_enabled(db, test_user.id) is False
    assert await auto_accept_enabled(db, test_user.id) is False


# --- the parser: a malformed answer is no answer (audit of #2424, finding 2) ---


def _model_answers(monkeypatch, items: list[dict]) -> None:
    """Put a stub in place of the provider. The real parser reads what the stub returns."""

    async def stream():
        yield json.dumps(items)

    monkeypatch.setattr("src.llm.stream_ai_json", lambda **_kwargs: stream())
    monkeypatch.setattr(settings, "ai_api_key", "test-key")


async def _general_account_count(db) -> int:
    return (await db.execute(select(func.count(Account.id)).where(Account.name.like("General %")))).scalar_one()


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"index": 0}, id="no-category-no-confidence"),
        pytest.param({"index": 0, "category": "DINING"}, id="no-confidence"),
        pytest.param({"index": 0, "confidence": 90}, id="no-category"),
        pytest.param({"index": 0, "category": None, "confidence": 90}, id="null-category"),
        pytest.param({"index": 0, "category": "  ", "confidence": 90}, id="blank-category"),
        pytest.param({"index": 0, "category": "DINING", "confidence": 0.95}, id="fraction-scale"),
        pytest.param({"index": 0, "category": "DINING", "confidence": "high"}, id="word"),
        pytest.param({"index": 0, "category": "DINING", "confidence": None}, id="null-confidence"),
        pytest.param({"index": 0, "category": "DINING", "confidence": True}, id="boolean-confidence"),
        pytest.param({"index": 0, "category": 7, "confidence": 90}, id="number-category"),
    ],
)
async def test_AC_extraction_auto_accept_4_an_unreadable_answer_writes_nothing(db, test_user, monkeypatch, answer):
    """AC-extraction.auto-accept.4: the real parser turns an answer that it cannot read into no answer.

    The row gets no classification and no general account. A later pass asks the model again.
    """
    txn = await _txn(db, test_user)
    _model_answers(monkeypatch, [answer])

    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2)

    assert await _row(db, txn) is None
    assert await _general_account_count(db) == 0
    assert outcomes[0].disposition == "no_proposal"


async def test_AC_extraction_auto_accept_4_a_class_outside_the_catalog_writes_nothing(db, test_user, monkeypatch):
    """AC-extraction.auto-accept.4: a name that the catalog does not hold means the model ignored the schema."""
    txn = await _txn(db, test_user)
    _model_answers(monkeypatch, [{"index": 0, "category": "FOOD_AND_DRINK", "confidence": 95}])

    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2)

    assert await _row(db, txn) is None
    assert await _general_account_count(db) == 0
    assert outcomes[0].disposition == "off_catalog"


@pytest.mark.parametrize(
    ("answer", "account_name", "score"),
    [
        pytest.param({"category": "dining", "confidence": 90}, "Expense - Dining", 90, id="lower-case"),
        pytest.param({"category": " Dining ", "confidence": "90%"}, "Expense - Dining", 90, id="spaces-and-percent"),
        pytest.param({"category": "DINING", "confidence": 87.6}, "Expense - Dining", 88, id="decimal-score"),
        pytest.param({"category": "dining", "confidence": 250}, "Expense - Dining", 100, id="score-above-100"),
    ],
)
async def test_AC_extraction_auto_accept_4_a_readable_answer_is_normalized(
    db, test_user, monkeypatch, answer, account_name, score
):
    """AC-extraction.auto-accept.4: case, spaces and a percent sign do not make an answer unreadable."""
    txn = await _txn(db, test_user)
    _model_answers(monkeypatch, [{"index": 0, **answer}])

    await classify_transactions(db, test_user.id, [txn], policy=V2)

    row = await _row(db, txn)
    assert (await _account(db, row)).name == account_name
    assert row.confidence_score == score


async def test_AC_extraction_auto_accept_4_a_mixed_case_class_with_a_hyphen_is_read(db, test_user, monkeypatch):
    """AC-extraction.auto-accept.4: the user path accepts `other income`; the model path accepts it too."""
    txn = await _txn(db, test_user, direction=TransactionDirection.IN)
    _model_answers(monkeypatch, [{"index": 0, "category": "Other-Income", "confidence": 70}])

    await classify_transactions(db, test_user.id, [txn], policy=V2)

    assert (await _account(db, await _row(db, txn))).name == "Income - Other"


# --- a dry run writes nothing, with the setting on (finding 7) ---


async def test_AC_extraction_auto_accept_4_a_dry_run_writes_nothing_and_creates_no_account(db, test_user):
    """AC-extraction.auto-accept.4: `commit_basis=False` gives the verdicts and no write, on every new route."""
    cases = {
        "low": (await _txn(db, test_user), ("DINING", 40)),
        "against": (await _txn(db, test_user, direction=TransactionDirection.OUT), ("SALARY", 95)),
        "loan": (await _txn(db, test_user), ("LOAN_PRINCIPAL", 66)),
        "trade": (await _txn(db, test_user), ("INVESTMENT_TRADE", 66)),
        "transfer": (await _txn(db, test_user), ("TRANSFER", 66)),
        "applied": (await _txn(db, test_user), ("DINING", 70)),
    }
    by_txn = {txn.id: answer for txn, answer in cases.values()}
    accounts_before = (await db.execute(select(func.count(Account.id)))).scalar_one()

    async def proposer(transactions, _policy):
        return [CategoryProposal(category=by_txn[t.id][0], confidence=by_txn[t.id][1]) for t in transactions]

    outcomes = await classify_transactions(
        db, test_user.id, [txn for txn, _ in cases.values()], policy=V2, proposer=proposer, commit_basis=False
    )

    assert {outcome.disposition for outcome in outcomes} == {"fallback", "applied", "non_pnl"}
    assert (await db.execute(select(func.count(TransactionClassification.id)))).scalar_one() == 0
    assert (await db.execute(select(func.count(Account.id)))).scalar_one() == accounts_before


# --- balance-sheet classes are accepted at any score (finding 4) ---


@pytest.mark.parametrize(
    ("category", "status", "account_name"),
    [
        ("LOAN_PRINCIPAL", ClassificationStatus.APPLIED, "Loans Payable (SGD)"),
        ("INVESTMENT_TRADE", ClassificationStatus.APPLIED, "Investments (SGD)"),
        ("TRANSFER", ClassificationStatus.DRAFT, None),
        ("CARD_REPAYMENT", ClassificationStatus.DRAFT, None),
    ],
)
async def test_AC_extraction_auto_accept_5_a_balance_sheet_class_is_accepted_below_the_review_score(
    db, test_user, category, status, account_name
):
    """AC-extraction.auto-accept.5: a weak transfer is still a transfer, not an expense.

    The model named a movement of money, and a General Expense row would count that money as spending. The
    two sides of one transfer must also land in the same place, whatever score each side got.
    """
    txn = await _txn(db, test_user)

    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, 55))

    row = await _row(db, txn)
    assert row.status is status
    assert row.tags["category"] == category
    assert (await _account(db, row)).name == account_name if account_name else row.account_id is None
    assert outcomes[0].disposition != "fallback"
    assert await _general_account_count(db) == 0


# --- a person's correction outranks the setting (finding 6) ---


async def test_AC_extraction_auto_accept_6_a_corrected_draft_stays_a_draft(db, test_user):
    """AC-extraction.auto-accept.6: the one-click approval posts a corrected draft as the decision of the person.

    The promotion would record the model as the decider and the confidence tier of the model.
    """
    txn = await _txn(db, test_user)
    draft = await _draft_from_the_review_path(db, test_user, txn, "DINING", 70)
    draft.tags = {**draft.tags, "corrected_by_user": True}
    await db.flush()

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("DINING", 70))

    await db.refresh(draft)
    assert draft.status is ClassificationStatus.DRAFT
    assert "auto_accepted" not in draft.tags


# --- the process flag is a ceiling (finding 5) ---


@pytest.mark.parametrize(
    ("process_flag", "stored", "expected"),
    [
        (True, None, True),
        (True, True, True),
        (True, False, False),
        (False, None, False),
        (False, True, False),
        (False, False, False),
    ],
)
async def test_AC_extraction_auto_accept_1_the_process_flag_is_a_ceiling(
    db, test_user, monkeypatch, process_flag, stored, expected
):
    """AC-extraction.auto-accept.1: the operator rollback `AUTO_ACCEPT_AI_SUGGESTIONS=false` reaches every user.

    A user who saved the settings panel once holds a stored `true`. That value must not outvote the operator.
    """
    from src.extraction import effective_auto_accept
    from src.extraction.extension.ai_settings import auto_accept_enabled

    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", process_flag)
    test_user.ai_settings = {} if stored is None else {"auto_accept_ai_suggestions": stored}
    await db.flush()

    assert await auto_accept_enabled(db, test_user.id) is expected
    assert effective_auto_accept(test_user.ai_settings) is expected
