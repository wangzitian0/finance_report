"""Per-node confidence tier on balance-sheet payloads (EPIC-005 AC5.18, issue #913).

Axiom B: confidence is a first-class, measured property. Each balance-sheet line
carries the confidence tier of its contributing ledger facts, and an aggregate
(Net Worth) rolls up to the *worst-input* tier — a defined rollup, not an
invented number.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.reporting import generate_balance_sheet


async def _post(db, user_id, *, debit: Account, credit: Account, amount: Decimal, source_type) -> None:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 1, 15),
        memo="bs confidence",
        source_type=source_type,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id, account_id=debit.id, direction=Direction.DEBIT, amount=amount, currency="SGD"
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency="SGD",
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_AC5_18_1_lines_carry_worst_input_confidence_tier(db, test_user):
    """AC-reporting.confidence.1: AC5.18.1: A line's tier is the worst confidence tier among its contributing entries."""
    cash = Account(user_id=test_user.id, name="Cash A", type=AccountType.ASSET, currency="SGD")
    savings = Account(user_id=test_user.id, name="Savings B", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, savings, salary])
    await db.flush()

    # Cash A built from a manual (TRUSTED) and an auto_parsed (LOW) entry -> worst is LOW.
    await _post(
        db, test_user.id, debit=cash, credit=salary, amount=Decimal("100.00"), source_type=JournalEntrySourceType.MANUAL
    )
    await _post(
        db,
        test_user.id,
        debit=cash,
        credit=salary,
        amount=Decimal("50.00"),
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    # Savings B built only from a user_confirmed (HIGH) entry.
    await _post(
        db,
        test_user.id,
        debit=savings,
        credit=salary,
        amount=Decimal("200.00"),
        source_type=JournalEntrySourceType.USER_CONFIRMED,
    )

    report = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))

    lines = {line["name"]: line for line in report["assets"]}
    assert lines["Cash A"]["confidence_tier"] == "LOW"
    assert lines["Savings B"]["confidence_tier"] == "HIGH"


@pytest.mark.asyncio
async def test_AC5_18_2_net_worth_rolls_up_to_worst_input_tier(db, test_user):
    """AC-reporting.confidence.2: AC5.18.2: The balance-sheet aggregate tier is the worst tier across its lines; None when there is nothing to rate."""
    empty = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))
    assert empty["confidence_tier"] is None
    assert empty["assets"] == []

    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    invest = Account(user_id=test_user.id, name="Brokerage", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, invest, salary])
    await db.flush()

    # One HIGH line and one LOW line -> aggregate is the worst (LOW).
    await _post(
        db,
        test_user.id,
        debit=cash,
        credit=salary,
        amount=Decimal("100.00"),
        source_type=JournalEntrySourceType.USER_CONFIRMED,
    )
    await _post(
        db,
        test_user.id,
        debit=invest,
        credit=salary,
        amount=Decimal("100.00"),
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )

    report = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))
    assert report["confidence_tier"] == "LOW"


@pytest.mark.asyncio
async def test_include_trust_signals_false_skips_tier_and_provenance(db, test_user):
    """Audit review (perf): callers that don't render badges can skip the two extra scans.

    The net-worth time series and the income statement's internal balance sheets pass
    include_trust_signals=False so they don't amplify the per-account ledger scans.
    """
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, salary])
    await db.flush()
    await _post(
        db, test_user.id, debit=cash, credit=salary, amount=Decimal("100.00"), source_type=JournalEntrySourceType.MANUAL
    )

    report = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31), include_trust_signals=False)

    assert report["confidence_tier"] is None
    assert all(line["confidence_tier"] is None and line["provenance"] is None for line in report["assets"])


@pytest.mark.asyncio
async def test_balance_sheet_aggregate_provenance_is_populated(db, test_user):
    """Audit review: the aggregate provenance is exposed on the payload, not always None (#938 gap)."""
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, salary])
    await db.flush()
    await _post(
        db,
        test_user.id,
        debit=cash,
        credit=salary,
        amount=Decimal("100.00"),
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    single = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))
    assert single["provenance"] == "imported"

    wallet = Account(user_id=test_user.id, name="Wallet", type=AccountType.ASSET, currency="SGD")
    db.add(wallet)
    await db.flush()
    await _post(
        db,
        test_user.id,
        debit=wallet,
        credit=salary,
        amount=Decimal("50.00"),
        source_type=JournalEntrySourceType.MANUAL,
    )
    mixed = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31))
    assert mixed["provenance"] == "derived"
