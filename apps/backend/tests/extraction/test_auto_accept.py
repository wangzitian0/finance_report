from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.config import settings
from src.extraction import ClassificationStatus, TransactionDirection, apply_suggestion_feedback, effective_auto_accept
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.ai_settings import auto_accept_enabled, classification_enabled
from src.extraction.extension.transaction_classification import CategoryProposal
from src.ledger import Account, AccountType
from tests.extraction._statement_run_helpers import (
    constant_proposer as _answer,
    draft_via_review_path as _draft_from_the_review_path,
    make_txn as _txn,
    mock_model_answers as _model_answers,
    row_account as _account,
    txn_classification as _row,
    verify_batch_scale_0_to_1,
    verify_classified_rows_not_asked_again,
    verify_existing_and_rejected_drafts,
)
from tests.statement_ingestion import classify_transactions

pytestmark = pytest.mark.asyncio
V2 = tc.POLICY_VERSIONS[-1]


@pytest.fixture(autouse=True)
def _automatic_path(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)


async def _general_account_count(db) -> int:
    return (await db.execute(select(func.count(Account.id)).where(Account.name.like("General %")))).scalar_one()


def _dict_proposer(answers: dict):
    async def _propose(txns, _policy):
        return [CategoryProposal(category=answers[t.id][0], confidence=answers[t.id][1], reason="test") for t in txns]

    return _propose


@pytest.mark.parametrize(
    ("category", "confidence", "direction", "expected_account", "tagged"),
    [
        ("DINING", 70, TransactionDirection.OUT, "Expense - Dining", True),
        ("DINING", 84, TransactionDirection.OUT, "Expense - Dining", True),
        ("DINING", 85, TransactionDirection.OUT, "Expense - Dining", False),
        ("OTHER_EXPENSE", 95, TransactionDirection.OUT, "Expense - Other", True),
        ("OTHER_INCOME", 72, TransactionDirection.IN, "Income - Other", True),
        ("OTHER_INCOME", 95, TransactionDirection.IN, "Income - Other", True),
    ],
)
async def test_AC_extraction_auto_accept_2_review_band_and_other_proposals_apply_with_tag(db, test_user, category, confidence, direction, expected_account, tagged):
    txn = await _txn(db, test_user, direction=direction)
    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, confidence))
    row = await _row(db, txn)
    assert (row.status, (await _account(db, row)).name, outcomes[0].disposition, row.tags.get("auto_accepted", False)) == (ClassificationStatus.APPLIED, expected_account, "applied", tagged)


@pytest.mark.parametrize(
    ("category", "confidence", "direction", "acct_name", "acct_type"),
    [
        ("DINING", 40, TransactionDirection.OUT, "General Expense (SGD)", AccountType.EXPENSE),
        ("DINING", 0, TransactionDirection.OUT, "General Expense (SGD)", AccountType.EXPENSE),
        ("SALARY", 95, TransactionDirection.OUT, "General Expense (SGD)", AccountType.EXPENSE),
        ("DINING", 90, TransactionDirection.IN, "General Income (SGD)", AccountType.INCOME),
    ],
)
async def test_AC_extraction_auto_accept_3_unplaced_row_falls_back_to_general_account(db, test_user, category, confidence, direction, acct_name, acct_type):
    txn = await _txn(db, test_user, direction=direction)
    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, confidence))
    row = await _row(db, txn)
    acct = await _account(db, row)
    assert (row.status, acct.name, acct.type, row.confidence_score, outcomes[0].disposition, row.tags["category"], row.tags["original_category"], row.tags["original_confidence"]) == (
        ClassificationStatus.APPLIED, acct_name, acct_type, 0, "fallback", "UNCLASSIFIED", category, confidence
    )


async def test_AC_extraction_auto_accept_4_no_answer_and_transfer_guards(db, test_user):
    txn = await _txn(db, test_user)
    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(None))
    retried = await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("GROCERIES", 91))
    assert (outcomes[0].disposition, retried[0].disposition, (await _account(db, await _row(db, txn))).name) == ("no_proposal", "applied", "Expense - Groceries")

    for category, confidence in (("TRANSFER", 88), ("CARD_REPAYMENT", 88), ("TRANSFER", 55), ("CARD_REPAYMENT", 55)):
        t = await _txn(db, test_user)
        outs = await classify_transactions(db, test_user.id, [t], policy=V2, proposer=_answer(category, confidence))
        row = await _row(db, t)
        assert (row.status, row.account_id, row.tags["category"], outs[0].disposition, "suspense" in row.tags, await _general_account_count(db)) == (ClassificationStatus.DRAFT, None, category, "non_pnl", False, 0)
    for bs_cat in ("LOAN_PRINCIPAL", "INVESTMENT_TRADE", "TRANSFER", "CARD_REPAYMENT"):
        t = await _txn(db, test_user)
        outs = await classify_transactions(db, test_user.id, [t], policy=V2, proposer=_answer(bs_cat, 0))
        assert (await _row(db, t), await _general_account_count(db), outs[0].disposition) == (None, 0, "no_proposal")


