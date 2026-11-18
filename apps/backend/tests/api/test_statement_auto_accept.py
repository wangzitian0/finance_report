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
from src.platform import DomainError
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.routers import statements as statements_router
from src.schemas.extraction import Stage1ApprovalRequest
from tests.api._statement_router_fixtures import (
    add_txn,
    counter_account_names,
    create_statement_with_bank,
)
from tests.statement_ingestion import classify_statement_rows, classify_transactions
from src.request_context import RequestContext

pytestmark = pytest.mark.asyncio


class _Model:
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


async def test_AC_extraction_auto_accept_7_one_approval_posts_every_row_of_the_statement(db, test_user, monkeypatch):
    "AC-extraction.auto-accept.7"
    statement, bank = await create_statement_with_bank(db, test_user.id, "auto_all", closing="550.00", confidence=70)
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
    await classify_statement_rows(db, statement)

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, request=None, ctx=RequestContext(db, test_user.id))
    assert result.status == BankStatementStatus.APPROVED
    assert result.validation_error is None
    assert result.journal_entries_created == 4
    assert await counter_account_names(db, interest, bank.id) == {"Income - Interest"}
    assert await counter_account_names(db, friend, bank.id) == {"Income - Other"}
    assert await counter_account_names(db, lunch, bank.id) == {"Expense - Dining"}
    assert await counter_account_names(db, opaque, bank.id) == {"General Expense (SGD)"}
    sources = set(
        (await db.execute(select(JournalEntry.source_type).where(JournalEntry.source_id.is_not(None)))).scalars()
    )
    assert sources == {JournalEntrySourceType.AUTO_PARSED}


async def test_AC_extraction_auto_accept_7_an_outage_does_not_turn_the_statement_into_general_entries(
    db, test_user, monkeypatch
):
    "AC-extraction.auto-accept.7"
    statement, _bank = await create_statement_with_bank(db, test_user.id, "auto_outage", closing="85.00", confidence=70)
    await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    model = _Model({}, fail=True)
    _install(monkeypatch, model)
    await classify_statement_rows(db, statement)

    with pytest.raises((HTTPException, DomainError)) as error:
        await statements_router.approve_statement_stage1(statement_id=statement.id, request=None, ctx=RequestContext(db, test_user.id))
    assert error.value.status_code == 409
    assert model.calls == 1
    assert (await db.execute(select(JournalEntry.id).where(JournalEntry.source_id.is_not(None)))).first() is None
    assert (await db.execute(select(Account.id).where(Account.name.like("General %")))).first() is None


async def test_AC_extraction_auto_accept_1_with_the_setting_off_the_same_statement_waits_for_review(
    db, test_user, monkeypatch
):
    "AC-extraction.auto-accept.1"
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}
    statement, _bank = await create_statement_with_bank(db, test_user.id, "auto_off", closing="85.00", confidence=70)
    await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    _install(monkeypatch, _Model({"Lunch": ("DINING", 66)}))

    with pytest.raises((HTTPException, DomainError)) as error:
        await statements_router.approve_statement_stage1(statement_id=statement.id, request=None, ctx=RequestContext(db, test_user.id))
    assert error.value.status_code == 409
    assert error.value.detail == "Economic review required: intent_missing"


async def test_AC_extraction_auto_accept_8_the_policy_threshold_follows_the_setting(db, test_user, monkeypatch):
    "AC-extraction.auto-accept.8"
    from src.extraction.extension.disposition_policy import current_statement_disposition_policy_snapshot

    monkeypatch.setattr(settings, "enable_ai_classification", True)
    on = await statement_disposition_policy_for_user(db, test_user.id)
    on_snapshot = current_statement_disposition_policy_snapshot(policy=on)
    test_user.ai_settings = {"auto_accept_ai_suggestions": False, "enable_ai_classification": False}
    await db.flush()
    off = await statement_disposition_policy_for_user(db, test_user.id)
    off_snapshot = current_statement_disposition_policy_snapshot(policy=off)
    assert (on.authoritative_threshold, off.authoritative_threshold) == (Decimal("0"), Decimal("0.85"))
    assert (on_snapshot.live_llm_proposals_enabled, off_snapshot.live_llm_proposals_enabled) == (True, False)


