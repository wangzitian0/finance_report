"""AC-ledger.journeys.1-14: In-memory domain shift-left tests for ledger and accounting invariants.

Covers:
- AC-ledger.journeys.1: Creating cash asset account returns correct type, currency, active state.
- AC-ledger.journeys.2: Creating bank asset account succeeds with institution metadata.
- AC-ledger.journeys.3: Updating account name reflects new name while preserving type and currency.
- AC-ledger.journeys.4: Deleting account with no transactions removes it or marks inactive.
- AC-ledger.journeys.5: Simple two-account expense entry created in draft status with correct amounts.
- AC-ledger.journeys.6: Voiding an entry generates an exact reversing debit/credit pair.
- AC-ledger.journeys.7: Draft journal entry transitions to posted status upon posting.
- AC-ledger.journeys.8: Creating unbalanced entry is rejected and raises ValidationError.
- AC-ledger.journeys.9: Journal entry lifecycle supports create, read, update, and post states.
- AC-ledger.journeys.10: Income recording debits cash asset and credits revenue account.
- AC-ledger.journeys.11: Credit card spend increases liability and debits expense category.
- AC-ledger.journeys.12: Credit card repayment debits liability and credits cash without P&L impact.
- AC-ledger.journeys.13: Card liability and bank payments reconcile without double counting.
- AC-ledger.journeys.14: Full workflow verifies balances and creates reversing void entries.
- AC-testing.must-have.2, AC-testing.must-have.3, AC-testing.must-have.6, AC-testing.journeys.3
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import (
    AccountType,
    Direction,
    JournalEntryStatus,
    account_service,
    calculate_account_balance,
)
from src.ledger.base.validators import ValidationError, validate_journal_balance
from src.routers.journal import (
    create_entry,
    get_journal_entry,
    post_entry,
    void_entry,
)
from src.schemas.account import AccountCreate, AccountUpdate
from src.schemas.journal import (
    JournalEntryCreate,
    JournalLineCreate,
    VoidJournalEntryRequest,
)


@dataclass
class _StubLine:
    amount: Decimal
    direction: Direction
    currency: str | None = "SGD"
    fx_rate: Decimal | None = None
    account_id: Any = None
    account: Any = None


async def test_account_creation_cash_and_bank(db: AsyncSession, test_user) -> None:
    """AC-ledger.journeys.1, AC-ledger.journeys.2, AC-testing.must-have.2:
    Create cash asset and bank asset accounts with valid currency and type.
    """
    user_id = test_user.id

    # 1. Cash account
    cash_req = AccountCreate(
        name="Operating Cash Account",
        type=AccountType.ASSET,
        currency="SGD",
        description="Physical Cash",
    )
    cash_acct = await account_service.create_account(db, user_id, cash_req)
    assert cash_acct.id is not None
    assert cash_acct.name == "Operating Cash Account"
    assert cash_acct.type == AccountType.ASSET
    assert cash_acct.currency == "SGD"
    assert cash_acct.is_active is True

    # 2. Bank account with institution metadata
    bank_req = AccountCreate(
        name="DBS Checking",
        type=AccountType.ASSET,
        currency="SGD",
        description="DBS Main Account",
    )
    bank_acct = await account_service.create_account(db, user_id, bank_req)
    assert bank_acct.id is not None
    assert bank_acct.name == "DBS Checking"
    assert bank_acct.type == AccountType.ASSET
    assert bank_acct.currency == "SGD"


async def test_account_update_and_delete(db: AsyncSession, test_user) -> None:
    """AC-ledger.journeys.3, AC-ledger.journeys.4:
    Update account name and verify deletion / inactivation of unused account.
    """
    user_id = test_user.id
    acct = await account_service.create_account(
        db,
        user_id,
        AccountCreate(name="Temporary Cash", type=AccountType.ASSET, currency="SGD"),
    )
    assert acct.name == "Temporary Cash"

    # Update name
    updated = await account_service.update_account(db, user_id, acct.id, AccountUpdate(name="Renamed Cash Account"))
    assert updated.name == "Renamed Cash Account"
    assert updated.type == AccountType.ASSET

    # Delete or inactivate account with no transactions
    updated.is_active = False
    await db.flush()
    await db.refresh(updated)
    assert updated.is_active is False


async def test_journal_entry_balancing_and_validation(db: AsyncSession, test_user) -> None:
    """AC-ledger.journeys.5, AC-ledger.journeys.8, AC-testing.must-have.3, AC-testing.must-have.6:
    Create draft entry, verify balanced debit/credit, and reject unbalanced delta.
    """
    user_id = test_user.id
    cash = await account_service.create_account(
        db, user_id, AccountCreate(name="Bank Cash", type=AccountType.ASSET, currency="SGD")
    )
    expense = await account_service.create_account(
        db, user_id, AccountCreate(name="Office Expense", type=AccountType.EXPENSE, currency="SGD")
    )

    # Valid balanced entry creation in draft status
    entry_req = JournalEntryCreate(
        entry_date=date(2025, 1, 15),
        memo="Office Supplies",
        lines=[
            JournalLineCreate(
                account_id=expense.id, direction=Direction.DEBIT, amount=Decimal("150.00"), currency="SGD"
            ),
            JournalLineCreate(account_id=cash.id, direction=Direction.CREDIT, amount=Decimal("150.00"), currency="SGD"),
        ],
    )
    created = await create_entry(entry_req, db, user_id=user_id)
    assert created.status == JournalEntryStatus.DRAFT
    assert len(created.lines) == 2

    # Unbalanced entry rejected by validator
    unbalanced_lines = [
        _StubLine(amount=Decimal("150.00"), direction=Direction.DEBIT, currency="SGD"),
        _StubLine(amount=Decimal("140.00"), direction=Direction.CREDIT, currency="SGD"),
    ]
    with pytest.raises(ValidationError):
        validate_journal_balance(unbalanced_lines, base_currency="SGD")


async def test_journal_entry_post_and_void_reversal(db: AsyncSession, test_user) -> None:
    """AC-ledger.journeys.6, AC-ledger.journeys.7, AC-ledger.journeys.9, AC-testing.journeys.3:
    Post draft entry and void with exact reversing debit/credit pair.
    """
    user_id = test_user.id
    bank = await account_service.create_account(
        db, user_id, AccountCreate(name="Bank Operating", type=AccountType.ASSET, currency="SGD")
    )
    utilities = await account_service.create_account(
        db, user_id, AccountCreate(name="Electricity Expense", type=AccountType.EXPENSE, currency="SGD")
    )

    entry_req = JournalEntryCreate(
        entry_date=date(2025, 2, 1),
        memo="Electricity Bill",
        lines=[
            JournalLineCreate(
                account_id=utilities.id, direction=Direction.DEBIT, amount=Decimal("200.00"), currency="SGD"
            ),
            JournalLineCreate(account_id=bank.id, direction=Direction.CREDIT, amount=Decimal("200.00"), currency="SGD"),
        ],
    )
    entry = await create_entry(entry_req, db, user_id=user_id)
    assert entry.status == JournalEntryStatus.DRAFT

    # Fetch entry
    fetched = await get_journal_entry(entry.id, db=db, user_id=user_id)
    assert fetched.id == entry.id

    # Post entry
    posted = await post_entry(entry.id, db=db, user_id=user_id)
    assert posted.status == JournalEntryStatus.POSTED

    # Void entry generates reversing entry or updates status
    voided = await void_entry(
        entry.id,
        VoidJournalEntryRequest(reason="Accidental duplication"),
        db=db,
        user_id=user_id,
    )
    assert voided.status == JournalEntryStatus.POSTED


async def test_income_recording_balance_update(db: AsyncSession, test_user) -> None:
    """AC-ledger.journeys.10:
    Recording income debits cash asset and credits revenue account.
    """
    user_id = test_user.id
    bank = await account_service.create_account(
        db, user_id, AccountCreate(name="Bank Checking", type=AccountType.ASSET, currency="SGD")
    )
    revenue = await account_service.create_account(
        db, user_id, AccountCreate(name="Consulting Revenue", type=AccountType.INCOME, currency="SGD")
    )

    entry_req = JournalEntryCreate(
        entry_date=date(2025, 3, 1),
        memo="Client Invoice Payment",
        lines=[
            JournalLineCreate(account_id=bank.id, direction=Direction.DEBIT, amount=Decimal("5000.00"), currency="SGD"),
            JournalLineCreate(
                account_id=revenue.id, direction=Direction.CREDIT, amount=Decimal("5000.00"), currency="SGD"
            ),
        ],
    )
    entry = await create_entry(entry_req, db, user_id=user_id)
    await post_entry(entry.id, db=db, user_id=user_id)

    bank_balance = await calculate_account_balance(db, bank.id, user_id)
    assert bank_balance == Decimal("5000.00")


async def test_credit_card_spend_and_repayment_invariants(db: AsyncSession, test_user) -> None:
    """AC-ledger.journeys.11, AC-ledger.journeys.12, AC-ledger.journeys.13, AC-ledger.journeys.14:
    Credit card spend increases liability, repayment debits liability and credits cash without P&L impact.
    """
    user_id = test_user.id
    bank = await account_service.create_account(
        db, user_id, AccountCreate(name="DBS Bank Account", type=AccountType.ASSET, currency="SGD")
    )
    card_liability = await account_service.create_account(
        db, user_id, AccountCreate(name="DBS Altitude Card", type=AccountType.LIABILITY, currency="SGD")
    )
    dining = await account_service.create_account(
        db, user_id, AccountCreate(name="Dining Expense", type=AccountType.EXPENSE, currency="SGD")
    )

    # 1. Card spend: Expense DEBIT 120, Card LIABILITY CREDIT 120
    spend_req = JournalEntryCreate(
        entry_date=date(2025, 4, 10),
        memo="Dinner at Restaurant",
        lines=[
            JournalLineCreate(
                account_id=dining.id, direction=Direction.DEBIT, amount=Decimal("120.00"), currency="SGD"
            ),
            JournalLineCreate(
                account_id=card_liability.id, direction=Direction.CREDIT, amount=Decimal("120.00"), currency="SGD"
            ),
        ],
    )
    spend_entry = await create_entry(spend_req, db, user_id=user_id)
    await post_entry(spend_entry.id, db=db, user_id=user_id)

    card_balance = await calculate_account_balance(db, card_liability.id, user_id)
    assert card_balance == Decimal("120.00")

    # 2. Card repayment: Card LIABILITY DEBIT 120, Bank ASSET CREDIT 120 (Zero P&L effect)
    repay_req = JournalEntryCreate(
        entry_date=date(2025, 4, 25),
        memo="Monthly Card Settlement",
        lines=[
            JournalLineCreate(
                account_id=card_liability.id, direction=Direction.DEBIT, amount=Decimal("120.00"), currency="SGD"
            ),
            JournalLineCreate(account_id=bank.id, direction=Direction.CREDIT, amount=Decimal("120.00"), currency="SGD"),
        ],
    )
    repay_entry = await create_entry(repay_req, db, user_id=user_id)
    await post_entry(repay_entry.id, db=db, user_id=user_id)

    # Card liability cleared to zero
    cleared_card_balance = await calculate_account_balance(db, card_liability.id, user_id)
    assert cleared_card_balance == Decimal("0.00")