@pytest.mark.parametrize(
    ("category", "direction", "intent", "account_name", "account_type"),
    [
        ("LOAN_PRINCIPAL", TransactionDirection.OUT, "loan_principal", "Loans Payable (SGD)", AccountType.LIABILITY),
        ("LOAN_PRINCIPAL", TransactionDirection.IN, "loan_principal", "Loans Payable (SGD)", AccountType.LIABILITY),
        ("INVESTMENT_TRADE", TransactionDirection.OUT, "investment_purchase", "Investments (SGD)", AccountType.ASSET),
        ("INVESTMENT_TRADE", TransactionDirection.IN, "investment_sale", "Investments (SGD)", AccountType.ASSET),
    ],
)
async def test_AC_extraction_auto_accept_5_a_loan_or_a_trade_is_applied_with_an_explicit_intent(db, test_user, category, direction, intent, account_name, account_type):
    txn = await _txn(db, test_user, direction=direction)
    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, 66))
    row = await _row(db, txn)
    acct = await _account(db, row)
    assert (row.status, acct.name, acct.type, row.tags["intent"], row.tags["category"]) == (ClassificationStatus.APPLIED, account_name, account_type, intent, category)

    if direction is TransactionDirection.OUT:
        txn2 = await _txn(db, test_user, direction=direction)
        outcomes2 = await classify_transactions(db, test_user.id, [txn2], policy=V2, proposer=_answer(category, 59))
        row2 = await _row(db, txn2)
        assert (row2.status, row2.account_id, row2.tags["category"], row2.tags["suspense"], row2.confidence_score, outcomes2[0].disposition, await _general_account_count(db)) == (
            ClassificationStatus.DRAFT, None, category, True, 59, "non_pnl", 0
        )


async def test_AC_extraction_auto_accept_1_a_user_who_turned_it_off_keeps_the_review_path(db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    assert await classification_enabled(db, test_user.id) is False and await auto_accept_enabled(db, test_user.id) is False
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}
    await db.flush()
    review, other, tail = await _txn(db, test_user), await _txn(db, test_user, direction=TransactionDirection.IN), await _txn(db, test_user)
    outcomes = await classify_transactions(db, test_user.id, [review, other, tail], policy=V2, proposer=_dict_proposer({review.id: ("DINING", 70), other.id: ("OTHER_INCOME", 95), tail.id: ("DINING", 40)}))
    assert {o.disposition for o in outcomes} == {"review", "tail"} and ((await _row(db, review)).status, (await _row(db, other)).status, await _row(db, tail)) == (ClassificationStatus.DRAFT, ClassificationStatus.DRAFT, None)


@pytest.mark.parametrize(
    ("category", "direction", "intent", "account_name"),
    [("LOAN_PRINCIPAL", TransactionDirection.OUT, "loan_principal", "Loans Payable (SGD)"), ("INVESTMENT_TRADE", TransactionDirection.IN, "investment_sale", "Investments (SGD)")],
)
async def test_AC_extraction_auto_accept_6_a_loan_or_a_trade_draft_gets_its_account_and_its_intent(db, test_user, category, direction, intent, account_name):
    txn = await _txn(db, test_user, direction=direction)
    draft = await _draft_from_the_review_path(db, test_user, txn, category, 70)
    assert draft.account_id is None
    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(category, 70))
    await db.refresh(draft)
    assert (draft.status, (await _account(db, draft)).name, draft.tags["intent"], draft.tags["category"]) == (ClassificationStatus.APPLIED, account_name, intent, category)


