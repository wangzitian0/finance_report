"""Integration tests for Processing account transfer detection during reconciliation.

Tests the three-phase reconciliation flow:
1. Phase 1: Transfer Detection (BEFORE normal matching)
2. Phase 2: Normal Matching (existing logic)
3. Phase 3: Auto-Pair Transfers (AFTER all matching)

See: docs/ssot/processing_account.md Section 7 (Integration Points)

Fixtures are built natively on Layer 2: each "statement" is an
``UploadedDocument`` + ``StatementSummary`` carrying the confirmed custody
account, and transactions are ``AtomicTransaction`` rows whose
``source_documents`` reference the document so ``resolve_custody_account_id``
can resolve the transfer source/destination account.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_enums import BankStatementStatus
from src.models.statement_summary import StatementSummary
from src.services.account_service import get_or_create_processing_account
from src.services.reconciliation import execute_matching


async def _seed_statement(
    db: AsyncSession,
    user_id,
    *,
    account_id,
    file_hash: str,
) -> UploadedDocument:
    """Create an UploadedDocument + StatementSummary conform for the given account."""
    doc = UploadedDocument(
        user_id=user_id,
        file_path=f"/tmp/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="test.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()

    summary = StatementSummary(
        user_id=user_id,
        account_id=account_id,
        uploaded_document_id=doc.id,
        file_hash=file_hash,
        institution="TestBank",
        account_last4="1234",
        currency="SGD",
        status=BankStatementStatus.PARSED,
    )
    db.add(summary)
    await db.flush()
    return doc


async def _seed_txn(
    db: AsyncSession,
    user_id,
    doc: UploadedDocument,
    *,
    description: str,
    amount: Decimal,
    direction: str,
    txn_date: date | None = None,
) -> AtomicTransaction:
    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=txn_date or date.today(),
        description=description,
        amount=amount,
        direction=TransactionDirection(direction),
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(doc.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
    )
    db.add(txn)
    await db.flush()
    return txn


class TestTransferDetectionDuringReconciliation:
    """Test Phase 1: Transfer detection with Processing account during reconciliation."""

    async def test_transfer_detected_creates_processing_entry(self, db: AsyncSession, test_user):
        """AC15.6.1 · Transfer detection creates Processing account entry with linked account."""
        user_id = test_user.id

        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        doc = await _seed_statement(db, user_id, account_id=cash.id, file_hash="test_hash_transfer_1")
        txn = await _seed_txn(
            db,
            user_id,
            doc,
            description="TRANSFER TO SAVINGS ACCOUNT",
            amount=Decimal("200.00"),
            direction="OUT",
        )

        matches = await execute_matching(db, user_id=user_id)

        assert len(matches) == 1
        match = matches[0]
        assert match.match_score == 100  # Transfer detection = exact match
        assert len(match.journal_entry_ids) == 1
        entry_id = UUID(match.journal_entry_ids[0])
        entry_result = await db.execute(select(JournalEntry).where(JournalEntry.id == entry_id))
        entry = entry_result.scalar_one()
        assert entry.source_type == JournalEntrySourceType.SYSTEM
        assert entry.status == JournalEntryStatus.RECONCILED
        assert "Transfer OUT" in entry.memo or "TRANSFER TO" in entry.memo

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

        cash_lines_result = await db.execute(
            select(JournalLine).where(
                JournalLine.journal_entry_id == entry.id,
                JournalLine.account_id == cash.id,
            )
        )
        cash_line = cash_lines_result.scalar_one()
        assert cash_line.direction.value == "CREDIT"
        assert cash_line.amount == Decimal("200.00")

        await db.refresh(txn)

    async def test_transfer_detection_skips_when_no_account_linked(self, db: AsyncSession, test_user):
        """AC15.6.2 · Transfer detection logs warning and skips when statement has no linked account."""
        user_id = test_user.id

        doc = await _seed_statement(db, user_id, account_id=None, file_hash="test_hash_no_account")
        txn = await _seed_txn(
            db,
            user_id,
            doc,
            description="TRANSFER TO CHECKING",
            amount=Decimal("150.00"),
            direction="OUT",
        )

        matches = await execute_matching(db, user_id=user_id)

        assert len(matches) == 0
        await db.refresh(txn)

        processing = await get_or_create_processing_account(db, user_id)
        lines_result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        lines = list(lines_result.scalars().all())
        assert len(lines) == 0

    async def test_transfer_in_creates_correct_processing_entry(self, db: AsyncSession, test_user):
        """AC15.6.3 · Transfer IN creates: DEBIT destination account, CREDIT Processing."""
        user_id = test_user.id

        checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
        db.add(checking)
        await db.flush()

        doc = await _seed_statement(db, user_id, account_id=checking.id, file_hash="test_hash_transfer_in")
        await _seed_txn(
            db,
            user_id,
            doc,
            description="PAYNOW TRANSFER FROM JANE",
            amount=Decimal("300.00"),
            direction="IN",
        )

        matches = await execute_matching(db, user_id=user_id)

        assert len(matches) == 1
        match = matches[0]
        assert len(match.journal_entry_ids) == 1
        entry_id = UUID(match.journal_entry_ids[0])
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

    async def test_auto_pair_transfers_same_amount_same_date(self, db: AsyncSession, test_user):
        """AC15.6.4 · Paired transfers (same amount, same date) are auto-paired, Processing balance = 0."""
        user_id = test_user.id

        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
        db.add_all([cash, checking])
        await db.flush()

        cash_doc = await _seed_statement(db, user_id, account_id=cash.id, file_hash="cash_stmt")
        checking_doc = await _seed_statement(db, user_id, account_id=checking.id, file_hash="checking_stmt")

        await _seed_txn(
            db,
            user_id,
            cash_doc,
            description="FAST PAYMENT TO BANK B",
            amount=Decimal("500.00"),
            direction="OUT",
        )
        await _seed_txn(
            db,
            user_id,
            checking_doc,
            description="FAST PAYMENT FROM BANK A",
            amount=Decimal("500.00"),
            direction="IN",
        )

        matches = await execute_matching(db, user_id=user_id)

        assert len(matches) == 2

        from src.services.processing_account import get_processing_balance

        balance = await get_processing_balance(db, user_id)
        assert balance == Decimal("0.00")

    async def test_unpaired_transfer_leaves_processing_nonzero(self, db: AsyncSession, test_user):
        """AC15.6.5 · Unpaired transfer leaves Processing balance ≠ 0."""
        user_id = test_user.id

        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.flush()

        doc = await _seed_statement(db, user_id, account_id=cash.id, file_hash="unpaired_stmt")
        await _seed_txn(
            db,
            user_id,
            doc,
            description="TRANSFER OUT - UNPAIRED",
            amount=Decimal("250.00"),
            direction="OUT",
        )

        matches = await execute_matching(db, user_id=user_id)

        assert len(matches) == 1

        from src.services.processing_account import get_processing_balance

        balance = await get_processing_balance(db, user_id)
        assert balance == Decimal("250.00")  # Positive = unpaired OUT transfer


class TestNormalMatchingPhaseIntegration:
    """Test Phase 2: Normal matching still works when transfers are present."""

    async def test_non_transfer_transaction_proceeds_to_normal_matching(self, db: AsyncSession, test_user):
        """AC15.6.6 · Non-transfer transactions skip Phase 1 and proceed to Phase 2 (normal matching)."""
        user_id = test_user.id

        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        expense = Account(
            user_id=user_id, name="Office Supplies", code="5001", type=AccountType.EXPENSE, currency="SGD"
        )
        db.add_all([cash, expense])
        await db.flush()

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

        doc = await _seed_statement(db, user_id, account_id=cash.id, file_hash="normal_txn_stmt")
        await _seed_txn(
            db,
            user_id,
            doc,
            description="OFFICE DEPOT STORE #123",
            amount=Decimal("35.50"),
            direction="OUT",
        )

        matches = await execute_matching(db, user_id=user_id)

        assert len(matches) == 1
        match = matches[0]
        assert UUID(match.journal_entry_ids[0]) == entry.id

        processing = await get_or_create_processing_account(db, user_id)
        lines_result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        lines = list(lines_result.scalars().all())
        assert len(lines) == 0

    async def test_mixed_transactions_both_phases_execute(self, db: AsyncSession, test_user):
        """AC15.6.6 · AC11.17.2 · Mix of transfer and non-transfer transactions: Phase 1 and Phase 2 both execute."""
        user_id = test_user.id

        cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
        expense = Account(user_id=user_id, name="Groceries", code="5010", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([cash, expense])
        await db.flush()

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

        doc = await _seed_statement(db, user_id, account_id=cash.id, file_hash="mixed_stmt")
        await _seed_txn(
            db,
            user_id,
            doc,
            description="PAYNOW TRANSFER TO SAVINGS",
            amount=Decimal("400.00"),
            direction="OUT",
        )
        await _seed_txn(
            db,
            user_id,
            doc,
            description="NTUC FAIRPRICE #512",
            amount=Decimal("85.30"),
            direction="OUT",
        )

        matches = await execute_matching(db, user_id=user_id)

        assert len(matches) == 2

        transfer_match = next(
            (m for m in matches if m.score_breakdown.get("transfer_out") or m.score_breakdown.get("transfer_in")),
            None,
        )
        assert transfer_match is not None
        assert transfer_match.match_score == 100

        grocery_match = next(
            (m for m in matches if str(grocery_entry.id) in (m.journal_entry_ids or [])),
            None,
        )
        assert grocery_match is not None
        assert UUID(grocery_match.journal_entry_ids[0]) == grocery_entry.id

        processing = await get_or_create_processing_account(db, user_id)
        lines_result = await db.execute(select(JournalLine).where(JournalLine.account_id == processing.id))
        processing_lines = list(lines_result.scalars().all())
        assert len(processing_lines) == 1
        assert processing_lines[0].amount == Decimal("400.00")
