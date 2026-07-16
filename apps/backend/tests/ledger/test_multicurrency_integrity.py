"""AC2.12: Multi-currency ledger integrity tests."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ValidationError,
    create_journal_entry,
    post_journal_entry,
    validate_journal_balance,
    verify_accounting_equation,
    void_journal_entry,
)


def test_AC2_12_1_multicurrency_entry_balances_in_base_currency(ac_evidence):
    """AC-ledger.12.1: Multi-currency journal validation balances converted base amounts."""
    bank_usd = JournalLine(
        account_id=uuid4(),
        direction=Direction.DEBIT,
        amount=Decimal("100.00"),
        currency="USD",
        fx_rate=Decimal("1.350000"),
    )
    equity_sgd = JournalLine(
        account_id=uuid4(),
        direction=Direction.CREDIT,
        amount=Decimal("135.00"),
        currency="SGD",
    )

    # 100.00 USD @ 1.35 == 135.00 SGD: the converted debit must equal the SGD credit.
    converted_debit = bank_usd.amount * bank_usd.fx_rate
    assert converted_debit == equity_sgd.amount == Decimal("135.00")
    validate_journal_balance([bank_usd, equity_sgd])

    understated_credit = JournalLine(
        account_id=uuid4(),
        direction=Direction.CREDIT,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    with pytest.raises(ValidationError):
        validate_journal_balance([bank_usd, understated_credit])

    # Behavioral evidence: the converted base amount equals the golden 135.00 SGD;
    # a wrong fx multiply or a missing conversion would not land on this number.
    ac_evidence(
        ac_id="AC-ledger.12.1",
        score=1.0,
        metric="usd_to_sgd_converted_base_amount_match",
        comment="100.00 USD @ 1.35 == 135.00 SGD converted base amount (deterministic)",
        provenance="deterministic",
    )


def test_explicit_usd_base_resolves_omitted_line_currency_without_env_fallback() -> None:
    debit = JournalLine(
        account_id=uuid4(),
        direction=Direction.DEBIT,
        amount=Decimal("100.00"),
        currency=None,
    )
    credit = JournalLine(
        account_id=uuid4(),
        direction=Direction.CREDIT,
        amount=Decimal("100.00"),
        currency="USD",
    )

    validate_journal_balance([debit, credit], base_currency="USD")


async def test_AC2_12_2_accounting_equation_uses_base_currency_balances(db: AsyncSession, test_user):
    """AC-ledger.12.2: Accounting equation verification uses base-currency converted balances."""
    user_id = test_user.id
    usd_asset = Account(user_id=user_id, name="USD Bank", type=AccountType.ASSET, currency="USD")
    equity = Account(user_id=user_id, name="Opening Equity", type=AccountType.EQUITY, currency="SGD")
    db.add_all([usd_asset, equity])
    await db.flush()

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 1, 1),
        memo="USD opening balance",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_asset.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
                fx_rate=Decimal("1.350000"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("135.00"),
                currency="SGD",
            ),
        ]
    )
    await db.flush()

    assert await verify_accounting_equation(db, user_id, base_currency="SGD") is True


async def test_effective_usd_base_drives_posting_trigger_and_equation(db: AsyncSession, test_user) -> None:
    """AC-ledger.signature.4: operation currency reaches Python and PostgreSQL invariants."""
    user_id = test_user.id
    usd_asset = Account(user_id=user_id, name="USD Cash", type=AccountType.ASSET, currency="USD")
    usd_equity = Account(user_id=user_id, name="USD Equity", type=AccountType.EQUITY, currency="USD")
    db.add_all([usd_asset, usd_equity])
    await db.flush()

    entry = await create_journal_entry(
        db,
        user_id,
        entry_date=date(2026, 1, 1),
        memo="USD base entry",
        lines_data=[
            {
                "account_id": usd_asset.id,
                "direction": Direction.DEBIT,
                "amount": Decimal("100.00"),
                "currency": "USD",
            },
            {
                "account_id": usd_equity.id,
                "direction": Direction.CREDIT,
                "amount": Decimal("100.00"),
                "currency": "USD",
            },
        ],
        base_currency="USD",
    )
    posted = await post_journal_entry(db, entry.id, user_id, base_currency="USD")
    assert posted.status == JournalEntryStatus.POSTED
    posted_id = posted.id
    await db.commit()

    reversal = await void_journal_entry(
        db,
        posted_id,
        "USD correction",
        user_id,
        base_currency="USD",
    )
    await db.commit()
    assert reversal.status == JournalEntryStatus.POSTED
    assert {line.currency for line in reversal.lines} == {"USD"}
    assert await verify_accounting_equation(db, user_id, base_currency="USD") is True

    with pytest.raises(ValidationError, match="fx_rate required"):
        await verify_accounting_equation(db, user_id, base_currency="SGD")


async def test_void_preserves_historical_base_after_effective_currency_change(db: AsyncSession, test_user) -> None:
    """AC-ledger.3.12: reversal uses the posted entry's historical currency basis."""
    user_id = test_user.id
    sgd_asset = Account(user_id=user_id, name="Historical SGD Cash", type=AccountType.ASSET, currency="SGD")
    sgd_equity = Account(
        user_id=user_id,
        name="Historical SGD Equity",
        type=AccountType.EQUITY,
        currency="SGD",
    )
    db.add_all([sgd_asset, sgd_equity])
    await db.flush()

    entry = await create_journal_entry(
        db,
        user_id,
        entry_date=date(2026, 1, 1),
        memo="Historical SGD entry",
        lines_data=[
            {
                "account_id": sgd_asset.id,
                "direction": Direction.DEBIT,
                "amount": Decimal("100.00"),
                "currency": "SGD",
            },
            {
                "account_id": sgd_equity.id,
                "direction": Direction.CREDIT,
                "amount": Decimal("100.00"),
                "currency": "SGD",
            },
        ],
        base_currency="SGD",
    )
    await post_journal_entry(db, entry.id, user_id, base_currency="SGD")
    entry_id = entry.id
    await db.commit()

    reversal = await void_journal_entry(
        db,
        entry_id,
        "Correction after base change",
        user_id,
        base_currency="USD",
    )
    await db.commit()

    assert reversal.status == JournalEntryStatus.POSTED
    assert {line.currency for line in reversal.lines} == {"SGD"}
