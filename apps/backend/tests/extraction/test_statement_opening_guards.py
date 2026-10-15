"""A source cannot obtain opening stock from missing or invalid historical FX."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from src.composition import compose_statement_posting_dependencies
from src.extraction.extension.statement_posting import try_auto_post_statement_opening_balance
from src.ledger import (
    Account,
    AccountType,
    JournalEntry,
    JournalEntryStatus,
    calculate_account_balance,
    initialize_opening_positions,
    list_opening_positions,
    void_journal_entry,
)
from src.reporting.extension.balance_sheet import generate_balance_sheet
from tests.factories import StatementSummaryFactory


@pytest.mark.parametrize(
    "case", ["missing_fields", "missing_provider", "provider_failure", "invalid_rate", "valid_rate"]
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


async def test_statement_opening_contiguous_reverse_upload_supersedes_later_opening(db, test_user):
    """Contiguous reverse upload (Feb then Jan, Jan.closing == Feb.opening) supersedes Feb opening and voids old entry."""
    account = Account(user_id=test_user.id, name="SGD Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    # Later statement (Feb 1) was already initialized with opening balance 500
    feb_entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 2, 1),
        balances={account.id: Decimal("500")},
        currency="SGD",
        base_currency="SGD",
    )
    assert feb_entry is not None
    assert feb_entry.status == JournalEntryStatus.POSTED

    # Earlier statement (Jan 1 to Jan 31) arrives with opening 200, closing 500 (Jan.closing == Feb.opening)
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="SGD",
        opening_balance=Decimal("200"),
        closing_balance=Decimal("500"),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
    )

    posted = await try_auto_post_statement_opening_balance(db, statement, test_user.id)
    assert posted is True

    # Verify Feb's opening JournalEntry is voided
    await db.refresh(feb_entry)
    assert feb_entry.status == JournalEntryStatus.VOID
    assert feb_entry.void_reason == "Superseded by earlier statement opening balance"

    # Verify opening position is now anchored at Jan 1 with amount 200
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date.max)
    assert len(positions) == 1
    assert positions[0].account_id == account.id
    assert positions[0].effective_date == date(2026, 1, 1)
    assert positions[0].amount == Decimal("200")

    # Verify total account balance equals 200 (not 500 + 200 = 700)
    # The original Feb entry (+500) and its reversal (-500) cancel to 0, leaving Jan (+200)
    current_balance = await calculate_account_balance(db, account.id, test_user.id)
    assert current_balance == Decimal("200")

    bs = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 2, 28), currency="SGD")
    asset_line = next(line for line in bs["assets"] if line["account_id"] == account.id)
    assert asset_line["amount"] == Decimal("200")


async def test_statement_opening_non_contiguous_reverse_upload_supersedes_later_opening(db, test_user):
    """Non-contiguous reverse upload (Dec then Jan, Jan.closing != Dec.opening) auto-posts cleanly, voiding Dec entry."""
    account = Account(user_id=test_user.id, name="SGD Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    # Dec statement (2025-12-01) posted first with opening balance 9000
    dec_entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 12, 1),
        balances={account.id: Decimal("9000")},
        currency="SGD",
        base_currency="SGD",
    )
    assert dec_entry is not None
    assert dec_entry.status == JournalEntryStatus.POSTED

    # Jan statement arrives (2025-01-01 to 2025-01-31) with opening 1000, closing 1500 (closing != 9000)
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="SGD",
        opening_balance=Decimal("1000"),
        closing_balance=Decimal("1500"),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
    )

    # Auto-posts cleanly without raising ValueError
    posted = await try_auto_post_statement_opening_balance(db, statement, test_user.id)
    assert posted is True

    # Dec entry is voided
    await db.refresh(dec_entry)
    assert dec_entry.status == JournalEntryStatus.VOID
    assert dec_entry.void_reason == "Superseded by earlier statement opening balance"

    # Anchored at Jan 1 with opening balance 1000
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date.max)
    assert len(positions) == 1
    assert positions[0].account_id == account.id
    assert positions[0].effective_date == date(2025, 1, 1)
    assert positions[0].amount == Decimal("1000")

    # Verify total account balance equals 1000 without double counting
    current_balance = await calculate_account_balance(db, account.id, test_user.id)
    assert current_balance == Decimal("1000")

    bs = await generate_balance_sheet(db, test_user.id, as_of_date=date(2025, 12, 31), currency="SGD")
    asset_line = next(line for line in bs["assets"] if line["account_id"] == account.id)
    assert asset_line["amount"] == Decimal("1000")


async def test_statement_opening_chronological_order_preserves_earlier_opening(db, test_user):
    """Chronological upload (Jan then Feb) leaves Jan opening balance as the single source of truth."""
    account = Account(user_id=test_user.id, name="SGD Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    # Jan statement posted first
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 1, 1),
        balances={account.id: Decimal("1000")},
        currency="SGD",
        base_currency="SGD",
    )

    # Feb statement arrives
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="SGD",
        opening_balance=Decimal("1500"),
        period_start=date(2025, 2, 1),
    )

    posted = await try_auto_post_statement_opening_balance(db, statement, test_user.id)
    assert posted is False

    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date.max)
    assert len(positions) == 1
    assert positions[0].effective_date == date(2025, 1, 1)
    assert positions[0].amount == Decimal("1000")


async def test_statement_opening_same_date_matching_balance_is_idempotent(db, test_user):
    """Same-date statement with matching opening balance returns False idempotently."""
    account = Account(user_id=test_user.id, name="SGD Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 1, 1),
        balances={account.id: Decimal("1000")},
        currency="SGD",
        base_currency="SGD",
    )

    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="SGD",
        opening_balance=Decimal("1000"),
        period_start=date(2025, 1, 1),
    )

    posted = await try_auto_post_statement_opening_balance(db, statement, test_user.id)
    assert posted is False


async def test_statement_opening_same_date_conflicting_balance_raises_error(db, test_user):
    """Same-date statement with conflicting opening balance raises an actionable ValueError."""
    account = Account(user_id=test_user.id, name="SGD Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 1, 1),
        balances={account.id: Decimal("1000")},
        currency="SGD",
        base_currency="SGD",
    )

    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="SGD",
        opening_balance=Decimal("2000"),
        period_start=date(2025, 1, 1),
    )

    with pytest.raises(ValueError, match="Opening balance conflicts with existing opening position for the same date"):
        await try_auto_post_statement_opening_balance(db, statement, test_user.id)


async def test_void_journal_entry_annihilates_balance_cleanly(db, test_user):
    """Voiding a journal entry leaves calculate_account_balance == 0 with zero reversal distortion."""
    account = Account(user_id=test_user.id, name="SGD Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={account.id: Decimal("500")},
        currency="SGD",
        base_currency="SGD",
    )
    assert await calculate_account_balance(db, account.id, test_user.id) == Decimal("500")

    await void_journal_entry(db, entry.id, "Test void", test_user.id)
    assert await calculate_account_balance(db, account.id, test_user.id) == Decimal("0")

    bs = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 1, 31), currency="SGD")
    asset_line = next((line for line in bs["assets"] if line["account_id"] == account.id), None)
    assert asset_line is None or asset_line["amount"] == Decimal("0")
