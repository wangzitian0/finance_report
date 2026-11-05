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


async def test_AC_ledger_2832_1_unexplained_gap_equity_account_and_superseding_opening_position(db, test_user):
    """AC-ledger.2832.1: get_or_create_unexplained_gap_equity_account provisions system equity account 3198
    per currency, and initialize_opening_positions(..., allow_supersede=True) supports re-anchoring an
    account opening position when statement chains are re-anchored."""
    from src.ledger.extension.account_service import (
        UNEXPLAINED_GAP_EQUITY_CODE,
        get_or_create_unexplained_gap_equity_account,
    )

    gap_sgd_1 = await get_or_create_unexplained_gap_equity_account(db, test_user.id, "SGD")
    gap_sgd_2 = await get_or_create_unexplained_gap_equity_account(db, test_user.id, "sgd")
    gap_usd = await get_or_create_unexplained_gap_equity_account(db, test_user.id, "USD")

    assert gap_sgd_1.id == gap_sgd_2.id
    assert gap_sgd_1.code == UNEXPLAINED_GAP_EQUITY_CODE == "3198"
    assert gap_sgd_1.type == AccountType.EQUITY
    assert gap_sgd_1.is_system is True
    assert gap_sgd_1.currency == "SGD"
    assert gap_usd.id != gap_sgd_1.id
    assert gap_usd.currency == "USD"

    account = Account(user_id=test_user.id, name="SGD Checking", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()

    jan_entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 1, 1),
        balances={account.id: Decimal("1000.00")},
        currency="SGD",
        base_currency="SGD",
    )
    assert jan_entry is not None
    assert jan_entry.status == JournalEntryStatus.POSTED

    # Re-anchoring to a later date (e.g. after retiring the Jan statement) succeeds when allow_supersede=True
    jun_entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 6, 1),
        balances={account.id: Decimal("1500.00")},
        currency="SGD",
        base_currency="SGD",
        allow_supersede=True,
    )
    assert jun_entry is not None
    assert jun_entry.status == JournalEntryStatus.POSTED
    await db.refresh(jan_entry)
    assert jan_entry.status == JournalEntryStatus.VOID

    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date.max)
    assert len(positions) == 1
    assert positions[0].effective_date == date(2025, 6, 1)
    assert positions[0].amount == Decimal("1500.00")
    assert await calculate_account_balance(db, account.id, test_user.id) == Decimal("1500.00")


