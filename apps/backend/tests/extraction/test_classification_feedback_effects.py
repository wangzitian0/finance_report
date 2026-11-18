from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import ClassificationStatus, RuleType, TransactionDirection
from src.extraction.orm.ai_feedback import AiFeedback
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.identity import User
from src.ledger import Account
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account
from tests.extraction._statement_run_helpers import make_account
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio


async def _draft(db: AsyncSession, user_id: UUID, *, direction: TransactionDirection = TransactionDirection.OUT, status: ClassificationStatus = ClassificationStatus.DRAFT, tags: object | None = None, category: str = "DINING", account_id: UUID | None = None) -> TransactionClassification:
    atomic = AtomicTransaction(user_id=user_id, txn_date=date(2025, 3, 1), amount=Decimal("12.34"), direction=direction, description=f"Draft {uuid4()}", currency="SGD", dedup_hash=f"feedback-effect-{uuid4()}", source_documents=[])
    rule = ClassificationRule(user_id=user_id, created_by=user_id, rule_name=f"rule-{uuid4()}", version_number=1, effective_date=date(2025, 1, 1), rule_type=RuleType.ML_MODEL, rule_config={})
    db.add_all([atomic, rule])
    await db.flush()
    cls = TransactionClassification(atomic_txn_id=atomic.id, rule_version_id=rule.id, account_id=account_id, tags={"category": category, "reason": "test"} if tags is None else tags, confidence_score=75, status=status)
    db.add(cls)
    await db.commit()
    return cls


async def _post(client: AsyncClient, suggestion_id: UUID, action: str, corrected_value: dict | None = None):
    return await client.post("/statements/classification-feedback", json={"suggestion_id": str(suggestion_id), "action": action, **({} if corrected_value is None else {"corrected_value": corrected_value})})


@pytest.mark.parametrize(("action", "corrected_value", "effect", "expected_status"), [("accept", None, "accepted", ClassificationStatus.DRAFT), ("reject", None, "rejected", ClassificationStatus.SUPERSEDED), ("edit_accept", {"value": "groceries"}, "corrected", ClassificationStatus.DRAFT)])
async def test_feedback_effects_and_status_transitions(client: AsyncClient, db: AsyncSession, test_user: User, action, corrected_value, effect, expected_status):
    draft = await _draft(db, test_user.id)
    resp = await _post(client, draft.id, action, corrected_value)
    await db.refresh(draft)
    assert (resp.status_code, resp.json()["effect"], draft.status) == (201, effect, expected_status)


async def test_feedback_edge_cases_foreign_applied_repeat_and_pending_list(client: AsyncClient, db: AsyncSession, test_user: User):
    other = await UserFactory.create_async(db)
    foreign, applied, rejected, corrected, accepted = await _draft(db, other.id), await _draft(db, test_user.id, status=ClassificationStatus.APPLIED), await _draft(db, test_user.id), await _draft(db, test_user.id), await _draft(db, test_user.id)
    for missing in (uuid4(), foreign.id):
        assert (await _post(client, missing, "reject")).status_code == 404 and (await db.execute(select(AiFeedback).where(AiFeedback.suggestion_id == missing))).scalars().all() == []

    assert (await _post(client, foreign.id, "edit_accept", {"value": "GROCERIES"})).status_code == 404
    await db.refresh(foreign)
    r_app = await _post(client, applied.id, "reject")
    await _post(client, rejected.id, "reject")
    r_second = await _post(client, rejected.id, "accept")
    await db.refresh(applied)
    await db.refresh(rejected)
    assert (foreign.status, foreign.tags["category"], r_app.status_code, r_app.json()["effect"], applied.status, r_second.status_code, r_second.json()["effect"], rejected.status) == (
        ClassificationStatus.DRAFT, "DINING", 201, "recorded", ClassificationStatus.APPLIED, 201, "recorded", ClassificationStatus.SUPERSEDED
    )

    await _post(client, corrected.id, "edit_accept", {"value": "groceries"})
    await _post(client, accepted.id, "accept")
    listed = {item["suggestion_id"] for item in (await client.get("/statements/classification-suggestions")).json()["items"]}
    assert str(accepted.id) in listed and str(corrected.id) not in listed


