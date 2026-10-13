"""AC-reconciliation.named-transfer-legs: a row that the AI named a movement between accounts posts a Processing leg (#2415).

The keyword fallback of the reconciliation run posts a transfer leg only when the description holds a
transfer keyword. The AI classification names a wallet payment, a card repayment, a loan payment or a
trade without such a keyword. `post_named_transfer_legs` posts the same leg for those rows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    get_or_create_processing_account,
)
from src.reconciliation import NamedTransfer, post_named_transfer_legs
from src.reconciliation.orm.reconciliation import (
    DispositionKind,
    ReconciliationMatch,
    ReconciliationStatus,
    ReconciliationTransferPair,
)
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account

pytestmark = pytest.mark.asyncio


async def _statement(db, user_id, file_hash: str, *, account_name: str = "Bank A", linked: bool = True):
    bank = await create_statement_account(db, user_id, account_name)
    statement = build_statement(user_id, file_hash, 90)
    statement.account_id = bank.id if linked else None
    db.add(statement)
    await db.flush()
    return statement, bank


async def _entry(db, entry_id: str) -> JournalEntry:
    return (
        await db.execute(
            select(JournalEntry).where(JournalEntry.id == UUID(entry_id)).options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()


async def test_AC_reconciliation_named_transfer_legs_1_an_outgoing_row_posts_dr_processing_cr_bank(db, test_user):
    """AC-reconciliation.named-transfer-legs.1: the leg is the same entry that the keyword fallback posts."""
    _statement_row, bank = await _statement(db, test_user.id, "named_leg_out")
    txn = await add_txn(
        db,
        _statement_row,
        txn_date=date(2025, 1, 11),
        description="Credit Card Repayment",
        amount=Decimal("1200.00"),
        direction="OUT",
    )

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="CARD_REPAYMENT", score=92)]
    )

    assert len(matches) == 1
    match = matches[0]
    assert match.atomic_txn_id == txn.id
    assert match.disposition_kind is DispositionKind.TRANSFER_LEG
    assert match.status is ReconciliationStatus.ACCEPTED
    assert match.match_score == 92
    assert match.score_breakdown["ai_category"] == "CARD_REPAYMENT"
    processing = await get_or_create_processing_account(db, test_user.id, currency="SGD")
    entry = await _entry(db, match.journal_entry_ids[0])
    assert entry.source_type is JournalEntrySourceType.SYSTEM
    assert entry.status is JournalEntryStatus.RECONCILED
    assert {(line.account_id, line.direction, line.amount) for line in entry.lines} == {
        (processing.id, Direction.DEBIT, Decimal("1200.00")),
        (bank.id, Direction.CREDIT, Decimal("1200.00")),
    }


async def test_AC_reconciliation_named_transfer_legs_1_an_incoming_row_posts_dr_bank_cr_processing(db, test_user):
    """AC-reconciliation.named-transfer-legs.1: money in debits the bank and credits Processing."""
    statement, bank = await _statement(db, test_user.id, "named_leg_in")
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 12),
        description="Loan drawdown",
        amount=Decimal("5000.00"),
        direction="IN",
    )

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="LOAN_PRINCIPAL", score=70)]
    )

    processing = await get_or_create_processing_account(db, test_user.id, currency="SGD")
    entry = await _entry(db, matches[0].journal_entry_ids[0])
    assert {(line.account_id, line.direction, line.amount) for line in entry.lines} == {
        (bank.id, Direction.DEBIT, Decimal("5000.00")),
        (processing.id, Direction.CREDIT, Decimal("5000.00")),
    }
    assert matches[0].match_score == 70


async def test_AC_reconciliation_named_transfer_legs_2_a_second_call_posts_nothing_more(db, test_user):
    """AC-reconciliation.named-transfer-legs.2: a row with a live match gets no second leg."""
    statement, _bank = await _statement(db, test_user.id, "named_leg_twice")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT"
    )
    named = [NamedTransfer(transaction=txn, category="TRANSFER", score=88)]

    first = await post_named_transfer_legs(db, user_id=test_user.id, named=named)
    second = await post_named_transfer_legs(db, user_id=test_user.id, named=named)

    assert len(first) == 1
    assert second == []
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 1
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 1


async def test_AC_reconciliation_named_transfer_legs_2_a_statement_without_an_account_posts_nothing(db, test_user):
    """AC-reconciliation.named-transfer-legs.2: no custody account means no leg and no error."""
    statement, _bank = await _statement(db, test_user.id, "named_leg_unlinked", linked=False)
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT"
    )

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=88)]
    )

    assert matches == []
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 0


async def test_AC_reconciliation_named_transfer_legs_2_a_currency_that_does_not_fit_posts_nothing(db, test_user):
    """AC-reconciliation.named-transfer-legs.2: the Processing account has one currency. A row in another one waits."""
    statement, _bank = await _statement(db, test_user.id, "named_leg_currency")
    await get_or_create_processing_account(db, test_user.id, currency="CNY")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT"
    )

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=88)]
    )

    assert matches == []
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 0
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 0


async def test_AC_reconciliation_named_transfer_legs_3_the_two_legs_of_one_transfer_are_paired(db, test_user):
    """AC-reconciliation.named-transfer-legs.3: the new legs enter the same pairing as the keyword legs."""
    statement_a, _bank_a = await _statement(db, test_user.id, "named_leg_pair_a", account_name="Bank A")
    statement_b, _bank_b = await _statement(db, test_user.id, "named_leg_pair_b", account_name="Bank B")
    description = "Funds moved between own accounts, reference NAMED20250110001"
    out_txn = await add_txn(
        db, statement_a, txn_date=date(2025, 1, 10), description=description, amount=Decimal("500.00"), direction="OUT"
    )
    in_txn = await add_txn(
        db, statement_b, txn_date=date(2025, 1, 11), description=description, amount=Decimal("500.00"), direction="IN"
    )

    matches = await post_named_transfer_legs(
        db,
        user_id=test_user.id,
        named=[
            NamedTransfer(transaction=out_txn, category="TRANSFER", score=90),
            NamedTransfer(transaction=in_txn, category="TRANSFER", score=90),
        ],
    )

    assert len(matches) == 2
    pairs = (await db.execute(select(func.count(ReconciliationTransferPair.id)))).scalar_one()
    assert pairs == 1
    processing = await db.scalar(select(Account).where(Account.user_id == test_user.id, Account.is_system.is_(True)))
    assert processing is not None and processing.type is AccountType.ASSET
