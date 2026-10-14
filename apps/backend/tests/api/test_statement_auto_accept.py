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
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.composition import compose_statement_posting_dependencies
from src.config import settings
from src.extraction import BankStatementStatus
from src.extraction.extension.disposition_policy import statement_disposition_policy_for_user
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.ledger import PROCESSING_ACCOUNT_CODE, Account, Direction, JournalEntry
from src.llm import AIStreamError
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.routers import statements as statements_router
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account

pytestmark = pytest.mark.asyncio


class _Model:
    """A stand-in for `src.llm.stream_ai_json`: it answers each indexed row from a table by description."""

    def __init__(self, answers: dict[str, tuple[str, int]], *, fail: bool = False):
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
            {
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
    assert await _counter_names(db, loan, bank.id) == {"Loans Payable (SGD)"}
    assert await _counter_names(db, trade, bank.id) == {"Investments (SGD)"}
    leg = (
        await db.execute(select(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == wallet.id))
    ).scalar_one()
    assert leg.status is ReconciliationStatus.AUTO_ACCEPTED  # the system accepted it, not a person
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
