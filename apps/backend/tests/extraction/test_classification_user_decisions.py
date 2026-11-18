from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from src.config import settings
from src.extraction import ClassificationStatus, RuleType, TransactionDirection
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.correction_service import clear_all_correction_cache
from src.extraction.extension.transaction_classification import CategoryProposal, apply_suggestion_feedback, classification_suggestions
from src.extraction.orm.correction import CorrectionLog
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from tests.factories import AtomicTransactionFactory
from tests.statement_ingestion import classify_transactions

pytestmark = pytest.mark.asyncio
V2 = tc.POLICY_VERSIONS[-1]


@pytest.fixture(autouse=True)
def _classification_on(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    clear_all_correction_cache()


async def _txn(db, user, description: str = "SHOP"):
    return await AtomicTransactionFactory.create_async(db, user_id=user.id, description=description, direction=TransactionDirection.OUT)


async def _rule(db, user, *, version: int, rule_type: RuleType = RuleType.ML_MODEL, name: str | None = None):
    rule = (await db.execute(select(ClassificationRule).where(ClassificationRule.user_id == user.id, ClassificationRule.rule_name == (name or tc.POLICY_RULE_NAME), ClassificationRule.version_number == version))).scalar_one_or_none()
    if rule is None:
        rule = ClassificationRule(user_id=user.id, created_by=user.id, rule_name=name or tc.POLICY_RULE_NAME, version_number=version, effective_date=date(2020, 1, 1), is_active=False, rule_type=rule_type, rule_config={"policy_version": version})
        db.add(rule)
        await db.flush()
    return rule


async def _row(db, user, txn, *, version: int, status: ClassificationStatus, category: str = "DINING", score: int = 72, rule_type: RuleType = RuleType.ML_MODEL, name: str | None = None) -> TransactionClassification:
    rule = await _rule(db, user, version=version, rule_type=rule_type, name=name)
    row = TransactionClassification(atomic_txn_id=txn.id, rule_version_id=rule.id, account_id=None, tags={"category": category, "reason": "test"}, confidence_score=score, status=status)
    db.add(row)
    await db.flush()
    return row


async def _states(db, txn) -> dict[tuple[str, int], tuple[ClassificationStatus, str | None]]:
    rows = (await db.execute(select(TransactionClassification, ClassificationRule).join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id).where(TransactionClassification.atomic_txn_id == txn.id))).all()
    return {(rule.rule_name, rule.version_number): (row.status, (row.tags or {}).get("category")) for row, rule in rows}


def _propose(category: str | None, confidence: int = 75):
    async def proposer(transactions, _policy):
        return [None if category is None else CategoryProposal(category=category, confidence=confidence) for _ in transactions]

    return proposer


@pytest.mark.parametrize(
    ("action", "value", "expected_effect", "expected_state"),
    [
        ("edit_accept", {"value": "groceries"}, "corrected", (ClassificationStatus.DRAFT, "GROCERIES")),
        ("reject", None, "rejected", (ClassificationStatus.SUPERSEDED, "DINING")),
    ],
)
async def test_AC_extraction_classification_hardening_7_user_feedback_survives_newer_policy(db, test_user, action, value, expected_effect, expected_state):
    txn = await _txn(db, test_user)
    draft = await _row(db, test_user, txn, version=1, status=ClassificationStatus.DRAFT, category="DINING")
    effect = await apply_suggestion_feedback(db, test_user.id, draft.id, action, value)
    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_propose("DINING", 90))
    assert (effect, await _states(db, txn)) == (expected_effect, {(tc.POLICY_RULE_NAME, 1): expected_state})