@pytest.mark.parametrize(
    ("direction", "initial_category", "corrected_value", "category", "account_name"),
    [
        (TransactionDirection.OUT, "TRANSPORT", {"value": "groceries"}, "GROCERIES", "Expense - Groceries"),
        (TransactionDirection.OUT, "TRANSPORT", {"value": "Expense - Dining"}, "DINING", "Expense - Dining"),
        (TransactionDirection.OUT, "TRANSPORT", {"category": "Other Expense"}, "OTHER_EXPENSE", "Expense - Other"),
        (TransactionDirection.OUT, "DINING", {"value": "transfer"}, "TRANSFER", None),
        (TransactionDirection.IN, "OTHER_INCOME", {"value": "SALARY"}, "SALARY", "Income - Salary"),
    ],
)
async def test_edit_accept_replaces_category_and_account(client: AsyncClient, db: AsyncSession, test_user: User, direction, initial_category, corrected_value, category, account_name):
    draft = await _draft(db, test_user.id, direction=direction, category=initial_category)
    resp = await _post(client, draft.id, "edit_accept", corrected_value)
    await db.refresh(draft)
    assert (resp.status_code, draft.status, draft.tags["category"], draft.tags["original_category"], draft.tags["corrected_by_user"]) == (201, ClassificationStatus.DRAFT, category, initial_category, True)
    if account_name is None:
        assert draft.account_id is None
    else:
        acct = await db.get(Account, draft.account_id)
        assert acct is not None and (acct.name, acct.user_id, acct.currency) == (account_name, test_user.id, "SGD")


@pytest.mark.parametrize(("corrected_value", "reason"), [(None, "A corrected category is required"), ({"value": "   "}, "A corrected category is required"), ({"value": "Food & Dining"}, "not a category"), ({"value": "SALARY"}, "does not fit")])
async def test_unusable_correction_is_refused(client: AsyncClient, db: AsyncSession, test_user: User, corrected_value: dict | None, reason: str):
    draft = await _draft(db, test_user.id)
    resp = await _post(client, draft.id, "edit_accept", corrected_value)
    await db.refresh(draft)
    stored = (await db.execute(select(AiFeedback).where(AiFeedback.suggestion_id == draft.id))).scalars().all()
    assert resp.status_code == 400 and reason in resp.json()["detail"] and (draft.status, draft.tags["category"], stored) == (ClassificationStatus.DRAFT, "DINING", [])


async def test_list_ai_suggestions_includes_direction_filters_statement_and_handles_non_dict_tags(client: AsyncClient, db: AsyncSession, test_user: User):
    bank, stmt1, stmt2 = await create_statement_account(db, test_user.id, "DBS Suggestions Filter"), build_statement(test_user.id, "hash_sugg_filter_1", 88), build_statement(test_user.id, "hash_sugg_filter_2", 88)
    stmt1.account_id = stmt2.account_id = bank.id
    db.add_all([stmt1, stmt2])
    await db.flush()
    txn1, txn2 = await add_txn(db, stmt1, txn_date=date(2025, 3, 1), description="Coffee", amount=Decimal("10.00"), direction="OUT"), await add_txn(db, stmt2, txn_date=date(2025, 3, 2), description="Bonus", amount=Decimal("500.00"), direction="IN")
    rule = ClassificationRule(user_id=test_user.id, created_by=test_user.id, rule_name=f"rule-{uuid4()}", version_number=1, effective_date=date(2025, 1, 1), rule_type=RuleType.ML_MODEL, rule_config={})
    db.add(rule)
    await db.flush()
    cls1, cls2 = (
        TransactionClassification(atomic_txn_id=txn1.id, rule_version_id=rule.id, account_id=None, tags={"category": "DINING", "reason": "test"}, confidence_score=75, status=ClassificationStatus.DRAFT),
        TransactionClassification(atomic_txn_id=txn2.id, rule_version_id=rule.id, account_id=None, tags={"category": "OTHER_INCOME", "reason": "test"}, confidence_score=72, status=ClassificationStatus.DRAFT),
    )
    db.add_all([cls1, cls2])
    acct = await make_account(db, test_user.id, name="Test acct")
    cls_nondict = await _draft(db, test_user.id, tags="not-a-dict", account_id=acct.id)

    for sid, expected_cls, expected_dir in ((stmt1.id, cls1.id, "OUT"), (stmt2.id, cls2.id, "IN")):
        resp = await client.get(f"/statements/classification-suggestions?statement_id={sid}")
        items = resp.json()["items"]
        assert (resp.status_code, len(items), items[0]["suggestion_id"], items[0]["direction"]) == (200, 1, str(expected_cls), expected_dir)

    all_items = (await client.get("/statements/classification-suggestions")).json()["items"]
    assert [i for i in all_items if i["suggestion_id"] == str(cls_nondict.id)][0]["suggested_category_or_match"] == str(acct.id)
