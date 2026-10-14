"""AC-ledger.71.6: a read never creates the Processing account (#2415).

The Processing account fixes the currency of the Processing balance. The first transfer leg creates it, in the
base currency of that moment. The account now commits at once (AC-ledger.71.5), so a page view that created it
would fix the currency for every user on the first visit of the home page. A later change of the base currency
would then block every transfer leg, and the product has no way to repair the account.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.ledger import (
    PROCESSING_ACCOUNT_CODE,
    Account,
    AccountType,
    create_transfer_out_entry,
    find_processing_account,
    find_transfer_pairs,
    get_or_create_processing_account,
    get_processing_balance,
    get_unpaired_transfers,
    list_processing_transfer_legs,
)
from src.ledger.extension import processing
from src.reconciliation import score_description
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio


async def _processing_count(db, user_id) -> int:
    return await db.scalar(
        select(func.count(Account.id)).where(Account.user_id == user_id, Account.code == PROCESSING_ACCOUNT_CODE)
    )


@pytest.mark.parametrize("path", ["/accounts/processing/summary", "/accounts/processing/pending"])
async def test_AC_ledger_71_6_a_page_view_creates_no_processing_account(client, db, test_user, path):
    """AC-ledger.71.6: the home page reads the card of a new user. The read answers zeros and leaves no account."""
    response = await client.get(path)

    assert response.status_code == 200
    body = response.json()
    if path.endswith("summary"):
        assert (body["pending_count"], body["current_balance"], body["pending_total"]) == (0, "0.00", "0.00")
    else:
        assert body == {"items": [], "total": 0}
    assert await _processing_count(db, test_user.id) == 0


async def test_AC_ledger_71_6_the_ledger_reads_create_no_processing_account(db, test_user):
    """AC-ledger.71.6: each read of the Processing machinery answers empty for a user without the account."""
    assert await get_processing_balance(db, test_user.id, currency="SGD") == Decimal("0")
    assert await get_unpaired_transfers(db, test_user.id, currency="SGD") == []
    assert await list_processing_transfer_legs(db, test_user.id, currency="SGD") == []
    assert await find_transfer_pairs(db, test_user.id, currency="SGD", description_scorer=score_description) == []
    assert await find_processing_account(db, test_user.id) is None
    assert await _processing_count(db, test_user.id) == 0


async def test_AC_ledger_71_6_a_view_does_not_fix_the_currency_before_the_first_leg(client, db, test_user):
    """AC-ledger.71.6: the user views the card, changes the base currency, and then posts the first leg."""
    from src.config_app import set_base_currency

    await client.get("/accounts/processing/summary")
    await set_base_currency(db, "USD")
    await db.commit()
    bank = Account(user_id=test_user.id, name="USD bank", type=AccountType.ASSET, currency="USD")
    db.add(bank)
    await db.commit()

    entry = await create_transfer_out_entry(
        db,
        user_id=test_user.id,
        source_account_id=bank.id,
        amount=Decimal("10.00"),
        txn_date=date(2025, 1, 5),
        description="Wallet",
        currency="USD",
    )

    assert entry is not None
    assert (await find_processing_account(db, test_user.id)).currency == "USD"


async def test_AC_ledger_71_6_two_processing_accounts_resolve_to_the_oldest_and_say_so(db, test_user, monkeypatch):
    """AC-ledger.71.6: legs on the newer account never pair, so the lookup must not hide the second account."""
    user = await UserFactory.create_async(db, email=f"dup-{uuid4()}@example.invalid")
    older = await get_or_create_processing_account(db, user.id, currency="SGD")
    db.add(
        Account(
            user_id=user.id,
            name="Processing",
            code=PROCESSING_ACCOUNT_CODE,
            type=AccountType.ASSET,
            currency="SGD",
            is_system=True,
        )
    )
    await db.flush()
    error = Mock()
    monkeypatch.setattr(processing.logger, "error", error)

    found = await find_processing_account(db, user.id)

    assert found.id == older.id
    error.assert_called_once()
    assert error.call_args.kwargs["user_id"] == str(user.id)
    assert len(error.call_args.kwargs["account_ids"]) == 2
