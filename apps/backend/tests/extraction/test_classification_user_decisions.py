"""AC-extraction.classification-hardening: a user decision on a draft outlives a later model pass (#2419).

A user can reject a draft or correct its category (`POST /ai/feedback`). A later pass of the classifier,
for example under a newer policy version, must not undo that decision.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from src.extraction import ClassificationStatus, RuleType, TransactionDirection
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.correction_service import clear_all_correction_cache
from src.extraction.extension.transaction_classification import (
    CategoryProposal,
    apply_suggestion_feedback,
    classification_suggestions,
    classify_transactions,
)
from src.extraction.orm.correction import CorrectionLog
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from tests.factories import AtomicTransactionFactory

pytestmark = pytest.mark.asyncio

V2 = tc.POLICY_VERSIONS[1]


@pytest.fixture(autouse=True)
def _classification_on(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", True)
    clear_all_correction_cache()


async def _txn(db, user, description: str = "SHOP", direction: TransactionDirection = TransactionDirection.OUT):
    return await AtomicTransactionFactory.create_async(
        db, user_id=user.id, description=description, direction=direction
    )


async def _rule(db, user, *, version: int, rule_type: RuleType = RuleType.ML_MODEL, name: str | None = None):
    rule = (
        await db.execute(
            select(ClassificationRule)
            .where(ClassificationRule.user_id == user.id)
            .where(ClassificationRule.rule_name == (name or tc.POLICY_RULE_NAME))
            .where(ClassificationRule.version_number == version)
        )
    ).scalar_one_or_none()
    if rule is None:
        rule = ClassificationRule(
            user_id=user.id,
            created_by=user.id,
            rule_name=name or tc.POLICY_RULE_NAME,
            version_number=version,
            effective_date=date(2020, 1, 1),
            is_active=False,
            rule_type=rule_type,
            rule_config={"policy_version": version},
        )
        db.add(rule)
        await db.flush()
    return rule


async def _row(
    db,
    user,
    txn,
    *,
    version: int,
    status: ClassificationStatus,
    category: str = "DINING",
    score: int = 72,
    rule_type: RuleType = RuleType.ML_MODEL,
    name: str | None = None,
) -> TransactionClassification:
    rule = await _rule(db, user, version=version, rule_type=rule_type, name=name)
    row = TransactionClassification(
        atomic_txn_id=txn.id,
        rule_version_id=rule.id,
        account_id=None,
        tags={"category": category, "reason": "test"},
        confidence_score=score,
        status=status,
    )
    db.add(row)
    await db.flush()
    return row


async def _states(db, txn) -> dict[tuple[str, int], tuple[ClassificationStatus, str | None]]:
    rows = (
        await db.execute(
            select(TransactionClassification, ClassificationRule)
            .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
            .where(TransactionClassification.atomic_txn_id == txn.id)
        )
    ).all()
    return {(rule.rule_name, rule.version_number): (row.status, (row.tags or {}).get("category")) for row, rule in rows}


async def _propose(category: str, confidence: int):
    async def proposer(transactions, _policy):
        return [CategoryProposal(category=category, confidence=confidence) for _ in transactions]

    return proposer


async def test_AC_extraction_classification_hardening_7_a_corrected_draft_survives_a_newer_policy(db, test_user):
    """AC-extraction.classification-hardening.7: the model must not post its own category over the correction."""
    txn = await _txn(db, test_user)
    draft = await _row(db, test_user, txn, version=1, status=ClassificationStatus.DRAFT, category="DINING")
    effect = await apply_suggestion_feedback(db, test_user.id, draft.id, "edit_accept", {"value": "groceries"})

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=await _propose("DINING", 90))

    assert effect == "corrected"
    assert await _states(db, txn) == {(tc.POLICY_RULE_NAME, 1): (ClassificationStatus.DRAFT, "GROCERIES")}


async def test_AC_extraction_classification_hardening_7_a_rejected_draft_is_not_proposed_again(db, test_user):
    """AC-extraction.classification-hardening.7: a newer policy does not bring a rejected suggestion back."""
    txn = await _txn(db, test_user)
    draft = await _row(db, test_user, txn, version=1, status=ClassificationStatus.DRAFT, category="DINING")
    effect = await apply_suggestion_feedback(db, test_user.id, draft.id, "reject", None)

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=await _propose("DINING", 90))

    assert effect == "rejected"
    assert await _states(db, txn) == {(tc.POLICY_RULE_NAME, 1): (ClassificationStatus.SUPERSEDED, "DINING")}


async def test_AC_extraction_classification_hardening_7_reject_retires_every_model_row_of_the_transaction(
    db, test_user
):
    """AC-extraction.classification-hardening.7: a v1 applied row must not come back after the v2 draft is rejected."""
    txn = await _txn(db, test_user)
    await _row(db, test_user, txn, version=1, status=ClassificationStatus.APPLIED, category="DINING", score=92)
    draft = await _row(db, test_user, txn, version=2, status=ClassificationStatus.DRAFT, category="SHOPPING")

    await apply_suggestion_feedback(db, test_user.id, draft.id, "reject", None)

    assert await _states(db, txn) == {
        (tc.POLICY_RULE_NAME, 1): (ClassificationStatus.SUPERSEDED, "DINING"),
        (tc.POLICY_RULE_NAME, 2): (ClassificationStatus.SUPERSEDED, "SHOPPING"),
    }
    assert await classification_suggestions(db, [txn.id]) == {}


async def test_AC_extraction_classification_hardening_7_a_correction_is_logged_with_the_value_it_replaced(
    db, test_user
):
    """AC-extraction.classification-hardening.7: a second correction keeps the first original and logs both."""
    txn = await _txn(db, test_user)
    draft = await _row(db, test_user, txn, version=2, status=ClassificationStatus.DRAFT, category="DINING")

    await apply_suggestion_feedback(db, test_user.id, draft.id, "edit_accept", {"value": "groceries"})
    await apply_suggestion_feedback(db, test_user.id, draft.id, "edit_accept", {"value": "transport"})

    await db.refresh(draft)
    assert draft.tags["category"] == "TRANSPORT"
    assert draft.tags["original_category"] == "DINING"
    log = (
        (
            await db.execute(
                select(CorrectionLog).where(CorrectionLog.transaction_id == txn.id).order_by(CorrectionLog.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [(entry.original_category, entry.corrected_category) for entry in log] == [
        ("DINING", "GROCERIES"),
        ("GROCERIES", "TRANSPORT"),
    ]
    assert all(entry.transaction_description == txn.description for entry in log)


async def test_AC_extraction_classification_hardening_7_the_reader_reports_a_corrected_row(db, test_user):
    """AC-extraction.classification-hardening.7: the one-click approval needs the flag to name the user."""
    txn = await _txn(db, test_user)
    draft = await _row(db, test_user, txn, version=2, status=ClassificationStatus.DRAFT, category="DINING")
    before = (await classification_suggestions(db, [txn.id]))[txn.id]

    await apply_suggestion_feedback(db, test_user.id, draft.id, "edit_accept", {"value": "groceries"})
    after = (await classification_suggestions(db, [txn.id]))[txn.id]

    assert (before.category, before.corrected) == ("DINING", False)
    assert (after.category, after.corrected) == ("GROCERIES", True)


@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_classification_hardening_3_a_pair_left_by_an_earlier_release_is_repaired(db, test_user):
    """AC-extraction.classification-hardening.3: a row that has both a v1 and a v2 row keeps only the newer one."""
    txn = await _txn(db, test_user)
    older = await _row(db, test_user, txn, version=1, status=ClassificationStatus.APPLIED, category="DINING", score=92)
    newer = await _row(db, test_user, txn, version=2, status=ClassificationStatus.DRAFT, category="SHOPPING")

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=await _propose("SHOPPING", 75))

    await db.refresh(older)
    await db.refresh(newer)
    assert older.status is ClassificationStatus.SUPERSEDED
    assert older.superseded_by_id == newer.id
    assert newer.status is ClassificationStatus.DRAFT


async def test_AC_extraction_classification_hardening_7_the_sweep_keeps_a_row_that_the_user_corrected(db, test_user):
    """AC-extraction.classification-hardening.7: a newer row of the model does not retire the correction."""
    txn = await _txn(db, test_user)
    older = await _row(db, test_user, txn, version=1, status=ClassificationStatus.DRAFT, category="DINING")
    await _row(db, test_user, txn, version=2, status=ClassificationStatus.DRAFT, category="SHOPPING")
    await apply_suggestion_feedback(db, test_user.id, older.id, "edit_accept", {"value": "groceries"})

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=await _propose("SHOPPING", 75))

    states = await _states(db, txn)
    assert states[(tc.POLICY_RULE_NAME, 1)] == (ClassificationStatus.DRAFT, "GROCERIES")


async def test_AC_extraction_classification_hardening_3_an_older_row_stays_when_the_newer_row_is_not_live(
    db, test_user
):
    """AC-extraction.classification-hardening.3: no live successor means nothing to retire the older row for."""
    txn = await _txn(db, test_user)
    await _row(db, test_user, txn, version=1, status=ClassificationStatus.APPLIED, category="DINING", score=92)
    await _row(db, test_user, txn, version=2, status=ClassificationStatus.SUPERSEDED, category="SHOPPING")

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=await _propose("SHOPPING", 75))

    states = await _states(db, txn)
    assert states[(tc.POLICY_RULE_NAME, 1)][0] is ClassificationStatus.APPLIED


async def test_AC_extraction_classification_hardening_3_the_sweep_leaves_rows_of_other_rules_alone(db, test_user):
    """AC-extraction.classification-hardening.3: only rows of the model policy are superseded."""
    txn = await _txn(db, test_user)
    await _row(db, test_user, txn, version=1, status=ClassificationStatus.APPLIED, category="DINING", score=92)
    await _row(
        db,
        test_user,
        txn,
        version=1,
        status=ClassificationStatus.APPLIED,
        category="HOUSING",
        score=100,
        rule_type=RuleType.KEYWORD_MATCH,
        name="user keyword rule",
    )

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=await _propose("SHOPPING", 75))

    states = await _states(db, txn)
    assert states[(tc.POLICY_RULE_NAME, 1)][0] is ClassificationStatus.SUPERSEDED
    assert states[("user keyword rule", 1)] == (ClassificationStatus.APPLIED, "HOUSING")


async def test_AC_extraction_classification_hardening_5_the_user_context_is_cleared_after_every_pass(db, test_user):
    """AC-extraction.classification-hardening.5: the user id must not leak into the next call of the same task."""
    txn = await _txn(db, test_user)
    unasked = await _txn(db, test_user)  # a row without a row is asked, so the failing provider runs

    async def failing(_transactions, _policy):
        raise RuntimeError("provider down")

    await classify_transactions(db, test_user.id, [txn], policy=V2, proposer=await _propose("SHOPPING", 75))
    assert tc._CLASSIFICATION_USER.get() is None
    with pytest.raises(RuntimeError):
        await classify_transactions(db, test_user.id, [txn, unasked], policy=V2, proposer=failing)
    assert tc._CLASSIFICATION_USER.get() is None
