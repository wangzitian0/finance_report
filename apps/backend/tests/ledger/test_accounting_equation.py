from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import (
    AccountType,
    Direction,
    JournalEntryStatus,
    ValidationError,
    calculate_account_balance,
    post_journal_entry,
    validate_journal_balance,
    verify_accounting_equation,
)
from tests.ledger._ledger_helpers import (
    create_anchored_test_journal_entry,
    lines_pair,
    make_account,
    make_entry,
    make_line,
)


@pytest.fixture
async def asset_account(db: AsyncSession, test_user_id):
    return await make_account(db, test_user_id, "Bank Account", AccountType.ASSET, commit=True, is_active=True)


@pytest.fixture
async def liability_account(db: AsyncSession, test_user_id):
    return await make_account(db, test_user_id, "Credit Card", AccountType.LIABILITY, commit=True, is_active=True)


@pytest.fixture
async def equity_account(db: AsyncSession, test_user_id):
    return await make_account(db, test_user_id, "Owner Capital", AccountType.EQUITY, commit=True, is_active=True)


@pytest.fixture
async def income_account(db: AsyncSession, test_user_id):
    return await make_account(db, test_user_id, "Salary Income", AccountType.INCOME, commit=True, is_active=True)


@pytest.fixture
async def expense_account(db: AsyncSession, test_user_id):
    return await make_account(db, test_user_id, "Food Expense", AccountType.EXPENSE, commit=True, is_active=True)


async def test_accounting_equation_violation_detected(db: AsyncSession, test_user_id, asset_account, income_account):
    await make_entry(
        db,
        test_user_id,
        [(asset_account.id, Direction.DEBIT, "5000.00"), (income_account.id, Direction.CREDIT, "5000.00")],
        memo="Valid salary entry",
        commit=True,
    )
    assert await verify_accounting_equation(db, test_user_id, base_currency="SGD") is True
    with pytest.raises(IntegrityError):
        await make_entry(
            db,
            test_user_id,
            [(asset_account.id, Direction.DEBIT, "1000.00"), (income_account.id, Direction.CREDIT, "999.00")],
            memo="Intentionally unbalanced entry",
            commit=True,
        )
    await db.rollback()
    assert await verify_accounting_equation(db, test_user_id, base_currency="SGD") is True


async def test_accounting_equation_holds_with_all_account_types(
    db: AsyncSession, test_user_id, asset_account, liability_account, equity_account, income_account, expense_account
):
    for debit_acc, credit_acc, amount in (
        (asset_account.id, equity_account.id, "10000"),
        (asset_account.id, income_account.id, "3000"),
        (expense_account.id, asset_account.id, "500"),
        (expense_account.id, liability_account.id, "200"),
    ):
        await make_entry(
            db,
            test_user_id,
            [(debit_acc, Direction.DEBIT, amount), (credit_acc, Direction.CREDIT, amount)],
            commit=True,
        )
    assert await verify_accounting_equation(db, test_user_id, base_currency="SGD") is True
    for acc, expected in (
        (asset_account, "12500"),
        (liability_account, "200"),
        (equity_account, "10000"),
        (income_account, "3000"),
        (expense_account, "700"),
    ):
        assert await calculate_account_balance(db, acc.id, test_user_id) == Decimal(expected)


async def test_posted_entry_cannot_be_reposted(db: AsyncSession, test_user_id, asset_account, income_account):
    entry = await create_anchored_test_journal_entry(
        db, test_user_id, date.today(), "Test entry", lines_pair(asset_account.id, income_account.id)
    )
    posted = await post_journal_entry(db, entry.id, test_user_id)
    assert posted.status == JournalEntryStatus.POSTED
    with pytest.raises(ValidationError, match="Can only post draft entries"):
        await post_journal_entry(db, entry.id, test_user_id)


@pytest.mark.parametrize(
    ("debit_amt", "credit_amt", "valid"),
    [
        ("999999999.99", "999999999.99", True),
        ("0.01", "0.01", True),
        ("100.01", "100.00", True),
        ("100.02", "100.00", False),
    ],
)
async def test_amount_boundaries_and_precision_tolerance(debit_amt, credit_amt, valid):
    lines = [make_line(Direction.DEBIT, debit_amt), make_line(Direction.CREDIT, credit_amt)]
    if valid:
        validate_journal_balance(lines)
    else:
        with pytest.raises(ValidationError, match="not balanced"):
            validate_journal_balance(lines)


async def test_many_lines_complex_salary_correct(db: AsyncSession, test_user_id):
    bank = await make_account(db, test_user_id, "Bank", AccountType.ASSET, is_active=True)
    cpf = await make_account(db, test_user_id, "CPF", AccountType.EXPENSE, is_active=True)
    tax = await make_account(db, test_user_id, "Tax", AccountType.EXPENSE, is_active=True)
    health = await make_account(db, test_user_id, "Health", AccountType.EXPENSE, is_active=True)
    salary = await make_account(db, test_user_id, "Salary", AccountType.INCOME, is_active=True)
    bonus = await make_account(db, test_user_id, "Bonus", AccountType.INCOME, is_active=True)
    await db.commit()
    lines_data = [
        {"account_id": acc.id, "direction": direction, "amount": Decimal(amt), "currency": "SGD"}
        for acc, direction, amt in (
            (bank, Direction.DEBIT, "3300.00"),
            (cpf, Direction.DEBIT, "1000.00"),
            (tax, Direction.DEBIT, "500.00"),
            (health, Direction.DEBIT, "200.00"),
            (salary, Direction.CREDIT, "4500.00"),
            (bonus, Direction.CREDIT, "500.00"),
        )
    ]
    entry = await create_anchored_test_journal_entry(db, test_user_id, date.today(), "Salary breakdown", lines_data)
    posted = await post_journal_entry(db, entry.id, test_user_id)
    assert posted.status == JournalEntryStatus.POSTED
    assert await verify_accounting_equation(db, test_user_id, base_currency="SGD") is True
    await db.refresh(posted, ["lines"])
    debits = sum((ln.amount for ln in posted.lines if ln.direction == Direction.DEBIT), Decimal("0"))
    credits = sum((ln.amount for ln in posted.lines if ln.direction == Direction.CREDIT), Decimal("0"))
    assert abs(debits - credits) == Decimal("0")
