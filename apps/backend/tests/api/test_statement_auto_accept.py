from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from src.audit import JournalEntrySourceType
from src.audit.orm.trace_record import TraceRecordRow
from src.composition import compose_statement_posting_dependencies
from src.config import settings
from src.extraction import BankStatementStatus, ClassificationStatus, apply_suggestion_feedback
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.disposition_policy import (
    current_statement_disposition_policy_snapshot,
    statement_disposition_policy_for_user,
)
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.extension.transaction_classification import CategoryProposal
from src.extraction.orm.layer3 import TransactionClassification
from src.ledger import PROCESSING_ACCOUNT_CODE, Account, Direction, JournalEntry
from src.llm import AIStreamError
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus
from tests.api._statement_router_fixtures import (
    add_txn,
    counter_account_names,
    create_statement_with_bank,
    leg_and_entry_for,
)
from tests.statement_ingestion import classify_statement_rows, classify_transactions

pytestmark = pytest.mark.asyncio


class _Model:
    def __init__(self, answers: dict[str, tuple[str, int] | None], *, fail: bool = False):
        self.answers, self.fail, self.calls = answers, fail, 0

    def __call__(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise AIStreamError("provider down")
        rows = [
            json.loads(line) for line in kwargs["messages"][0]["content"].splitlines() if line.startswith('{"index"')
        ]
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


async def _install_and_classify(db, monkeypatch, statement, answers, *, fail: bool = False):
    model = _Model(answers, fail=fail)
    monkeypatch.setattr("src.llm.stream_ai_json", model)
    await classify_statement_rows(db, statement)
    await db.commit()
    return model


async def test_one_approval_posts_every_row_of_the_statement(client: AsyncClient, db, test_user, monkeypatch):
    statement, bank = await create_statement_with_bank(db, test_user.id, "auto_all", closing="550.00", confidence=70)
    txns = [
        await add_txn(db, statement, txn_date=date(2025, 1, d), description=desc, amount=Decimal(amt), direction=dir_)
        for d, desc, amt, dir_ in (
            (2, "Interest", "20.00", "IN"),
            (3, "PayNow from a friend", "450.00", "IN"),
            (4, "Lunch", "15.00", "OUT"),
            (5, "Opaque", "5.00", "OUT"),
        )
    ]
    await _install_and_classify(
        db,
        monkeypatch,
        statement,
        {
            "Interest": ("INTEREST", 92),
            "PayNow from a friend": ("OTHER_INCOME", 70),
            "Lunch": ("DINING", 66),
            "Opaque": ("DINING", 40),
        },
    )

    response = await client.post(f"/statements/{statement.id}/approvals")
    assert response.status_code == 200 and (
        response.json()["status"],
        response.json()["validation_error"],
        response.json()["journal_entries_created"],
    ) == (BankStatementStatus.APPROVED.value, None, 4)
    for txn, expected in zip(
        txns, ({"Income - Interest"}, {"Income - Other"}, {"Expense - Dining"}, {"General Expense (SGD)"})
    ):
        assert await counter_account_names(db, txn, bank.id) == expected
    assert set(
        (await db.execute(select(JournalEntry.source_type).where(JournalEntry.source_id.is_not(None)))).scalars()
    ) == {JournalEntrySourceType.AUTO_PARSED}


@pytest.mark.parametrize("case", ["outage", "setting_off", "observe"])
async def test_outage_setting_off_and_observe_mode_do_not_post(
    client: AsyncClient, db, test_user, monkeypatch, case: str
):
    if case == "setting_off":
        test_user.ai_settings = {"auto_accept_ai_suggestions": False}
    elif case == "observe":
        monkeypatch.setattr(settings, "statement_disposition_mode", "observe")
    statement, _ = await create_statement_with_bank(
        db, test_user.id, f"auto_{case}", closing="80.00" if case == "observe" else "85.00", confidence=70
    )
    desc, amt = ("Payment to GrabPay Wallet", Decimal("20.00")) if case == "observe" else ("Lunch", Decimal("15.00"))
    await add_txn(db, statement, txn_date=date(2025, 1, 4), description=desc, amount=amt, direction="OUT")
    await db.commit()
    model = (
        _Model({}, fail=True)
        if case == "outage"
        else _Model({"Payment to GrabPay Wallet": ("TRANSFER", 90)} if case == "observe" else {"Lunch": ("DINING", 66)})
    )
    monkeypatch.setattr("src.llm.stream_ai_json", model)
    if case == "outage":
        await classify_statement_rows(db, statement)
        await db.commit()

    assert (err := await client.post(f"/statements/{statement.id}/approvals")).status_code == 409 and (
        await db.execute(select(JournalEntry.id).where(JournalEntry.source_id.is_not(None)))
    ).first() is None
    if case == "outage":
        assert (
            model.calls == 1
            and (await db.execute(select(Account.id).where(Account.name.like("General %")))).first() is None
        )
    elif case == "setting_off":
        assert err.json()["detail"] == "Economic review required: intent_missing"
    else:
        assert (await db.execute(select(ReconciliationMatch.id))).first() is None and (
            await db.execute(select(Account.id).where(Account.code == PROCESSING_ACCOUNT_CODE))
        ).first() is None


async def test_policy_threshold_follows_the_setting(db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    on = await statement_disposition_policy_for_user(db, test_user.id)
    test_user.ai_settings = {"auto_accept_ai_suggestions": False, "enable_ai_classification": False}
    await db.flush()
    off = await statement_disposition_policy_for_user(db, test_user.id)
    assert (on.authoritative_threshold, off.authoritative_threshold) == (Decimal("0"), Decimal("0.85"))
    assert (
        current_statement_disposition_policy_snapshot(policy=on).live_llm_proposals_enabled,
        current_statement_disposition_policy_snapshot(policy=off).live_llm_proposals_enabled,
    ) == (True, False)


async def test_transfers_loans_and_trades_post_without_a_click(client: AsyncClient, db, test_user, monkeypatch):
    statement, bank = await create_statement_with_bank(
        db, test_user.id, "auto_balance_sheet", closing="330.00", confidence=70
    )
    statement.opening_balance = Decimal("1000.00")
    wallet, loan, trade = [
        await add_txn(db, statement, txn_date=date(2025, 1, d), description=desc, amount=Decimal(amt), direction="OUT")
        for d, desc, amt in (
            (5, "Payment to GrabPay Wallet", "120.00"),
            (6, "Loan repayment", "300.00"),
            (7, "Buy units", "250.00"),
        )
    ]
    await _install_and_classify(
        db,
        monkeypatch,
        statement,
        {
            "Payment to GrabPay Wallet": ("TRANSFER", 90),
            "Loan repayment": ("LOAN_PRINCIPAL", 80),
            "Buy units": ("INVESTMENT_TRADE", 75),
        },
    )

    assert (resp := await client.post(f"/statements/{statement.id}/approvals")).status_code == 200 and (
        resp.json()["status"],
        resp.json()["journal_entries_created"],
    ) == (BankStatementStatus.APPROVED.value, 3)
    assert await counter_account_names(db, loan, bank.id) == {"Loans Payable (SGD)"} and await counter_account_names(
        db, trade, bank.id
    ) == {"Investments (SGD)"}
    leg, entry = await leg_and_entry_for(db, wallet)
    draft = (
        await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id == wallet.id))
    ).scalar_one()
    processing = (await db.execute(select(Account).where(Account.code == PROCESSING_ACCOUNT_CODE))).scalar_one()
    assert (
        leg.status is ReconciliationStatus.AUTO_ACCEPTED
        and draft.status is ClassificationStatus.APPLIED
        and draft.tags["auto_accepted"] is True
        and "accepted_by_user" not in draft.tags
    )
    assert {(line.account_id, line.direction) for line in entry.lines} == {
        (processing.id, Direction.DEBIT),
        (bank.id, Direction.CREDIT),
    }


