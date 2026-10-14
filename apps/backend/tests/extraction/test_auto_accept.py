"""AC-extraction.auto-accept: the system decides every row that the model answered, so a statement posts without a click.

The owner rule of #2405: the user uploads, the system produces the base tables and the default three
statements. The review band (a score from 60 to 84), the Other classes and the rows that the model could not
place no longer wait for a person. The model answered them, so the system accepts the suggestion or uses the
general account of the direction. A row that the model did not answer (an outage, an unreadable answer) writes
nothing, so a later pass can still classify it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

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
    from src.config import settings

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
        ("NOT_IN_THE_CATALOG", 90, "off the catalog"),
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
    """AC-extraction.auto-accept.6: turning the setting on also settles the drafts that the review path left."""
    txn = await _txn(db, test_user)
    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("DINING", 70))
    row = await _row(db, txn)
    row.status = ClassificationStatus.DRAFT  # what the review path would have written
    await db.flush()

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