async def test_AC_extraction_auto_accept_9_transfers_loans_and_trades_post_without_a_click(db, test_user, monkeypatch):
    "AC-extraction.auto-accept.9"
    statement, bank = await create_statement_with_bank(
        db, test_user.id, "auto_balance_sheet", closing="330.00", confidence=70
    )
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
    await classify_statement_rows(db, statement)

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, request=None, ctx=RequestContext(db, test_user.id))
    assert result.status == BankStatementStatus.APPROVED
    assert result.journal_entries_created == 3
    assert await counter_account_names(db, loan, bank.id) == {"Loans Payable (SGD)"}
    assert await counter_account_names(db, trade, bank.id) == {"Investments (SGD)"}
    leg = (
        await db.execute(select(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == wallet.id))
    ).scalar_one()
    assert leg.status is ReconciliationStatus.AUTO_ACCEPTED
    draft = (
        await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id == wallet.id))
    ).scalar_one()
    assert draft.status is ClassificationStatus.APPLIED
    assert draft.tags["auto_accepted"] is True
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


async def test_AC_extraction_auto_accept_5_a_weak_loan_posts_to_suspense_and_never_to_income_or_expense(
    db, test_user, monkeypatch
):
    "AC-extraction.auto-accept.5"
    statement, bank = await create_statement_with_bank(
        db, test_user.id, "auto_weak_loan", closing="70.00", confidence=70
    )
    loan = await add_txn(
        db, statement, txn_date=date(2025, 1, 6), description="Loan repayment", amount=Decimal("30.00"), direction="OUT"
    )
    await db.commit()
    _install(monkeypatch, _Model({"Loan repayment": ("LOAN_PRINCIPAL", 55)}))
    await classify_statement_rows(db, statement)

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, request=None, ctx=RequestContext(db, test_user.id))
    assert result.status == BankStatementStatus.APPROVED
    assert result.journal_entries_created == 1
    leg = (
        await db.execute(select(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == loan.id))
    ).scalar_one()
    assert leg.status is ReconciliationStatus.AUTO_ACCEPTED
    assert leg.match_score == 55
    assert leg.score_breakdown["ai_category"] == "LOAN_PRINCIPAL"
    processing = (await db.execute(select(Account).where(Account.code == PROCESSING_ACCOUNT_CODE))).scalar_one()
    entry = (
        await db.execute(
            select(JournalEntry).where(JournalEntry.source_id == loan.id).options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()
    assert {(line.account_id, line.direction) for line in entry.lines} == {
        (processing.id, Direction.DEBIT),
        (bank.id, Direction.CREDIT),
    }
    assert (await db.execute(select(Account.id).where(Account.name.like("General %")))).first() is None
    assert (await db.execute(select(Account.id).where(Account.name.like("Loans Payable%")))).first() is None


async def test_AC_extraction_auto_accept_10_a_high_confidence_statement_posts_when_it_is_parsed(
    db, test_user, monkeypatch
):
    "AC-extraction.auto-accept.10"
    statement, bank = await create_statement_with_bank(
        db, test_user.id, "auto_parse_time", closing="85.00", confidence=95
    )
    statement.status = BankStatementStatus.APPROVED
    statement.balance_validated = True
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    await db.commit()
    _install(monkeypatch, _Model({"Lunch": ("DINING", 66)}))
    await classify_statement_rows(db, statement)

    created = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=compose_statement_posting_dependencies()
    )
    assert created == 1
    assert await counter_account_names(db, lunch, bank.id) == {"Expense - Dining"}
    await db.refresh(statement)
    assert statement.status == BankStatementStatus.APPROVED


async def test_AC_extraction_auto_accept_9_the_observe_mode_posts_no_leg(db, test_user, monkeypatch):
    "AC-extraction.auto-accept.9"
    monkeypatch.setattr(settings, "statement_disposition_mode", "observe")
    statement, _bank = await create_statement_with_bank(
        db, test_user.id, "auto_observe", closing="80.00", confidence=70
    )
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

    with pytest.raises((HTTPException, DomainError)) as error:
        await statements_router.approve_statement_stage1(statement_id=statement.id, request=None, ctx=RequestContext(db, test_user.id))
    assert error.value.status_code == 409
    assert (await db.execute(select(ReconciliationMatch.id))).first() is None
    assert (await db.execute(select(JournalEntry.id).where(JournalEntry.source_id.is_not(None)))).first() is None
    assert (await db.execute(select(Account.id).where(Account.code == PROCESSING_ACCOUNT_CODE))).first() is None


async def test_AC_extraction_auto_accept_9_a_leg_survives_a_review_stop_and_only_the_fill_posts_the_rest(
    db, test_user, monkeypatch
):
    "AC-extraction.auto-accept.9"
    statement, bank = await create_statement_with_bank(
        db, test_user.id, "auto_leg_then_retry", closing="65.00", confidence=70
    )
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
    await classify_statement_rows(db, statement)

    def posted_sources():
        return db.execute(select(JournalEntry.source_id).where(JournalEntry.source_id.is_not(None)))

    with pytest.raises((HTTPException, DomainError)) as first:
        await statements_router.approve_statement_stage1(statement_id=statement.id, request=None, ctx=RequestContext(db, test_user.id))
    assert first.value.status_code == 409
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 1
    assert (await posted_sources()).scalars().all() == [wallet.id]

    answering = _Model({"Payment to GrabPay Wallet": ("TRANSFER", 90), "Lunch": ("DINING", 66)})
    _install(monkeypatch, answering)
    with pytest.raises((HTTPException, DomainError)) as retry:
        await statements_router.approve_statement_stage1(statement_id=statement.id, request=None, ctx=RequestContext(db, test_user.id))
    assert retry.value.status_code == 409
    assert retry.value.detail.startswith("Economic review required:")
    assert answering.calls == 0, "a plain retry of the approve asks no model"
    assert (await posted_sources()).scalars().all() == [wallet.id], "a plain retry posts no row without an answer"

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, request=Stage1ApprovalRequest(auto_fill_default_categories=True), ctx=RequestContext(db, test_user.id))
    assert result.status == BankStatementStatus.APPROVED
    assert result.journal_entries_created == 1
    assert answering.calls == 0, "the one-click fill asks no model"
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 1
    assert sorted((await posted_sources()).scalars().all()) == sorted([wallet.id, lunch.id])
    assert await counter_account_names(db, lunch, bank.id) == {"General Expense (SGD)"}


