"""AC-reconciliation.consistency-checks.11: Falsifiable consistency checks across distinct currencies.

Verifies that duplicate and transfer-pair detection cannot produce false-positive
matches between transactions having identical amounts but distinct currencies.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import DocumentType, TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.reconciliation.extension.consistency_checks import (
    detect_duplicates,
    detect_transfer_pairs,
)


async def _create_txn(
    db: AsyncSession,
    user_id,
    *,
    amount: Decimal,
    direction: TransactionDirection,
    currency: str,
    txn_date: date,
    description: str,
) -> AtomicTransaction:
    txn = AtomicTransaction(
        id=uuid4(),
        user_id=user_id,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=direction,
        currency=currency,
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[
            {
                "doc_id": str(uuid4()),
                "doc_type": DocumentType.BANK_STATEMENT.value,
            }
        ],
    )
    db.add(txn)
    await db.flush()
    return txn


@pytest.mark.asyncio
async def test_detect_duplicates_does_not_flag_different_currencies(db: AsyncSession, test_user):
    """AC-reconciliation.consistency-checks.8: Transactions with same amount/description but distinct currencies are NOT duplicates."""
    d = date(2026, 3, 15)
    # User spends 100 USD and 100 JPY on the same day with the same description
    await _create_txn(
        db,
        test_user.id,
        amount=Decimal("100.00"),
        direction=TransactionDirection.OUT,
        currency="USD",
        txn_date=d,
        description="Coffee shop",
    )
    await _create_txn(
        db,
        test_user.id,
        amount=Decimal("100.00"),
        direction=TransactionDirection.OUT,
        currency="JPY",
        txn_date=d,
        description="Coffee shop",
    )

    checks = await detect_duplicates(db, test_user.id)
    assert len(checks) == 0, f"Expected 0 duplicate checks for different currencies, got {len(checks)}"


@pytest.mark.asyncio
async def test_detect_transfer_pairs_does_not_pair_different_currencies(db: AsyncSession, test_user):
    """AC-reconciliation.consistency-checks.8: In/Out transactions with same amount but distinct currencies are NOT transfer pairs."""
    d = date(2026, 3, 15)
    # User spends 100 USD (OUT) and receives 100 JPY (IN) on the same day
    await _create_txn(
        db,
        test_user.id,
        amount=Decimal("100.00"),
        direction=TransactionDirection.OUT,
        currency="USD",
        txn_date=d,
        description="Payment out",
    )
    await _create_txn(
        db,
        test_user.id,
        amount=Decimal("100.00"),
        direction=TransactionDirection.IN,
        currency="JPY",
        txn_date=d,
        description="Deposit in",
    )

    checks = await detect_transfer_pairs(db, test_user.id)
    assert len(checks) == 0, f"Expected 0 transfer pair checks for different currencies, got {len(checks)}"