async def test_AC_extraction_2832_2_reconcile_statement_chain_anchors_out_of_order_and_gap_plugs(db, test_user):
    """AC-extraction.2832.2: Out-of-order statement approvals (June first, January second, February gap-fill third,
    then retiring January) anchor S_0 to 3199 Opening Balance Equity and calibrate inter-statement gaps in 3198
    Unexplained Statement Gap Equity so every approved statement's opening and closing balances tie out on the
    Balance Sheet."""
    from src.extraction.base.source_vocabulary import BankStatementStatus
    from src.extraction.base.types import RetireStatementCommand
    from src.extraction.extension.source_lifecycle import retire_statement
    from src.extraction.extension.statement_posting import reconcile_account_statement_chain
    from src.ledger import Direction, submit_system_journal_entry
    from src.ledger.extension.account_service import get_or_create_unexplained_gap_equity_account

    account = Account(user_id=test_user.id, name="DBS Multiplier", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    db.add_all([account, income])
    await db.flush()

    # 1. User uploads & approves June 2025 first (opening 15,000, +3,000 net txns, closing 18,000)
    stmt_jun = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        institution="DBS",
        account_last4="8888",
        currency="SGD",
        opening_balance=Decimal("15000.00"),
        closing_balance=Decimal("18000.00"),
        period_start=date(2025, 6, 1),
        period_end=date(2025, 6, 30),
        status=BankStatementStatus.APPROVED,
    )
    db.add(stmt_jun)
    await db.flush()
    await submit_system_journal_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2025, 6, 15),
        memo="June salary",
        lines_data=[
            {"account_id": account.id, "direction": Direction.DEBIT, "amount": Decimal("3000.00"), "currency": "SGD"},
            {"account_id": income.id, "direction": Direction.CREDIT, "amount": Decimal("3000.00"), "currency": "SGD"},
        ],
        base_currency="SGD",
        operation="test-june-txn",
    )
    await try_auto_post_statement_opening_balance(db, stmt_jun, test_user.id)

    bs_jun_only = await generate_balance_sheet(db, test_user.id, as_of_date=date(2025, 6, 30), currency="SGD")
    assert bs_jun_only["is_balanced"] is True
    assert next(a["amount"] for a in bs_jun_only["assets"] if a["account_id"] == account.id) == Decimal("18000.00")

    # 2. User next uploads & approves January 2025 (opening 10,000, +2,000 net txns, closing 12,000)
    stmt_jan = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        institution="DBS",
        account_last4="8888",
        currency="SGD",
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("12000.00"),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        status=BankStatementStatus.APPROVED,
    )
    db.add(stmt_jan)
    await db.flush()
    await submit_system_journal_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2025, 1, 15),
        memo="Jan salary",
        lines_data=[
            {"account_id": account.id, "direction": Direction.DEBIT, "amount": Decimal("2000.00"), "currency": "SGD"},
            {"account_id": income.id, "direction": Direction.CREDIT, "amount": Decimal("2000.00"), "currency": "SGD"},
        ],
        base_currency="SGD",
        operation="test-jan-txn",
    )
    await try_auto_post_statement_opening_balance(db, stmt_jan, test_user.id)

    # Check anchors at Jan 1 (10,000), Jan 31 (12,000), Jun 1 (15,000), Jun 30 (18,000) via Balance Sheet
    for anchor_date, expected_bal in (
        (date(2025, 1, 1), Decimal("10000.00")),
        (date(2025, 1, 31), Decimal("12000.00")),
        (date(2025, 6, 1), Decimal("15000.00")),
        (date(2025, 6, 30), Decimal("18000.00")),
    ):
        bs = await generate_balance_sheet(db, test_user.id, as_of_date=anchor_date, currency="SGD")
        assert bs["is_balanced"] is True
        assert next(a["amount"] for a in bs["assets"] if a["account_id"] == account.id) == expected_bal

    gap_equity = await get_or_create_unexplained_gap_equity_account(db, test_user.id, "SGD")
    assert await calculate_account_balance(db, gap_equity.id, test_user.id) == Decimal("3000.00")

    # 3. User uploads & approves February 2025 (opening 12,000, +1,200 net txns, closing 13,200)
    stmt_feb = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=account.id,
        institution="DBS",
        account_last4="8888",
        currency="SGD",
        opening_balance=Decimal("12000.00"),
        closing_balance=Decimal("13200.00"),
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
        status=BankStatementStatus.APPROVED,
    )
    db.add(stmt_feb)
    await db.flush()
    await submit_system_journal_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2025, 2, 15),
        memo="Feb salary",
        lines_data=[
            {"account_id": account.id, "direction": Direction.DEBIT, "amount": Decimal("1200.00"), "currency": "SGD"},
            {"account_id": income.id, "direction": Direction.CREDIT, "amount": Decimal("1200.00"), "currency": "SGD"},
        ],
        base_currency="SGD",
        operation="test-feb-txn",
    )
    await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=account.id)

    # Now (Jan, Feb) has 0 gap, and (Feb, Jun) has +1,800 gap! 3198 shrank from 3,000 to 1,800!
    assert await calculate_account_balance(db, gap_equity.id, test_user.id) == Decimal("1800.00")
    bs_feb = await generate_balance_sheet(db, test_user.id, as_of_date=date(2025, 2, 28), currency="SGD")
    assert bs_feb["is_balanced"] is True
    assert next(a["amount"] for a in bs_feb["assets"] if a["account_id"] == account.id) == Decimal("13200.00")
    bs_jun = await generate_balance_sheet(db, test_user.id, as_of_date=date(2025, 6, 30), currency="SGD")
    assert bs_jun["is_balanced"] is True
    assert next(a["amount"] for a in bs_jun["assets"] if a["account_id"] == account.id) == Decimal("18000.00")

    # 4. Retiring February preserves the June anchor (15,000 opening, 18,000 closing) cleanly
    await retire_statement(db, RetireStatementCommand(statement_id=stmt_feb.id, user_id=test_user.id))
    bs_jun_open = await generate_balance_sheet(db, test_user.id, as_of_date=date(2025, 6, 1), currency="SGD")
    assert bs_jun_open["is_balanced"] is True
    assert next(a["amount"] for a in bs_jun_open["assets"] if a["account_id"] == account.id) == Decimal("15000.00")
    assert await calculate_account_balance(db, account.id, test_user.id) == Decimal("18000.00")


