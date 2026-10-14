"""AC-extraction.accept-ai-suggestions: the one-click approval finishes a statement that holds balance-sheet rows (#2415).

On staging v0.1.83, the GXS fixture (two wallet payments) and the MariBank fixture (one card repayment)
ended with status 409 `intent_missing`. The one-click approval left every row that the AI named a
transfer, a card repayment, a loan payment or a trade, and posting is all or nothing per statement.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.config import settings
from src.extraction import BankStatementStatus, ClassificationStatus, RuleType, apply_suggestion_feedback
from src.extraction.extension.transaction_classification import POLICY_RULE_NAME
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import (
    PROCESSING_ACCOUNT_CODE,
    Account,
    AccountType,
    Direction,
    JournalEntry,
    get_or_create_processing_account,
)
from src.reconciliation.orm.reconciliation import DispositionKind, ReconciliationMatch, ReconciliationStatus
from src.routers import statements as statements_router
from src.schemas.review import Stage1ApprovalRequest
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account

pytestmark = pytest.mark.asyncio

CLICK = Stage1ApprovalRequest(auto_fill_default_categories=True)


async def _category_account(db, user_id, name: str, account_type: AccountType) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency="SGD")
    db.add(account)
    await db.flush()
    return account


async def _classification(
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


async def _statement(db, user_id, file_hash: str, *, closing: str):
    bank = await create_statement_account(db, user_id, f"Bank {file_hash}")
    statement = build_statement(user_id, file_hash, 95)
    statement.account_id = bank.id
    statement.closing_balance = Decimal(closing)
    db.add(statement)
    await db.flush()
    return statement, bank


async def _leg_for(db, txn) -> tuple[ReconciliationMatch, JournalEntry]:
    match = (
        await db.execute(select(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == txn.id))
    ).scalar_one()
    entry = (
        await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id == match.journal_entry_ids[0])
            .options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()
    return match, entry


async def test_AC_extraction_accept_ai_suggestions_2_a_gxs_shaped_statement_reaches_approved(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.2: wallet payments post as Processing legs, the other rows as before."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(db, test_user.id, "hash_bs_gxs", closing="370.00")
    statement.validation_error = "Economic review required: intent_missing"
    interest = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Interest Earned", amount=Decimal("20.00"), direction="IN"
    )
    paynow = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 3),
        description="PayNow from ALVIN GOH",
        amount=Decimal("450.00"),
        direction="IN",
    )
    wallet_one = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 5),
        description="Payment to GrabPay Wallet",
        amount=Decimal("120.00"),
        direction="OUT",
    )
    wallet_two = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 26),
        description="Payment to GrabPay Wallet",
        amount=Decimal("80.00"),
        direction="OUT",
    )
    await db.flush()
    interest_account = await _category_account(db, test_user.id, "Income - Interest", AccountType.INCOME)
    other_income = await _category_account(db, test_user.id, "Income - Other", AccountType.INCOME)
    await _classification(
        db,
        test_user.id,
        interest,
        category="INTEREST",
        account=interest_account,
        score=92,
        status=ClassificationStatus.APPLIED,
    )
    await _classification(db, test_user.id, paynow, category="OTHER_INCOME", account=other_income, score=70)
    await _classification(db, test_user.id, wallet_one, category="TRANSFER", account=None, score=90)
    await _classification(db, test_user.id, wallet_two, category="TRANSFER", account=None, score=78)
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    assert result.validation_error is None
    assert result.journal_entries_created == 4
    processing = await get_or_create_processing_account(db, test_user.id, currency="SGD")
    for txn, score in ((wallet_one, 90), (wallet_two, 78)):
        match, entry = await _leg_for(db, txn)
        assert match.disposition_kind is DispositionKind.TRANSFER_LEG
        assert match.status is ReconciliationStatus.ACCEPTED
        assert match.match_score == score
        assert match.score_breakdown["ai_category"] == "TRANSFER"
        assert {(line.account_id, line.direction) for line in entry.lines} == {
            (processing.id, Direction.DEBIT),
            (bank.id, Direction.CREDIT),
        }
    # A balance-sheet row is never income or expense: no general account, and no expense account at all.
    names = set((await db.execute(select(Account.name).where(Account.user_id == test_user.id))).scalars())
    assert not {name for name in names if name.startswith(("General", "Expense"))}
    # The drafts that the approval used are settled: they leave the pending list.
    settled = {
        row.atomic_txn_id: row
        for row in (await db.execute(select(TransactionClassification))).scalars().all()
        if row.atomic_txn_id in (wallet_one.id, wallet_two.id)
    }
    assert {row.status for row in settled.values()} == {ClassificationStatus.APPLIED}
    assert all(row.tags["accepted_by_user"] is True for row in settled.values())


@pytest.mark.parametrize(("category", "direction"), [("TRANSFER", "OUT"), ("CARD_REPAYMENT", "OUT")])
async def test_AC_extraction_accept_ai_suggestions_2_an_own_account_movement_posts_a_processing_leg(
    db, test_user, monkeypatch, category, direction
):
    """AC-extraction.accept-ai-suggestions.2: a transfer and a card repayment share one path: the Processing leg."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, _bank = await _statement(db, test_user.id, f"hash_bs_{category}", closing="0.00")
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 5),
        description="Opaque movement",
        amount=Decimal("100.00"),
        direction=direction,
    )
    await db.flush()
    await _classification(db, test_user.id, txn, category=category, account=None, score=88)
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    match, _entry = await _leg_for(db, txn)
    assert match.score_breakdown["ai_category"] == category


