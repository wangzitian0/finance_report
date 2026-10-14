"""AC-extraction.default-account.1: one resolver finds the default account of a user (#2415).

Two code paths create the same default accounts: the classifier (`General Expense (CUR)`, `Loans Payable (CUR)`,
`Investments (CUR)`, the category accounts) and the one-click approval. They must agree on which account is the
default. Posting refuses an inactive counter account, and a second row with the same name used to make every
later lookup fail. The audit of #2424 named both cases.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from src.composition import _get_or_create_default_counter_account
from src.extraction.extension.review_queue import get_or_create_account
from src.ledger import Account, AccountType

pytestmark = pytest.mark.asyncio

NAME = "General Expense (SGD)"


async def _account(db, user_id, *, active: bool, age_days: int = 0) -> Account:
    account = Account(
        user_id=user_id,
        name=NAME,
        type=AccountType.EXPENSE,
        currency="SGD",
        is_active=active,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    db.add(account)
    await db.flush()
    return account


async def test_AC_extraction_default_account_1_an_inactive_default_account_is_not_the_default(db, test_user):
    """AC-extraction.default-account.1: the user deactivated the account. Posting would refuse it, so a new one is made."""
    inactive = await _account(db, test_user.id, active=False)

    found = await get_or_create_account(
        db, name=NAME, account_type=AccountType.EXPENSE, currency="SGD", user_id=test_user.id
    )

    assert found.id != inactive.id
    assert found.is_active is True
    assert (await db.execute(select(func.count(Account.id)).where(Account.name == NAME))).scalar_one() == 2


async def test_AC_extraction_default_account_1_two_active_rows_resolve_to_the_oldest(db, test_user):
    """AC-extraction.default-account.1: duplicates must not turn every approval into an error."""
    # The newer row is inserted first. A table returns rows in insertion order, so only the ORDER BY of the
    # lookup can pick the older one.
    await _account(db, test_user.id, active=True, age_days=1)
    older = await _account(db, test_user.id, active=True, age_days=10)

    found = await get_or_create_account(
        db, name=NAME, account_type=AccountType.EXPENSE, currency="SGD", user_id=test_user.id
    )

    assert found.id == older.id


async def test_AC_extraction_default_account_1_the_one_click_approval_uses_the_same_resolver(db, test_user):
    """AC-extraction.default-account.1: the approval and the classifier never create two defaults."""
    from_classifier = await get_or_create_account(
        db, name=NAME, account_type=AccountType.EXPENSE, currency="SGD", user_id=test_user.id
    )
    db.info.pop("_default_account_cache", None)

    from_approval = await _get_or_create_default_counter_account(db, test_user.id, AccountType.EXPENSE, "SGD")

    assert from_approval.id == from_classifier.id
    assert (await db.execute(select(func.count(Account.id)).where(Account.name == NAME))).scalar_one() == 1


async def test_AC_extraction_default_account_1_two_active_rows_are_reported(db, test_user, monkeypatch):
    """AC-extraction.default-account.1: the oldest row wins, and the log names both ids.

    Entries on the newer row would stay out of the balance of the oldest row without any sign of it.
    """
    from unittest.mock import Mock

    from src.extraction.extension import review_queue

    older = await _account(db, test_user.id, active=True, age_days=10)
    newer = await _account(db, test_user.id, active=True, age_days=1)
    error = Mock()
    monkeypatch.setattr(review_queue.logger, "error", error)

    found = await get_or_create_account(
        db, name=NAME, account_type=AccountType.EXPENSE, currency="SGD", user_id=test_user.id
    )

    assert found.id == older.id
    error.assert_called_once()
    assert set(error.call_args.kwargs["account_ids"]) == {str(older.id), str(newer.id)}
