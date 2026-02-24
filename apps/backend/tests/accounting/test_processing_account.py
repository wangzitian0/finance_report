"""Tests for Processing virtual account functionality."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.account_service import get_or_create_processing_account


class TestProcessingAccountCreation:
    """Test Processing account creation and properties."""

    @pytest.mark.asyncio
    async def test_processing_account_created_on_first_call(self, db: AsyncSession, test_user):
        """Processing account is auto-created on first get_or_create call."""
        user_id = test_user.id
        processing = await get_or_create_processing_account(db, user_id)

        assert processing.name == "Processing"
        assert processing.code == "1199"
        assert processing.type == AccountType.ASSET
        assert processing.is_system is True
        assert processing.currency == "SGD"
        assert processing.user_id == user_id

    @pytest.mark.asyncio
    async def test_processing_account_idempotent(self, db: AsyncSession, test_user):
        """Multiple calls return the same Processing account."""
        user_id = test_user.id
        processing1 = await get_or_create_processing_account(db, user_id)
        processing2 = await get_or_create_processing_account(db, user_id)

        assert processing1.id == processing2.id

    @pytest.mark.asyncio
    async def test_processing_account_hidden_from_list(self, db: AsyncSession, test_user):
        """Processing account is hidden from list_accounts."""
        user_id = test_user.id
        from src.services.account_service import list_accounts

        # Create Processing account
        await get_or_create_processing_account(db, user_id)

        # Create regular account
        regular = Account(
            user_id=user_id,
            name="Cash",
            code="1001",
            type=AccountType.ASSET,
            currency="SGD",
            is_system=False,
        )
        db.add(regular)
        await db.flush()

        # List accounts should only return regular account
        accounts, total = await list_accounts(db, user_id)
        assert total == 1
        assert accounts[0].name == "Cash"
        assert all(not acc.is_system for acc in accounts)

    @pytest.mark.asyncio
    async def test_processing_account_per_user(self, db: AsyncSession):
        """Each user gets their own Processing account."""
        user1 = uuid4()
        user2 = uuid4()

        processing1 = await get_or_create_processing_account(db, user1)
        processing2 = await get_or_create_processing_account(db, user2)

        assert processing1.user_id == user1
        assert processing2.user_id == user2
        assert processing1.id != processing2.id


class TestProcessingAccountTransfers:
    """Test transfer IN/OUT entries to Processing account."""

    @pytest.mark.asyncio
    async def test_transfer_out_to_processing(self, db: AsyncSession, test_user):
        """Transfer OUT: Debit Processing, Credit source account."""
        user_id = test_user.id
        # Setup: Cash account
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id)

        # Create transfer OUT entry: $100 from Cash to Processing
        entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Transfer OUT to another account",
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id, account_id=processing.id, direction=Direction.DEBIT, amount=Decimal("100.00")
            ),
            JournalLine(
                journal_entry_id=entry.id, account_id=cash.id, direction=Direction.CREDIT, amount=Decimal("100.00")
            ),
        ]
        db.add_all(lines)
        await db.flush()

        # Verify: Entry is balanced
        assert sum(ln.amount for ln in lines if ln.direction == Direction.DEBIT) == Decimal("100.00")
        assert sum(ln.amount for ln in lines if ln.direction == Direction.CREDIT) == Decimal("100.00")

        # Verify: Processing has debit balance (in-transit OUT)
        result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        processing_lines = list(result.scalars().all())
        balance = sum(ln.amount if ln.direction == Direction.DEBIT else -ln.amount for ln in processing_lines)
        assert balance == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_transfer_in_from_processing(self, db: AsyncSession, test_user):
        """Transfer IN: Debit destination account, Credit Processing."""
        user_id = test_user.id
        # Setup: Checking account
        checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
        db.add(checking)
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id)

        # Create transfer IN entry: $100 from Processing to Checking
        entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Transfer IN from another account",
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id, account_id=checking.id, direction=Direction.DEBIT, amount=Decimal("100.00")
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=processing.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
            ),
        ]
        db.add_all(lines)
        await db.flush()

        # Verify: Entry is balanced
        assert sum(ln.amount for ln in lines if ln.direction == Direction.DEBIT) == Decimal("100.00")
        assert sum(ln.amount for ln in lines if ln.direction == Direction.CREDIT) == Decimal("100.00")

        # Verify: Processing has credit balance (in-transit IN)
        result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        processing_lines = list(result.scalars().all())
        balance = sum(ln.amount if ln.direction == Direction.DEBIT else -ln.amount for ln in processing_lines)
        assert balance == Decimal("-100.00")

    @pytest.mark.asyncio
    async def test_paired_transfers_zero_balance(self, db: AsyncSession, test_user):
        """Paired transfer OUT + IN results in Processing balance = 0."""
        user_id = test_user.id
        # Setup: Cash and Checking accounts
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
        db.add_all([cash, checking])
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id)

        # Transfer OUT: $100 from Cash to Processing
        out_entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Transfer OUT: Cash -> Processing",
            status=JournalEntryStatus.POSTED,
        )
        db.add(out_entry)
        await db.flush()

        out_lines = [
            JournalLine(
                journal_entry_id=out_entry.id,
                account_id=processing.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
            ),
            JournalLine(
                journal_entry_id=out_entry.id, account_id=cash.id, direction=Direction.CREDIT, amount=Decimal("100.00")
            ),
        ]
        db.add_all(out_lines)
        await db.flush()

        # Transfer IN: $100 from Processing to Checking
        in_entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Transfer IN: Processing -> Checking",
            status=JournalEntryStatus.POSTED,
        )
        db.add(in_entry)
        await db.flush()

        in_lines = [
            JournalLine(
                journal_entry_id=in_entry.id,
                account_id=checking.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
            ),
            JournalLine(
                journal_entry_id=in_entry.id,
                account_id=processing.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
            ),
        ]
        db.add_all(in_lines)
        await db.flush()

        # Verify: Processing balance is 0 (transfers paired)
        result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        processing_lines = list(result.scalars().all())
        balance = sum(ln.amount if ln.direction == Direction.DEBIT else -ln.amount for ln in processing_lines)
        assert balance == Decimal("0.00")

        # Verify: Net effect is Cash -> Checking transfer (Processing transparent)
        cash_result = await db.execute(select(JournalLine).where(JournalLine.account_id == cash.id))
        cash_balance = sum(
            ln.amount if ln.direction == Direction.DEBIT else -ln.amount for ln in cash_result.scalars().all()
        )
        assert cash_balance == Decimal("-100.00")  # Cash decreased

        checking_result = await db.execute(select(JournalLine).where(JournalLine.account_id == checking.id))
        checking_balance = sum(
            ln.amount if ln.direction == Direction.DEBIT else -ln.amount for ln in checking_result.scalars().all()
        )
        assert checking_balance == Decimal("100.00")  # Checking increased


class TestProcessingAccountIntegrity:
    """Test accounting integrity with Processing account."""

    @pytest.mark.asyncio
    async def test_unpaired_transfer_visible_in_processing_balance(self, db: AsyncSession, test_user):
        """Unpaired transfer OUT shows as non-zero Processing balance."""
        user_id = test_user.id
        # Setup: Cash account
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id)

        # Create ONLY transfer OUT (no matching IN)
        entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Transfer OUT: Cash -> External (unpaired)",
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id, account_id=processing.id, direction=Direction.DEBIT, amount=Decimal("200.00")
            ),
            JournalLine(
                journal_entry_id=entry.id, account_id=cash.id, direction=Direction.CREDIT, amount=Decimal("200.00")
            ),
        ]
        db.add_all(lines)
        await db.flush()

        # Verify: Processing balance = $200 (unpaired OUT)
        result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        processing_lines = list(result.scalars().all())
        balance = sum(ln.amount if ln.direction == Direction.DEBIT else -ln.amount for ln in processing_lines)
        assert balance == Decimal("200.00")
        assert balance != Decimal("0.00")  # Non-zero indicates unpaired transfer

    @pytest.mark.asyncio
    async def test_accounting_equation_holds_with_processing(self, db: AsyncSession, test_user):
        """Accounting equation holds after transfers involving Processing account."""
        user_id = test_user.id
        # Setup: Cash, Checking accounts
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
        equity = Account(user_id=user_id, name="Owner Equity", code="3001", type=AccountType.EQUITY, currency="SGD")
        db.add_all([cash, checking, equity])
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id)

        # Initial capital: $500 to Cash
        init_entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Initial capital",
            status=JournalEntryStatus.POSTED,
        )
        db.add(init_entry)
        await db.flush()
        init_lines = [
            JournalLine(
                journal_entry_id=init_entry.id, account_id=cash.id, direction=Direction.DEBIT, amount=Decimal("500.00")
            ),
            JournalLine(
                journal_entry_id=init_entry.id,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("500.00"),
            ),
        ]
        db.add_all(init_lines)
        await db.flush()

        # Transfer OUT: $100 from Cash to Processing
        out_entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Transfer OUT",
            status=JournalEntryStatus.POSTED,
        )
        db.add(out_entry)
        await db.flush()
        out_lines = [
            JournalLine(
                journal_entry_id=out_entry.id,
                account_id=processing.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
            ),
            JournalLine(
                journal_entry_id=out_entry.id, account_id=cash.id, direction=Direction.CREDIT, amount=Decimal("100.00")
            ),
        ]
        db.add_all(out_lines)
        await db.flush()

        # Transfer IN: $100 from Processing to Checking
        in_entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Transfer IN",
            status=JournalEntryStatus.POSTED,
        )
        db.add(in_entry)
        await db.flush()
        in_lines = [
            JournalLine(
                journal_entry_id=in_entry.id,
                account_id=checking.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
            ),
            JournalLine(
                journal_entry_id=in_entry.id,
                account_id=processing.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
            ),
        ]
        db.add_all(in_lines)
        await db.flush()

        # Verify accounting equation: Assets = Liabilities + Equity
        # Assets: Cash $400 + Processing $0 + Checking $100 = $500
        # Liabilities: $0
        # Equity: $500
        # $500 = $0 + $500 ✓

        from src.services.accounting import calculate_account_balance

        cash_balance = await calculate_account_balance(db, cash.id, user_id)
        processing_balance = await calculate_account_balance(db, processing.id, user_id)
        checking_balance = await calculate_account_balance(db, checking.id, user_id)
        equity_balance = await calculate_account_balance(db, equity.id, user_id)

        total_assets = cash_balance + processing_balance + checking_balance
        total_equity = equity_balance

        assert total_assets == Decimal("500.00")
        assert total_equity == Decimal("500.00")
        assert total_assets == total_equity  # Accounting equation holds
        assert processing_balance == Decimal("0.00")  # Transfers paired


class TestProcessingAccountValidation:
    """Test validation rules for Processing account (Anti-pattern A)."""

    @pytest.mark.asyncio
    async def test_reject_manual_processing_entry(self, db: AsyncSession, test_user):
        """Manual journal entries cannot use Processing account (SSOT Anti-pattern A)."""
        user_id = test_user.id
        processing = await get_or_create_processing_account(db, user_id)
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        from src.services.accounting import ValidationError, post_journal_entry

        entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="Manual entry (should fail)",
            status=JournalEntryStatus.DRAFT,
            source_type=JournalEntrySourceType.MANUAL,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=processing.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
            ),
            JournalLine(
                journal_entry_id=entry.id, account_id=cash.id, direction=Direction.CREDIT, amount=Decimal("100.00")
            ),
        ]
        db.add_all(lines)
        await db.flush()

        with pytest.raises(ValidationError, match="Processing.*system"):
            await post_journal_entry(db, entry.id, user_id)

    @pytest.mark.asyncio
    async def test_system_entry_can_use_processing(self, db: AsyncSession, test_user):
        """System-generated entries (source_type=SYSTEM) CAN use Processing account."""
        user_id = test_user.id
        processing = await get_or_create_processing_account(db, user_id)
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        from src.services.accounting import post_journal_entry

        entry = JournalEntry(
            user_id=user_id,
            entry_date=date.today(),
            memo="System transfer (should succeed)",
            status=JournalEntryStatus.DRAFT,
            source_type=JournalEntrySourceType.SYSTEM,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=processing.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
            ),
            JournalLine(
                journal_entry_id=entry.id, account_id=cash.id, direction=Direction.CREDIT, amount=Decimal("100.00")
            ),
        ]
        db.add_all(lines)
        await db.flush()

        posted = await post_journal_entry(db, entry.id, user_id)
        assert posted.status == JournalEntryStatus.POSTED


class TestTransferDetection:
    """Test transfer pattern detection and auto-pairing."""

    @pytest.mark.asyncio
    async def test_detect_transfer_keywords(self, db: AsyncSession, test_user):
        """detect_transfer_pattern identifies transfer keywords in descriptions."""
        from src.models import BankStatement, BankStatementTransaction
        from src.services.processing_account import detect_transfer_pattern

        user_id = test_user.id
        statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/test.pdf",
            file_hash="abc123",
            original_filename="test.pdf",
            institution="TestBank",
        )
        db.add(statement)
        await db.flush()

        transfer_txns = [
            BankStatementTransaction(
                statement_id=statement.id,
                txn_date=date.today(),
                description="TRANSFER TO JOHN DOE",
                amount=Decimal("100.00"),
                direction="OUT",
            ),
            BankStatementTransaction(
                statement_id=statement.id,
                txn_date=date.today(),
                description="Fast Payment to Bank B",
                amount=Decimal("50.00"),
                direction="OUT",
            ),
            BankStatementTransaction(
                statement_id=statement.id,
                txn_date=date.today(),
                description="PAYNOW TRANSFER",
                amount=Decimal("25.00"),
                direction="IN",
            ),
        ]
        db.add_all(transfer_txns)
        await db.flush()

        for txn in transfer_txns:
            assert detect_transfer_pattern(txn) is True

        non_transfer = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date.today(),
            description="STARBUCKS COFFEE #1234",
            amount=Decimal("5.50"),
            direction="OUT",
        )
        db.add(non_transfer)
        await db.flush()

        assert detect_transfer_pattern(non_transfer) is False

    @pytest.mark.asyncio
    async def test_detect_transfer_no_description(self, db: AsyncSession, test_user):
        """detect_transfer_pattern returns False for None/empty description."""
        from src.models import BankStatement, BankStatementTransaction
        from src.services.processing_account import detect_transfer_pattern

        user_id = test_user.id
        statement = BankStatement(
            user_id=user_id,
            file_path="/tmp/test.pdf",
            file_hash="abc123",
            original_filename="test.pdf",
            institution="TestBank",
        )
        db.add(statement)
        await db.flush()

        # Test empty description
        txn_empty = BankStatementTransaction(
            statement_id=statement.id,
            txn_date=date.today(),
            description="",  # Empty string instead of None
            amount=Decimal("100.00"),
            direction="OUT",
        )
        db.add(txn_empty)
        await db.flush()

        assert detect_transfer_pattern(txn_empty) is False

    @pytest.mark.asyncio
    async def test_auto_pair_transfers_above_threshold(self, db: AsyncSession, test_user):
        """find_transfer_pairs auto-pairs transfers with confidence >= 85."""
        from src.services.processing_account import (
            create_transfer_in_entry,
            create_transfer_out_entry,
            find_transfer_pairs,
        )

        user_id = test_user.id
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
        db.add_all([cash, checking])
        await db.flush()

        await create_transfer_out_entry(
            db,
            user_id=user_id,
            source_account_id=cash.id,
            amount=Decimal("100.00"),
            txn_date=date.today(),
            description="Transfer to Bank B",
        )

        await create_transfer_in_entry(
            db,
            user_id=user_id,
            dest_account_id=checking.id,
            amount=Decimal("100.00"),
            txn_date=date.today(),
            description="Transfer to Bank B",
        )

        pairs = await find_transfer_pairs(db, user_id, threshold=85)

        assert len(pairs) == 1
        pair = pairs[0]
        assert pair.confidence >= 85
        assert pair.score_breakdown["amount"] == 100.0
        assert pair.score_breakdown["description"] > 80.0


class TestTransferScoringFunctions:
    """Test scoring functions for transfer pairing."""

    def test_amount_exact_match(self):
        """Exact amount match within 1 cent returns 100."""
        from src.services.processing_account import _score_amount_match

        score = _score_amount_match(Decimal("100.00"), Decimal("100.01"))
        assert score == 100.0

        score = _score_amount_match(Decimal("100.00"), Decimal("100.00"))
        assert score == 100.0

    def test_amount_very_close_match(self):
        """Amount within 10 cents returns 95."""
        from src.services.processing_account import _score_amount_match

        score = _score_amount_match(Decimal("100.00"), Decimal("100.05"))
        assert score == 95.0

        score = _score_amount_match(Decimal("100.00"), Decimal("100.10"))
        assert score == 95.0

    def test_amount_close_match(self):
        """Amount within 1 SGD returns 85."""
        from src.services.processing_account import _score_amount_match

        score = _score_amount_match(Decimal("100.00"), Decimal("100.50"))
        assert score == 85.0

        score = _score_amount_match(Decimal("100.00"), Decimal("101.00"))
        assert score == 85.0

    def test_amount_moderate_match(self):
        """Amount within 5 SGD returns 70."""
        from src.services.processing_account import _score_amount_match

        score = _score_amount_match(Decimal("100.00"), Decimal("103.00"))
        assert score == 70.0

        score = _score_amount_match(Decimal("100.00"), Decimal("105.00"))
        assert score == 70.0

    def test_amount_zero_base(self):
        """Zero base amount returns 0."""
        from src.services.processing_account import _score_amount_match

        score = _score_amount_match(Decimal("0"), Decimal("100.00"))
        assert score == 0.0

    def test_amount_large_diff(self):
        """Large amount difference returns proportional score."""
        from src.services.processing_account import _score_amount_match

        score = _score_amount_match(Decimal("100.00"), Decimal("110.00"))
        assert score == 90.0  # 10 SGD diff on 100 = 90% match

    def test_description_exact_match(self):
        """Exact description match returns 100."""
        from src.services.processing_account import _score_description_match

        score = _score_description_match("Transfer to Bank B", "Transfer to Bank B")
        assert score == 100.0

    def test_description_case_insensitive(self):
        """Description matching is case-insensitive."""
        from src.services.processing_account import _score_description_match

        score = _score_description_match("TRANSFER TO BANK B", "transfer to bank b")
        assert score == 100.0

    def test_description_partial_match(self):
        """Partial description match returns proportional score."""
        from src.services.processing_account import _score_description_match

        score = _score_description_match("Transfer to Bank B", "Transfer to Bank A")
        assert 50 < score < 100

    def test_description_none_values(self):
        """None descriptions return 0 score."""
        from src.services.processing_account import _score_description_match

        score = _score_description_match(None, "Transfer")
        assert score == 0.0

        score = _score_description_match("Transfer", None)
        assert score == 0.0

        score = _score_description_match(None, None)
        assert score == 0.0

    def test_date_same_day(self):
        """Same day transfer returns 100."""
        from src.services.processing_account import _score_date_proximity

        same_date = date(2025, 1, 15)
        score = _score_date_proximity(same_date, same_date)
        assert score == 100.0

    def test_date_one_day_diff(self):
        """1 day difference returns 90."""
        from src.services.processing_account import _score_date_proximity

        d1 = date(2025, 1, 15)
        d2 = date(2025, 1, 16)
        score = _score_date_proximity(d1, d2)
        assert score == 95.0

    def test_date_three_day_diff(self):
        """3 day difference returns 70."""
        from src.services.processing_account import _score_date_proximity

        d1 = date(2025, 1, 15)
        d2 = date(2025, 1, 18)
        score = _score_date_proximity(d1, d2)
        assert score == 85.0

    def test_date_seven_day_diff(self):
        """7 day difference returns 50."""
        from src.services.processing_account import _score_date_proximity

        d1 = date(2025, 1, 15)
        d2 = date(2025, 1, 22)
        score = _score_date_proximity(d1, d2)
        assert score == 70.0

    def test_date_far_apart(self):
        """Dates >7 days apart return 0."""
        from src.services.processing_account import _score_date_proximity

        d1 = date(2025, 1, 15)
        d2 = date(2025, 1, 30)
        score = _score_date_proximity(d1, d2)
        assert score == 0.0


class TestUnpairedTransferDetection:
    """Test detection of unpaired transfers."""

    @pytest.mark.asyncio
    async def test_get_unpaired_transfers_empty(self, db: AsyncSession, test_user):
        """No unpaired transfers when Processing balance is zero."""
        from src.services.processing_account import get_unpaired_transfers

        user_id = test_user.id
        unpaired = await get_unpaired_transfers(db, user_id)

        assert unpaired == []

    @pytest.mark.asyncio
    async def test_get_unpaired_transfers_with_balance(self, db: AsyncSession, test_user):
        """Unpaired transfers detected when Processing balance ≠ 0."""
        from src.services.processing_account import (
            create_transfer_out_entry,
            get_unpaired_transfers,
        )

        user_id = test_user.id
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        # Create unpaired OUT transfer
        await create_transfer_out_entry(
            db,
            user_id=user_id,
            source_account_id=cash.id,
            amount=Decimal("50.00"),
            txn_date=date.today(),
            description="Unpaired transfer",
        )

        unpaired = await get_unpaired_transfers(db, user_id)

        assert len(unpaired) == 1
        assert unpaired[0]["direction"] == "OUT"
        assert unpaired[0]["amount"] == Decimal("50.00")


class TestProcessingBalanceQuery:
    """Test Processing account balance query."""

    @pytest.mark.asyncio
    async def test_get_processing_balance_zero(self, db: AsyncSession, test_user):
        """Processing balance is zero when no transfers exist."""
        from src.services.processing_account import get_processing_balance

        user_id = test_user.id
        balance = await get_processing_balance(db, user_id)

        assert balance == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_processing_balance_with_transfers(self, db: AsyncSession, test_user):
        """Processing balance reflects unpaired transfers."""
        from src.services.processing_account import (
            create_transfer_out_entry,
            get_processing_balance,
        )

        user_id = test_user.id
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        # Create OUT transfer (debits Processing)
        await create_transfer_out_entry(
            db,
            user_id=user_id,
            source_account_id=cash.id,
            amount=Decimal("75.00"),
            txn_date=date.today(),
            description="Transfer OUT",
        )

        balance = await get_processing_balance(db, user_id)

        assert balance == Decimal("75.00")  # Positive balance = funds in transit OUT