async def test_AC_extraction_auto_accept_6_draft_guards_and_direction(db, test_user):
    for cat in ("TRANSFER", "CARD_REPAYMENT"):
        txn = await _txn(db, test_user)
        draft = await _draft_from_the_review_path(db, test_user, txn, cat, 80)
        await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer(cat, 80))
        await db.refresh(draft)
        assert (draft.status, draft.account_id) == (ClassificationStatus.DRAFT, None)

    txn = await _txn(db, test_user, direction=TransactionDirection.OUT)
    draft = await _draft_from_the_review_path(db, test_user, txn, "SALARY", 70)
    assert (await _account(db, draft)).name == "Income - Salary"
    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("SALARY", 70))
    await db.refresh(draft)
    assert (draft.status, (await _account(db, draft)).name, draft.tags["category"], draft.tags["original_category"], draft.confidence_score) == (ClassificationStatus.APPLIED, "General Expense (SGD)", "UNCLASSIFIED", "SALARY", 0)

    for cat, direction, expected_status, expected_account in (("DINING", TransactionDirection.OUT, ClassificationStatus.APPLIED, "Expense - Dining"), ("SALARY", TransactionDirection.OUT, ClassificationStatus.DRAFT, "Income - Salary")):
        t = await _txn(db, test_user, direction=direction)
        d = await _draft_from_the_review_path(db, test_user, t, cat, 70)
        d.tags = {**d.tags, "corrected_by_user": True}
        await db.flush()
        await classify_transactions(db, test_user.id, [t], policy=V2, proposer=_answer(cat, 70))
        await db.refresh(d)
        assert (d.status, (await _account(db, d)).name) == (expected_status, expected_account) and (expected_status is not ClassificationStatus.APPLIED or (d.tags["corrected_by_user"] is True and "auto_accepted" not in d.tags))


@pytest.mark.parametrize(
    ("overrides", "process_flag", "expected"),
    [
        ({}, True, True), ({"auto_accept_ai_suggestions": False}, True, False), ({"enable_ai_classification": False}, True, False),
        ({"enable_ai_classification": False, "auto_accept_ai_suggestions": True}, True, False), ({"enable_ai_classification": True, "auto_accept_ai_suggestions": True}, True, True),
        ({}, False, False), ({"auto_accept_ai_suggestions": True}, False, False), ({"auto_accept_ai_suggestions": False}, False, False),
    ],
)
async def test_AC_extraction_auto_accept_1_settings_and_process_ceiling(db, test_user, monkeypatch, overrides, process_flag, expected):
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", process_flag)
    test_user.ai_settings = overrides
    await db.flush()
    assert await auto_accept_enabled(db, test_user.id) is expected and effective_auto_accept(test_user.ai_settings) is expected


@pytest.mark.parametrize(
    ("answer", "expected_disp"),
    [
        ({"index": 0}, "no_proposal"), ({"index": 0, "category": "DINING"}, "no_proposal"), ({"index": 0, "confidence": 90}, "no_proposal"),
        ({"index": 0, "category": None, "confidence": 90}, "no_proposal"), ({"index": 0, "category": "  ", "confidence": 90}, "no_proposal"),
        ({"index": 0, "category": "DINING", "confidence": "high"}, "no_proposal"), ({"index": 0, "category": "DINING", "confidence": None}, "no_proposal"),
        ({"index": 0, "category": "DINING", "confidence": True}, "no_proposal"), ({"index": 0, "category": 7, "confidence": 90}, "no_proposal"),
        ({"index": 0, "category": "DINING", "confidence": -5}, "no_proposal"), ({"index": 0, "category": "DINING", "confidence": "-5"}, "no_proposal"),
        ({"index": 0, "category": "DINING", "confidence": -5.5}, "no_proposal"), ({"index": 0, "category": "DINING", "confidence": "1e3"}, "no_proposal"),
        ({"index": 0, "category": "DINING", "confidence": -(10**400)}, "no_proposal"), ({"index": 0, "category": "DINING", "confidence": "9" * 400}, "no_proposal"),
        ({"index": 0, "category": "FOOD_AND_DRINK", "confidence": 95}, "off_catalog"),
    ],
)
async def test_AC_extraction_auto_accept_4_unusable_answers_write_nothing(db, test_user, monkeypatch, answer, expected_disp):
    txn = await _txn(db, test_user)
    _model_answers(monkeypatch, [answer])
    outcomes = await classify_transactions(db, test_user.id, [txn], policy=V2)
    assert (await _row(db, txn), await _general_account_count(db), outcomes[0].disposition) == (None, 0, expected_disp)


@pytest.mark.parametrize(
    ("answer", "direction", "account_name", "score"),
    [
        ({"category": "dining", "confidence": 90}, TransactionDirection.OUT, "Expense - Dining", 90),
        ({"category": " Dining ", "confidence": "90%"}, TransactionDirection.OUT, "Expense - Dining", 90),
        ({"category": "DINING", "confidence": 87.6}, TransactionDirection.OUT, "Expense - Dining", 87),
        ({"category": "dining", "confidence": 250}, TransactionDirection.OUT, "Expense - Dining", 100),
        ({"category": "DINING", "confidence": "87.0"}, TransactionDirection.OUT, "Expense - Dining", 87),
        ({"category": "DINING", "confidence": 87.0}, TransactionDirection.OUT, "Expense - Dining", 87),
        ({"category": "DINING", "confidence": 0.95}, TransactionDirection.OUT, "Expense - Dining", 95),
        ({"category": "DINING", "confidence": 10**400}, TransactionDirection.OUT, "Expense - Dining", 100),
        ({"category": "Other-Income", "confidence": 70}, TransactionDirection.IN, "Income - Other", 70),
    ],
)
async def test_AC_extraction_auto_accept_4_a_readable_answer_is_normalized(db, test_user, monkeypatch, answer, direction, account_name, score):
    txn = await _txn(db, test_user, direction=direction)
    _model_answers(monkeypatch, [{"index": 0, **answer}])
    await classify_transactions(db, test_user.id, [txn], policy=V2)
    row = await _row(db, txn)
    assert ((await _account(db, row)).name, row.confidence_score) == (account_name, score)