async def test_weak_loan_posts_to_suspense_and_never_to_income_or_expense(
    client: AsyncClient, db, test_user, monkeypatch
):
    statement, bank = await create_statement_with_bank(
        db, test_user.id, "auto_weak_loan", closing="70.00", confidence=70
    )
    loan = await add_txn(
        db, statement, txn_date=date(2025, 1, 6), description="Loan repayment", amount=Decimal("30.00"), direction="OUT"
    )
    await _install_and_classify(db, monkeypatch, statement, {"Loan repayment": ("LOAN_PRINCIPAL", 55)})

    assert (resp := await client.post(f"/statements/{statement.id}/approvals")).status_code == 200 and (
        resp.json()["status"],
        resp.json()["journal_entries_created"],
    ) == (BankStatementStatus.APPROVED.value, 1)
    leg, entry = await leg_and_entry_for(db, loan)
    processing = (await db.execute(select(Account).where(Account.code == PROCESSING_ACCOUNT_CODE))).scalar_one()
    assert (leg.status, leg.match_score, leg.score_breakdown["ai_category"]) == (
        ReconciliationStatus.AUTO_ACCEPTED,
        55,
        "LOAN_PRINCIPAL",
    )
    assert {(line.account_id, line.direction) for line in entry.lines} == {
        (processing.id, Direction.DEBIT),
        (bank.id, Direction.CREDIT),
    }
    assert (await db.execute(select(Account.id).where(Account.name.like("General %")))).first() is None and (
        await db.execute(select(Account.id).where(Account.name.like("Loans Payable%")))
    ).first() is None


