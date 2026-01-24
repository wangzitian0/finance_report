"""Tests for test data factories.

Validates that factories produce correct, balanced, and valid test data.
"""

from decimal import Decimal
from uuid import UUID

import pytest

from src.models.account import AccountType
from src.models.journal import Direction, JournalEntryStatus
from src.models.reconciliation import ReconciliationStatus
from src.models.statement import BankStatementStatus
from tests.factories import (
    AccountFactory,
    BankStatementFactory,
    BankStatementTransactionFactory,
    JournalEntryFactory,
    ReconciliationMatchFactory,
    UserFactory,
)


@pytest.mark.asyncio
class TestAccountFactory:
    async def test_create_async_basic(self, db, test_user):
        account = await AccountFactory.create_async(db, user_id=test_user.id)

        assert account.id is not None
        assert account.user_id == test_user.id
        assert account.name.startswith("Account")
        assert account.currency == "SGD"
        assert account.type in AccountType

    async def test_create_async_with_overrides(self, db, test_user):
        account = await AccountFactory.create_async(
            db, user_id=test_user.id, name="Custom Cash Account", currency="USD", type=AccountType.ASSET
        )

        assert account.name == "Custom Cash Account"
        assert account.currency == "USD"
        assert account.type == AccountType.ASSET

    async def test_factory_respects_user_id(self, db, test_user):
        from tests.factories import UserFactory

        another_user = await UserFactory.create_async(db)

        account = await AccountFactory.create_async(db, user_id=test_user.id)

        assert account.user_id == test_user.id
        assert account.user_id != another_user.id


@pytest.mark.asyncio
class TestJournalEntryFactory:
    async def test_create_balanced_async_actually_balances(self, db, test_user):
        entry, debit_acc, credit_acc = await JournalEntryFactory.create_balanced_async(
            db, user_id=test_user.id, amount=Decimal("123.45")
        )

        await db.refresh(entry, ["lines"])
        lines = entry.lines

        assert len(lines) == 2, "Balanced entry should have exactly 2 lines"

        debit_lines = [line for line in lines if line.direction == Direction.DEBIT]
        credit_lines = [line for line in lines if line.direction == Direction.CREDIT]

        assert len(debit_lines) == 1, "Should have exactly 1 debit line"
        assert len(credit_lines) == 1, "Should have exactly 1 credit line"

        debit_sum = sum(line.amount for line in debit_lines)
        credit_sum = sum(line.amount for line in credit_lines)

        assert debit_sum == Decimal("123.45"), f"Debit sum {debit_sum} != 123.45"
        assert credit_sum == Decimal("123.45"), f"Credit sum {credit_sum} != 123.45"
        assert debit_sum == credit_sum, "Entry is unbalanced"

    async def test_create_balanced_returns_correct_types(self, db, test_user):
        entry, debit_acc, credit_acc = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)

        from src.models.account import Account
        from src.models.journal import JournalEntry

        assert isinstance(entry, JournalEntry)
        assert isinstance(debit_acc, Account)
        assert isinstance(credit_acc, Account)

        assert debit_acc.user_id == test_user.id
        assert credit_acc.user_id == test_user.id

    async def test_create_balanced_with_custom_memo(self, db, test_user):
        custom_memo = "Test Transaction - Salary Payment"
        entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id, memo=custom_memo)

        assert entry.memo == custom_memo

    async def test_entry_has_valid_status(self, db, test_user):
        entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)

        assert entry.status in JournalEntryStatus


@pytest.mark.asyncio
class TestUserFactory:
    async def test_create_async_generates_unique_emails(self, db):
        user1 = await UserFactory.create_async(db)
        user2 = await UserFactory.create_async(db)

        assert user1.email != user2.email
        assert "@example.com" in user1.email
        assert "@example.com" in user2.email

    async def test_user_has_valid_id(self, db):
        user = await UserFactory.create_async(db)

        assert isinstance(user.id, UUID)


@pytest.mark.asyncio
class TestBankStatementFactory:
    async def test_create_async_valid_statement(self, db, test_user):
        statement = await BankStatementFactory.create_async(db, user_id=test_user.id)

        assert statement.user_id == test_user.id
        assert statement.status in BankStatementStatus
        assert statement.institution is not None
        assert statement.account_last4 is not None

    async def test_statement_has_file_path(self, db, test_user):
        statement = await BankStatementFactory.create_async(db, user_id=test_user.id)

        assert statement.file_path is not None
        assert isinstance(statement.file_path, str)


@pytest.mark.asyncio
class TestBankStatementTransactionFactory:
    async def test_create_async_valid_transaction(self, db, test_user):
        statement = await BankStatementFactory.create_async(db, user_id=test_user.id)

        transaction = await BankStatementTransactionFactory.create_async(db, statement_id=statement.id)

        assert transaction.statement_id == statement.id
        assert transaction.amount is not None
        assert isinstance(transaction.amount, Decimal)


@pytest.mark.asyncio
class TestReconciliationMatchFactory:
    async def test_create_async_valid_match(self, db, test_user):
        statement = await BankStatementFactory.create_async(db, user_id=test_user.id)
        stmt_txn = await BankStatementTransactionFactory.create_async(db, statement_id=statement.id)
        entry, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)

        match = await ReconciliationMatchFactory.create_async(
            db, bank_txn_id=stmt_txn.id, journal_entry_ids=[str(entry.id)]
        )

        assert match.bank_txn_id == stmt_txn.id
        assert str(entry.id) in match.journal_entry_ids
        assert match.status in ReconciliationStatus
        assert 0 <= match.match_score <= 100


@pytest.mark.asyncio
class TestFactoryIsolation:
    async def test_factories_dont_interfere(self, db, test_user):
        account1 = await AccountFactory.create_async(db, user_id=test_user.id)
        entry1, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)
        account2 = await AccountFactory.create_async(db, user_id=test_user.id)
        entry2, _, _ = await JournalEntryFactory.create_balanced_async(db, user_id=test_user.id)

        assert account1.id != account2.id
        assert entry1.id != entry2.id

        assert account1.user_id == test_user.id
        assert account2.user_id == test_user.id
        assert entry1.user_id == test_user.id
        assert entry2.user_id == test_user.id
