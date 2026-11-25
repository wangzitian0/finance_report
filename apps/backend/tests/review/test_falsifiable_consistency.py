from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import TransactionDirection
from src.reconciliation.extension.consistency_checks import detect_duplicates, detect_transfer_pairs
from tests.factories import AtomicTransactionFactory


async def _add_txns(
    db: AsyncSession, user_id, rows: list[tuple[Decimal, TransactionDirection, str, date, str]]
) -> None:
    for amount, direction, currency, txn_date, description in rows:
        await AtomicTransactionFactory.create_async(
            db,
            user_id=user_id,
            amount=amount,
            direction=direction,
            currency=currency,
            txn_date=txn_date,
            description=description,
        )


async def test_consistency_checks_strictly_partition_by_currency(db: AsyncSession, test_user):
    d1, d2 = date(2026, 3, 15), date(2026, 4, 20)
    await _add_txns(
        db,
        test_user.id,
        [
            (Decimal("100.00"), TransactionDirection.OUT, "USD", d1, "Coffee shop"),
            (Decimal("100.00"), TransactionDirection.OUT, "JPY", d1, "Coffee shop"),
            (Decimal("50.00"), TransactionDirection.OUT, "USD", d2, "Subscription"),
            (Decimal("50.00"), TransactionDirection.OUT, "SGD", d2, "Subscription"),
        ],
    )
    assert await detect_duplicates(db, test_user.id) == []

    d3, d4 = date(2026, 5, 10), date(2026, 6, 15)
    await _add_txns(
        db,
        test_user.id,
        [
            (Decimal("100.00"), TransactionDirection.OUT, "USD", d3, "Payment out"),
            (Decimal("100.00"), TransactionDirection.IN, "JPY", d3, "Deposit in"),
            (Decimal("200.00"), TransactionDirection.OUT, "USD", d4, "Wire transfer"),
            (Decimal("200.00"), TransactionDirection.IN, "EUR", d4, "Wire transfer"),
        ],
    )
    assert await detect_transfer_pairs(db, test_user.id) == []
