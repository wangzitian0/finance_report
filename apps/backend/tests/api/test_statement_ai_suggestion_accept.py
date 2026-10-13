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

from src.audit.orm.trace_record import TraceRecordRow
from src.config import settings
from src.extraction import ClassificationStatus, RuleType
from src.extraction.extension.transaction_classification import POLICY_RULE_NAME
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.identity import AiFeedbackRequest
from src.ledger import Account, AccountType, JournalEntry
from src.routers import ai_feedback as ai_feedback_router, statements as statements_router
from src.schemas.review import Stage1ApprovalRequest
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account

pytestmark = pytest.mark.asyncio


async def _category_account(db, user_id, name: str, account_type: AccountType) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency="SGD")
    db.add(account)
    await db.flush()
    return account


async def _draft(
    db,
    user_id,
    txn,
    *,
    category: str,
    account: Account | None,
    score: int,
    status: ClassificationStatus = ClassificationStatus.DRAFT,
) -> None:
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
            status=status,
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


async def test_AC_extraction_accept_ai_suggestions_5_applied_rows_keep_their_ai_category(db, test_user, monkeypatch):
    """AC-extraction.accept-ai-suggestions.5: a row that the classifier applied posts to its AI account, not a general one."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(db, test_user.id, "hash_accept_ai_5")
    applied = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Interest Earned", amount=Decimal("20.00"), direction="IN"
    )
    draft = await add_txn(
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
    await _draft(
        db,
        test_user.id,
        applied,
        category="INTEREST",
        account=income_account,
        score=92,
        status=ClassificationStatus.APPLIED,
    )
    await _draft(db, test_user.id, draft, category="DINING", account=expense_account, score=76)
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    assert result.journal_entries_created == 3
    assert await _counter_account_names(db, applied, bank.id) == {"Income - Interest"}
    assert await _counter_account_names(db, draft, bank.id) == {"Expense - Dining"}
    assert await _counter_account_names(db, opaque, bank.id) == {"General Expense (SGD)"}

    # Provenance: the classifier decided the applied row, so the normal posting records a live-LLM
    # proposal. The one-click records a person's decision for the draft and the general row only.
    provenance_by_txn = {
        row.target_id: row.provenance
        for row in (
            await db.execute(
                select(TraceRecordRow)
                .where(TraceRecordRow.assertion_kind == "economic_intent")
                .where(TraceRecordRow.target_id.in_([str(applied.id), str(draft.id), str(opaque.id)]))
            )
        ).scalars()
    }
    assert provenance_by_txn[str(applied.id)] == "live_llm"
    assert provenance_by_txn[str(draft.id)] != "live_llm"
    assert provenance_by_txn[str(opaque.id)] != "live_llm"


async def _classification_id(db, txn):
    return (
        await db.execute(select(TransactionClassification.id).where(TransactionClassification.atomic_txn_id == txn.id))
    ).scalar_one()


async def test_AC_extraction_classification_hardening_2_a_rejected_draft_is_not_booked_by_the_approval(
    db, test_user, monkeypatch
):
    """AC-extraction.classification-hardening.2: the user refused the draft category. The approval uses the default."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(db, test_user.id, "hash_hardening_2_reject")
    statement.closing_balance = Decimal("80.00")
    refused = await add_txn(
        db, statement, txn_date=date(2025, 1, 3), description="Refused", amount=Decimal("15.00"), direction="OUT"
    )
    kept = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Kept", amount=Decimal("5.00"), direction="OUT"
    )
    await db.flush()
    dining = await _category_account(db, test_user.id, "Expense - Dining", AccountType.EXPENSE)
    await _draft(db, test_user.id, refused, category="DINING", account=dining, score=76)
    await _draft(db, test_user.id, kept, category="DINING", account=dining, score=76)
    await db.commit()

    await ai_feedback_router.create_ai_feedback(
        AiFeedbackRequest(suggestion_id=await _classification_id(db, refused), action="reject"),
        db=db,
        user_id=test_user.id,
    )
    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    assert result.journal_entries_created == 2
    assert await _counter_account_names(db, refused, bank.id) == {"General Expense (SGD)"}
    assert await _counter_account_names(db, kept, bank.id) == {"Expense - Dining"}