@pytest.mark.parametrize(
    ("category", "account_name"),
    [("LOAN_PRINCIPAL", "Loans Payable (SGD)"), ("INVESTMENT_TRADE", "Investments (SGD)"), ("DINING", "Expense - Dining")],
)
async def test_AC_extraction_auto_accept_3_5_review_score_60_vs_59_gate(db, test_user, category, account_name):
    at_gate, below_gate = await _txn(db, test_user), await _txn(db, test_user)
    await classify_transactions(db, test_user.id, [at_gate, below_gate], policy=V2, proposer=_dict_proposer({at_gate.id: (category, 60), below_gate.id: (category, 59)}))
    booked, below = await _row(db, at_gate), await _row(db, below_gate)
    assert (booked.status, (await _account(db, booked)).name) == (ClassificationStatus.APPLIED, account_name)
    assert (below.status, (await _account(db, below)).name) == (ClassificationStatus.APPLIED, "General Expense (SGD)") if category == "DINING" else (below.status is ClassificationStatus.DRAFT and below.tags["suspense"] is True)


async def test_AC_extraction_auto_accept_4_decimal_truncation_and_suspense_correction(db, test_user, monkeypatch):
    below, at_gate = await _txn(db, test_user, description="ROW A"), await _txn(db, test_user, description="ROW B")
    _model_answers(monkeypatch, [{"index": 0, "category": "DINING", "confidence": 59.9}, {"index": 1, "category": "DINING", "confidence": 60.4}])
    await classify_transactions(db, test_user.id, [below, at_gate], policy=V2)
    assert ((await _row(db, below)).tags["original_confidence"], (await _account(db, await _row(db, below))).name, (await _row(db, at_gate)).confidence_score, (await _account(db, await _row(db, at_gate))).name) == (59, "General Expense (SGD)", 60, "Expense - Dining")

    txn = await _txn(db, test_user)
    for _ in range(2):
        await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("INVESTMENT_TRADE", 55))
    draft = await _row(db, txn)
    assert (draft.status, draft.account_id) == (ClassificationStatus.DRAFT, None)
    effect = await apply_suggestion_feedback(db, test_user.id, draft.id, "edit_accept", {"value": "loan_principal"})
    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_answer("INVESTMENT_TRADE", 55))
    await db.refresh(draft)
    assert (effect, "suspense" in draft.tags, draft.tags["corrected_by_user"], draft.status, (await _account(db, draft)).name) == ("corrected", False, True, ClassificationStatus.APPLIED, "Loans Payable (SGD)")


@pytest.mark.parametrize(
    ("second_item", "second_written", "expected_disps"),
    [
        ({"index": 1, "category": "GROCERIES", "confidence": 0.5}, False, ["applied", "no_proposal"]),
        ({"index": 1, "category": "GROCERIES", "confidence": 1.0}, True, ["applied", "fallback"]),
        ({"index": 1, "category": "TRANSFER", "confidence": 0.0}, False, ["applied", "no_proposal"]),
    ],
)
async def test_AC_extraction_auto_accept_4_mixed_scale_batch_cases(db, test_user, monkeypatch, second_item, second_written, expected_disps):
    first, second = await _txn(db, test_user, description="ROW A"), await _txn(db, test_user, description="ROW B")
    _model_answers(monkeypatch, [{"index": 0, "category": "DINING", "confidence": 90}, second_item])
    outcomes = await classify_transactions(db, test_user.id, [first, second], policy=V2)
    assert (await _account(db, await _row(db, first))).name == "Expense - Dining" and [o.disposition for o in outcomes] == expected_disps
    assert (await _account(db, await _row(db, second))).name.startswith("General ") if second_written else await _row(db, second) is None


async def test_AC_extraction_auto_accept_delegated(db, test_user, monkeypatch):
    await verify_batch_scale_0_to_1(db, test_user, monkeypatch)
    await verify_existing_and_rejected_drafts(db, test_user)
    await verify_classified_rows_not_asked_again(db, test_user)
