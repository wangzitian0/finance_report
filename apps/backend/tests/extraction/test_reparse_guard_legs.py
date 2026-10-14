"""AC-extraction.transaction-identity.6: a posted Processing leg blocks a changed re-parse (#2415).

A statement that holds only Processing legs (a wallet payment, a card repayment) has no statement-source
entry. The re-parse guard looked at statement-source entries only. A rejected statement could then parse
again with a changed description, get a new transaction identity, and post a second leg for the same
payment. The bank account would be credited twice.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.extraction.extension.deduplication import _check_reparse_identity_conflicts
from src.extraction.extension.transaction_identity import TransactionIdentityReviewRequired
from src.ledger import JournalEntry, JournalEntryStatus
from src.reconciliation import NamedTransfer, post_named_transfer_legs
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account

pytestmark = pytest.mark.asyncio

OLD = {"statement_extraction_result": {"result_id": "first", "rows": ["Card repayment"]}}
CHANGED = {"statement_extraction_result": {"result_id": "second", "rows": ["Card repayment 2"]}}


async def _statement_with_one_leg(db, user_id, file_hash: str):
    bank = await create_statement_account(db, user_id, f"Bank {file_hash}")
    statement = build_statement(user_id, file_hash, 90)
    statement.account_id = bank.id
    statement.extraction_metadata = OLD
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 11),
        description="Credit Card Repayment",
        amount=Decimal("1200.00"),
        direction="OUT",
    )
    matches = await post_named_transfer_legs(
        db, user_id=user_id, named=[NamedTransfer(transaction=txn, category="CARD_REPAYMENT", score=92)]
    )
    assert len(matches) == 1
    leg = (await db.execute(select(JournalEntry).where(JournalEntry.source_id == txn.id))).scalar_one()
    assert leg.status is JournalEntryStatus.RECONCILED
    return statement, leg


async def test_AC_extraction_transaction_identity_6_a_changed_reparse_after_a_leg_needs_review(db, test_user):
    """AC-extraction.transaction-identity.6: the leg is a posted fact of the source. Changing the source needs review."""
    statement, _leg = await _statement_with_one_leg(db, test_user.id, "reparse_leg_changed")

    with pytest.raises(TransactionIdentityReviewRequired, match="Changed posted source"):
        await _check_reparse_identity_conflicts(db, test_user.id, statement.file_hash, CHANGED)


async def test_AC_extraction_transaction_identity_6_the_same_reparse_after_a_leg_passes(db, test_user):
    """AC-extraction.transaction-identity.6: an identical re-parse changes nothing, so it needs no review."""
    statement, _leg = await _statement_with_one_leg(db, test_user.id, "reparse_leg_same")

    await _check_reparse_identity_conflicts(db, test_user.id, statement.file_hash, OLD)


async def test_AC_extraction_transaction_identity_6_a_statement_without_entries_may_reparse(db, test_user):
    """AC-extraction.transaction-identity.6: nothing is posted, so a changed re-parse is free."""
    bank = await create_statement_account(db, test_user.id, "Bank free")
    statement = build_statement(test_user.id, "reparse_free", 90)
    statement.account_id = bank.id
    statement.extraction_metadata = OLD
    db.add(statement)
    await db.flush()
    await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Lunch", amount=Decimal("5.00"), direction="OUT"
    )

    await _check_reparse_identity_conflicts(db, test_user.id, statement.file_hash, CHANGED)


async def test_AC_extraction_transaction_identity_6_a_posted_statement_entry_still_needs_review(db, test_user):
    """AC-extraction.transaction-identity.6: the guard for statement-source entries stays as it was."""
    from src.audit import JournalEntrySourceType
    from tests.factories import JournalEntryFactory

    bank = await create_statement_account(db, test_user.id, "Bank posted")
    statement = build_statement(test_user.id, "reparse_posted_entry", 90)
    statement.account_id = bank.id
    statement.extraction_metadata = OLD
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db, statement, txn_date=date(2025, 1, 11), description="Lunch", amount=Decimal("5.00"), direction="OUT"
    )
    await JournalEntryFactory.create_balanced_async(
        db,
        test_user.id,
        amount=Decimal("5.00"),
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=txn.id,
        status=JournalEntryStatus.POSTED,
    )

    with pytest.raises(TransactionIdentityReviewRequired, match="Changed posted source"):
        await _check_reparse_identity_conflicts(db, test_user.id, statement.file_hash, CHANGED)