async def test_AC_extraction_classification_hardening_2_a_corrected_draft_is_booked_with_the_user_category(
    db, test_user, monkeypatch
):
    """AC-extraction.classification-hardening.2: the approval books the category that the user typed."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(db, test_user.id, "hash_hardening_2_edit")
    statement.closing_balance = Decimal("85.00")
    corrected = await add_txn(
        db, statement, txn_date=date(2025, 1, 3), description="Corrected", amount=Decimal("15.00"), direction="OUT"
    )
    await db.flush()
    dining = await _category_account(db, test_user.id, "Expense - Dining", AccountType.EXPENSE)
    await _draft(db, test_user.id, corrected, category="DINING", account=dining, score=76)
    await db.commit()

    await ai_feedback_router.create_ai_feedback(
        AiFeedbackRequest(
            suggestion_id=await _classification_id(db, corrected),
            action="edit_accept",
            corrected_value={"value": "groceries"},
        ),
        db=db,
        user_id=test_user.id,
    )
    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    assert result.journal_entries_created == 1
    assert await _counter_account_names(db, corrected, bank.id) == {"Expense - Groceries"}


async def test_AC_extraction_classification_hardening_4_an_applied_row_that_the_policy_refuses_gets_the_default(
    db, test_user, monkeypatch
):
    """AC-extraction.classification-hardening.4: an applied income category on an outgoing row cannot post by itself.

    The one-click approval used to skip every applied row, so this row kept the statement in review for good.
    """
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(db, test_user.id, "hash_hardening_4")
    statement.closing_balance = Decimal("80.00")
    contradicted = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Odd label", amount=Decimal("20.00"), direction="OUT"
    )
    await db.flush()
    salary = await _category_account(db, test_user.id, "Income - Salary", AccountType.INCOME)
    await _draft(
        db,
        test_user.id,
        contradicted,
        category="SALARY",
        account=salary,
        score=92,
        status=ClassificationStatus.APPLIED,
    )
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    assert result.journal_entries_created == 1
    assert await _counter_account_names(db, contradicted, bank.id) == {"General Expense (SGD)"}


async def test_AC_extraction_classification_hardening_2_the_rationale_names_a_user_correction(db, test_user):
    """AC-extraction.classification-hardening.2: a corrected category is not recorded as an accepted AI suggestion."""
    from src.composition import _accepted_suggestion_for
    from src.extraction import ClassificationSuggestion

    statement, _bank = await _statement(db, test_user.id, "hash_hardening_2_rationale")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 3), description="Rationale", amount=Decimal("15.00"), direction="OUT"
    )
    groceries = await _category_account(db, test_user.id, "Expense - Groceries", AccountType.EXPENSE)
    corrected = ClassificationSuggestion(
        atomic_txn_id=txn.id,
        category="GROCERIES",
        confidence=76,
        account_id=groceries.id,
        applied=False,
        corrected=True,
    )

    from_user = await _accepted_suggestion_for(db, test_user.id, txn, corrected)
    from_model = await _accepted_suggestion_for(
        db, test_user.id, txn, corrected.model_copy(update={"corrected": False})
    )

    assert from_user is not None and from_model is not None
    assert from_user[3] == "Category corrected by the user: GROCERIES"
    assert from_model[3] == "Accepted AI suggestion GROCERIES (score 76)"


async def test_AC_extraction_classification_hardening_4_a_reviewed_rule_row_keeps_its_liability_account(
    db, test_user, monkeypatch
):
    """AC-extraction.classification-hardening.4: the one-click approval asks the disposition policy, not a stand-in.

    A reviewed rule can carry an explicit intent. A card repayment to a liability account is a row that the
    policy accepts and the posting posts. The stand-in test (income account for money in, expense account for
    money out) refused it, and the approval then booked a general expense.
    """
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(db, test_user.id, "hash_hardening_4_rule")
    statement.closing_balance = Decimal("0.00")
    repayment = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="CARD PAYMENT", amount=Decimal("100.00"), direction="OUT"
    )
    await db.flush()
    card = Account(user_id=test_user.id, name="Visa Card", type=AccountType.LIABILITY, currency="SGD")
    db.add(card)
    rule = ClassificationRule(
        user_id=test_user.id,
        created_by=test_user.id,
        rule_name="card repayments",
        version_number=1,
        effective_date=date(2020, 1, 1),
        is_active=True,
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["card payment"]},
    )
    db.add(rule)
    await db.flush()
    db.add(
        TransactionClassification(
            atomic_txn_id=repayment.id,
            rule_version_id=rule.id,
            account_id=card.id,
            tags={"category": "Card payment", "intent": "card_repayment"},
            confidence_score=100,
            status=ClassificationStatus.APPLIED,
        )
    )
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    assert result.journal_entries_created == 1
    assert await _counter_account_names(db, repayment, bank.id) == {"Visa Card"}
    general = set((await db.execute(select(Account.name).where(Account.name.like("General %")))).scalars())
    assert general == set()


async def test_AC_extraction_classification_hardening_8_the_approval_settles_the_drafts_it_decided(
    db, test_user, monkeypatch
):
    """AC-extraction.classification-hardening.8: a posted row leaves the pending list. A later click cannot edit a posted row."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, _bank = await _statement(db, test_user.id, "hash_hardening_2_settle")
    statement.closing_balance = Decimal("65.00")
    accepted = await add_txn(
        db, statement, txn_date=date(2025, 1, 3), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    refused = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Odd label", amount=Decimal("20.00"), direction="OUT"
    )
    await db.flush()
    dining = await _category_account(db, test_user.id, "Expense - Dining", AccountType.EXPENSE)
    salary = await _category_account(db, test_user.id, "Income - Salary", AccountType.INCOME)
    await _draft(db, test_user.id, accepted, category="DINING", account=dining, score=76)
    await _draft(db, test_user.id, refused, category="SALARY", account=salary, score=79)
    await db.commit()

    await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    rows = {
        row.atomic_txn_id: row
        for row in (await db.execute(select(TransactionClassification))).scalars().all()
        if row.atomic_txn_id in (accepted.id, refused.id)
    }
    assert rows[accepted.id].status is ClassificationStatus.APPLIED
    assert rows[accepted.id].tags["accepted_by_user"] is True
    assert rows[refused.id].status is ClassificationStatus.SUPERSEDED
