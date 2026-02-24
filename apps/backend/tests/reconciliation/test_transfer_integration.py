"""Integration tests for Processing account transfer detection during reconciliation.

Tests the three-phase reconciliation flow:
1. Phase 1: Transfer Detection (BEFORE normal matching)
2. Phase 2: Normal Matching (existing logic)
3. Phase 3: Auto-Pair Transfers (AFTER all matching)

See: docs/ssot/processing_account.md Section 7 (Integration Points)
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementTransaction,
    BankTransactionStatus,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.account_service import get_or_create_processing_account
from src.services.reconciliation import execute_matching


class TestTransferDetectionDuringReconciliation:
    """Test Phase 1: Transfer detection with Processing account during reconciliation."""

    @pytest.mark.asyncio
    async def test_transfer_detected_creates_processing_entry(self, db: AsyncSession, test_user):
        """Transfer detection creates Processing account entry with linked account."""
        user_id = test_user.id

        # Setup: Cash account
        cash = Account(
            user_id=user_id,
            name="Cash",
            code="1001",
            type=AccountType.ASSET,
            currency="SGD",
        )
        db.add(cash)
        await db.flush()

        # Create bank statement with linked account
        statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/test.pdf",
            file_hash="test_hash_transfer_1",
            original_filename="test.pdf",
            institution="TestBank",
            account_id=cash.id,  # Link statement to Cash account
        )
        db.add(statement)
        await db.flush()

        # Create transfer transaction (OUT)
        txn = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date.today(),
            description="TRANSFER TO SAVINGS ACCOUNT",
            amount=Decimal("200.00"),
            direction="OUT",
            status=BankTransactionStatus.PENDING,
        )
        db.add(txn)
        await db.flush()

        # Execute reconciliation
        matches = await execute_matching(db, user_id=user_id, statement_id=statement.id)

        # Verify: Transfer detected and Processing entry created
        assert len(matches) == 1
        match = matches[0]
        assert match.match_score == 100  # Transfer detection = exact match
        assert len(match.journal_entry_ids) == 1
        entry_id = UUID(match.journal_entry_ids[0])
        # Verify: Journal entry exists
        entry_result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry_id))
        entry = entry_result.scalar_one()
        assert entry.source_type == JournalEntrySourceType.SYSTEM
        assert entry.status == JournalEntryStatus.RECONCILED  # Entry status updated to RECONCILED after matching
        assert "Transfer OUT" in entry.memo or "TRANSFER TO" in entry.memo

        # Verify: Processing account has DEBIT line (transfer OUT)
        processing = await get_or_create_processing_account(db, user_id)
        lines_result = await db.execute(
            select(JournalLine).where(
                JournalLine.journal_entry_id == entry.id,
                JournalLine.account_id == processing.id,
            )
        )
        processing_line = lines_result.scalar_one()
        assert processing_line.direction.value == "DEBIT"
        assert processing_line.amount == Decimal("200.00")

        # Verify: Cash account has CREDIT line (funds leave Cash)
        cash_lines_result = await db.execute(
            select(JournalLine).where(
                JournalLine.journal_entry_id == entry.id,
                JournalLine.account_id == cash.id,
            )
        )
        cash_line = cash_lines_result.scalar_one()
        assert cash_line.direction.value == "CREDIT"
        assert cash_line.amount == Decimal("200.00")

        # Verify: Transaction status updated to MATCHED
        await db.refresh(txn)
        assert txn.status == BankTransactionStatus.MATCHED

    @pytest.mark.asyncio
    async def test_transfer_detection_skips_when_no_account_linked(self, db: AsyncSession, test_user):
        """Transfer detection logs warning and skips when statement has no linked account."""
        user_id = test_user.id

        # Create bank statement WITHOUT linked account
        statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/test.pdf",
            file_hash="test_hash_no_account",
            original_filename="test.pdf",
            institution="TestBank",
            account_id=None,  # No linked account
        )
        db.add(statement)
        await db.flush()

        # Create transfer transaction
        txn = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date.today(),
            description="TRANSFER TO CHECKING",
            amount=Decimal("150.00"),
            direction="OUT",
            status=BankTransactionStatus.PENDING,
        )
        db.add(txn)
        await db.flush()

        # Execute reconciliation
        matches = await execute_matching(db, user_id=user_id, statement_id=statement.id)

        # Verify: No match created (transfer detection skipped, no normal match found)
        assert len(matches) == 0

        # Verify: Transaction remains PENDING (not matched)
        await db.refresh(txn)
        assert txn.status == BankTransactionStatus.UNMATCHED  # Transaction marked UNMATCHED when no match found

        # Verify: No Processing account entry created
        processing = await get_or_create_processing_account(db, user_id)
        lines_result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        lines = list(lines_result.scalars().all())
        assert len(lines) == 0

    @pytest.mark.asyncio
    async def test_transfer_in_creates_correct_processing_entry(self, db: AsyncSession, test_user):
        """Transfer IN creates: DEBIT destination account, CREDIT Processing."""
        user_id = test_user.id

        # Setup: Checking account
        checking = Account(
            user_id=user_id,
            name="Checking",
            code="1002",
            type=AccountType.ASSET,
            currency="SGD",
        )
        db.add(checking)
        await db.flush()

        # Create bank statement linked to Checking
        statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/test.pdf",
            file_hash="test_hash_transfer_in",
            original_filename="test.pdf",
            institution="TestBank",
            account_id=checking.id,
        )
        db.add(statement)
        await db.flush()

        # Create transfer transaction (IN)
        txn = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date.today(),
            description="PAYNOW TRANSFER FROM JANE",
            amount=Decimal("300.00"),
            direction="IN",
            status=BankTransactionStatus.PENDING,
        )
        db.add(txn)
        await db.flush()

        # Execute reconciliation
        matches = await execute_matching(db, user_id=user_id, statement_id=statement.id)

        # Verify: Match created
        assert len(matches) == 1
        match = matches[0]
        assert len(match.journal_entry_ids) == 1
        entry_id = UUID(match.journal_entry_ids[0])
        # Verify: Processing account has CREDIT line (transfer IN)
        processing = await get_or_create_processing_account(db, user_id)
        entry_result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry_id))
        entry = entry_result.scalar_one()

        processing_line_result = await db.execute(
            select(JournalLine).where(
                JournalLine.journal_entry_id == entry.id,
                JournalLine.account_id == processing.id,
            )
        )
        processing_line = processing_line_result.scalar_one()
        assert processing_line.direction.value == "CREDIT"
        assert processing_line.amount == Decimal("300.00")

        # Verify: Checking account has DEBIT line (funds enter Checking)
        checking_line_result = await db.execute(
            select(JournalLine).where(
                JournalLine.journal_entry_id == entry.id,
                JournalLine.account_id == checking.id,
            )
        )
        checking_line = checking_line_result.scalar_one()
        assert checking_line.direction.value == "DEBIT"
        assert checking_line.amount == Decimal("300.00")


class TestTransferAutoPairingPhase:
    """Test Phase 3: Auto-pairing of transfers after all matching completes."""

    @pytest.mark.asyncio
    async def test_auto_pair_transfers_same_amount_same_date(self, db: AsyncSession, test_user):
        """Paired transfers (same amount, same date) are auto-paired, Processing balance = 0."""
        user_id = test_user.id

        # Setup: Cash and Checking accounts
        cash = Account(
            user_id=user_id,
            name="Cash",
            code="1001",
            type=AccountType.ASSET,
            currency="SGD",
        )
        checking = Account(
            user_id=user_id,
            name="Checking",
            code="1002",
            type=AccountType.ASSET,
            currency="SGD",
        )
        db.add_all([cash, checking])
        await db.flush()

        # Create statements
        cash_statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/cash.pdf",
            file_hash="cash_stmt",
            original_filename="cash.pdf",
            institution="Bank A",
            account_id=cash.id,
        )
        checking_statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/checking.pdf",
            file_hash="checking_stmt",
            original_filename="checking.pdf",
            institution="Bank B",
            account_id=checking.id,
        )
        db.add_all([cash_statement, checking_statement])
        await db.flush()

        # Create OUT transaction from Cash
        txn_out = BankStatementTransaction(
            statement_id=cash_statement.id,
            txn_date=date.today(),
            description="FAST PAYMENT TO BANK B",
            amount=Decimal("500.00"),
            direction="OUT",
            status=BankTransactionStatus.PENDING,
        )
        # Create IN transaction to Checking
        txn_in = BankStatementTransaction(
            statement_id=checking_statement.id,
            txn_date=date.today(),
            description="FAST PAYMENT FROM BANK A",
            amount=Decimal("500.00"),
            direction="IN",
            status=BankTransactionStatus.PENDING,
        )
        db.add_all([txn_out, txn_in])
        await db.flush()

        # Execute reconciliation (processes BOTH transactions)
        matches = await execute_matching(db, user_id=user_id)

        # Verify: Two matches created (one for OUT, one for IN)
        assert len(matches) == 2

        # Verify: Processing balance is 0 (transfers paired)
        from src.services.processing_account import get_processing_balance

        balance = await get_processing_balance(db, user_id)
        assert balance == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_unpaired_transfer_leaves_processing_nonzero(self, db: AsyncSession, test_user):
        """Unpaired transfer leaves Processing balance ≠ 0."""
        user_id = test_user.id

        # Setup: Cash account
        cash = Account(
            user_id=user_id,
            name="Cash",
            code="1001",
            type=AccountType.ASSET,
            currency="SGD",
        )
        db.add(cash)
        await db.flush()

        # Create statement
        statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/test.pdf",
            file_hash="unpaired_stmt",
            original_filename="test.pdf",
            institution="TestBank",
            account_id=cash.id,
        )
        db.add(statement)
        await db.flush()

        # Create ONLY OUT transaction (no matching IN)
        txn = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date.today(),
            description="TRANSFER OUT - UNPAIRED",
            amount=Decimal("250.00"),
            direction="OUT",
            status=BankTransactionStatus.PENDING,
        )
        db.add(txn)
        await db.flush()

        # Execute reconciliation
        matches = await execute_matching(db, user_id=user_id, statement_id=statement.id)

        # Verify: Match created
        assert len(matches) == 1

        # Verify: Processing balance is NOT zero (unpaired)
        from src.services.processing_account import get_processing_balance

        balance = await get_processing_balance(db, user_id)
        assert balance == Decimal("250.00")  # Positive = unpaired OUT transfer


class TestNormalMatchingPhaseIntegration:
    """Test Phase 2: Normal matching still works when transfers are present."""

    @pytest.mark.asyncio
    async def test_non_transfer_transaction_proceeds_to_normal_matching(self, db: AsyncSession, test_user):
        """Non-transfer transactions skip Phase 1 and proceed to Phase 2 (normal matching)."""
        user_id = test_user.id

        # Setup: Cash account and journal entry for normal expense
        cash = Account(
            user_id=user_id,
            name="Cash",
            code="1001",
            type=AccountType.ASSET,
            currency="SGD",
        )
        expense = Account(
            user_id=user_id,
            name="Office Supplies",
            code="5001",
            type=AccountType.EXPENSE,
            currency="SGD",
        )
        db.add_all([cash, expense])
        await db.flush()

        # Create manual journal entry (for normal matching)
        entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Office supplies purchase",
            status=JournalEntryStatus.POSTED,
            source_type=JournalEntrySourceType.MANUAL,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=expense.id,
                direction="DEBIT",
                amount=Decimal("35.50"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction="CREDIT",
                amount=Decimal("35.50"),
            ),
        ]
        db.add_all(lines)
        await db.flush()

        # Create statement
        statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/test.pdf",
            file_hash="normal_txn_stmt",
            original_filename="test.pdf",
            institution="TestBank",
            account_id=cash.id,
        )
        db.add(statement)
        await db.flush()

        # Create non-transfer transaction (regular expense)
        txn = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date.today(),
            description="OFFICE DEPOT STORE #123",
            amount=Decimal("35.50"),
            direction="OUT",
            status=BankTransactionStatus.PENDING,
        )
        db.add(txn)
        await db.flush()

        # Execute reconciliation
        matches = await execute_matching(db, user_id=user_id, statement_id=statement.id)

        # Verify: Match created via normal matching (Phase 2)
        assert len(matches) == 1
        match = matches[0]
        assert UUID(match.journal_entry_ids[0]) == entry.id  # Matched to existing manual entry

        # Verify: Processing account NOT involved (no transfer detected)
        processing = await get_or_create_processing_account(db, user_id)
        lines_result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        lines = list(lines_result.scalars().all())
        assert len(lines) == 0  # Processing account untouched

    @pytest.mark.asyncio
    async def test_mixed_transactions_both_phases_execute(self, db: AsyncSession, test_user):
        """Mix of transfer and non-transfer transactions: Phase 1 and Phase 2 both execute."""
        user_id = test_user.id

        # Setup accounts
        cash = Account(
            user_id=user_id,
            name="Cash",
            code="1001",
            type=AccountType.ASSET,
            currency="SGD",
        )
        expense = Account(
            user_id=user_id,
            name="Groceries",
            code="5010",
            type=AccountType.EXPENSE,
            currency="SGD",
        )
        db.add_all([cash, expense])
        await db.flush()

        # Create manual entry for normal matching
        grocery_entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Supermarket purchase",
            status=JournalEntryStatus.POSTED,
            source_type=JournalEntrySourceType.MANUAL,
        )
        db.add(grocery_entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=grocery_entry.id,
                account_id=expense.id,
                direction="DEBIT",
                amount=Decimal("85.30"),
            ),
            JournalLine(
                journal_entry_id=grocery_entry.id,
                account_id=cash.id,
                direction="CREDIT",
                amount=Decimal("85.30"),
            ),
        ]
        db.add_all(lines)
        await db.flush()

        # Create statement
        statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/test.pdf",
            file_hash="mixed_stmt",
            original_filename="test.pdf",
            institution="TestBank",
            account_id=cash.id,
        )
        db.add(statement)
        await db.flush()

        # Create two transactions: one transfer, one normal expense
        txn_transfer = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date.today(),
            description="PAYNOW TRANSFER TO SAVINGS",
            amount=Decimal("400.00"),
            direction="OUT",
            status=BankTransactionStatus.PENDING,
        )
        txn_grocery = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date.today(),
            description="NTUC FAIRPRICE #512",
            amount=Decimal("85.30"),
            direction="OUT",
            status=BankTransactionStatus.PENDING,
        )
        db.add_all([txn_transfer, txn_grocery])
        await db.flush()

        # Execute reconciliation
        matches = await execute_matching(db, user_id=user_id, statement_id=statement.id)

        # Verify: Two matches created
        assert len(matches) == 2

        # Verify: Transfer matched via Phase 1 (new Processing entry)
        transfer_match = next((m for m in matches if m.bank_txn_id == txn_transfer.id), None)
        assert transfer_match is not None
        assert transfer_match.match_score == 100  # Transfer detection score

        # Verify: Grocery matched via Phase 2 (existing manual entry)
        grocery_match = next((m for m in matches if m.bank_txn_id == txn_grocery.id), None)
        assert grocery_match is not None
        assert UUID(grocery_match.journal_entry_ids[0]) == grocery_entry.id

        # Verify: Processing account has transfer entry
        processing = await get_or_create_processing_account(db, user_id)
        lines_result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        processing_lines = list(lines_result.scalars().all())
        assert len(processing_lines) == 1  # Only transfer involves Processing
        assert processing_lines[0].amount == Decimal("400.00")
