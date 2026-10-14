"""AC-extraction.classification-hardening: POST /ai/feedback changes the draft classification (#2419).

The one-click approval books the draft AI suggestion of a row. Before this change, a rejection or a
correction was stored and nothing else changed, so the approval booked the draft that the user had
refused. Each test sends the request through the HTTP client and reads the stored draft afterwards.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import ClassificationStatus, RuleType, TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.identity import AiFeedback, User
from src.ledger import Account
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio


async def _draft(
    db: AsyncSession,
    user_id: UUID,
    *,
    direction: TransactionDirection = TransactionDirection.OUT,
    status: ClassificationStatus = ClassificationStatus.DRAFT,
    category: str = "DINING",
) -> TransactionClassification:
    atomic = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2025, 3, 1),
        amount=Decimal("12.34"),
        direction=direction,
        description=f"Draft {uuid4()}",
        currency="SGD",
        dedup_hash=f"feedback-effect-{uuid4()}",
        source_documents=[],
    )
    db.add(atomic)
    await db.flush()
    rule = ClassificationRule(
        user_id=user_id,
        created_by=user_id,
        rule_name=f"rule-{uuid4()}",
        version_number=1,
        effective_date=date(2025, 1, 1),
        rule_type=RuleType.ML_MODEL,
        rule_config={},
    )
    db.add(rule)
    await db.flush()
    classification = TransactionClassification(
        atomic_txn_id=atomic.id,
        rule_version_id=rule.id,
        account_id=None,
        tags={"category": category, "reason": "test"},
        confidence_score=75,
        status=status,
    )
    db.add(classification)
    await db.commit()
    return classification


async def _reload(db: AsyncSession, classification: TransactionClassification) -> TransactionClassification:
    await db.refresh(classification)
    return classification


async def _post(client: AsyncClient, suggestion_id: UUID, action: str, corrected_value: dict | None = None):
    body: dict = {"suggestion_id": str(suggestion_id), "action": action}
    if corrected_value is not None:
        body["corrected_value"] = corrected_value
    return await client.post("/ai/feedback", json=body)


async def test_AC_extraction_classification_hardening_2_reject_supersedes_the_draft(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    """AC-extraction.classification-hardening.2: a rejection supersedes the draft."""
    draft = await _draft(db, test_user.id)

    response = await _post(client, draft.id, "reject")

    assert response.status_code == 201
    assert (await _reload(db, draft)).status is ClassificationStatus.SUPERSEDED


async def test_AC_extraction_classification_hardening_2_accept_keeps_the_draft_for_the_approval(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    """AC-extraction.classification-hardening.2: an acceptance leaves the draft for the approval."""
    draft = await _draft(db, test_user.id)

    response = await _post(client, draft.id, "accept")

    assert response.status_code == 201
    reloaded = await _reload(db, draft)
    assert reloaded.status is ClassificationStatus.DRAFT
    assert reloaded.tags["category"] == "DINING"


@pytest.mark.parametrize(
    ("action", "corrected_value", "effect"),
    [
        ("accept", None, "accepted"),
        ("reject", None, "rejected"),
        ("edit_accept", {"value": "groceries"}, "corrected"),
    ],
)
async def test_AC_extraction_classification_hardening_2_the_response_names_the_effect(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    action: str,
    corrected_value: dict | None,
    effect: str,
) -> None:
    """AC-extraction.classification-hardening.2: the page shows what happened, not what the button promised."""
    draft = await _draft(db, test_user.id)

    response = await _post(client, draft.id, action, corrected_value)

    assert response.status_code == 201
    assert response.json()["effect"] == effect


async def test_AC_extraction_classification_hardening_2_a_second_decision_on_a_rejected_draft_is_only_recorded(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    """AC-extraction.classification-hardening.2: reject, then accept. The second answer must not claim an effect."""
    draft = await _draft(db, test_user.id)
    await _post(client, draft.id, "reject")

    response = await _post(client, draft.id, "accept")

    assert response.status_code == 201
    assert response.json()["effect"] == "recorded"
    assert (await _reload(db, draft)).status is ClassificationStatus.SUPERSEDED


async def test_AC_extraction_classification_hardening_2_an_unknown_foreign_or_applied_id_is_only_recorded(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    """AC-extraction.classification-hardening.2: all three get the same answer, so the answer leaks nothing."""
    other = await UserFactory.create_async(db)
    foreign = await _draft(db, other.id)
    applied = await _draft(db, test_user.id, status=ClassificationStatus.APPLIED)

    answers = [
        (await _post(client, suggestion_id, "reject")).json()["effect"]
        for suggestion_id in (uuid4(), foreign.id, applied.id)
    ]

    assert answers == ["recorded", "recorded", "recorded"]


async def test_AC_extraction_classification_hardening_2_a_corrected_draft_leaves_the_pending_list(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    """AC-extraction.classification-hardening.2: a decided suggestion is not pending. An accepted one still is."""
    corrected = await _draft(db, test_user.id)
    accepted = await _draft(db, test_user.id)
    await _post(client, corrected.id, "edit_accept", {"value": "groceries"})
    await _post(client, accepted.id, "accept")

    listed = {item["suggestion_id"] for item in (await client.get("/ai/suggestions")).json()["items"]}

    assert listed == {str(accepted.id)}


async def test_AC_extraction_classification_hardening_2_feedback_on_a_foreign_draft_changes_nothing(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    """The caller owns no such draft. The answer is the same as for an unknown id."""
    other = await UserFactory.create_async(db)
    foreign = await _draft(db, other.id)

    reject = await _post(client, foreign.id, "reject")
    edit = await _post(client, foreign.id, "edit_accept", {"value": "GROCERIES"})

    assert reject.status_code == 201
    assert edit.status_code == 201
    reloaded = await _reload(db, foreign)
    assert reloaded.status is ClassificationStatus.DRAFT
    assert reloaded.tags["category"] == "DINING"


async def test_AC_extraction_classification_hardening_2_an_applied_row_is_not_rejected_by_feedback(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    applied = await _draft(db, test_user.id, status=ClassificationStatus.APPLIED)

    response = await _post(client, applied.id, "reject")

    assert response.status_code == 201
    assert (await _reload(db, applied)).status is ClassificationStatus.APPLIED


@pytest.mark.parametrize(
    ("corrected_value", "category", "account_name"),
    [
        ({"value": "groceries"}, "GROCERIES", "Expense - Groceries"),
        ({"value": "Expense - Dining"}, "DINING", "Expense - Dining"),
        ({"category": "Other Expense"}, "OTHER_EXPENSE", "Expense - Other"),
    ],
)
async def test_AC_extraction_classification_hardening_2_edit_accept_replaces_category_and_account(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    corrected_value: dict,
    category: str,
    account_name: str,
) -> None:
    """AC-extraction.classification-hardening.2: a correction replaces the category and the account of the draft."""
    draft = await _draft(db, test_user.id, category="TRANSPORT")

    response = await _post(client, draft.id, "edit_accept", corrected_value)

    assert response.status_code == 201
    reloaded = await _reload(db, draft)
    assert reloaded.status is ClassificationStatus.DRAFT
    assert reloaded.tags["category"] == category
    assert reloaded.tags["original_category"] == "TRANSPORT"
    assert reloaded.tags["corrected_by_user"] is True
    account = await db.get(Account, reloaded.account_id)
    assert account is not None
    assert (account.name, account.user_id, account.currency) == (account_name, test_user.id, "SGD")


async def test_AC_extraction_classification_hardening_2_edit_accept_to_a_transfer_leaves_no_account(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    """A class that is not income or expense has no category account. The draft keeps no account.

    The one-click approval then books a transfer as a Processing leg.
    """
    draft = await _draft(db, test_user.id)

    response = await _post(client, draft.id, "edit_accept", {"value": "transfer"})

    assert response.status_code == 201
    reloaded = await _reload(db, draft)
    assert reloaded.tags["category"] == "TRANSFER"
    assert reloaded.account_id is None


@pytest.mark.parametrize(
    ("corrected_value", "reason"),
    [
        (None, "A corrected category is required"),
        ({"value": "   "}, "A corrected category is required"),
        ({"value": "Food & Dining"}, "not a category"),
        ({"value": "SALARY"}, "does not fit"),  # income category for an outgoing row
    ],
)
async def test_AC_extraction_classification_hardening_2_an_unusable_correction_is_refused(
    client: AsyncClient, db: AsyncSession, test_user: User, corrected_value: dict | None, reason: str
) -> None:
    """The user hears that the correction failed. Nothing is stored and the draft stays as it was."""
    draft = await _draft(db, test_user.id)

    response = await _post(client, draft.id, "edit_accept", corrected_value)

    assert response.status_code == 400
    assert reason in response.json()["detail"]
    reloaded = await _reload(db, draft)
    assert reloaded.status is ClassificationStatus.DRAFT
    assert reloaded.tags["category"] == "DINING"
    stored = (await db.execute(select(AiFeedback).where(AiFeedback.suggestion_id == draft.id))).scalars().all()
    assert stored == []


async def test_AC_extraction_classification_hardening_2_an_income_correction_fits_an_incoming_row(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    """The direction rule is a rule, not a ban: SALARY is the right answer for money in."""
    draft = await _draft(db, test_user.id, direction=TransactionDirection.IN, category="OTHER_INCOME")

    response = await _post(client, draft.id, "edit_accept", {"value": "SALARY"})

    assert response.status_code == 201
    reloaded = await _reload(db, draft)
    assert reloaded.tags["category"] == "SALARY"
    account = await db.get(Account, reloaded.account_id)
    assert account is not None and account.name == "Income - Salary"


async def test_list_ai_suggestions_includes_direction_and_filters_by_statement_id(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    """GET /ai/suggestions returns direction and filters by statement_id when provided."""
    from tests.api._statement_router_fixtures import (
        add_txn,
        build_statement,
        create_statement_account,
    )

    bank = await create_statement_account(db, test_user.id, "DBS Suggestions Filter")
    stmt1 = build_statement(test_user.id, "hash_sugg_filter_1", 88)
    stmt1.account_id = bank.id
    stmt2 = build_statement(test_user.id, "hash_sugg_filter_2", 88)
    stmt2.account_id = bank.id
    db.add_all([stmt1, stmt2])
    await db.flush()

    txn1 = await add_txn(
        db, stmt1, txn_date=date(2025, 3, 1), description="Coffee", amount=Decimal("10.00"), direction="OUT"
    )
    txn2 = await add_txn(
        db, stmt2, txn_date=date(2025, 3, 2), description="Bonus", amount=Decimal("500.00"), direction="IN"
    )

    rule = ClassificationRule(
        user_id=test_user.id,
        created_by=test_user.id,
        rule_name=f"rule-{uuid4()}",
        version_number=1,
        effective_date=date(2025, 1, 1),
        rule_type=RuleType.ML_MODEL,
        rule_config={},
    )
    db.add(rule)
    await db.flush()

    cls1 = TransactionClassification(
        atomic_txn_id=txn1.id,
        rule_version_id=rule.id,
        account_id=None,
        tags={"category": "DINING", "reason": "test"},
        confidence_score=75,
        status=ClassificationStatus.DRAFT,
    )
    cls2 = TransactionClassification(
        atomic_txn_id=txn2.id,
        rule_version_id=rule.id,
        account_id=None,
        tags={"category": "OTHER_INCOME", "reason": "test"},
        confidence_score=72,
        status=ClassificationStatus.DRAFT,
    )
    db.add_all([cls1, cls2])
    await db.commit()

    resp_stmt1 = await client.get(f"/ai/suggestions?statement_id={stmt1.id}")
    assert resp_stmt1.status_code == 200
    items1 = resp_stmt1.json()["items"]
    assert len(items1) == 1
    assert items1[0]["suggestion_id"] == str(cls1.id)
    assert items1[0]["direction"] == "OUT"

    resp_stmt2 = await client.get(f"/ai/suggestions?statement_id={stmt2.id}")
    assert resp_stmt2.status_code == 200
    items2 = resp_stmt2.json()["items"]
    assert len(items2) == 1
    assert items2[0]["suggestion_id"] == str(cls2.id)
    assert items2[0]["direction"] == "IN"
