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
    get_pending_stage1_review,
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
        """AC1.1.2 Verify balance match within the defined 0.001 tolerance."""
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
            closing_balance=Decimal("1100.0009"),
            status=BankStatementStatus.PARSED,
        )
        db.add(stmt)
        await db.flush()

        txn = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt.id,
            txn_date=date(2024, 1, 15),
            description="Deposit",
            amount=Decimal("100.0009"),
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
        """AC1.1.3 Verify balance mismatch when delta exceeds the 0.001 tolerance."""
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


class TestGetPendingStage1Review:
    async def test_returns_parsed_statements(self, db, user_id):
        """AC1.6.1 get_pending_stage1_review returns PARSED statements with null/PENDING stage1_status."""
        # PARSED with no stage1_status (null) -> should be returned
        stmt_pending = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="pending.pdf",
            file_hash="hash_pend",
            original_filename="pending.pdf",
            institution="Test Bank",
            currency="USD",
            status=BankStatementStatus.PARSED,
        )
        # PARSED with stage1_status=PENDING_REVIEW -> should be returned
        stmt_review = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="review.pdf",
            file_hash="hash_review",
            original_filename="review.pdf",
            institution="Test Bank",
            currency="USD",
            status=BankStatementStatus.PARSED,
            stage1_status=Stage1Status.PENDING_REVIEW,
        )
        # APPROVED -> should NOT be returned
        stmt_approved = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="approved.pdf",
            file_hash="hash_approved",
            original_filename="approved.pdf",
            institution="Test Bank",
            currency="USD",
            status=BankStatementStatus.APPROVED,
            stage1_status=Stage1Status.APPROVED,
        )
        db.add_all([stmt_pending, stmt_review, stmt_approved])
        await db.flush()

        result = await get_pending_stage1_review(db, user_id)
        ids = {s.id for s in result}
        assert stmt_pending.id in ids
        assert stmt_review.id in ids
        assert stmt_approved.id not in ids

    async def test_returns_empty_when_none_pending(self, db, user_id):
        """AC1.6.2 get_pending_stage1_review returns empty when no pending statements."""
        result = await get_pending_stage1_review(db, user_id)
        assert result == []


class TestValidateBalanceChainEdgeCases:
    async def test_statement_not_found_raises(self, db):
        """AC16.3.1 validate_balance_chain raises ValueError when statement not found."""
        non_existent_id = uuid4()
        with pytest.raises(ValueError, match="Statement not found"):
            await validate_balance_chain(db, non_existent_id)

    async def test_opening_balance_from_statement_when_no_manual_no_prev(self, db, user_id):
        """AC16.3.2 _get_opening_balance falls back to opening_balance when no prev statement."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="test.pdf",
            file_hash="hash_no_prev",
            original_filename="test.pdf",
            institution="Test Bank",
            currency="USD",
            period_start=date(2024, 3, 1),
            period_end=date(2024, 3, 31),
            opening_balance=Decimal("500.00"),
            closing_balance=Decimal("700.00"),
            status=BankStatementStatus.PARSED,
        )
        db.add(stmt)
        txn = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt.id,
            txn_date=date(2024, 3, 15),
            description="Deposit",
            amount=Decimal("200.00"),
            direction="IN",
            status="pending",
            confidence="high",
        )
        db.add(txn)
        await db.flush()

        result = await validate_balance_chain(db, stmt.id)
        # No prev statement, falls back to opening_balance
        assert result["opening_balance"] == "500.00"
        assert result["closing_match"] is True

    async def test_opening_balance_from_prev_statement(self, db, user_id):
        """AC16.3.3 _get_opening_balance uses prev statement closing_balance when available."""
        prev_stmt = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="prev.pdf",
            file_hash="hash_prev_old",
            original_filename="prev.pdf",
            institution="Test Bank",
            currency="USD",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1200.00"),
            status=BankStatementStatus.APPROVED,
        )
        db.add(prev_stmt)
        await db.flush()

        curr_stmt = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="curr.pdf",
            file_hash="hash_curr_new",
            original_filename="curr.pdf",
            institution="Test Bank",
            currency="USD",
            period_start=date(2024, 2, 1),
            period_end=date(2024, 2, 29),
            opening_balance=Decimal("999.00"),
            closing_balance=Decimal("1350.00"),
            status=BankStatementStatus.PARSED,
        )
        db.add(curr_stmt)
        txn = BankStatementTransaction(
            id=uuid4(),
            statement_id=curr_stmt.id,
            txn_date=date(2024, 2, 15),
            description="Transfer",
            amount=Decimal("150.00"),
            direction="IN",
            status="pending",
            confidence="high",
        )
        db.add(txn)
        await db.flush()

        result = await validate_balance_chain(db, curr_stmt.id)
        # Opening balance comes from prev stmt closing_balance (1200.00)
        assert result["opening_balance"] == "1200.00"
        assert result["calculated_closing"] == "1350.00"
        assert result["closing_match"] is True

    async def test_get_statement_for_update_wrong_user_raises(self, db, user_id, statement_with_transactions):
        """AC16.3.6 _get_statement_for_update raises ValueError when called with wrong user_id."""
        wrong_user_id = uuid4()
        with pytest.raises(ValueError, match="Statement not found or access denied"):
            await approve_statement(db, statement_with_transactions.id, wrong_user_id)


class TestRejectStatementEdgeCases:
    async def test_reject_without_reason(self, db, statement_with_transactions, user_id):
        """AC16.3.4 reject_statement without reason does not set validation_error."""
        stmt = await reject_statement(db, statement_with_transactions.id, user_id)

        assert stmt.stage1_status == Stage1Status.REJECTED
        assert stmt.status == BankStatementStatus.REJECTED
        assert stmt.validation_error is None


class TestEditAndApproveEdgeCases:
    async def test_edit_transaction_fields(self, db, user_id):
        """AC16.3.5 edit_and_approve edits transaction fields and recalculates balance."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="edit_test.pdf",
            file_hash="hash_edit_ok",
            original_filename="edit_test.pdf",
            institution="Test Bank",
            currency="USD",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1100.00"),
            status=BankStatementStatus.PARSED,
        )
        db.add(stmt)
        txn_id = uuid4()
        txn = BankStatementTransaction(
            id=txn_id,
            statement_id=stmt.id,
            txn_date=date(2024, 1, 15),
            description="Old desc",
            amount=Decimal("50.00"),
            direction="IN",
            status="pending",
            confidence="high",
        )
        db.add(txn)
        await db.flush()
        edits = [
            {
                "txn_id": str(txn_id),
                "amount": "100.00",
                "description": "Updated Deposit",
                "direction": "IN",
            }
        ]
        updated_stmt = await edit_and_approve(db, stmt.id, user_id, edits)
        assert updated_stmt.stage1_status == Stage1Status.EDITED
        assert updated_stmt.status == BankStatementStatus.APPROVED

    async def test_edit_and_approve_still_invalid_raises(self, db, user_id):
        """AC16.3.5 edit_and_approve raises ValueError when balance still invalid after edits."""
        stmt = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="test.pdf",
            file_hash="hash_edit_fail",
            original_filename="test.pdf",
            institution="Test Bank",
            currency="USD",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("5000.00"),
            status=BankStatementStatus.PARSED,
        )
        db.add(stmt)
        txn = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt.id,
            txn_date=date(2024, 1, 15),
            description="Small",
            amount=Decimal("10.00"),
            direction="IN",
            status="pending",
            confidence="high",
        )
        db.add(txn)
        await db.flush()

        with pytest.raises(ValueError, match="Balance still invalid after edits"):
            await edit_and_approve(db, stmt.id, user_id, [])