def test_statement_chain_ssot_constants_and_effective_opening() -> None:
    """AC-extraction.posting.2: Cross-period gap constants and effective opening balance have one source (#2832)."""
    from src.extraction.extension import statement_posting, statement_validation
    from src.ledger import account_service

    assert not hasattr(statement_validation, "_get_opening_balance")
    assert (
        account_service.OPENING_BALANCE_EQUITY_CODE,
        account_service.UNEXPLAINED_GAP_EQUITY_CODE,
        statement_posting.account_service.CROSS_PERIOD_GAP_PLUG_TOLERANCE,
        statement_posting.account_service.CROSS_PERIOD_GAP_PLUG_EVENT_TYPE,
    ) == ("3199", "3198", Decimal("0.10"), "cross_period_gap_plug")
    stmt = StatementSummaryFactory.build(opening_balance=Decimal("100.00"), manual_opening_balance=None)
    assert stmt.effective_opening_balance() == Decimal("100.00")
    stmt.manual_opening_balance = Decimal("250.00")
    assert stmt.effective_opening_balance() == Decimal("250.00")


async def test_AC_extraction_2832_3_reconcile_chain_retirement_and_fx_plug_guards(db, test_user):
    """AC-extraction.2832.3: Cover retiring all statements on an account (voiding plugs and opening entries),
    retiring earlier S_0 to promote S_1, and foreign-currency gap plug FX rate resolution and error guards."""
    from uuid import uuid4

    from src.extraction.base.source_vocabulary import BankStatementStatus
    from src.extraction.extension.statement_posting import (
        reconcile_account_statement_chain,
        void_statement_posted_entries,
    )
    from src.pricing import PricingError

    # 1. Missing account returns False
    assert await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=uuid4()) is False

    # 2. Foreign currency account (USD) with 2 statements and a gap plug -> tests FX provider and default PricingError guard
    usd_acc = Account(user_id=test_user.id, name="USD Custody", type=AccountType.ASSET, currency="USD")
    db.add(usd_acc)
    await db.flush()

    s_usd_jan = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=usd_acc.id,
        institution="DBS",
        account_last4="1234",
        currency="USD",
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1000.00"),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        status=BankStatementStatus.APPROVED,
    )
    s_usd_mar = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=usd_acc.id,
        institution="DBS",
        account_last4="1234",
        currency="USD",
        opening_balance=Decimal("1500.00"),
        closing_balance=Decimal("1500.00"),
        period_start=date(2025, 3, 1),
        period_end=date(2025, 3, 31),
        status=BankStatementStatus.APPROVED,
    )
    db.add_all([s_usd_jan, s_usd_mar])
    await db.flush()

    # Provider succeeds for Jan 1 opening (call 1) and fails for Feb 28 plug (call 2)
    failing_plug_provider = AsyncMock(side_effect=[Decimal("1.35"), ValueError("No plug FX")])
    deps_fail = replace(
        compose_statement_posting_dependencies(),
        fx_rate_provider=failing_plug_provider,
        fx_rate_error=ValueError,
    )
    with pytest.raises(ValueError, match="FX rate required for cross-period gap plug in USD"):
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=usd_acc.id, dependencies=deps_fail)

    # Default get_exchange_rate fallback when dependencies=None and opening is already anchored
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "src.pricing.get_exchange_rate",
            AsyncMock(side_effect=PricingError("No rate")),
        )
        with pytest.raises(ValueError, match="FX rate required for cross-period gap plug in USD"):
            await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=usd_acc.id, dependencies=None)

    # Provider succeeds for plug creation
    ok_provider = AsyncMock(return_value=Decimal("1.35"))
    deps_ok = replace(
        compose_statement_posting_dependencies(),
        fx_rate_provider=ok_provider,
        fx_rate_error=ValueError,
    )
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=usd_acc.id, dependencies=deps_ok)
        is True
    )
    # Second call with identical chain keeps existing plug (lines 997-998, 1011) and returns False
    assert (
        await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=usd_acc.id, dependencies=deps_ok)
        is False
    )

    # 3. Base-currency account (SGD): retiring earliest statement promotes next statement, then retiring all statements voids plugs and opening entry
    sgd_acc = Account(user_id=test_user.id, name="SGD Custody", type=AccountType.ASSET, currency="SGD")
    db.add(sgd_acc)
    await db.flush()

    s_sgd_jan = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=sgd_acc.id,
        institution="DBS",
        account_last4="5678",
        currency="SGD",
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1000.00"),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        status=BankStatementStatus.APPROVED,
    )
    db.add(s_sgd_jan)
    await db.flush()
    assert await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=sgd_acc.id) is True

    # Retiring earliest statement (s_sgd_jan) and approving s_sgd_mar promotes s_sgd_mar via retired_at_existing check (lines 895-906)
    s_sgd_jan.status = BankStatementStatus.RETIRED
    s_sgd_mar = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=sgd_acc.id,
        institution="DBS",
        account_last4="5678",
        currency="SGD",
        opening_balance=Decimal("1500.00"),
        closing_balance=Decimal("1500.00"),
        period_start=date(2025, 3, 1),
        period_end=date(2025, 3, 31),
        status=BankStatementStatus.APPROVED,
    )
    s_sgd_may = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=sgd_acc.id,
        institution="DBS",
        account_last4="5678",
        currency="SGD",
        opening_balance=Decimal("2000.00"),
        closing_balance=Decimal("2000.00"),
        period_start=date(2025, 5, 1),
        period_end=date(2025, 5, 31),
        status=BankStatementStatus.APPROVED,
    )
    db.add_all([s_sgd_mar, s_sgd_may])
    await db.flush()
    assert await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=sgd_acc.id) is True

    # Retiring all statements voids remaining plugs and opening entry (lines 850-876)
    s_sgd_mar.status = BankStatementStatus.RETIRED
    s_sgd_may.status = BankStatementStatus.RETIRED
    await db.flush()
    assert await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=sgd_acc.id) is True

    # 4. void_statement_posted_entries with empty transactions returns 0
    assert await void_statement_posted_entries(db, s_sgd_mar, test_user.id) == 0


