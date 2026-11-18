from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.audit.orm.trace_record import TraceRecordRow
from src.config import settings
from src.extraction import BankStatementStatus, ClassificationStatus
from src.extraction.orm.layer3 import TransactionClassification
from src.ledger import (
    PROCESSING_ACCOUNT_CODE,
    Account,
    AccountType,
    Direction,
    JournalEntry,
    get_or_create_processing_account,
)
from src.reconciliation.orm.reconciliation import DispositionKind, ReconciliationMatch, ReconciliationStatus
from tests.api._statement_router_fixtures import (
    add_txn,
    counter_account_names,
    create_category_account,
    create_statement_with_bank,
    leg_and_entry_for,
    seed_classification,
)

pytestmark = pytest.mark.asyncio
CLICK = {"auto_fill_default_categories": True}


async def test_AC_extraction_accept_ai_suggestions_1_auto_fill_posts_the_draft_category_and_account(
    client: AsyncClient, db, test_user, monkeypatch
):
    "AC-extraction.accept-ai-suggestions.1"
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await create_statement_with_bank(db, test_user.id, "hash_accept_ai_1", bank_name="DBS Accept AI")
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
    income_account = await create_category_account(db, test_user.id, "Income - Interest", AccountType.INCOME)
    expense_account = await create_category_account(db, test_user.id, "Expense - Dining", AccountType.EXPENSE)
    await seed_classification(db, test_user.id, interest, category="INTEREST", account=income_account, score=80)
    await seed_classification(db, test_user.id, dining, category="DINING", account=expense_account, score=76)
    await db.commit()

    response = await client.post(f"/statements/{statement.id}/approvals", json=CLICK)
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 3
    assert await counter_account_names(db, interest, bank.id) == {"Income - Interest"}
    assert await counter_account_names(db, dining, bank.id) == {"Expense - Dining"}
    assert await counter_account_names(db, opaque, bank.id) == {"General Expense (SGD)"}


async def test_AC_extraction_accept_ai_suggestions_2_a_gxs_shaped_statement_reaches_approved(
    client: AsyncClient, db, test_user, monkeypatch
):
    "AC-extraction.accept-ai-suggestions.2"
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await create_statement_with_bank(db, test_user.id, "hash_bs_gxs", closing="370.00", confidence=95)
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
    interest_account = await create_category_account(db, test_user.id, "Income - Interest", AccountType.INCOME)
    other_income = await create_category_account(db, test_user.id, "Income - Other", AccountType.INCOME)
    await seed_classification(
        db,
        test_user.id,
        interest,
        category="INTEREST",
        account=interest_account,
        score=92,
        status=ClassificationStatus.APPLIED,
    )
    await seed_classification(db, test_user.id, paynow, category="OTHER_INCOME", account=other_income, score=70)
    await seed_classification(db, test_user.id, wallet_one, category="TRANSFER", account=None, score=90)
    await seed_classification(db, test_user.id, wallet_two, category="TRANSFER", account=None, score=78)
    await db.commit()

    response = await client.post(f"/statements/{statement.id}/approvals", json=CLICK)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == BankStatementStatus.APPROVED.value
    assert result["validation_error"] is None
    assert result["journal_entries_created"] == 4
    processing = await get_or_create_processing_account(db, test_user.id, currency="SGD")
    for txn, score in ((wallet_one, 90), (wallet_two, 78)):
        match, entry = await leg_and_entry_for(db, txn)
        assert match.disposition_kind is DispositionKind.TRANSFER_LEG
        assert match.status is ReconciliationStatus.ACCEPTED
        assert match.match_score == score
        assert match.score_breakdown["ai_category"] == "TRANSFER"
        assert {(line.account_id, line.direction) for line in entry.lines} == {
            (processing.id, Direction.DEBIT),
            (bank.id, Direction.CREDIT),
        }
    names = set((await db.execute(select(Account.name).where(Account.user_id == test_user.id))).scalars())
    assert not {name for name in names if name.startswith(("General", "Expense"))}
    settled = {
        row.atomic_txn_id: row
        for row in (await db.execute(select(TransactionClassification))).scalars().all()
        if row.atomic_txn_id in (wallet_one.id, wallet_two.id)
    }
    assert {row.status for row in settled.values()} == {ClassificationStatus.APPLIED}
    assert all(row.tags["accepted_by_user"] is True for row in settled.values())


async def test_AC_extraction_accept_ai_suggestions_3_a_suggestion_that_contradicts_the_direction_falls_back(
    client: AsyncClient, db, test_user, monkeypatch
):
    "AC-extraction.accept-ai-suggestions.3"
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await create_statement_with_bank(db, test_user.id, "hash_accept_ai_3", bank_name="DBS Accept AI")
    outgoing = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Odd label", amount=Decimal("20.00"), direction="OUT"
    )
    incoming = await add_txn(
        db, statement, txn_date=date(2025, 1, 3), description="Salary", amount=Decimal("20.00"), direction="IN"
    )
    await db.flush()
    income_account = await create_category_account(db, test_user.id, "Income - Salary", AccountType.INCOME)
    await seed_classification(db, test_user.id, outgoing, category="SALARY", account=income_account, score=79)
    await db.commit()

    response = await client.post(f"/statements/{statement.id}/approvals", json=CLICK)
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 2
    assert await counter_account_names(db, outgoing, bank.id) == {"General Expense (SGD)"}
    assert await counter_account_names(db, incoming, bank.id) == {"General Income (SGD)"}


