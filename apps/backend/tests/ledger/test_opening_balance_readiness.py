from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType
from src.ledger.extension.accounting import get_opening_balance_readiness, post_opening_balance_entry
from tests.ledger._ledger_helpers import create_valid_posted_entry, make_account


@pytest.mark.parametrize(
    ("activity_date", "opening_date", "expected"),
    [
        (None, None, (False, False, False, None)),
        (date(2026, 3, 1), None, (True, True, False, date(2026, 3, 1))),
        (date(2026, 3, 1), date(2026, 1, 1), (True, True, True, date(2026, 3, 1))),
        (date(2026, 1, 1), date(2026, 2, 1), (True, True, True, date(2026, 1, 1))),
    ],
)
async def test_opening_balance_readiness(
    db: AsyncSession, test_user, activity_date: date | None, opening_date: date | None, expected: tuple
) -> None:
    if activity_date is not None:
        await create_valid_posted_entry(db, test_user.id, entry_date=activity_date)
    if opening_date is not None:
        asset = await make_account(db, test_user.id, "Bank", AccountType.ASSET)
        await post_opening_balance_entry(
            db, test_user.id, entry_date=opening_date, balances={asset.id: Decimal("1000.00")}, currency="SGD", base_currency="SGD", memo="Opening balances"
        )
        await db.commit()
    readiness = await get_opening_balance_readiness(db, test_user.id)
    assert (
        readiness["needs_opening_balance"],
        readiness["has_activity"],
        readiness["has_opening_entry"],
        readiness["earliest_activity_date"],
    ) == expected


async def test_readiness_endpoint_returns_status(client: AsyncClient) -> None:
    resp = await client.get("/accounts/opening-balance-readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert (body["needs_opening_balance"], body["has_activity"], body["has_opening_entry"]) == (False, False, False)
