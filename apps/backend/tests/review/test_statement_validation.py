from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.models import BankStatement, BankStatementStatus, BankStatementTransaction
from src.models.statement import Stage1Status
from src.services.statement_validation import (
    BALANCE_TOLERANCE,
    approve_statement,
    edit_and_approve,
    reject_statement,
    set_opening_balance,
    validate_balance_chain,
)


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
async def statement_with_transactions(db, user_id):
    stmt = BankStatement(
        id=uuid4(),
        user_id=user_id,
        file_path="test.pdf",
        file_hash="hash123",
        original_filename="test.pdf",
        institution="Test Bank",
        currency="USD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1100.00"),
        status=BankStatementStatus.PARSED,
    )
    db.add(stmt)
    await db.flush()

    txn1 = BankStatementTransaction(
        id=uuid4(),
        statement_id=stmt.id,
        txn_date=date(2024, 1, 15),
        description="Deposit",
        amount=Decimal("200.00"),
        direction="IN",
        status="pending",
        confidence="high",
    )
    txn2 = BankStatementTransaction(
        id=uuid4(),
        statement_id=stmt.id,
        txn_date=date(2024, 1, 20),
        description="Withdrawal",
        amount=Decimal("100.00"),
        direction="OUT",
        status="pending",
        confidence="high",
    )
    db.add_all([txn1, txn2])
    await db.flush()
    await db.refresh(stmt, ["transactions"])
    return stmt


class TestValidateBalanceChain:
    async def test_exact_match(self, db, statement_with_transactions):
        """AC1.1.1 Verify exact balance match when calculated closing matches stated closing."""
        result = await validate_balance_chain(db, statement_with_transactions.id)

        assert result["opening_match"] is True
        assert result["closing_match"] is True
        assert Decimal(result["closing_delta"]) == Decimal("0.00")
        assert result["calculated_closing"] == "1100.00"

    async def test_within_tolerance(self, db, user_id):
        """AC1.1.2 Verify balance match within the defined 0.01 tolerance."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="test.pdf",
            file_hash="hash456",
            original_filename="test.pdf",
            institution="Test Bank",
            currency="USD",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1100.01"),
            status=BankStatementStatus.PARSED,
        )
        db.add(stmt)
        await db.flush()

        txn = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt.id,
            txn_date=date(2024, 1, 15),
            description="Deposit",
            amount=Decimal("100.01"),
            direction="IN",
            status="pending",
            confidence="high",
        )
        db.add(txn)
        await db.flush()

        result = await validate_balance_chain(db, stmt.id)
        assert result["closing_match"] is True
        assert Decimal(result["closing_delta"]) <= BALANCE_TOLERANCE

    async def test_exceeds_tolerance(self, db, user_id):
        """AC1.1.3 Verify balance mismatch when delta exceeds the 0.01 tolerance."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="test.pdf",
            file_hash="hash789",
            original_filename="test.pdf",
            institution="Test Bank",
            currency="USD",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1100.02"),
            status=BankStatementStatus.PARSED,
        )
        db.add(stmt)
        await db.flush()

        txn = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt.id,
            txn_date=date(2024, 1, 15),
            description="Deposit",
            amount=Decimal("100.00"),
            direction="IN",
            status="pending",
            confidence="high",
        )
        db.add(txn)
        await db.flush()

        result = await validate_balance_chain(db, stmt.id)
        assert result["closing_match"] is False
        assert Decimal(result["closing_delta"]) > BALANCE_TOLERANCE

    async def test_manual_opening_balance(self, db, user_id):
        """AC1.1.4 Verify opening balance chain validation using manual override."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="test.pdf",
            file_hash="hash111",
            original_filename="test.pdf",
            institution="Test Bank",
            currency="USD",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            opening_balance=Decimal("0.00"),
            closing_balance=Decimal("150.00"),
            manual_opening_balance=Decimal("100.00"),
            status=BankStatementStatus.PARSED,
        )
        db.add(stmt)
        await db.flush()

        txn = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt.id,
            txn_date=date(2024, 1, 15),
            description="Deposit",
            amount=Decimal("50.00"),
            direction="IN",
            status="pending",
            confidence="high",
        )
        db.add(txn)
        await db.flush()

        result = await validate_balance_chain(db, stmt.id)
        assert result["opening_balance"] == "100.00"
        assert result["calculated_closing"] == "150.00"


class TestApproveStatement:
    async def test_approve_with_valid_balance(self, db, statement_with_transactions, user_id):
        """AC1.2.1 Approve statement when balance chain is valid."""
        stmt = await approve_statement(db, statement_with_transactions.id, user_id)

        assert stmt.stage1_status == Stage1Status.APPROVED
        assert stmt.status == BankStatementStatus.APPROVED
        assert stmt.balance_validation_result is not None
        assert stmt.balance_validation_result["closing_match"] is True

    async def test_approve_with_invalid_balance_raises(self, db, user_id):
        """AC1.2.2 Reject approval attempt when balance chain is invalid."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="test.pdf",
            file_hash="hash222",
            original_filename="test.pdf",
            institution="Test Bank",
            currency="USD",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("2000.00"),
            status=BankStatementStatus.PARSED,
        )
        db.add(stmt)
        await db.flush()

        txn = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt.id,
            txn_date=date(2024, 1, 15),
            description="Small deposit",
            amount=Decimal("10.00"),
            direction="IN",
            status="pending",
            confidence="high",
        )
        db.add(txn)
        await db.flush()

        with pytest.raises(ValueError, match="Balance mismatch"):
            await approve_statement(db, stmt.id, user_id)


class TestRejectStatement:
    async def test_reject_sets_status(self, db, statement_with_transactions, user_id):
        """AC1.3.1 Reject statement and update status."""
        stmt = await reject_statement(db, statement_with_transactions.id, user_id, reason="Test rejection")

        assert stmt.stage1_status == Stage1Status.REJECTED
        assert stmt.status == BankStatementStatus.REJECTED
        assert stmt.validation_error == "Test rejection"


class TestEditAndApprove:
    async def test_edit_and_approve(self, db, statement_with_transactions, user_id):
        """AC1.4.1 Edit transactions and approve statement in a single atomic action."""
        stmt = await edit_and_approve(
            db,
            statement_with_transactions.id,
            user_id,
            [],
        )

        assert stmt.stage1_status == Stage1Status.EDITED
        assert stmt.status == BankStatementStatus.APPROVED


class TestSetOpeningBalance:
    async def test_set_opening_balance(self, db, statement_with_transactions, user_id):
        """AC1.5.1 Set manual opening balance for a statement."""
        stmt = await set_opening_balance(
            db,
            statement_with_transactions.id,
            user_id,
            Decimal("500.00"),
        )

        assert stmt.manual_opening_balance == Decimal("500.00")
