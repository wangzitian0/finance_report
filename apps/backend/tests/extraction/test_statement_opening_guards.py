from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from src.composition import compose_statement_posting_dependencies
from src.extraction.extension import statement_posting, statement_validation
from src.extraction.extension.statement_posting import try_auto_post_statement_opening_balance
from src.ledger import (
    AccountType,
    JournalEntry,
    JournalEntryStatus,
    account_service,
    calculate_account_balance,
    initialize_opening_positions,
    list_opening_positions,
    void_journal_entry,
)
from src.ledger.extension.account_service import (
    UNEXPLAINED_GAP_EQUITY_CODE,
    get_or_create_unexplained_gap_equity_account,
)
from src.reporting.extension.balance_sheet import generate_balance_sheet
from tests.extraction._statement_run_helpers import (
    assert_bs_asset,
    make_account,
    verify_foreign_currency_opening_and_retire,
    verify_manual_override_and_lifecycle_guards,
    verify_reconcile_chain_out_of_order,
    verify_reconcile_chain_retirement_and_fx,
)
from tests.factories import StatementSummaryFactory


@pytest.mark.parametrize(
    "case", ["missing_fields", "missing_provider", "provider_failure", "invalid_rate", "valid_rate"]
)
async def test_statement_opening_requires_valid_historical_inputs(db, test_user, case):
    account = await make_account(db, test_user.id, name="Foreign source", currency="USD")
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="USD",
        opening_balance=None if case == "missing_fields" else Decimal("100"),
        period_start=date(2026, 1, 1),
    )
    provider = (
        AsyncMock(side_effect=ValueError("FX unavailable"))
        if case == "provider_failure"
        else AsyncMock(return_value=Decimal("0") if case == "invalid_rate" else Decimal("1.35"))
    )
    deps = replace(compose_statement_posting_dependencies(), fx_rate_provider=provider, fx_rate_error=ValueError)
    if case == "valid_rate":
        assert await try_auto_post_statement_opening_balance(db, statement, test_user.id, dependencies=deps)
        provider.assert_awaited_once_with(db, "USD", "SGD", date(2026, 1, 1), lazy_load=True)
    else:
        with pytest.raises(ValueError):
            await try_auto_post_statement_opening_balance(
                db, statement, test_user.id, dependencies=None if case == "missing_provider" else deps
            )
        assert (
            await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id))
            == 0
        )


@pytest.mark.parametrize(
    ("later_date", "later_amt", "start", "end", "open_bal", "close_bal", "bs_date"),
    [
        (date(2026, 2, 1), "500", date(2026, 1, 1), date(2026, 1, 31), "200", "500", date(2026, 2, 28)),
        (date(2025, 12, 1), "9000", date(2025, 1, 1), date(2025, 1, 31), "1000", "1500", date(2025, 12, 31)),
    ],
)
async def test_statement_opening_reverse_upload_supersedes_later_opening(
    db, test_user, later_date, later_amt, start, end, open_bal, close_bal, bs_date
):
    account = await make_account(db, test_user.id, name="SGD Checking")
    later_entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=later_date,
        balances={account.id: Decimal(later_amt)},
        currency="SGD",
        base_currency="SGD",
    )
    assert later_entry is not None and later_entry.status == JournalEntryStatus.POSTED
    statement = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="SGD",
        opening_balance=Decimal(open_bal),
        closing_balance=Decimal(close_bal),
        period_start=start,
        period_end=end,
    )
    assert await try_auto_post_statement_opening_balance(db, statement, test_user.id, base_currency="SGD") is True
    await db.refresh(later_entry)
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date.max)
    assert (
        later_entry.status,
        later_entry.void_reason,
        len(positions),
        positions[0].account_id,
        positions[0].effective_date,
        positions[0].amount,
        await calculate_account_balance(db, account.id, test_user.id),
    ) == (
        JournalEntryStatus.VOID,
        "Superseded by earlier statement opening balance",
        1,
        account.id,
        start,
        Decimal(open_bal),
        Decimal(open_bal),
    )
    await assert_bs_asset(
        db, test_user.id, as_of_date=bs_date, currency="SGD", account_id=account.id, expected=Decimal(open_bal)
    )


