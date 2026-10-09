"""Tests for Processing virtual account functionality."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction import TransactionDirection
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    create_transfer_in_entry,
    create_transfer_out_entry,
    detect_transfer_pattern,
    find_transfer_pairs,
    get_or_create_processing_account,
    get_processing_balance,
    get_unpaired_transfers,
    post_journal_entry,
)
from src.ledger.base.processing import (
    _calculate_pair_confidence,
    _score_amount_match,
    _score_date_proximity,
)
from src.reconciliation import score_description
from tests.factories import UserFactory


def _make_pair(
    user_id,
    memo: str,
    debit_acc_id,
    credit_acc_id,
    amount: Decimal = Decimal("100.00"),
    status: JournalEntryStatus = JournalEntryStatus.POSTED,
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date.today(),
        memo=memo,
        status=status,
        source_type=source_type,
    )
    entry.lines = [
        JournalLine(account_id=debit_acc_id, direction=Direction.DEBIT, amount=amount),
        JournalLine(account_id=credit_acc_id, direction=Direction.CREDIT, amount=amount),
    ]
    return entry


async def _make_account(db: AsyncSession, user_id, name: str = "Cash", code: str = "1001") -> Account:
    acct = Account(user_id=user_id, name=name, code=code, type=AccountType.ASSET, currency="SGD")
    db.add(acct)
    await db.flush()
    return acct


class TestProcessingAccountCreation:
    """Test Processing account creation and properties."""

    async def test_processing_account_created_on_first_call(self, db: AsyncSession, test_user):
        """AC-ledger.71.1 · Processing account is auto-created on first get_or_create call."""
        user_id = test_user.id
        processing = await get_or_create_processing_account(db, user_id, currency="SGD")

        assert processing.name == "Processing"
        assert processing.code == "1199"
        assert processing.type == AccountType.ASSET
        assert processing.is_system is True
        assert processing.currency == "SGD"
        assert processing.user_id == user_id

    async def test_processing_account_idempotent(self, db: AsyncSession, test_user):
        """AC-ledger.71.2 · Multiple calls return the same Processing account."""
        user_id = test_user.id
        processing1 = await get_or_create_processing_account(db, user_id, currency="SGD")
        processing2 = await get_or_create_processing_account(db, user_id, currency="SGD")

        assert processing1.id == processing2.id

    async def test_processing_account_hidden_from_list(self, db: AsyncSession, test_user):
        """AC-ledger.71.3 · Processing account is hidden from list_accounts."""
        user_id = test_user.id
        from src.ledger.extension.account_service import list_accounts

        # Create Processing account
        await get_or_create_processing_account(db, user_id, currency="SGD")

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

    async def test_processing_account_per_user(self, db: AsyncSession):
        """AC-ledger.71.4 · Each user gets their own Processing account."""
        user1 = (await UserFactory.create_async(db)).id
        user2 = (await UserFactory.create_async(db)).id

        processing1 = await get_or_create_processing_account(db, user1, currency="SGD")
        processing2 = await get_or_create_processing_account(db, user2, currency="SGD")

        assert processing1.user_id == user1
        assert processing2.user_id == user2
        assert processing1.id != processing2.id


class TestProcessingAccountTransfers:
    """Test transfer IN/OUT entries to Processing account."""

    async def test_transfer_out_to_processing(self, db: AsyncSession, test_user):
        """AC-ledger.72.1 · Transfer OUT: Debit Processing, Credit source account."""
        user_id = test_user.id
        # Setup: Cash account
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id, currency="SGD")

        # Create transfer OUT entry: $100 from Cash to Processing
        entry = _make_pair(user_id, "Transfer OUT to another account", processing.id, cash.id)
        db.add(entry)
        await db.flush()
        lines = entry.lines

        # Verify: Entry is balanced
        assert sum(ln.amount for ln in lines if ln.direction == Direction.DEBIT) == Decimal("100.00")
        assert sum(ln.amount for ln in lines if ln.direction == Direction.CREDIT) == Decimal("100.00")

        # Verify: Processing has debit balance (in-transit OUT)
        result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        processing_lines = list(result.scalars().all())
        balance = sum(ln.amount if ln.direction == Direction.DEBIT else -ln.amount for ln in processing_lines)
        assert balance == Decimal("100.00")

    async def test_transfer_in_from_processing(self, db: AsyncSession, test_user):
        """AC-ledger.72.2 · Transfer IN: Debit destination account, Credit Processing."""
        user_id = test_user.id
        # Setup: Checking account
        checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
        db.add(checking)
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id, currency="SGD")

        # Create transfer IN entry: $100 from Processing to Checking
        entry = _make_pair(user_id, "Transfer IN from another account", checking.id, processing.id)
        db.add(entry)
        await db.flush()
        lines = entry.lines

        # Verify: Entry is balanced
        assert sum(ln.amount for ln in lines if ln.direction == Direction.DEBIT) == Decimal("100.00")
        assert sum(ln.amount for ln in lines if ln.direction == Direction.CREDIT) == Decimal("100.00")

        # Verify: Processing has credit balance (in-transit IN)
        result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        processing_lines = list(result.scalars().all())
        balance = sum(ln.amount if ln.direction == Direction.DEBIT else -ln.amount for ln in processing_lines)
        assert balance == Decimal("-100.00")

    async def test_paired_transfers_zero_balance(self, db: AsyncSession, test_user):
        """AC-ledger.72.3 · Paired transfer OUT + IN results in Processing balance = 0."""
        user_id = test_user.id
        # Setup: Cash and Checking accounts
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
        db.add_all([cash, checking])
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id, currency="SGD")

        # Transfer OUT and IN: $100 each
        out_entry = _make_pair(user_id, "Transfer OUT: Cash -> Processing", processing.id, cash.id)
        in_entry = _make_pair(user_id, "Transfer IN: Processing -> Checking", checking.id, processing.id)
        db.add_all([out_entry, in_entry])
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

    async def test_unpaired_transfer_visible_in_processing_balance(self, db: AsyncSession, test_user):
        """AC-ledger.73.1 · Unpaired transfer OUT shows as non-zero Processing balance."""
        user_id = test_user.id
        # Setup: Cash account
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id, currency="SGD")

        # Create ONLY transfer OUT (no matching IN)
        entry = _make_pair(
            user_id, "Transfer OUT: Cash -> External (unpaired)", processing.id, cash.id, amount=Decimal("200.00")
        )
        db.add(entry)
        await db.flush()

        # Verify: Processing balance = $200 (unpaired OUT)
        result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        processing_lines = list(result.scalars().all())
        balance = sum(ln.amount if ln.direction == Direction.DEBIT else -ln.amount for ln in processing_lines)
        assert balance == Decimal("200.00")
        assert balance != Decimal("0.00")  # Non-zero indicates unpaired transfer

    async def test_accounting_equation_holds_with_processing(self, db: AsyncSession, test_user):
        """AC-ledger.73.2 · Accounting equation holds after transfers involving Processing account."""
        user_id = test_user.id
        # Setup: Cash, Checking accounts
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
        equity = Account(user_id=user_id, name="Owner Equity", code="3001", type=AccountType.EQUITY, currency="SGD")
        db.add_all([cash, checking, equity])
        await db.flush()

        # Get Processing account
        processing = await get_or_create_processing_account(db, user_id, currency="SGD")

        # Initial capital + Transfer OUT + Transfer IN
        init_entry = _make_pair(user_id, "Initial capital", cash.id, equity.id, amount=Decimal("500.00"))
        out_entry = _make_pair(user_id, "Transfer OUT", processing.id, cash.id)
        in_entry = _make_pair(user_id, "Transfer IN", checking.id, processing.id)
        db.add_all([init_entry, out_entry, in_entry])
        await db.flush()

        # Verify accounting equation: Assets = Liabilities + Equity
        # Assets: Cash $400 + Processing $0 + Checking $100 = $500
        # Liabilities: $0
        # Equity: $500
        # $500 = $0 + $500 ✓

        from src.ledger import calculate_account_balance

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

    async def test_reject_manual_processing_entry(self, db: AsyncSession, test_user):
        """SSOT Anti-pattern A · Manual journal entries cannot use Processing account."""
        user_id = test_user.id
        processing = await get_or_create_processing_account(db, user_id, currency="SGD")
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        from src.ledger import ValidationError, post_journal_entry

        entry = _make_pair(
            user_id,
            "Manual entry (should fail)",
            processing.id,
            cash.id,
            status=JournalEntryStatus.DRAFT,
            source_type=JournalEntrySourceType.MANUAL,
        )
        db.add(entry)
        await db.flush()

        with pytest.raises(ValidationError, match="System accounts.*system-generated"):
            await post_journal_entry(db, entry.id, user_id)

    async def test_system_entry_can_use_processing(self, db: AsyncSession, test_user):
        """SSOT Anti-pattern A · System-generated entries (source_type=SYSTEM) CAN use Processing account."""
        user_id = test_user.id
        processing = await get_or_create_processing_account(db, user_id, currency="SGD")
        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        entry = _make_pair(
            user_id,
            "System transfer (should succeed)",
            processing.id,
            cash.id,
            status=JournalEntryStatus.DRAFT,
            source_type=JournalEntrySourceType.SYSTEM,
        )
        db.add(entry)
        await db.flush()

        posted = await post_journal_entry(db, entry.id, user_id)
        assert posted.status == JournalEntryStatus.POSTED


class TestTransferDetection:
    """Test transfer pattern detection and auto-pairing."""

    async def test_detect_transfer_keywords(self, db: AsyncSession, test_user):
        """AC-ledger.74.1 · detect_transfer_pattern identifies transfer keywords in descriptions."""
        from tests.factories import AtomicTransactionFactory, UploadedDocumentFactory

        user_id = test_user.id
        document = await UploadedDocumentFactory.create_async(db, user_id=user_id)

        transfer_txns = [
            await AtomicTransactionFactory.create_async(
                db,
                user_id=user_id,
                source_doc_id=document.id,
                txn_date=date.today(),
                description=desc,
                amount=amt,
                direction=direction,
            )
            for desc, amt, direction in [
                ("TRANSFER TO JOHN DOE", Decimal("100.00"), TransactionDirection.OUT),
                ("Fast Payment to Bank B", Decimal("50.00"), TransactionDirection.OUT),
                ("PAYNOW TRANSFER", Decimal("25.00"), TransactionDirection.IN),
            ]
        ]

        for txn in transfer_txns:
            assert detect_transfer_pattern(txn.description) is True

        non_transfer = await AtomicTransactionFactory.create_async(
            db,
            user_id=user_id,
            source_doc_id=document.id,
            txn_date=date.today(),
            description="STARBUCKS COFFEE #1234",
            amount=Decimal("5.50"),
            direction=TransactionDirection.OUT,
        )

        assert detect_transfer_pattern(non_transfer.description) is False

    async def test_detect_transfer_no_description(self, db: AsyncSession, test_user):
        """AC-ledger.74.2 · detect_transfer_pattern returns False for None/empty description."""
        from src.ledger import detect_transfer_pattern
        from tests.factories import AtomicTransactionFactory, UploadedDocumentFactory

        user_id = test_user.id
        document = await UploadedDocumentFactory.create_async(db, user_id=user_id)

        # Test empty description
        txn_empty = await AtomicTransactionFactory.create_async(
            db,
            user_id=user_id,
            source_doc_id=document.id,
            txn_date=date.today(),
            description="",  # Empty string instead of None
            amount=Decimal("100.00"),
            direction=TransactionDirection.OUT,
        )

        assert detect_transfer_pattern(txn_empty.description) is False

    async def test_auto_pair_transfers_above_threshold(self, db: AsyncSession, test_user):
        """AC-ledger.74.3 · find_transfer_pairs auto-pairs transfers with confidence >= 85."""
        user_id = test_user.id
        cash = await _make_account(db, user_id, "Cash", "1001")
        checking = await _make_account(db, user_id, "Checking", "1002")

        await create_transfer_out_entry(
            db,
            user_id=user_id,
            source_account_id=cash.id,
            amount=Decimal("100.00"),
            txn_date=date.today(),
            description="Transfer to Bank B",
            currency="SGD",
        )

        await create_transfer_in_entry(
            db,
            user_id=user_id,
            dest_account_id=checking.id,
            amount=Decimal("100.00"),
            txn_date=date.today(),
            description="Transfer to Bank B",
            currency="SGD",
        )

        pairs = await find_transfer_pairs(
            db,
            user_id,
            currency="SGD",
            description_scorer=score_description,
            threshold=85,
        )

        assert len(pairs) == 1
        pair = pairs[0]
        assert pair.confidence >= 85
        assert pair.score_breakdown["amount"] == 100.0
        assert pair.score_breakdown["description"] > 80.0


class TestTransferScoringFunctions:
    """Test scoring functions for transfer pairing."""

    def test_amount_exact_match(self):
        """AC-ledger.75.1 · Exact amount match within 1 cent returns 100."""
        assert _score_amount_match(Decimal("100.00"), Decimal("100.01")) == 100.0
        assert _score_amount_match(Decimal("100.00"), Decimal("100.00")) == 100.0

    def test_amount_very_close_match(self):
        """AC-ledger.75.2 · Amount within 10 cents returns 95."""
        assert _score_amount_match(Decimal("100.00"), Decimal("100.05")) == 95.0
        assert _score_amount_match(Decimal("100.00"), Decimal("100.10")) == 95.0

    def test_amount_close_match(self):
        """AC-ledger.75.2 · Amount within 1 SGD returns 85."""
        assert _score_amount_match(Decimal("100.00"), Decimal("100.50")) == 85.0
        assert _score_amount_match(Decimal("100.00"), Decimal("101.00")) == 85.0

    def test_amount_moderate_match(self):
        """AC-ledger.75.2 · Amount within 5 SGD returns 70."""
        assert _score_amount_match(Decimal("100.00"), Decimal("103.00")) == 70.0
        assert _score_amount_match(Decimal("100.00"), Decimal("105.00")) == 70.0

    def test_amount_zero_base(self):
        """AC-ledger.75.2 · Zero base amount returns 0."""
        assert _score_amount_match(Decimal("0"), Decimal("100.00")) == 0.0

    def test_amount_large_diff(self):
        """AC-ledger.75.2 · Large amount difference returns proportional score."""
        assert _score_amount_match(Decimal("100.00"), Decimal("110.00")) == 90.0

    def test_description_exact_match(self):
        """AC-ledger.75.3 · Exact description match returns 100."""
        assert score_description("Transfer to Bank B", "Transfer to Bank B") == 100.0

    def test_description_case_insensitive(self):
        """AC-ledger.75.3 · Description matching is case-insensitive."""
        assert score_description("TRANSFER TO BANK B", "transfer to bank b") == 100.0

    def test_description_partial_match(self):
        """AC-ledger.75.3 · Partial description match returns proportional score."""
        assert 50 < score_description("Transfer to Bank B", "Transfer to Bank A") < 100

    def test_description_none_values(self):
        """AC-ledger.75.3 · None descriptions return 0 score."""
        assert score_description(None, "Transfer") == 0.0
        assert score_description("Transfer", None) == 0.0
        assert score_description(None, None) == 0.0

    def test_date_same_day(self):
        """AC-ledger.75.4 · Same day transfer returns 100."""
        same_date = date(2025, 1, 15)
        assert _score_date_proximity(same_date, same_date) == 100.0

    def test_date_one_day_diff(self):
        """AC-ledger.75.4 · 1 day difference returns 95."""
        assert _score_date_proximity(date(2025, 1, 15), date(2025, 1, 16)) == 95.0

    def test_date_three_day_diff(self):
        """AC-ledger.75.4 · 3 day difference returns 85."""
        assert _score_date_proximity(date(2025, 1, 15), date(2025, 1, 18)) == 85.0

    def test_date_seven_day_diff(self):
        """AC-ledger.75.4 · 7 day difference returns 70."""
        assert _score_date_proximity(date(2025, 1, 15), date(2025, 1, 22)) == 70.0

    def test_date_far_apart(self):
        """AC-ledger.75.4 · Dates >7 days apart return 0."""
        assert _score_date_proximity(date(2025, 1, 15), date(2025, 1, 30)) == 0.0


class TestUnpairedTransferDetection:
    """Test detection of unpaired transfers."""

    async def test_get_unpaired_transfers_empty(self, db: AsyncSession, test_user):
        """AC-ledger.73.1 · No unpaired transfers when Processing balance is zero."""
        user_id = test_user.id
        unpaired = await get_unpaired_transfers(db, user_id, currency="SGD")
        assert unpaired == []

    async def test_get_unpaired_transfers_with_balance(self, db: AsyncSession, test_user):
        """AC-ledger.73.1 · Unpaired transfers detected when Processing balance ≠ 0."""
        user_id = test_user.id
        cash = await _make_account(db, user_id, "Cash", "1001")

        await create_transfer_out_entry(
            db,
            user_id=user_id,
            source_account_id=cash.id,
            amount=Decimal("50.00"),
            txn_date=date.today(),
            description="Unpaired transfer",
            currency="SGD",
        )

        unpaired = await get_unpaired_transfers(db, user_id, currency="SGD")

        assert len(unpaired) == 1
        assert unpaired[0]["direction"] == "OUT"
        assert unpaired[0]["amount"] == Decimal("50.00")


class TestProcessingBalanceQuery:
    """Test Processing account balance query."""

    async def test_get_processing_balance_zero(self, db: AsyncSession, test_user):
        """AC-ledger.73.2 · Processing balance is zero when no transfers exist."""
        from src.ledger import get_processing_balance

        user_id = test_user.id
        balance = await get_processing_balance(db, user_id, currency="SGD")

        assert balance == Decimal("0")

    async def test_get_processing_balance_with_transfers(self, db: AsyncSession, test_user):
        """AC-ledger.73.2 · Processing balance reflects unpaired transfers."""
        user_id = test_user.id
        cash = await _make_account(db, user_id, "Cash", "1001")
        await create_transfer_out_entry(
            db, user_id, cash.id, Decimal("75.00"), date.today(), "Transfer OUT", currency="SGD"
        )
        balance = await get_processing_balance(db, user_id, currency="SGD")
        assert balance == Decimal("75.00")  # Positive balance = funds in transit OUT


class TestTransferEntryValidation:
    """Test input validation for create_transfer_out_entry and create_transfer_in_entry."""

    async def test_transfer_out_rejects_zero_amount(self, db: AsyncSession, test_user):
        """AC-ledger.72.1 · create_transfer_out_entry rejects amount <= 0."""
        cash = await _make_account(db, test_user.id, "Cash", "1001")
        with pytest.raises(ValueError, match="Transfer amount must be positive"):
            await create_transfer_out_entry(
                db, test_user.id, cash.id, Decimal("0"), date.today(), "Test", currency="SGD"
            )

    async def test_transfer_out_rejects_negative_amount(self, db: AsyncSession, test_user):
        """AC-ledger.72.1 · create_transfer_out_entry rejects negative amount."""
        cash = await _make_account(db, test_user.id, "Cash", "1001")
        with pytest.raises(ValueError, match="Transfer amount must be positive"):
            await create_transfer_out_entry(
                db, test_user.id, cash.id, Decimal("-50"), date.today(), "Test", currency="SGD"
            )

    async def test_transfer_out_rejects_empty_description(self, db: AsyncSession, test_user):
        """AC-ledger.72.1 · create_transfer_out_entry rejects empty description."""
        cash = await _make_account(db, test_user.id, "Cash", "1001")
        with pytest.raises(ValueError, match="Transfer description must not be empty"):
            await create_transfer_out_entry(db, test_user.id, cash.id, Decimal("100"), date.today(), "", currency="SGD")

    async def test_transfer_out_rejects_whitespace_description(self, db: AsyncSession, test_user):
        """AC-ledger.72.1 · create_transfer_out_entry rejects whitespace-only description."""
        cash = await _make_account(db, test_user.id, "Cash", "1001")
        with pytest.raises(ValueError, match="Transfer description must not be empty"):
            await create_transfer_out_entry(
                db, test_user.id, cash.id, Decimal("100"), date.today(), "   ", currency="SGD"
            )

    async def test_transfer_in_rejects_zero_amount(self, db: AsyncSession, test_user):
        """AC-ledger.72.2 · create_transfer_in_entry rejects amount <= 0."""
        checking = await _make_account(db, test_user.id, "Checking", "1002")
        with pytest.raises(ValueError, match="Transfer amount must be positive"):
            await create_transfer_in_entry(
                db, test_user.id, checking.id, Decimal("0"), date.today(), "Test", currency="SGD"
            )

    async def test_transfer_in_rejects_empty_description(self, db: AsyncSession, test_user):
        """AC-ledger.72.2 · create_transfer_in_entry rejects empty description."""
        checking = await _make_account(db, test_user.id, "Checking", "1002")
        with pytest.raises(ValueError, match="Transfer description must not be empty"):
            await create_transfer_in_entry(
                db, test_user.id, checking.id, Decimal("100"), date.today(), "", currency="SGD"
            )


class TestDescriptionScoringEdgeCases:
    """Test edge cases in description scoring."""

    def test_description_whitespace_only(self):
        """AC-ledger.75.3 · Whitespace-only descriptions return 0 score."""
        score = score_description("   ", "Transfer")
        assert score == 0.0

        score = score_description("Transfer", "   ")
        assert score == 0.0


class TestPairConfidenceEdgeCases:
    """
    GIVEN _calculate_pair_confidence is called with edge-case inputs
    WHEN processing_account_id is None
    THEN it falls back to finding the first DEBIT line (lines 204-208)
    """

    def _make_entry(self, lines_data, memo="test"):
        from types import SimpleNamespace

        mock_lines = [SimpleNamespace(account_id=aid, direction=d, amount=amt) for aid, d, amt in lines_data]
        return SimpleNamespace(memo=memo, entry_date=date.today(), lines=mock_lines)

    def test_pair_confidence_none_processing_account_id(self):
        acct_a, acct_b = uuid4(), uuid4()
        out_entry = self._make_entry(
            [(acct_a, Direction.DEBIT, Decimal("100.00")), (acct_b, Direction.CREDIT, Decimal("100.00"))]
        )
        in_entry = self._make_entry(
            [(acct_b, Direction.DEBIT, Decimal("100.00")), (acct_a, Direction.CREDIT, Decimal("100.00"))]
        )

        score, breakdown = _calculate_pair_confidence(
            out_entry, in_entry, processing_account_id=None, description_scorer=score_description
        )
        assert score > 0
        assert breakdown["amount"] == 100.0

    def test_pair_confidence_no_debit_line_fallback(self):
        acct_a, acct_b = uuid4(), uuid4()
        out_entry = self._make_entry([(acct_a, Direction.CREDIT, Decimal("100.00"))])
        in_entry = self._make_entry([(acct_b, Direction.CREDIT, Decimal("100.00"))])

        score, breakdown = _calculate_pair_confidence(
            out_entry, in_entry, processing_account_id=None, description_scorer=score_description
        )
        assert breakdown["amount"] == 100.0

    def test_pair_confidence_no_matching_line_in_in_entry(self):
        acct_a, acct_b = uuid4(), uuid4()
        out_entry = self._make_entry(
            [(acct_a, Direction.DEBIT, Decimal("100.00")), (acct_b, Direction.CREDIT, Decimal("100.00"))]
        )
        in_entry = self._make_entry([(acct_b, Direction.DEBIT, Decimal("50.00"))])

        score, breakdown = _calculate_pair_confidence(
            out_entry, in_entry, processing_account_id=None, description_scorer=score_description
        )
        assert breakdown["amount"] == 0.0