async def test_AC_extraction_accept_ai_suggestions_5_applied_rows_keep_their_ai_category(
    client: AsyncClient, db, test_user, monkeypatch
):
    "AC-extraction.accept-ai-suggestions.5"
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await create_statement_with_bank(db, test_user.id, "hash_accept_ai_5", bank_name="DBS Accept AI")
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
    income_account = await create_category_account(db, test_user.id, "Income - Interest", AccountType.INCOME)
    expense_account = await create_category_account(db, test_user.id, "Expense - Dining", AccountType.EXPENSE)
    await seed_classification(
        db,
        test_user.id,
        applied,
        category="INTEREST",
        account=income_account,
        score=92,
        status=ClassificationStatus.APPLIED,
    )
    await seed_classification(db, test_user.id, draft, category="DINING", account=expense_account, score=76)
    await db.commit()

    response = await client.post(f"/statements/{statement.id}/approvals", json=CLICK)
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 3
    assert await counter_account_names(db, applied, bank.id) == {"Income - Interest"}
    assert await counter_account_names(db, draft, bank.id) == {"Expense - Dining"}
    assert await counter_account_names(db, opaque, bank.id) == {"General Expense (SGD)"}
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


async def test_AC_extraction_accept_ai_suggestions_6_posting_clears_only_the_economic_review_note(
    client: AsyncClient, db, test_user, monkeypatch
):
    "AC-extraction.accept-ai-suggestions.6"
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    notes = {
        "hash_note_review": ("Economic review required: intent_missing", None),
        "hash_note_other": ("Closing balance 1.00 is not in the document text", "kept"),
    }
    for file_hash, (note, outcome) in notes.items():
        statement, _bank = await create_statement_with_bank(db, test_user.id, file_hash, closing="85.00", confidence=95)
        statement.validation_error = note
        txn = await add_txn(
            db, statement, txn_date=date(2025, 1, 3), description="Lunch", amount=Decimal("15.00"), direction="OUT"
        )
        await db.flush()
        dining = await create_category_account(db, test_user.id, f"Expense - Dining {file_hash}", AccountType.EXPENSE)
        await seed_classification(db, test_user.id, txn, category="DINING", account=dining, score=76)
        await db.commit()

        response = await client.post(f"/statements/{statement.id}/approvals", json=CLICK)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == BankStatementStatus.APPROVED.value
        assert result["validation_error"] == (note if outcome == "kept" else None)


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
    client: AsyncClient, db, test_user, monkeypatch, category, direction, account_name, account_type, bank_side, counter_side
):
    "AC-extraction.accept-ai-suggestions.7"
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    closing = "0.00" if direction == "OUT" else "200.00"
    statement, bank = await create_statement_with_bank(
        db, test_user.id, f"hash_bs_{category}_{direction}", closing=closing, confidence=95
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
    await seed_classification(db, test_user.id, txn, category=category, account=None, score=64)
    await db.commit()

    response = await client.post(f"/statements/{statement.id}/approvals", json=CLICK)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == BankStatementStatus.APPROVED.value
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
    assert (await db.execute(select(Account.name).where(Account.code == PROCESSING_ACCOUNT_CODE))).first() is None
    assert (await db.execute(select(ReconciliationMatch))).first() is None
    names = set((await db.execute(select(Account.name).where(Account.user_id == test_user.id))).scalars())
    assert not {name for name in names if name.startswith(("General", "Expense", "Income"))}


async def test_AC_extraction_classification_hardening_4_an_applied_row_that_the_policy_refuses_gets_the_default(
    client: AsyncClient, db, test_user, monkeypatch
):
    "AC-extraction.classification-hardening.4"
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, bank = await create_statement_with_bank(
        db, test_user.id, "hash_hardening_4", closing="80.00", bank_name="DBS Accept AI"
    )
    contradicted = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Odd label", amount=Decimal("20.00"), direction="OUT"
    )
    await db.flush()
    salary = await create_category_account(db, test_user.id, "Income - Salary", AccountType.INCOME)
    await seed_classification(
        db, test_user.id, contradicted, category="SALARY", account=salary, score=92, status=ClassificationStatus.APPLIED
    )
    await db.commit()

    response = await client.post(f"/statements/{statement.id}/approvals", json=CLICK)
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == 1
    assert await counter_account_names(db, contradicted, bank.id) == {"General Expense (SGD)"}


async def test_AC_extraction_classification_hardening_8_the_approval_settles_the_drafts_it_decided(
    client: AsyncClient, db, test_user, monkeypatch
):
    "AC-extraction.classification-hardening.8"
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    statement, _bank = await create_statement_with_bank(
        db, test_user.id, "hash_hardening_2_settle", closing="65.00", bank_name="DBS Accept AI"
    )
    accepted = await add_txn(
        db, statement, txn_date=date(2025, 1, 3), description="Lunch", amount=Decimal("15.00"), direction="OUT"
    )
    refused = await add_txn(
        db, statement, txn_date=date(2025, 1, 4), description="Odd label", amount=Decimal("20.00"), direction="OUT"
    )
    await db.flush()
    dining = await create_category_account(db, test_user.id, "Expense - Dining", AccountType.EXPENSE)
    salary = await create_category_account(db, test_user.id, "Income - Salary", AccountType.INCOME)
    await seed_classification(db, test_user.id, accepted, category="DINING", account=dining, score=76)
    await seed_classification(db, test_user.id, refused, category="SALARY", account=salary, score=79)
    await db.commit()

    assert (await client.post(f"/statements/{statement.id}/approvals", json=CLICK)).status_code == 200
    rows = {
        row.atomic_txn_id: row
        for row in (await db.execute(select(TransactionClassification))).scalars().all()
        if row.atomic_txn_id in (accepted.id, refused.id)
    }
    assert rows[accepted.id].status is ClassificationStatus.APPLIED
    assert rows[accepted.id].tags["accepted_by_user"] is True
    assert rows[refused.id].status is ClassificationStatus.SUPERSEDED
