"""A source cannot obtain opening stock from missing or invalid historical FX."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from src.composition import compose_statement_posting_dependencies
from src.extraction.extension.statement_posting import try_auto_post_statement_opening_balance
from src.ledger import Account, AccountType, JournalEntry, initialize_opening_positions
from tests.factories import StatementSummaryFactory


@pytest.mark.parametrize(
    "case", ["missing_fields", "later_opening", "missing_provider", "provider_failure", "invalid_rate", "valid_rate"]
)
async def test_statement_opening_requires_valid_historical_inputs(db, test_user, case):
    """AC-extraction.opening-lineage.1: only usable historical facts can establish stock."""
    account = Account(user_id=test_user.id, name="Foreign source", type=AccountType.ASSET, currency="USD")
    db.add(account)
    await db.flush()
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="USD",
        opening_balance=Decimal("100"),
        period_start=date(2026, 1, 1),
    )
    if case == "missing_fields":
        statement.opening_balance = None
    if case == "later_opening":
        await initialize_opening_positions(
            db,
            test_user.id,
            entry_date=date(2026, 1, 2),
            balances={account.id: Decimal("0")},
            currency="USD",
            base_currency="SGD",
        )
    provider = (
        AsyncMock(side_effect=ValueError("FX unavailable"))
        if case == "provider_failure"
        else AsyncMock(return_value=Decimal("0") if case == "invalid_rate" else Decimal("1.35"))
    )
    dependencies = replace(
        compose_statement_posting_dependencies(), fx_rate_provider=provider, fx_rate_error=ValueError
    )
    if case == "valid_rate":
        assert await try_auto_post_statement_opening_balance(db, statement, test_user.id, dependencies=dependencies)
        provider.assert_awaited_once_with(db, "USD", "SGD", date(2026, 1, 1), lazy_load=True)
    else:
        with pytest.raises(ValueError):
            await try_auto_post_statement_opening_balance(
                db, statement, test_user.id, dependencies=None if case == "missing_provider" else dependencies
            )
        assert (
            await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id))
            == 0
        )


async def test_statement_opening_allows_continuous_out_of_order_upload(db, test_user):
    """Out-of-order statement upload succeeds when earlier statement closing balance matches existing opening position."""
    account = Account(user_id=test_user.id, name="SGD Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    # Later statement (Feb 1) was already initialized with opening balance 500
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 2, 1),
        balances={account.id: Decimal("500")},
        currency="SGD",
        base_currency="SGD",
    )

    # Earlier statement (Jan 1 to Jan 31) arrives with closing balance 500
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="SGD",
        opening_balance=Decimal("200"),
        closing_balance=Decimal("500"),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )

    # Should not raise ValueError; returns False indicating continuity holds and no contradictory opening entry needed
    posted = await try_auto_post_statement_opening_balance(db, statement, test_user.id)
    assert posted is False