@pytest.mark.parametrize(
    ("category", "direction", "account_name", "account_type", "bank_side", "counter_side"),
    [
        ("LOAN_PRINCIPAL", "OUT", "Loans Payable (SGD)", AccountType.LIABILITY, Direction.CREDIT, Direction.DEBIT),
        ("LOAN_PRINCIPAL", "IN", "Loans Payable (SGD)", AccountType.LIABILITY, Direction.DEBIT, Direction.CREDIT),
        ("INVESTMENT_TRADE", "OUT", "Investments (SGD)", AccountType.ASSET, Direction.CREDIT, Direction.DEBIT),
        ("INVESTMENT_TRADE", "IN", "Investments (SGD)", AccountType.ASSET, Direction.DEBIT, Direction.CREDIT),
    ],
)
async def test_AC_extraction_accept_ai_suggestions_7_a_loan_or_a_trade_posts_to_a_balance_sheet_account(
    db, test_user, monkeypatch, category, direction, account_name, account_type, bank_side, counter_side
):
    """AC-extraction.accept-ai-suggestions.7: the row is neither income nor expense and not a Processing leg.

    A loan repayment lowers the liability and a drawdown raises it. A purchase raises the asset and a sale
    lowers it. The approval decides this itself, so the statement reaches approved without a person.
    """
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(
        db, test_user.id, f"hash_bs_{category}_{direction}", closing="0.00" if direction == "OUT" else "200.00"
    )
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 5),
        description="Opaque movement",
        amount=Decimal("100.00"),
        direction=direction,
    )
    await db.flush()
    await _classification(db, test_user.id, txn, category=category, account=None, score=64)
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    entry = (
        await db.execute(
            select(JournalEntry).where(JournalEntry.source_id == txn.id).options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()
    counter = (await db.execute(select(Account).where(Account.name == account_name))).scalar_one()
    assert counter.type is account_type and counter.currency == "SGD"
    assert {(line.account_id, line.direction, line.amount) for line in entry.lines} == {
        (bank.id, bank_side, Decimal("100.00")),
        (counter.id, counter_side, Decimal("100.00")),
    }
    # Not a Processing leg, and no profit or loss account.
    assert (await db.execute(select(Account.name).where(Account.code == PROCESSING_ACCOUNT_CODE))).first() is None
    assert (await db.execute(select(ReconciliationMatch))).first() is None
    names = set((await db.execute(select(Account.name).where(Account.user_id == test_user.id))).scalars())
    assert not {name for name in names if name.startswith(("General", "Expense", "Income"))}


async def test_AC_extraction_accept_ai_suggestions_2_a_foreign_currency_statement_waits_without_an_error(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.2: base currency SGD, statement in CNY. The row stays; nothing fails.

    A leg in a foreign currency fails at commit, because a later posting resets the base currency of the
    transaction. The approval therefore leaves the row for a person and answers 409.
    """
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    bank = Account(user_id=test_user.id, name="CNY bank", type=AccountType.ASSET, currency="CNY")
    db.add(bank)
    await db.flush()
    statement = build_statement(test_user.id, "hash_bs_cny", 95)
    statement.account_id = bank.id
    statement.currency = "CNY"
    statement.closing_balance = Decimal("80.00")
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 5), description="Opaque", amount=Decimal("20.00"), direction="OUT"
    )
    await db.flush()
    await _classification(db, test_user.id, txn, category="TRANSFER", account=None, score=91)
    await db.commit()

    with pytest.raises(HTTPException) as error:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
        )

    assert error.value.status_code == 409
    assert (await db.execute(select(Account.name).where(Account.code == PROCESSING_ACCOUNT_CODE))).first() is None
    assert (await db.execute(select(ReconciliationMatch))).first() is None


async def test_AC_extraction_accept_ai_suggestions_2_a_class_that_the_user_chose_is_not_recorded_as_an_ai_score(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.2: a correction to TRANSFER carries the user as its source, not the AI score."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, _bank = await _statement(db, test_user.id, "hash_bs_user_class", closing="80.00")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 5), description="Opaque", amount=Decimal("20.00"), direction="OUT"
    )
    await db.flush()
    dining = await _category_account(db, test_user.id, "Expense - Dining", AccountType.EXPENSE)
    await _classification(db, test_user.id, txn, category="DINING", account=dining, score=72)
    await db.commit()
    draft_id = (await db.execute(select(TransactionClassification.id))).scalar_one()
    await apply_suggestion_feedback(db, test_user.id, draft_id, "edit_accept", {"value": "transfer"})
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    match, _entry = await _leg_for(db, txn)
    assert match.match_score == 100
    assert match.score_breakdown["user_category"] == "TRANSFER"
    assert "ai_category" not in match.score_breakdown


async def test_AC_extraction_accept_ai_suggestions_2_only_a_posted_leg_settles_its_draft(db, test_user, monkeypatch):
    """AC-extraction.accept-ai-suggestions.2: a skipped row keeps its draft, so a person can still decide it.

    The ledger refuses the leg of the second row. The function skips that row and keeps the first leg.
    """
    from src.ledger import TransferAccountCurrencyMismatchError
    from src.reconciliation.extension import named_transfers

    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, _bank = await _statement(db, test_user.id, "hash_bs_partial", closing="60.00")
    posted = await add_txn(
        db, statement, txn_date=date(2025, 1, 5), description="Wallet A", amount=Decimal("15.00"), direction="OUT"
    )
    skipped = await add_txn(
        db, statement, txn_date=date(2025, 1, 6), description="Wallet B", amount=Decimal("25.00"), direction="OUT"
    )
    real = named_transfers.post_transfer_leg

    async def refuse_the_second_row(db_, **kwargs):
        if kwargs["txn"].id == skipped.id:
            raise TransferAccountCurrencyMismatchError("refused")
        return await real(db_, **kwargs)

    monkeypatch.setattr(named_transfers, "post_transfer_leg", refuse_the_second_row)
    await _classification(db, test_user.id, posted, category="TRANSFER", account=None, score=90)
    await _classification(db, test_user.id, skipped, category="TRANSFER", account=None, score=90)
    await db.commit()

    with pytest.raises(HTTPException) as error:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
        )

    assert error.value.status_code == 409
    drafts = {
        row.atomic_txn_id: row.status for row in (await db.execute(select(TransactionClassification))).scalars().all()
    }
    assert drafts[posted.id] is ClassificationStatus.APPLIED
    assert drafts[skipped.id] is ClassificationStatus.DRAFT


async def test_AC_extraction_accept_ai_suggestions_2_a_rejected_match_suggestion_does_not_block_the_approval(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.2: a rejected suggestion is history. The row is unmatched and gets its leg.

    Before the fix, the leg function counted the rejected suggestion as the owner of the row. The approval
    answered 409 on every attempt, and no other action in the product could book the row as a transfer.
    """
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await _statement(db, test_user.id, "hash_bs_rejected", closing="20.00")
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 6),
        description="Payment to GrabPay Wallet",
        amount=Decimal("80.00"),
        direction="OUT",
    )
    await _classification(db, test_user.id, txn, category="TRANSFER", account=None, score=90)
    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[],
            match_score=0,
            score_breakdown={},
            status=ReconciliationStatus.REJECTED,
            disposition_kind=DispositionKind.REVIEWED_UNMATCHED,
        )
    )
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    live = (
        (
            await db.execute(
                select(ReconciliationMatch).where(
                    ReconciliationMatch.atomic_txn_id == txn.id,
                    ReconciliationMatch.status != ReconciliationStatus.REJECTED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(live) == 1 and live[0].disposition_kind is DispositionKind.TRANSFER_LEG
    processing = (await db.execute(select(Account).where(Account.code == PROCESSING_ACCOUNT_CODE))).scalar_one()
    entry = (
        await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id == live[0].journal_entry_ids[0])
            .options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()
    assert {(line.account_id, line.direction) for line in entry.lines} == {
        (processing.id, Direction.DEBIT),
        (bank.id, Direction.CREDIT),
    }


async def test_AC_extraction_accept_ai_suggestions_6_a_statement_without_rows_loses_its_review_note(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.6: nothing is left to review, so the note goes."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, _bank = await _statement(db, test_user.id, "hash_note_empty", closing="100.00")
    statement.validation_error = "Economic review required: intent_missing"
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    assert result.validation_error is None


async def test_AC_extraction_accept_ai_suggestions_2_a_leg_that_cannot_post_stays_for_a_person(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.2: Processing holds one currency. A row in another currency waits."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, _bank = await _statement(db, test_user.id, "hash_bs_currency", closing="80.00")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 5), description="Opaque", amount=Decimal("20.00"), direction="OUT"
    )
    await db.flush()
    await get_or_create_processing_account(db, test_user.id, currency="CNY")
    await _classification(db, test_user.id, txn, category="TRANSFER", account=None, score=88)
    await db.commit()

    with pytest.raises(HTTPException) as error:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
        )

    assert error.value.status_code == 409
    assert error.value.detail == "Economic review required: intent_missing"
    assert (await db.execute(select(ReconciliationMatch))).first() is None
    await db.refresh(statement)
    assert statement.status == BankStatementStatus.PARSED
    assert statement.validation_error == "Economic review required: intent_missing"


async def test_AC_extraction_accept_ai_suggestions_6_posting_clears_only_the_economic_review_note(
    db, test_user, monkeypatch
):
    """AC-extraction.accept-ai-suggestions.6: an approved statement shows no stale review note; other notes stay."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    notes = {
        "hash_note_review": ("Economic review required: intent_missing", None),
        "hash_note_other": ("Closing balance 1.00 is not in the document text", "kept"),
    }
    for file_hash, (note, outcome) in notes.items():
        statement, _bank = await _statement(db, test_user.id, file_hash, closing="85.00")
        statement.validation_error = note
        txn = await add_txn(
            db, statement, txn_date=date(2025, 1, 3), description="Lunch", amount=Decimal("15.00"), direction="OUT"
        )
        await db.flush()
        dining = await _category_account(db, test_user.id, f"Expense - Dining {file_hash}", AccountType.EXPENSE)
        await _classification(db, test_user.id, txn, category="DINING", account=dining, score=76)
        await db.commit()

        result = await statements_router.approve_statement_stage1(
            statement_id=statement.id, request=CLICK, db=db, user_id=test_user.id
        )

        assert result.status == BankStatementStatus.APPROVED
        assert result.validation_error == (note if outcome == "kept" else None)
