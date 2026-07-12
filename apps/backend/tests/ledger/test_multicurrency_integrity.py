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
    validate_journal_balance,
    verify_accounting_equation,
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

    assert await verify_accounting_equation(db, user_id) is True