async def test_audit_completeness_reconcile_chain_lifecycle_and_manual_override_guards(db, test_user):
    """AC-extraction.2832.2: Verify the completeness gaps found in /audit:
    1) set_statement_opening_balance on an APPROVED statement re-runs reconcile_account_statement_chain and supersedes 3199/3198;
    2) reject_statement_workflow on a zero-transaction APPROVED statement re-runs reconcile_account_statement_chain;
    3) retiring or rejecting the earliest statement when a gap plug precedes the new earliest statement voids the obsolete plug
       before initialize_opening_positions checks for prior activity.
    """
    from src.extraction.base.source_vocabulary import BankStatementStatus
    from src.extraction.extension.statement_posting import reconcile_account_statement_chain
    from src.extraction.extension.statement_workflow import reject_statement_workflow
    from src.ledger import calculate_account_balance, list_opening_positions
    from src.ledger.extension.account_service import get_or_create_unexplained_gap_equity_account
    from src.routers import statements as statements_router
    from src.schemas.review import SetOpeningBalanceRequest

    acc = Account(user_id=test_user.id, name="OCBC 360", type=AccountType.ASSET, currency="SGD")
    db.add(acc)
    await db.flush()

    # (1) Approve statement with opening_balance=2000.00, manual_opening_balance=2500.00 -> anchors at 2500.00
    stmt_manual = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=acc.id,
        institution="OCBC",
        account_last4="1111",
        currency="SGD",
        opening_balance=Decimal("2000.00"),
        manual_opening_balance=Decimal("2500.00"),
        closing_balance=Decimal("2500.00"),
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        status=BankStatementStatus.APPROVED,
    )
    db.add(stmt_manual)
    await db.flush()
    assert await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=acc.id) is True
    assert await calculate_account_balance(db, acc.id, test_user.id) == Decimal("2500.00")

    # Updating manual_opening_balance on an APPROVED statement updates the 3199 anchor on the ledger
    await statements_router.set_statement_opening_balance(
        statement_id=stmt_manual.id,
        request=SetOpeningBalanceRequest(opening_balance=Decimal("3200.00")),
        db=db,
        user_id=test_user.id,
    )
    assert await calculate_account_balance(db, acc.id, test_user.id) == Decimal("3200.00")

    # (2) Rejecting a zero-transaction APPROVED statement voids its 3199 opening anchor via reconcile_account_statement_chain
    await reject_statement_workflow(db, stmt_manual.id, test_user.id, reason="Dormant statement rejected")
    assert await calculate_account_balance(db, acc.id, test_user.id) == Decimal("0.00")
    assert len(await list_opening_positions(db, user_id=test_user.id, as_of=date.max)) == 0

    # (3) Retiring the earliest statement (March) when a gap plug (2025-05-31) precedes the new earliest (June)
    stmt_mar = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=acc.id,
        institution="OCBC",
        account_last4="1111",
        currency="SGD",
        opening_balance=Decimal("4000.00"),
        closing_balance=Decimal("4000.00"),
        period_start=date(2025, 3, 1),
        period_end=date(2025, 3, 31),
        status=BankStatementStatus.APPROVED,
    )
    stmt_jun = StatementSummaryFactory.build(
        user_id=test_user.id,
        account_id=acc.id,
        institution="OCBC",
        account_last4="1111",
        currency="SGD",
        opening_balance=Decimal("5000.00"),
        closing_balance=Decimal("5000.00"),
        period_start=date(2025, 6, 1),
        period_end=date(2025, 6, 30),
        status=BankStatementStatus.APPROVED,
    )
    db.add_all([stmt_mar, stmt_jun])
    await db.flush()
    assert await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=acc.id) is True
    gap_eq = await get_or_create_unexplained_gap_equity_account(db, test_user.id, "SGD")
    assert await calculate_account_balance(db, gap_eq.id, test_user.id) == Decimal("1000.00")

    # Retire March -> June becomes earliest; obsolete plug on 2025-05-31 must be voided BEFORE June's 3199 anchor is posted
    stmt_mar.status = BankStatementStatus.RETIRED
    await db.flush()
    assert await reconcile_account_statement_chain(db, user_id=test_user.id, account_id=acc.id) is True
    assert await calculate_account_balance(db, gap_eq.id, test_user.id) == Decimal("0.00")
    assert await calculate_account_balance(db, acc.id, test_user.id) == Decimal("5000.00")