async def test_AC_extraction_classification_hardening_7_reject_retires_all_and_correction_logs_and_reader(db, test_user):
    txn1 = await _txn(db, test_user, "SHOP 1")
    await _row(db, test_user, txn1, version=1, status=ClassificationStatus.APPLIED, category="DINING", score=92)
    draft1 = await _row(db, test_user, txn1, version=2, status=ClassificationStatus.DRAFT, category="SHOPPING")
    await apply_suggestion_feedback(db, test_user.id, draft1.id, "reject", None)
    assert (await _states(db, txn1), await classification_suggestions(db, [txn1.id])) == (
        {(tc.POLICY_RULE_NAME, 1): (ClassificationStatus.SUPERSEDED, "DINING"), (tc.POLICY_RULE_NAME, 2): (ClassificationStatus.SUPERSEDED, "SHOPPING")},
        {},
    )

    txn2 = await _txn(db, test_user, "SHOP 2")
    draft2 = await _row(db, test_user, txn2, version=2, status=ClassificationStatus.DRAFT, category="DINING")
    before = (await classification_suggestions(db, [txn2.id]))[txn2.id]
    await apply_suggestion_feedback(db, test_user.id, draft2.id, "edit_accept", {"value": "groceries"})
    after = (await classification_suggestions(db, [txn2.id]))[txn2.id]
    await apply_suggestion_feedback(db, test_user.id, draft2.id, "edit_accept", {"value": "transport"})
    await db.refresh(draft2)
    log = (await db.execute(select(CorrectionLog).where(CorrectionLog.transaction_id == txn2.id).order_by(CorrectionLog.created_at))).scalars().all()
    assert (
        (before.category, before.corrected),
        (after.category, after.corrected),
        draft2.tags["category"],
        draft2.tags["original_category"],
        [(e.original_category, e.corrected_category) for e in log],
        all(e.transaction_description == txn2.description for e in log),
    ) == (("DINING", False), ("GROCERIES", True), "TRANSPORT", "DINING", [("DINING", "GROCERIES"), ("GROCERIES", "TRANSPORT")], True)


@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_classification_hardening_3_sweep_repairs_and_respects_correction_and_rules(db, test_user):
    txn1 = await _txn(db, test_user, "PAIR")
    older = await _row(db, test_user, txn1, version=1, status=ClassificationStatus.APPLIED, category="DINING", score=92)
    newer = await _row(db, test_user, txn1, version=2, status=ClassificationStatus.DRAFT, category="SHOPPING")
    await classify_transactions(db, test_user.id, [txn1], policy=V2, proposer=_propose("SHOPPING", 75))
    await db.refresh(older)
    await db.refresh(newer)
    assert (older.status, older.superseded_by_id, newer.status) == (ClassificationStatus.SUPERSEDED, newer.id, ClassificationStatus.DRAFT)

    txn2 = await _txn(db, test_user, "CORRECTED")
    older2 = await _row(db, test_user, txn2, version=1, status=ClassificationStatus.DRAFT, category="DINING")
    await _row(db, test_user, txn2, version=2, status=ClassificationStatus.DRAFT, category="SHOPPING")
    await apply_suggestion_feedback(db, test_user.id, older2.id, "edit_accept", {"value": "groceries"})
    await classify_transactions(db, test_user.id, [txn2], policy=V2, proposer=_propose("SHOPPING", 75))
    assert (await _states(db, txn2))[tc.POLICY_RULE_NAME, 1] == (ClassificationStatus.DRAFT, "GROCERIES")

    txn3 = await _txn(db, test_user, "NONLIVE")
    await _row(db, test_user, txn3, version=1, status=ClassificationStatus.APPLIED, category="DINING", score=92)
    await _row(db, test_user, txn3, version=2, status=ClassificationStatus.SUPERSEDED, category="SHOPPING")
    await classify_transactions(db, test_user.id, [txn3], policy=V2, proposer=_propose(None))
    await tc._supersede_older_model_rows(db, test_user.id, [txn3.id], V2.version)
    assert (await _states(db, txn3))[tc.POLICY_RULE_NAME, 1][0] is ClassificationStatus.APPLIED

    txn4 = await _txn(db, test_user, "OTHER_RULE")
    await _row(db, test_user, txn4, version=1, status=ClassificationStatus.APPLIED, category="DINING", score=92)
    await _row(db, test_user, txn4, version=1, status=ClassificationStatus.APPLIED, category="HOUSING", score=100, rule_type=RuleType.KEYWORD_MATCH, name="user keyword rule")
    await classify_transactions(db, test_user.id, [txn4], policy=V2, proposer=_propose("SHOPPING", 75))
    states4 = await _states(db, txn4)
    assert (states4[tc.POLICY_RULE_NAME, 1][0], states4["user keyword rule", 1]) == (ClassificationStatus.SUPERSEDED, (ClassificationStatus.APPLIED, "HOUSING"))


async def test_AC_extraction_classification_hardening_5_the_user_context_is_cleared_after_every_pass(db, test_user):
    txn, unasked = await _txn(db, test_user), await _txn(db, test_user)

    async def failing(_transactions, _policy):
        raise RuntimeError("provider down")

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=_propose("SHOPPING", 75))
    assert tc._CLASSIFICATION_USER.get() is None
    with pytest.raises(RuntimeError):
        await classify_transactions(db, test_user.id, [txn, unasked], policy=V2, proposer=failing)
    assert tc._CLASSIFICATION_USER.get() is None
