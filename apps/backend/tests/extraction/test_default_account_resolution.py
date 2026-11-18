from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from src.composition import _get_or_create_default_counter_account
from src.extraction.extension import review_queue
from src.extraction.extension.review_queue import get_or_create_account
from src.ledger import Account, AccountType

pytestmark = pytest.mark.asyncio
NAME = "General Expense (SGD)"


async def _account(db, user_id, *, active: bool, age_days: int = 0) -> Account:
    account = Account(user_id=user_id, name=NAME, type=AccountType.EXPENSE, currency="SGD", is_active=active, created_at=datetime.now(UTC) - timedelta(days=age_days))
    db.add(account)
    await db.flush()
    return account


async def test_AC_extraction_default_account_1_resolution_and_approval_consistency(db, test_user):
    inactive = await _account(db, test_user.id, active=False)
    created = await get_or_create_account(db, name=NAME, account_type=AccountType.EXPENSE, currency="SGD", user_id=test_user.id)
    db.info.pop("_default_account_cache", None)
    from_approval = await _get_or_create_default_counter_account(db, test_user.id, AccountType.EXPENSE, "SGD")
    assert (created.id != inactive.id, created.is_active, from_approval.id, (await db.execute(select(func.count(Account.id)).where(Account.name == NAME))).scalar_one()) == (True, True, created.id, 2)


async def test_AC_extraction_default_account_1_oldest_wins_and_reports_duplicates(db, test_user, monkeypatch):
    newer = await _account(db, test_user.id, active=True, age_days=1)
    older = await _account(db, test_user.id, active=True, age_days=10)
    error = Mock()
    monkeypatch.setattr(review_queue.logger, "error", error)
    found = await get_or_create_account(db, name=NAME, account_type=AccountType.EXPENSE, currency="SGD", user_id=test_user.id)
    assert found.id == older.id and set(error.call_args.kwargs["account_ids"]) == {str(older.id), str(newer.id)}