async def test_AC_extraction_auto_accept_6_a_corrected_suggestion_posts_as_the_decision_of_the_person(
    db, test_user, monkeypatch
):
    "AC-extraction.auto-accept.6"
    from src.audit.orm.trace_record import TraceRecordRow
    from src.extraction import apply_suggestion_feedback
    from src.extraction.extension import transaction_classification as tc
    from src.extraction.extension.transaction_classification import CategoryProposal

    statement, bank = await create_statement_with_bank(
        db, test_user.id, "auto_corrected", closing="85.00", confidence=70
    )
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}
    await db.flush()

    async def proposer(transactions, _policy):
        return [CategoryProposal(category="DINING", confidence=70, reason="test") for _ in transactions]

    await classify_transactions(db, test_user.id, [lunch], policy=tc.POLICY_VERSIONS[-1], proposer=proposer)
    draft_id = (await db.execute(select(TransactionClassification.id))).scalar_one()
    await apply_suggestion_feedback(db, test_user.id, draft_id, "edit_accept", {"value": "groceries"})
    test_user.ai_settings = {}
    await db.commit()
    _install(monkeypatch, _Model({"Lunch": ("DINING", 66)}))
    await classify_statement_rows(db, statement)

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, request=None, ctx=RequestContext(db, test_user.id))
    assert result.status == BankStatementStatus.APPROVED
    assert await counter_account_names(db, lunch, bank.id) == {"Expense - Groceries"}
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
