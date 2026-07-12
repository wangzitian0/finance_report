"""Opening-balance readiness nudge (#949, EPIC-002 AC2.16).

Warns the everyday-user persona who has posted activity but never recorded a
starting position, so they don't silently ship an incomplete balance sheet.
"""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType
from src.ledger.extension.accounting import get_opening_balance_readiness, post_opening_balance_entry

from ._ledger_helpers import create_valid_posted_entry


async def _asset(db: AsyncSession, user_id, name: str = "Bank") -> Account:
    account = Account(user_id=user_id, name=name, type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    return account


async def test_AC2_16_1_no_activity_does_not_need_opening_balance(db: AsyncSession, test_user) -> None:
    """AC-ledger.16.1: a user with no posted activity is not nudged — there is nothing
    to be incomplete about yet."""
    readiness = await get_opening_balance_readiness(db, test_user.id)
    assert readiness["needs_opening_balance"] is False
    assert readiness["has_activity"] is False
    assert readiness["earliest_activity_date"] is None


async def test_AC2_16_1_activity_without_opening_entry_needs_opening_balance(db: AsyncSession, test_user) -> None:
    """AC-ledger.16.1: posted activity with no opening-balance entry flags the gap."""
    await create_valid_posted_entry(db, test_user.id, entry_date=date(2026, 3, 1))

    readiness = await get_opening_balance_readiness(db, test_user.id)
    assert readiness["needs_opening_balance"] is True
    assert readiness["has_activity"] is True
    assert readiness["has_opening_entry"] is False
    assert readiness["earliest_activity_date"] == date(2026, 3, 1)


async def test_AC2_16_1_opening_entry_before_activity_clears_the_nudge(db: AsyncSession, test_user) -> None:
    """AC-ledger.16.1: an opening-balance entry on/before the earliest activity clears it."""
    asset = await _asset(db, test_user.id)
    await create_valid_posted_entry(db, test_user.id, entry_date=date(2026, 3, 1))
    await post_opening_balance_entry(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={asset.id: Decimal("1000.00")},
        currency="SGD",
        memo="Opening balances",
    )
    await db.commit()

    readiness = await get_opening_balance_readiness(db, test_user.id)
    assert readiness["needs_opening_balance"] is False
    assert readiness["has_opening_entry"] is True


async def test_AC2_16_1_opening_entry_after_activity_still_needs(db: AsyncSession, test_user) -> None:
    """AC-ledger.16.1: an opening entry dated *after* the earliest activity leaves the
    early period uncovered, so the nudge stays on."""
    asset = await _asset(db, test_user.id)
    await create_valid_posted_entry(db, test_user.id, entry_date=date(2026, 1, 1))
    await post_opening_balance_entry(
        db,
        test_user.id,
        entry_date=date(2026, 2, 1),
        balances={asset.id: Decimal("1000.00")},
        currency="SGD",
        memo="Opening balances",
    )
    await db.commit()

    readiness = await get_opening_balance_readiness(db, test_user.id)
    assert readiness["needs_opening_balance"] is True
    assert readiness["has_opening_entry"] is True


async def test_AC2_16_2_readiness_endpoint_returns_status(client: AsyncClient) -> None:
    """AC-ledger.16.2: the endpoint exposes the readiness signal to the UI."""
    resp = await client.get("/accounts/opening-balance-readiness")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_opening_balance"] is False
    assert body["has_activity"] is False
    assert body["has_opening_entry"] is False
