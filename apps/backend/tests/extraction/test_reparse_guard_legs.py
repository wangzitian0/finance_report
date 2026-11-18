from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.audit import JournalEntrySourceType
from src.extraction.extension.deduplication import _check_reparse_identity_conflicts
from src.extraction.extension.transaction_identity import TransactionIdentityReviewRequired
from src.ledger import JournalEntry, JournalEntryStatus
from src.reconciliation import NamedTransfer, post_named_transfer_legs
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account
from tests.factories import JournalEntryFactory

pytestmark = pytest.mark.asyncio
OLD = {"statement_extraction_result": {"result_id": "first", "rows": ["Card repayment"]}}
CHANGED = {"statement_extraction_result": {"result_id": "second", "rows": ["Card repayment 2"]}}


async def _stmt_with_txn(db, user_id, file_hash: str, *, description: str, amount: Decimal):
    bank = await create_statement_account(db, user_id, f"Bank {file_hash}")
    stmt = build_statement(user_id, file_hash, 90)
    stmt.account_id, stmt.extraction_metadata = bank.id, OLD
    db.add(stmt)
    await db.flush()
    txn = await add_txn(db, stmt, txn_date=date(2025, 1, 11), description=description, amount=amount, direction="OUT")
    return stmt, txn


async def test_AC_extraction_transaction_identity_6_reparse_leg_and_posted_guards(db, test_user):
    stmt_leg, txn_leg = await _stmt_with_txn(db, test_user.id, "reparse_leg", description="Credit Card Repayment", amount=Decimal("1200.00"))
    matches = await post_named_transfer_legs(db, user_id=test_user.id, named=[NamedTransfer(transaction=txn_leg, category="CARD_REPAYMENT", score=92)], base_currency="SGD")
    leg = (await db.execute(select(JournalEntry).where(JournalEntry.source_id == txn_leg.id))).scalar_one()
    assert len(matches) == 1 and leg.status is JournalEntryStatus.RECONCILED
    await _check_reparse_identity_conflicts(db, test_user.id, stmt_leg.file_hash, OLD)
    with pytest.raises(TransactionIdentityReviewRequired, match="Changed posted source"):
        await _check_reparse_identity_conflicts(db, test_user.id, stmt_leg.file_hash, CHANGED)

    stmt_free, _ = await _stmt_with_txn(db, test_user.id, "reparse_free", description="Lunch", amount=Decimal("5.00"))
    await _check_reparse_identity_conflicts(db, test_user.id, stmt_free.file_hash, CHANGED)

    stmt_posted, txn_posted = await _stmt_with_txn(db, test_user.id, "reparse_posted_entry", description="Lunch", amount=Decimal("5.00"))
    await JournalEntryFactory.create_balanced_async(db, test_user.id, amount=Decimal("5.00"), source_type=JournalEntrySourceType.USER_CONFIRMED, source_id=txn_posted.id, status=JournalEntryStatus.POSTED)
    with pytest.raises(TransactionIdentityReviewRequired, match="Changed posted source"):
        await _check_reparse_identity_conflicts(db, test_user.id, stmt_posted.file_hash, CHANGED)
