"""AC-reconciliation.named-transfer-legs.6: the keyword fallback posts a leg only in the base currency (#2415).

The Processing account holds the effective base currency. The ledger takes the currency of the caller, so the
keyword phase decides. A statement in another currency used to create a Processing account in that
currency. The named transfers of the user were then skipped, and the approval answered 409 without a hint.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from src.ledger import PROCESSING_ACCOUNT_CODE, Account, JournalEntry
from src.reconciliation.extension.phases.transfer_detection import run_transfer_detection_phase
from src.reconciliation.extension.repository import SqlReconciliationRepository
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account

pytestmark = pytest.mark.asyncio


async def _statement(db, user_id, file_hash: str, *, currency: str):
    bank = await create_statement_account(db, user_id, f"Bank {file_hash}")
    bank.currency = currency
    statement = build_statement(user_id, file_hash, 90)
    statement.account_id = bank.id
    statement.currency = currency
    db.add(statement)
    await db.flush()
    return statement, bank


async def _run(db, user_id, txns):
    return await run_transfer_detection_phase(
        db, transactions=txns, matched_txn_ids=set(), repository=SqlReconciliationRepository(db), user_id=user_id
    )


async def test_AC_reconciliation_named_transfer_legs_6_a_foreign_row_posts_no_leg_and_creates_no_account(db, test_user):
    """AC-reconciliation.named-transfer-legs.6: a USD row on a SGD base posts nothing, and the account is not created."""
    statement, _bank = await _statement(db, test_user.id, "keyword_usd", currency="USD")
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 11),
        description="Transfer to savings",
        amount=Decimal("80.00"),
        direction="OUT",
    )

    created = await _run(db, test_user.id, [txn])
    await db.commit()

    assert created == []
    assert (
        await db.execute(select(func.count(Account.id)).where(Account.code == PROCESSING_ACCOUNT_CODE))
    ).scalar_one() == 0
    assert (await db.execute(select(func.count(JournalEntry.id)))).scalar_one() == 0


async def test_AC_reconciliation_named_transfer_legs_6_a_base_currency_row_still_posts_a_leg(db, test_user):
    """AC-reconciliation.named-transfer-legs.6: the check does not stop the rows that the keyword phase served before."""
    statement, _bank = await _statement(db, test_user.id, "keyword_sgd", currency="SGD")
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 11),
        description="Transfer to savings",
        amount=Decimal("80.00"),
        direction="OUT",
    )

    created = await _run(db, test_user.id, [txn])
    await db.commit()

    assert len(created) == 1
    processing = (await db.execute(select(Account).where(Account.code == PROCESSING_ACCOUNT_CODE))).scalar_one()
    assert processing.currency == "SGD"


async def test_AC_reconciliation_named_transfer_legs_6_the_keyword_leg_carries_the_source_id(db, test_user):
    """AC-reconciliation.named-transfer-legs.6: two identical keyword rows get two entries, as the named legs do."""
    statement, _bank = await _statement(db, test_user.id, "keyword_identical", currency="SGD")
    rows = [
        await add_txn(
            db,
            statement,
            txn_date=date(2025, 1, 11),
            description="Transfer to savings",
            amount=Decimal("80.00"),
            direction=direction,
        )
        for direction in ("OUT", "OUT", "IN", "IN")
    ]

    created = await _run(db, test_user.id, rows)
    await db.commit()

    assert len(created) == 4
    entries = (await db.execute(select(JournalEntry.source_id))).scalars().all()
    assert sorted(entries) == sorted(row.id for row in rows)