async def test_high_confidence_statement_posts_when_parsed(db, test_user, monkeypatch):
    statement, bank = await create_statement_with_bank(
        db, test_user.id, "auto_parse_time", closing="85.00", confidence=95
    )
    statement.status, statement.balance_validated = BankStatementStatus.APPROVED, True
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    monkeypatch.setattr("src.llm.stream_ai_json", _Model({"Lunch": ("DINING", 66)}))
    await classify_statement_rows(db, statement)

    assert (
        await try_auto_approve_high_confidence_statement(
            db, statement.id, test_user.id, dependencies=compose_statement_posting_dependencies()
        )
        == 1
    )
    await db.refresh(statement)
    assert (
        await counter_account_names(db, lunch, bank.id) == {"Expense - Dining"}
        and statement.status == BankStatementStatus.APPROVED
    )


async def test_leg_survives_review_stop_and_only_fill_posts_the_rest(client: AsyncClient, db, test_user, monkeypatch):
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
    await _install_and_classify(
        db, monkeypatch, statement, {"Payment to GrabPay Wallet": ("TRANSFER", 90), "Lunch": None}
    )

    posted_sources = lambda: db.execute(select(JournalEntry.source_id).where(JournalEntry.source_id.is_not(None)))
    assert (await client.post(f"/statements/{statement.id}/approvals")).status_code == 409
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 1 and (
        await posted_sources()
    ).scalars().all() == [wallet.id]

    answering = _Model({"Payment to GrabPay Wallet": ("TRANSFER", 90), "Lunch": ("DINING", 66)})
    monkeypatch.setattr("src.llm.stream_ai_json", answering)
    retry = await client.post(f"/statements/{statement.id}/approvals")
    assert (
        retry.status_code == 409
        and retry.json()["detail"].startswith("Economic review required:")
        and answering.calls == 0
        and (await posted_sources()).scalars().all() == [wallet.id]
    )

    response = await client.post(f"/statements/{statement.id}/approvals", json={"auto_fill_default_categories": True})
    assert response.status_code == 200 and (response.json()["status"], response.json()["journal_entries_created"]) == (
        BankStatementStatus.APPROVED.value,
        1,
    )
    assert answering.calls == 0 and (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 1
    assert sorted((await posted_sources()).scalars().all()) == sorted(
        [wallet.id, lunch.id]
    ) and await counter_account_names(db, lunch, bank.id) == {"General Expense (SGD)"}


async def test_corrected_suggestion_posts_as_manual_decision(client: AsyncClient, db, test_user, monkeypatch):
    statement, bank = await create_statement_with_bank(
        db, test_user.id, "auto_corrected", closing="85.00", confidence=70
    )
    lunch = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}
    await db.flush()
    await classify_transactions(
        db,
        test_user.id,
        [lunch],
        policy=tc.POLICY_VERSIONS[-1],
        proposer=lambda txns, _p: _async_proposals(
            txns, CategoryProposal(category="DINING", confidence=70, reason="test")
        ),
    )
    await apply_suggestion_feedback(
        db,
        test_user.id,
        (await db.execute(select(TransactionClassification.id))).scalar_one(),
        "edit_accept",
        {"value": "groceries"},
    )
    test_user.ai_settings = {}
    await _install_and_classify(db, monkeypatch, statement, {"Lunch": ("DINING", 66)})

    assert (await client.post(f"/statements/{statement.id}/approvals")).status_code == 200
    entry = (await db.execute(select(JournalEntry).where(JournalEntry.source_id == lunch.id))).scalar_one()
    candidate = (
        await db.execute(
            select(TraceRecordRow).where(
                TraceRecordRow.target_id == str(lunch.id), TraceRecordRow.assertion_kind == "economic_intent"
            )
        )
    ).scalar_one()
    assert (
        await counter_account_names(db, lunch, bank.id) == {"Expense - Groceries"}
        and entry.source_type is JournalEntrySourceType.USER_CONFIRMED
        and candidate.provenance == "manual"
    )


async def _async_proposals(txns, proposal):
    return [proposal for _ in txns]
