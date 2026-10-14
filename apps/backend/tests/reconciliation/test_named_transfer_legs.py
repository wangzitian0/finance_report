"""AC-reconciliation.named-transfer-legs: a row that the AI named a movement between own accounts posts a Processing leg (#2415).

The keyword fallback of the reconciliation run posts a transfer leg only when the description holds a
transfer keyword. The AI classification names a wallet payment or a card repayment without such a keyword.
`post_named_transfer_legs` posts the same leg for those rows. A loan principal and an investment trade do not
use a leg: the approval books them to a default balance-sheet account.
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
    PROCESSING_ACCOUNT_CODE,
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    find_transfer_pairs,
    get_or_create_processing_account,
)
from src.reconciliation import NamedTransfer, post_named_transfer_legs, score_description
from src.reconciliation.extension.transfer_pairs import persist_transfer_pairs
from src.reconciliation.orm.reconciliation import (
    DispositionKind,
    ReconciliationMatch,
    ReconciliationStatus,
    ReconciliationTransferPair,
)
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account
from tests.db_lock_probe import backend_pid, backend_waits_for_a_lock

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
    assert entry.source_id == txn.id
    assert entry.status is JournalEntryStatus.RECONCILED
    assert match.score_breakdown["ai_score"] == 92.0
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
        description="Wallet refund",
        amount=Decimal("5000.00"),
        direction="IN",
    )

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=70)]
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


def _ledger_must_not_run(monkeypatch) -> None:
    """Replace the ledger call of the leg function with a call that fails the test."""
    from src.reconciliation.extension import named_transfers

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("the ledger must not be called for this row")

    monkeypatch.setattr(named_transfers, "post_transfer_leg", must_not_run)


async def test_AC_reconciliation_named_transfer_legs_2_a_processing_account_in_another_currency_blocks_every_row(
    db, test_user, monkeypatch
):
    """AC-reconciliation.named-transfer-legs.2: Processing holds one currency. A row in the base currency waits.

    The check runs before any ledger call. The ledger would refuse the leg as well, so the spy proves the order.
    """
    _ledger_must_not_run(monkeypatch)
    statement, _bank = await _statement(db, test_user.id, "named_leg_processing_currency")
    cny = await get_or_create_processing_account(db, test_user.id, currency="CNY")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT"
    )

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=88)]
    )

    assert matches == []
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 0
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 0
    assert (await db.get(Account, cny.id)).currency == "CNY"


@pytest.mark.parametrize("currency", ["CNY", "XXX", ""])
async def test_AC_reconciliation_named_transfer_legs_2_a_row_outside_the_base_currency_creates_no_account(
    db, test_user, currency, monkeypatch
):
    """AC-reconciliation.named-transfer-legs.2: a skipped row leaves no Processing account behind.

    The ledger posts a leg in the Processing currency, and a later posting resets the base currency of the
    transaction. A leg in a foreign currency then fails at commit. The function therefore refuses the row
    before any ledger call.
    """
    _ledger_must_not_run(monkeypatch)
    statement, _bank = await _statement(db, test_user.id, f"named_leg_foreign_{currency or 'blank'}")
    statement.currency = currency or "SGD"
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT"
    )
    txn.currency = currency

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=88)]
    )

    assert matches == []
    assert (
        await db.execute(select(func.count(Account.id)).where(Account.code == PROCESSING_ACCOUNT_CODE))
    ).scalar_one() == 0
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 0


async def test_AC_reconciliation_named_transfer_legs_2_a_custody_account_in_another_currency_makes_no_ledger_call(
    db, test_user, monkeypatch
):
    """AC-reconciliation.named-transfer-legs.2: the leg needs a custody account in the base currency too.

    The check runs before any ledger call. The ledger would refuse the leg as well, but only after it had
    created the Processing account, and the savepoint would have to undo that.
    """
    from src.reconciliation.extension import named_transfers

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("the ledger must not be called for this row")

    monkeypatch.setattr(named_transfers, "post_transfer_leg", must_not_run)
    statement, bank = await _statement(db, test_user.id, "named_leg_custody_currency")
    bank.currency = "CNY"
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT"
    )

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=88)]
    )

    assert matches == []
    assert (
        await db.execute(select(func.count(Account.id)).where(Account.code == PROCESSING_ACCOUNT_CODE))
    ).scalar_one() == 0


async def test_AC_reconciliation_named_transfer_legs_2_a_ledger_refusal_skips_one_row_and_keeps_the_others(
    db, test_user, monkeypatch
):
    """AC-reconciliation.named-transfer-legs.2: each leg has its own savepoint.

    The pre-checks make a ledger refusal rare. When one happens, the failed leg leaves no trace and the
    next row still posts.
    """
    from src.ledger import TransferAccountCurrencyMismatchError
    from src.reconciliation.extension import named_transfers

    statement, _bank = await _statement(db, test_user.id, "named_leg_refusal")
    first = await add_txn(
        db, statement, txn_date=date(2025, 1, 5), description="Wallet A", amount=Decimal("10.00"), direction="OUT"
    )
    second = await add_txn(
        db, statement, txn_date=date(2025, 1, 6), description="Wallet B", amount=Decimal("20.00"), direction="OUT"
    )
    real = named_transfers.post_transfer_leg

    async def refuse_the_first(db_, **kwargs):
        if kwargs["txn"].id == first.id:
            await get_or_create_processing_account(db_, kwargs["user_id"], currency="SGD")
            raise TransferAccountCurrencyMismatchError("refused")
        return await real(db_, **kwargs)

    monkeypatch.setattr(named_transfers, "post_transfer_leg", refuse_the_first)

    matches = await post_named_transfer_legs(
        db,
        user_id=test_user.id,
        named=[
            NamedTransfer(transaction=first, category="TRANSFER", score=90),
            NamedTransfer(transaction=second, category="TRANSFER", score=90),
        ],
    )

    assert [match.atomic_txn_id for match in matches] == [second.id]
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 1


async def test_AC_reconciliation_named_transfer_legs_2_a_ledger_refusal_leaves_no_entry_and_no_match_behind(
    db, test_user, monkeypatch
):
    """AC-reconciliation.named-transfer-legs.2: the savepoint undoes the entry and the match of the refused leg.

    The Processing account commits in its own transaction (`find_or_create_account`) and stays. An account
    without entries changes no balance, and the next leg uses it.
    """
    from src.ledger import TransferAccountCurrencyMismatchError
    from src.reconciliation.extension import named_transfers

    statement, _bank = await _statement(db, test_user.id, "named_leg_refusal_alone")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 5), description="Wallet A", amount=Decimal("10.00"), direction="OUT"
    )
    real = named_transfers.post_transfer_leg

    async def post_then_refuse(db_, **kwargs):
        await real(db_, **kwargs)
        raise TransferAccountCurrencyMismatchError("refused after the entry exists")

    monkeypatch.setattr(named_transfers, "post_transfer_leg", post_then_refuse)

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=90)]
    )

    assert matches == []
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 0
    assert (await db.execute(select(func.count(ReconciliationMatch.id)))).scalar_one() == 0


async def test_AC_reconciliation_named_transfer_legs_3_two_identical_rows_post_two_legs(db, test_user):
    """AC-reconciliation.named-transfer-legs.3: two top-ups of the same amount on one day are two payments.

    Without the source id, the ledger takes the second command for a retry of the first and returns the
    first entry. The bank is then credited once, and the statement still reaches approved.
    """
    statement, bank = await _statement(db, test_user.id, "named_leg_identical")
    rows = [
        await add_txn(
            db,
            statement,
            txn_date=date(2025, 1, 5),
            description="Payment to GrabPay Wallet",
            amount=Decimal("50.00"),
            direction="OUT",
        )
        for _ in range(2)
    ]

    matches = await post_named_transfer_legs(
        db,
        user_id=test_user.id,
        named=[NamedTransfer(transaction=row, category="TRANSFER", score=90) for row in rows],
    )

    assert len(matches) == 2
    assert matches[0].journal_entry_ids != matches[1].journal_entry_ids
    entries = [await _entry(db, match.journal_entry_ids[0]) for match in matches]
    credited = sum(
        line.amount
        for entry in entries
        for line in entry.lines
        if line.account_id == bank.id and line.direction is Direction.CREDIT
    )
    assert credited == Decimal("100.00")


async def test_AC_reconciliation_named_transfer_legs_4_the_legs_pair_in_the_next_reconciliation_run(db, test_user):
    """AC-reconciliation.named-transfer-legs.4: the legs carry anchors, so the run pairs them with the other side.

    The function posts the legs and does not pair them. The run pairs all open legs of the user with the
    step below. The pair count is read before and after that step.
    """
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
    pairs_before = (await db.execute(select(func.count(ReconciliationTransferPair.id)))).scalar_one()
    found = await find_transfer_pairs(
        db, test_user.id, currency="SGD", description_scorer=score_description, threshold=85
    )
    await persist_transfer_pairs(db, found)
    pairs_after = (await db.execute(select(func.count(ReconciliationTransferPair.id)))).scalar_one()

    assert len(matches) == 2
    assert (pairs_before, pairs_after) == (0, 1)
    processing = await db.scalar(select(Account).where(Account.user_id == test_user.id, Account.is_system.is_(True)))
    assert processing is not None and processing.type is AccountType.ASSET


@pytest.mark.parametrize("history", [ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED])
async def test_AC_reconciliation_named_transfer_legs_2_a_rejected_suggestion_does_not_own_the_row(
    db, test_user, history
):
    """AC-reconciliation.named-transfer-legs.2: a rejected or superseded match is history, as in the active index.

    The readme says that a rejected suggestion does not own the manual workflow. The unmatched query of the
    approval already lists such a row. The leg must post for it, or the statement can never be approved.
    """
    statement, _bank = await _statement(db, test_user.id, f"named_leg_{history.value}")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT"
    )
    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[],
            match_score=0,
            score_breakdown={},
            status=history,
            disposition_kind=DispositionKind.REVIEWED_UNMATCHED,
        )
    )
    await db.flush()

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=88)]
    )

    assert len(matches) == 1
    assert matches[0].disposition_kind is DispositionKind.TRANSFER_LEG
    current = (
        (
            await db.execute(
                select(ReconciliationMatch).where(
                    ReconciliationMatch.atomic_txn_id == txn.id,
                    ReconciliationMatch.status != history,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [match.id for match in current] == [matches[0].id]


@pytest.mark.parametrize(
    "status",
    [ReconciliationStatus.PENDING_REVIEW, ReconciliationStatus.ACCEPTED, ReconciliationStatus.AUTO_ACCEPTED],
)
async def test_AC_reconciliation_named_transfer_legs_2_a_current_match_still_owns_the_row(db, test_user, status):
    """AC-reconciliation.named-transfer-legs.2: a pending or accepted match blocks the leg, as the active index does."""
    statement, _bank = await _statement(db, test_user.id, f"named_leg_owned_{status.value}")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT"
    )
    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[],
            match_score=70,
            score_breakdown={},
            status=status,
            disposition_kind=DispositionKind.JOURNAL_MATCH,
        )
    )
    await db.flush()

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=88)]
    )

    assert matches == []
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 0


async def test_AC_reconciliation_named_transfer_legs_3_two_identical_incoming_rows_post_two_legs(db, test_user):
    """AC-reconciliation.named-transfer-legs.3: the source id also separates two incoming rows."""
    statement, bank = await _statement(db, test_user.id, "named_leg_identical_in")
    rows = [
        await add_txn(
            db,
            statement,
            txn_date=date(2025, 1, 5),
            description="Wallet top-up refund",
            amount=Decimal("50.00"),
            direction="IN",
        )
        for _ in range(2)
    ]

    matches = await post_named_transfer_legs(
        db,
        user_id=test_user.id,
        named=[NamedTransfer(transaction=row, category="TRANSFER", score=90) for row in rows],
    )

    assert len(matches) == 2
    entries = [await _entry(db, match.journal_entry_ids[0]) for match in matches]
    assert {entry.source_id for entry in entries} == {row.id for row in rows}
    debited = sum(
        line.amount
        for entry in entries
        for line in entry.lines
        if line.account_id == bank.id and line.direction is Direction.DEBIT
    )
    assert debited == Decimal("100.00")


async def test_AC_reconciliation_named_transfer_legs_5_a_long_description_posts_a_leg_with_a_bounded_memo(
    db, test_user
):
    """AC-reconciliation.named-transfer-legs.5: the memo column holds 500 characters, and the memo adds a prefix.

    A description of 495 characters is valid for the transaction. The leg must post. A retry of the same command
    must find the same entry, because the cut is the same each time.
    """
    from src.ledger import create_transfer_out_entry

    statement, bank = await _statement(db, test_user.id, "named_leg_long_memo")
    description = "W" * 495
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description=description, amount=Decimal("80.00"), direction="OUT"
    )

    matches = await post_named_transfer_legs(
        db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category="TRANSFER", score=88)]
    )
    await db.flush()

    assert len(matches) == 1
    entry = await _entry(db, matches[0].journal_entry_ids[0])
    assert len(entry.memo) == 500
    assert entry.memo.startswith("Transfer OUT: WWW")
    retry = await create_transfer_out_entry(
        db,
        user_id=test_user.id,
        source_account_id=bank.id,
        amount=txn.amount,
        txn_date=txn.txn_date,
        description=txn.description,
        currency=txn.currency,
        source_id=txn.id,
    )
    assert retry.id == entry.id
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 1


async def test_AC_reconciliation_named_transfer_legs_2_the_claim_for_a_decision_locks_the_row(db, test_user, db_engine):
    """AC-reconciliation.named-transfer-legs.2: a second request waits until the first request ends.

    Without the row lock, two approvals post two legs for one row. The unique index on active matches then
    makes the second request fail with an integrity error.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.reconciliation.extension.repository import SqlReconciliationRepository

    statement, _bank = await _statement(db, test_user.id, "named_leg_claim_lock")
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT"
    )
    await db.commit()
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    first, second = sessions(), sessions()
    try:
        assert await SqlReconciliationRepository(first).claim_transaction_for_decision(txn.id) is None
        second_pid = await backend_pid(second)  # opens the connection of the second session first
        waiting = asyncio.create_task(SqlReconciliationRepository(second).claim_transaction_for_decision(txn.id))
        # The database must report the wait. A sleep would pass when the second session is merely slow.
        assert await backend_waits_for_a_lock(db_engine, second_pid), "the second claim must wait for the row lock"
        await first.commit()
        assert await asyncio.wait_for(waiting, timeout=15) is None
    finally:
        await first.close()
        await second.close()
