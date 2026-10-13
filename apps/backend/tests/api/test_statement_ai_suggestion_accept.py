"""AC-extraction.accept-ai-suggestions: the one-click approval uses the draft AI suggestions (#2415).

The statement review page offers "Auto-Fill Default Categories & Approve". Before this change, the
action posted every unresolved row as "General Expense" or "General Income" from its direction and
ignored the draft AI suggestions that the classifier had stored for the row.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.config import settings
from src.extraction import ClassificationStatus, RuleType
from src.extraction.extension.transaction_classification import POLICY_RULE_NAME
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import Account, AccountType, JournalEntry
from src.routers import statements as statements_router
from src.schemas.review import Stage1ApprovalRequest
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account

pytestmark = pytest.mark.asyncio


async def _category_account(db, user_id, name: str, account_type: AccountType) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency="SGD")
    db.add(account)
    await db.flush()
    return account


async def _draft(db, user_id, txn, *, category: str, account: Account | None, score: int) -> None:
    rule = (
        await db.execute(
            select(ClassificationRule)
            .where(ClassificationRule.user_id == user_id)
            .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
        )
    ).scalar_one_or_none()
    if rule is None:
        rule = ClassificationRule(
            user_id=user_id,
            created_by=user_id,
            rule_name=POLICY_RULE_NAME,
            version_number=2,
            effective_date=date(2020, 1, 1),
            is_active=False,
            rule_type=RuleType.ML_MODEL,
            rule_config={"policy_version": 2},
        )
        db.add(rule)
        await db.flush()
    db.add(
        TransactionClassification(
            atomic_txn_id=txn.id,
            rule_version_id=rule.id,
            account_id=account.id if account else None,
            tags={"category": category, "reason": "test"},
            confidence_score=score,
            status=ClassificationStatus.DRAFT,
        )
    )
    await db.flush()


async def _statement(db, user_id, file_hash: str):
    bank = await create_statement_account(db, user_id, "DBS Accept AI")
    statement = build_statement(user_id, file_hash, 88)
    statement.account_id = bank.id
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.flush()
    return statement, bank


async def _counter_account_names(db, txn, bank_id) -> set[str]:
    entry = (
        await db.execute(
            select(JournalEntry).where(JournalEntry.source_id == txn.id).options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()
    account_ids = {line.account_id for line in entry.lines if line.account_id != bank_id}
    return set((await db.execute(select(Account.name).where(Account.id.in_(account_ids)))).scalars())


async def test_AC_extraction_accept_ai_suggestions_1_auto_fill_posts_the_draft_category_and_account(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.1: a row with a draft AI suggestion posts to that account."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(db, test_user.id, "hash_accept_ai_1")
    interest = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Interest Earned", amount=Decimal("20.00"), direction="IN"
    )
    dining = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 3),
        description="PayNow to MERCHANT HAWKER",
        amount=Decimal("15.00"),
        direction="OUT",
    )
    opaque = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Opaque merchant", amount=Decimal("5.00"), direction="OUT"
    )
    await db.flush()
    income_account = await _category_account(db, test_user.id, "Income - Interest", AccountType.INCOME)
    expense_account = await _category_account(db, test_user.id, "Expense - Dining", AccountType.EXPENSE)
    await _draft(db, test_user.id, interest, category="INTEREST", account=income_account, score=80)
    await _draft(db, test_user.id, dining, category="DINING", account=expense_account, score=76)
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    assert result.journal_entries_created == 3
    assert await _counter_account_names(db, interest, bank.id) == {"Income - Interest"}
    assert await _counter_account_names(db, dining, bank.id) == {"Expense - Dining"}
    # No draft exists for the third row, so the old default still applies.
    assert await _counter_account_names(db, opaque, bank.id) == {"General Expense (SGD)"}


async def test_AC_extraction_accept_ai_suggestions_2_a_non_income_expense_draft_is_left_for_a_person(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.2: a row that the AI named TRANSFER is not posted as a general expense."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, _bank = await _statement(db, test_user.id, "hash_accept_ai_2")
    statement.closing_balance = Decimal("80.00")
    transfer = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 2),
        description="Move to savings",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    await db.flush()
    await _draft(db, test_user.id, transfer, category="TRANSFER", account=None, score=78)
    await db.commit()

    with pytest.raises(HTTPException) as error:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id,
            request=Stage1ApprovalRequest(auto_fill_default_categories=True),
            db=db,
            user_id=test_user.id,
        )

    assert error.value.status_code == 409
    assert error.value.detail == "Economic review required: intent_missing"
    posted = set((await db.execute(select(JournalEntry.source_id))).scalars())
    assert transfer.id not in posted, "the transfer row must wait for a person"
    general = set((await db.execute(select(Account.name).where(Account.name.like("General %")))).scalars())
    assert general == set(), "no general account is created for a row that the AI named a transfer"


async def test_AC_extraction_accept_ai_suggestions_3_a_suggestion_that_contradicts_the_direction_falls_back(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.3: an income suggestion on an outgoing row uses the direction default."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(db, test_user.id, "hash_accept_ai_3")
    outgoing = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Odd label", amount=Decimal("20.00"), direction="OUT"
    )
    incoming = await add_txn(
        db, statement, txn_date=date(2025, 1, 3), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    await db.flush()
    income_account = await _category_account(db, test_user.id, "Income - Salary", AccountType.INCOME)
    await _draft(db, test_user.id, outgoing, category="SALARY", account=income_account, score=79)
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    assert result.journal_entries_created == 2
    assert await _counter_account_names(db, outgoing, bank.id) == {"General Expense (SGD)"}
    assert await _counter_account_names(db, incoming, bank.id) == {"General Income (SGD)"}
