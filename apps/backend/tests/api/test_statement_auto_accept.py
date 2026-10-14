"""AC-extraction.auto-accept: a statement posts without a click when the user accepts the AI suggestions (#2405).

The owner rule: the user uploads, the system produces the base tables and the default three statements.
Each test drives the real posting path with a stub in place of the model provider. The stub answers by the
description of a row, so the tests do not depend on any live model.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.composition import compose_statement_posting_dependencies
from src.config import settings
from src.extraction import BankStatementStatus, ClassificationStatus
from src.extraction.extension.disposition_policy import statement_disposition_policy_for_user
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.orm.layer3 import TransactionClassification
from src.ledger import PROCESSING_ACCOUNT_CODE, Account, Direction, JournalEntry
from src.llm import AIStreamError
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.routers import statements as statements_router
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account

pytestmark = pytest.mark.asyncio


class _Model:
    """A stand-in for `src.llm.stream_ai_json`: it answers each indexed row from a table by description."""

    def __init__(self, answers: dict[str, tuple[str, int] | None], *, fail: bool = False):
        self.answers = answers
        self.fail = fail
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise AIStreamError("provider down")
        content = kwargs["messages"][0]["content"]
        rows = [json.loads(line) for line in content.splitlines() if line.startswith('{"index"')]
        items = [
            {"index": row["index"]}
            if self.answers[row["description"]] is None
            else {
                "index": row["index"],
                "category": self.answers[row["description"]][0],
                "confidence": self.answers[row["description"]][1],
                "reason": "test",
            }
            for row in rows
        ]

        async def stream():
            yield json.dumps(items)

        return stream()


@pytest.fixture(autouse=True)
def _automatic_path(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)
    monkeypatch.setattr(settings, "ai_api_key", "test-key")


def _install(monkeypatch, model: _Model) -> None:
    monkeypatch.setattr("src.llm.stream_ai_json", model)


async def _statement(db, user_id: str, file_hash: str, *, closing: str, confidence: int = 70):
    bank = await create_statement_account(db, user_id, f"Bank {file_hash}")
    statement = build_statement(user_id, file_hash, confidence)
    statement.account_id = bank.id
    statement.closing_balance = Decimal(closing)
    db.add(statement)
    await db.flush()
    return statement, bank


async def _counter_names(db, txn, bank_id) -> set[str]:
    entry = (
        await db.execute(
            select(JournalEntry).where(JournalEntry.source_id == txn.id).options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()
    ids = {line.account_id for line in entry.lines if line.account_id != bank_id}
    return set((await db.execute(select(Account.name).where(Account.id.in_(ids)))).scalars())


async def test_AC_extraction_auto_accept_7_one_approval_posts_every_row_of_the_statement(db, test_user, monkeypatch):
    """AC-extraction.auto-accept.7: confident, uncertain, "Other" and unplaceable rows all post.

    Opening 100.00; +20 +450 -15 -5 gives a closing balance of 550.00.
    """
    statement, bank = await _statement(db, test_user.id, "auto_all", closing="550.00")
    interest = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Interest", amount=Decimal("20.00"), direction="IN"
    )
    friend = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 3),
        description="PayNow from a friend",
        amount=Decimal("450.00"),
        direction="IN",
    )
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    opaque = await add_txn(
        db, statement, txn_date=date(2025, 1, 5), description="Opaque", amount=Decimal("5.00"), direction="OUT"
    )
    await db.commit()
    _install(
        monkeypatch,
        _Model(
            {
                "Interest": ("INTEREST", 92),
                "PayNow from a friend": ("OTHER_INCOME", 70),
                "Lunch": ("DINING", 66),
                "Opaque": ("DINING", 40),
            }
        ),
    )

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=None, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    assert result.validation_error is None
    assert result.journal_entries_created == 4
    assert await _counter_names(db, interest, bank.id) == {"Income - Interest"}
    assert await _counter_names(db, friend, bank.id) == {"Income - Other"}
    assert await _counter_names(db, lunch, bank.id) == {"Expense - Dining"}
    assert await _counter_names(db, opaque, bank.id) == {"General Expense (SGD)"}
    sources = set(
        (await db.execute(select(JournalEntry.source_type).where(JournalEntry.source_id.is_not(None)))).scalars()
    )
    assert sources == {JournalEntrySourceType.AUTO_PARSED}  # the low confidence tier, not "user confirmed"


async def test_AC_extraction_auto_accept_7_an_outage_does_not_turn_the_statement_into_general_entries(
    db, test_user, monkeypatch
):
    """AC-extraction.auto-accept.7: no answer means no decision. The statement waits and posts nothing."""
    statement, _bank = await _statement(db, test_user.id, "auto_outage", closing="85.00")
    await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    model = _Model({}, fail=True)
    _install(monkeypatch, model)

    with pytest.raises(HTTPException) as error:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id, request=None, db=db, user_id=test_user.id
        )

    assert error.value.status_code == 409
    assert model.calls == 1
    assert (await db.execute(select(JournalEntry.id).where(JournalEntry.source_id.is_not(None)))).first() is None
    assert (await db.execute(select(Account.id).where(Account.name.like("General %")))).first() is None


async def test_AC_extraction_auto_accept_1_with_the_setting_off_the_same_statement_waits_for_review(
    db, test_user, monkeypatch
):
    """AC-extraction.auto-accept.1: the rollback path is the user setting."""
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}
    statement, _bank = await _statement(db, test_user.id, "auto_off", closing="85.00")
    await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    _install(monkeypatch, _Model({"Lunch": ("DINING", 66)}))

    with pytest.raises(HTTPException) as error:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id, request=None, db=db, user_id=test_user.id
        )

    assert error.value.status_code == 409
    assert error.value.detail == "Economic review required: intent_missing"


async def test_AC_extraction_auto_accept_8_the_policy_threshold_follows_the_setting(db, test_user):
    """AC-extraction.auto-accept.8: the recorded policy tells the truth about the score that the system accepts."""
    on = await statement_disposition_policy_for_user(db, test_user.id)
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}
    await db.flush()
    off = await statement_disposition_policy_for_user(db, test_user.id)

    assert (on.authoritative_threshold, off.authoritative_threshold) == (Decimal("0"), Decimal("0.85"))


async def test_AC_extraction_auto_accept_9_transfers_loans_and_trades_post_without_a_click(db, test_user, monkeypatch):
    """AC-extraction.auto-accept.9: the three balance-sheet routes work in the posting path itself.

    A wallet payment posts a Processing leg. A loan repayment posts to Loans Payable. A trade posts to Investments.
    Opening 1000.00; -120 -300 -250 gives a closing balance of 330.00.
    """
    statement, bank = await _statement(db, test_user.id, "auto_balance_sheet", closing="330.00")
    # build_statement starts at 100.00, so raise the opening balance first
    statement.opening_balance = Decimal("1000.00")
    wallet = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 5),
        description="Payment to GrabPay Wallet",
        amount=Decimal("120.00"),
        direction="OUT",
    )
    loan = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 6),
        description="Loan repayment",
        amount=Decimal("300.00"),
        direction="OUT",
    )
    trade = await add_txn(
        db, statement, txn_date=date(2025, 1, 7), description="Buy units", amount=Decimal("250.00"), direction="OUT"
    )
    await db.commit()
    _install(
        monkeypatch,
        _Model(
            {
                "Payment to GrabPay Wallet": ("TRANSFER", 90),
                "Loan repayment": ("LOAN_PRINCIPAL", 80),
                "Buy units": ("INVESTMENT_TRADE", 75),
            }
        ),
    )

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=None, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    assert result.journal_entries_created == 3  # one leg, one loan entry, one trade entry
    assert await _counter_names(db, loan, bank.id) == {"Loans Payable (SGD)"}
    assert await _counter_names(db, trade, bank.id) == {"Investments (SGD)"}
    leg = (
        await db.execute(select(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == wallet.id))
    ).scalar_one()
    assert leg.status is ReconciliationStatus.AUTO_ACCEPTED  # the system accepted it, not a person
    draft = (
        await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id == wallet.id))
    ).scalar_one()
    assert draft.status is ClassificationStatus.APPLIED
    assert draft.tags["auto_accepted"] is True  # the draft has the same name as its leg
    assert "accepted_by_user" not in draft.tags
    processing = (await db.execute(select(Account).where(Account.code == PROCESSING_ACCOUNT_CODE))).scalar_one()
    entry = (
        await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id == leg.journal_entry_ids[0])
            .options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()
    assert {(line.account_id, line.direction) for line in entry.lines} == {
        (processing.id, Direction.DEBIT),
        (bank.id, Direction.CREDIT),
    }


async def test_AC_extraction_auto_accept_10_a_high_confidence_statement_posts_when_it_is_parsed(
    db, test_user, monkeypatch
):
    """AC-extraction.auto-accept.10: the parse-time path posts a statement that has uncertain rows. This is zero click.

    Opening 100.00; -15 gives a closing balance of 85.00.
    """
    statement, bank = await _statement(db, test_user.id, "auto_parse_time", closing="85.00", confidence=95)
    statement.status = BankStatementStatus.APPROVED
    statement.balance_validated = True
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    _install(monkeypatch, _Model({"Lunch": ("DINING", 66)}))

    created = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=compose_statement_posting_dependencies()
    )

    assert created == 1
    assert await _counter_names(db, lunch, bank.id) == {"Expense - Dining"}
    await db.refresh(statement)
    assert statement.status == BankStatementStatus.APPROVED


async def test_AC_extraction_auto_accept_9_the_observe_mode_posts_no_leg(db, test_user, monkeypatch):
    """AC-extraction.auto-accept.9: a leg is a command, and only the mode that applies commands may post it."""
    monkeypatch.setattr(settings, "statement_disposition_mode", "observe")
    statement, _bank = await _statement(db, test_user.id, "auto_observe", closing="80.00")
    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 5),
        description="Payment to GrabPay Wallet",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    await db.commit()
    _install(monkeypatch, _Model({"Payment to GrabPay Wallet": ("TRANSFER", 90)}))

    with pytest.raises(HTTPException) as error:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id, request=None, db=db, user_id=test_user.id
        )

    assert error.value.status_code == 409
    assert (await db.execute(select(ReconciliationMatch.id))).first() is None
    assert (await db.execute(select(JournalEntry.id).where(JournalEntry.source_id.is_not(None)))).first() is None
    assert (await db.execute(select(Account.id).where(Account.code == PROCESSING_ACCOUNT_CODE))).first() is None


async def test_AC_extraction_auto_accept_9_a_leg_survives_a_review_stop_and_the_retry_posts_the_rest(
    db, test_user, monkeypatch
):
    """AC-extraction.auto-accept.9: the first approval stops at a row without an answer, and the second finishes.

    The leg of the wallet row is committed by the first approval. The second approval must not post it again.
    Opening 100.00; -20 -15 gives a closing balance of 65.00.
    """
    statement, bank = await _statement(db, test_user.id, "auto_leg_then_retry", closing="65.00")
    wallet = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 5),
        description="Payment to GrabPay Wallet",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 6), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    _install(monkeypatch, _Model({"Payment to GrabPay Wallet": ("TRANSFER", 90), "Lunch": None}))

    with pytest.raises(HTTPException) as first:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id, request=None, db=db, user_id=test_user.id
        )

    assert first.value.status_code == 409
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 1
    assert (
        await db.execute(select(JournalEntry.source_id).where(JournalEntry.source_id.is_not(None)))
    ).scalars().all() == [wallet.id]

    _install(monkeypatch, _Model({"Payment to GrabPay Wallet": ("TRANSFER", 90), "Lunch": ("DINING", 66)}))
    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=None, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    assert result.journal_entries_created == 1  # the lunch entry; the leg exists already
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 1
    sources = (
        (await db.execute(select(JournalEntry.source_id).where(JournalEntry.source_id.is_not(None)))).scalars().all()
    )
    assert sorted(sources) == sorted([wallet.id, lunch.id])
    assert await _counter_names(db, lunch, bank.id) == {"Expense - Dining"}


async def test_AC_extraction_auto_accept_9_a_second_approval_posts_nothing_more(db, test_user, monkeypatch):
    """AC-extraction.auto-accept.9: approving twice gives one entry per row and one leg per wallet row."""
    statement, _bank = await _statement(db, test_user.id, "auto_twice", closing="65.00")
    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 5),
        description="Payment to GrabPay Wallet",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    await add_txn(
        db, statement, txn_date=date(2025, 1, 6), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    _install(monkeypatch, _Model({"Payment to GrabPay Wallet": ("TRANSFER", 90), "Lunch": ("DINING", 66)}))

    first = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=None, db=db, user_id=test_user.id
    )
    entries_after_first = (await db.execute(select(func.count(JournalEntry.id)))).scalar_one()
    second = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=None, db=db, user_id=test_user.id
    )

    assert first.journal_entries_created == 2
    assert second.journal_entries_created == 0
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == entries_after_first
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 1


async def test_AC_extraction_auto_accept_6_a_corrected_suggestion_posts_as_the_decision_of_the_person(
    db, test_user, monkeypatch
):
    """AC-extraction.auto-accept.6: the plain approval posts a row that the user corrected, and names the user.

    The correction is the decision of the person. The entry gets the confidence tier of a person, and the trace
    names a manual decision. Before this, the plain approval answered 409 for the row that the user just decided.

    Opening 100.00; -15 gives a closing balance of 85.00.
    """
    from sqlalchemy import select as _select

    from src.audit.orm.trace_record import TraceRecordRow
    from src.extraction import apply_suggestion_feedback
    from src.extraction.extension import transaction_classification as tc
    from src.extraction.orm.layer3 import TransactionClassification

    statement, bank = await _statement(db, test_user.id, "auto_corrected", closing="85.00")
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}  # the review path writes the draft
    await db.flush()
    from src.extraction.extension.transaction_classification import CategoryProposal, classify_transactions

    async def proposer(transactions, _policy):
        return [CategoryProposal(category="DINING", confidence=70, reason="test") for _ in transactions]

    await classify_transactions(db, test_user.id, [lunch], policy=tc.POLICY_VERSIONS[1], proposer=proposer)
    draft_id = (await db.execute(_select(TransactionClassification.id))).scalar_one()
    await apply_suggestion_feedback(db, test_user.id, draft_id, "edit_accept", {"value": "groceries"})
    test_user.ai_settings = {}  # the product default again
    await db.commit()
    _install(monkeypatch, _Model({"Lunch": ("DINING", 66)}))

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=None, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    assert await _counter_names(db, lunch, bank.id) == {"Expense - Groceries"}
    entry = (await db.execute(select(JournalEntry).where(JournalEntry.source_id == lunch.id))).scalar_one()
    assert entry.source_type is JournalEntrySourceType.USER_CONFIRMED
    candidate = (
        await db.execute(
            select(TraceRecordRow).where(
                TraceRecordRow.target_id == str(lunch.id), TraceRecordRow.assertion_kind == "economic_intent"
            )
        )
    ).scalar_one()
    assert candidate.provenance == "manual"


async def test_AC_extraction_auto_accept_9_a_leg_that_the_user_chose_is_accepted_and_its_draft_names_the_user(
    db, test_user, monkeypatch
):
    """AC-extraction.auto-accept.9: the correction of a person to a transfer posts a leg that a person accepted.

    The leg has the status accepted, and the draft has the tag accepted_by_user and not auto_accepted.
    Opening 100.00; -40 gives a closing balance of 60.00.
    """
    from src.extraction import apply_suggestion_feedback
    from src.extraction.extension import transaction_classification as tc
    from src.extraction.extension.transaction_classification import CategoryProposal, classify_transactions

    statement, bank = await _statement(db, test_user.id, "auto_user_leg", closing="60.00")
    wallet = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 4),
        description="Payment to GrabPay Wallet",
        amount=Decimal("40.00"),
        direction="OUT",
    )
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}  # the review path writes the draft
    await db.flush()

    async def proposer(transactions, _policy):
        return [CategoryProposal(category="DINING", confidence=70, reason="test") for _ in transactions]

    await classify_transactions(db, test_user.id, [wallet], policy=tc.POLICY_VERSIONS[1], proposer=proposer)
    draft_id = (await db.execute(select(TransactionClassification.id))).scalar_one()
    await apply_suggestion_feedback(db, test_user.id, draft_id, "edit_accept", {"value": "transfer"})
    test_user.ai_settings = {}  # the product default again
    await db.commit()
    _install(monkeypatch, _Model({"Payment to GrabPay Wallet": ("DINING", 66)}))

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=None, db=db, user_id=test_user.id
    )

    assert result.status == BankStatementStatus.APPROVED
    leg = (
        await db.execute(select(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == wallet.id))
    ).scalar_one()
    assert leg.status is ReconciliationStatus.ACCEPTED
    draft = (
        await db.execute(select(TransactionClassification).where(TransactionClassification.id == draft_id))
    ).scalar_one()
    assert draft.status is ClassificationStatus.APPLIED
    assert draft.tags["accepted_by_user"] is True
    assert draft.tags["corrected_by_user"] is True
    assert "auto_accepted" not in draft.tags


async def test_AC_extraction_auto_accept_8_the_posted_trace_names_the_accept_any_score_policy(
    db, test_user, monkeypatch
):
    """AC-extraction.auto-accept.8: the recorded policy version tells which score gate ran.

    The default policy keeps `disposition-v1` and the gate 0.85. The policy of a user who lets the system accept
    suggestions has its own version and the gate 0.
    """
    from src.audit.orm.trace_record import TraceRecordRow
    from src.extraction.extension.disposition_policy import AUTO_ACCEPT_POLICY_VERSION, statement_disposition_policy

    assert statement_disposition_policy(auto_accept=False).version == "disposition-v1"
    assert statement_disposition_policy(auto_accept=True).version == AUTO_ACCEPT_POLICY_VERSION
    statement, _bank = await _statement(db, test_user.id, "auto_trace_version", closing="85.00")
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    _install(monkeypatch, _Model({"Lunch": ("DINING", 66)}))

    await statements_router.approve_statement_stage1(
        statement_id=statement.id, request=None, db=db, user_id=test_user.id
    )

    versions = {
        row.assertion_version
        for row in (
            await db.execute(
                select(TraceRecordRow).where(
                    TraceRecordRow.target_id == str(lunch.id), TraceRecordRow.assertion_kind == "economic_intent"
                )
            )
        )
        .scalars()
        .all()
    }
    assert len(versions) == 1
    assert f"|{AUTO_ACCEPT_POLICY_VERSION}|enforce|machine:0|" in next(iter(versions))


async def test_AC_extraction_auto_accept_8_the_one_click_approval_leaves_an_accepted_row_to_the_posting(
    db, test_user, monkeypatch
):
    """AC-extraction.auto-accept.8: the one-click approval asks the policy of the user, so it agrees with the posting.

    A row that the classifier applied at 70 posts to its category. With the default gate 0.85, the one-click
    approval would book that row to the general account instead.

    Opening 100.00; -15 gives a closing balance of 85.00.
    """
    from src.schemas.review import Stage1ApprovalRequest

    statement, bank = await _statement(db, test_user.id, "auto_oneclick_policy", closing="85.00")
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    _install(monkeypatch, _Model({"Lunch": ("DINING", 70)}))

    result = await statements_router.approve_statement_stage1(
        statement_id=statement.id,
        request=Stage1ApprovalRequest(auto_fill_default_categories=True),
        db=db,
        user_id=test_user.id,
    )

    assert result.status == BankStatementStatus.APPROVED
    assert await _counter_names(db, lunch, bank.id) == {"Expense - Dining"}