@pytest.mark.parametrize(
    ("period_start", "opening", "conflict"),
    [(date(2025, 2, 1), "1500", False), (date(2025, 1, 1), "1000", False), (date(2025, 1, 1), "2000", True)],
)
async def test_statement_opening_chronological_and_same_date_guards(db, test_user, period_start, opening, conflict):
    account = await make_account(db, test_user.id, name="SGD Checking")
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 1, 1),
        balances={account.id: Decimal("1000")},
        currency="SGD",
        base_currency="SGD",
    )
    stmt = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        currency="SGD",
        opening_balance=Decimal(opening),
        period_start=period_start,
    )
    if conflict:
        with pytest.raises(
            ValueError, match="Opening balance conflicts with existing opening position for the same date"
        ):
            await try_auto_post_statement_opening_balance(db, stmt, test_user.id, base_currency="SGD")
    else:
        assert await try_auto_post_statement_opening_balance(db, stmt, test_user.id, base_currency="SGD") is False
        pos = await list_opening_positions(db, user_id=test_user.id, as_of=date.max)
        assert len(pos) == 1 and (pos[0].effective_date, pos[0].amount) == (date(2025, 1, 1), Decimal("1000"))


async def test_void_equity_and_ssot_constants(db, test_user):
    account = await make_account(db, test_user.id, name="SGD Checking")
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
    bs = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 1, 31), currency="SGD")
    line = next((row for row in bs["assets"] if row["account_id"] == account.id), None)
    assert await calculate_account_balance(db, account.id, test_user.id) == Decimal("0") and (
        line is None or line["amount"] == Decimal("0")
    )

    g1, g2, g_usd = (
        await get_or_create_unexplained_gap_equity_account(db, test_user.id, "SGD"),
        await get_or_create_unexplained_gap_equity_account(db, test_user.id, "sgd"),
        await get_or_create_unexplained_gap_equity_account(db, test_user.id, "USD"),
    )
    assert g1.id == g2.id != g_usd.id and (g1.code, g1.type, g1.is_system, g1.currency, g_usd.currency) == (
        UNEXPLAINED_GAP_EQUITY_CODE,
        AccountType.EQUITY,
        True,
        "SGD",
        "USD",
    )

    jan_e = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 1, 1),
        balances={account.id: Decimal("1000.00")},
        currency="SGD",
        base_currency="SGD",
    )
    jun_e = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 6, 1),
        balances={account.id: Decimal("1500.00")},
        currency="SGD",
        base_currency="SGD",
        allow_supersede=True,
    )
    await db.refresh(jan_e)
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date.max)
    assert (
        jan_e.status,
        jun_e.status,
        len(positions),
        positions[0].effective_date,
        positions[0].amount,
        await calculate_account_balance(db, account.id, test_user.id),
    ) == (
        JournalEntryStatus.VOID,
        JournalEntryStatus.POSTED,
        1,
        date(2025, 6, 1),
        Decimal("1500.00"),
        Decimal("1500.00"),
    )

    stmt = StatementSummaryFactory.build(opening_balance=Decimal("100.00"), manual_opening_balance=None)
    assert not hasattr(statement_validation, "_get_opening_balance") and (
        account_service.OPENING_BALANCE_EQUITY_CODE,
        account_service.UNEXPLAINED_GAP_EQUITY_CODE,
        statement_posting.account_service.CROSS_PERIOD_GAP_PLUG_TOLERANCE,
        statement_posting.account_service.CROSS_PERIOD_GAP_PLUG_EVENT_TYPE,
        stmt.effective_opening_balance(),
    ) == ("3199", "3198", Decimal("0.10"), "cross_period_gap_plug", Decimal("100.00"))
    stmt.manual_opening_balance = Decimal("250.00")
    assert stmt.effective_opening_balance() == Decimal("250.00")


@pytest.mark.parametrize(
    "verify",
    [
        verify_reconcile_chain_out_of_order,
        verify_reconcile_chain_retirement_and_fx,
        verify_manual_override_and_lifecycle_guards,
        verify_foreign_currency_opening_and_retire,
    ],
)
async def test_AC_extraction_2832_reconcile_chain_helpers(db, test_user, verify):
    await verify(db, test_user)
