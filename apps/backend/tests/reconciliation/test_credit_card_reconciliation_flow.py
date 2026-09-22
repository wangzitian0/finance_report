"""Tests for Flow 16: Credit Card Repayment & Reconciliation Flow.

SSOT Flow 16:
- Name: Credit Card Repayment & Refund Clearing
- Title: 信用卡还款勾稽 / 对账流
- UI Surface: /reconciliation
- Frontend Component: Workbench (ReconciliationWorkbench)
- Backend Endpoint: POST /reconciliation/matches/{match_id}/accept (and transfer auto-pairing)
- Invariant: Bank cash outflow Dr CreditCardLiability == Credit card statement payment Inflow;
             Processing virtual account (1199) net balance == Decimal("0.00");
             Every transfer entry debits == credits strictly balanced.
- Reference: apps/backend/tests/reconciliation/test_credit_card_reconciliation_flow.py
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus, DocumentType, TransactionDirection, UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    calculate_account_balance,
    create_transfer_in_entry,
    create_transfer_out_entry,
    find_transfer_pairs,
    get_processing_balance,
    post_journal_entry,
    submit_manual_journal_entry,
    validate_journal_balance,
    validate_manual_journal_entry_for_post,
)
from src.reconciliation import (
    ReconciliationStatus,
    execute_matching,
    score_description,
)
from src.reconciliation.extension.transfer_pairs import persist_transfer_pairs


async def _seed_statement(
    db: AsyncSession,
    user_id: UUID,
    *,
    account_id: UUID,
    institution: str = "DBS Bank",
    file_hash: str | None = None,
) -> UploadedDocument:
    """Create an UploadedDocument + StatementSummary tied to an account."""
    h = file_hash or f"stmt_{uuid4().hex[:12]}"
    doc = UploadedDocument(
        user_id=user_id,
        file_path=f"/statements/{h}.pdf",
        file_hash=h,
        original_filename=f"{h}.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()

    summary = StatementSummary(
        user_id=user_id,
        account_id=account_id,
        uploaded_document_id=doc.id,
        file_hash=h,
        institution=institution,
        account_last4="8888",
        currency="SGD",
        status=BankStatementStatus.PARSED,
    )
    db.add(summary)
    await db.flush()
    return doc


async def _seed_atomic_txn(
    db: AsyncSession,
    user_id: UUID,
    doc: UploadedDocument,
    *,
    description: str,
    amount: Decimal,
    direction: TransactionDirection,
    txn_date: date | None = None,
) -> AtomicTransaction:
    """Create an AtomicTransaction tied to an UploadedDocument."""
    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=txn_date or date(2026, 6, 10),
        description=description,
        amount=amount,
        direction=direction,
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(doc.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
    )
    db.add(txn)
    await db.flush()
    return txn


class TestCreditCardReconciliationFlow:
    """Flow 16: Adversarial and rigorous credit card repayment and reconciliation tests."""

    async def test_flow16_e2e_credit_card_repayment_clearing_invariants(
        self,
        db: AsyncSession,
        test_user,
        client: AsyncClient,
    ) -> None:
        """Flow 16 E2E: Repayment reduces liability, clears 1199 processing, and balances debits/credits.

        Scenario:
        1. User incurs a $500.00 dining expense on Credit Card (increasing liability).
        2. User pays $500.00 from Bank Checking account to Credit Card.
        3. Bank statement captures outflow: Checking -> Processing (1199).
        4. Credit Card statement captures payment: Processing (1199) -> Credit Card.
        5. Reconciliation matching executes:
           - Phase 1 recognizes transfer keywords and generates transfer legs.
           - Phase 3 pairs the transfer legs.
        6. Match accept API resolves review item if pending review.
        7. Invariants:
           - Credit card liability decreases by exactly $500.00 to $0.00.
           - Processing account 1199 net balance is strictly $0.00.
           - Every journal entry debits == credits.
        """
        user_id = test_user.id

        # 1. Setup Accounts
        checking_acc = Account(
            user_id=user_id,
            name="DBS Multiplier Checking",
            code="1001",
            type=AccountType.ASSET,
            currency="SGD",
        )
        cc_liability_acc = Account(
            user_id=user_id,
            name="DBS Altitude Visa Card",
            code="2001",
            type=AccountType.LIABILITY,
            currency="SGD",
        )
        expense_acc = Account(
            user_id=user_id,
            name="Dining Expense",
            code="5001",
            type=AccountType.EXPENSE,
            currency="SGD",
        )
        db.add_all([checking_acc, cc_liability_acc, expense_acc])
        await db.flush()

        # 2. Initial charge on credit card: $500 dining expense
        initial_charge = await submit_manual_journal_entry(
            db,
            user_id=user_id,
            entry_date=date(2026, 6, 1),
            memo="Restaurant Dinner",
            rationale="Credit card purchase",
            lines_data=[
                {
                    "account_id": expense_acc.id,
                    "direction": Direction.DEBIT,
                    "amount": Decimal("500.00"),
                    "currency": "SGD",
                },
                {
                    "account_id": cc_liability_acc.id,
                    "direction": Direction.CREDIT,
                    "amount": Decimal("500.00"),
                    "currency": "SGD",
                },
            ],
            base_currency="SGD",
        )
        await db.refresh(initial_charge, ["lines"])
        await validate_manual_journal_entry_for_post(db, user_id=user_id, entry=initial_charge, base_currency="SGD")
        await post_journal_entry(db, initial_charge.id, user_id, base_currency="SGD")
        await db.flush()

        initial_liability = await calculate_account_balance(db, cc_liability_acc.id, user_id)
        assert initial_liability == Decimal("500.00")

        # 3. Bank and Credit Card statements with repayment transaction
        bank_doc = await _seed_statement(db, user_id, account_id=checking_acc.id, institution="DBS Bank")
        cc_doc = await _seed_statement(db, user_id, account_id=cc_liability_acc.id, institution="DBS Cards")

        # Bank side: payment to credit card (OUT)
        await _seed_atomic_txn(
            db,
            user_id,
            bank_doc,
            description="GIRO PAYMENT TO DBS CREDIT CARD",
            amount=Decimal("500.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2026, 6, 15),
        )

        # Credit card side: payment received (IN)
        await _seed_atomic_txn(
            db,
            user_id,
            cc_doc,
            description="PAYMENT TO CARD RECEIVED - THANK YOU",
            amount=Decimal("500.00"),
            direction=TransactionDirection.IN,
            txn_date=date(2026, 6, 15),
        )

        # 4. Execute reconciliation engine matching
        matches = await execute_matching(db, user_id=user_id, currency="SGD")
        assert len(matches) >= 2

        # 5. Check if matches are auto-accepted or in review; accept if needed via API
        for m in matches:
            if m.status == ReconciliationStatus.PENDING_REVIEW:
                resp = await client.post(f"/reconciliation/matches/{m.id}/accept")
                assert resp.status_code == 200

        # 6. Core Invariant 1: Processing Account 1199 net balance strictly zero
        processing_bal = await get_processing_balance(db, user_id, currency="SGD")
        assert processing_bal == Decimal("0.00")

        # 7. Core Invariant 2: Credit card liability accurately decreased from 500 to 0
        final_liability = await calculate_account_balance(db, cc_liability_acc.id, user_id)
        assert final_liability == Decimal("0.00")

        # 8. Core Invariant 3: Validate journal balance for all created entries
        entries_res = await db.execute(
            select(JournalEntry).where(
                JournalEntry.user_id == user_id,
                JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]),
            )
        )
        entries = entries_res.scalars().all()
        for e in entries:
            await db.refresh(e, ["lines"])
            validate_journal_balance(e.lines, base_currency="SGD")

    async def test_flow16_partial_repayment_liability_reduction(
        self,
        db: AsyncSession,
        test_user,
    ) -> None:
        """Flow 16: Partial credit card repayment reduces liability proportionately and clears in-transit."""
        user_id = test_user.id

        checking_acc = Account(
            user_id=user_id,
            name="Bank Checking",
            code="1002",
            type=AccountType.ASSET,
            currency="SGD",
        )
        cc_liability_acc = Account(
            user_id=user_id,
            name="Visa Credit Card",
            code="2002",
            type=AccountType.LIABILITY,
            currency="SGD",
        )
        expense_acc = Account(
            user_id=user_id,
            name="Travel Expense",
            code="5002",
            type=AccountType.EXPENSE,
            currency="SGD",
        )
        db.add_all([checking_acc, cc_liability_acc, expense_acc])
        await db.flush()

        # Charge $1,000.00 flight tickets on credit card
        charge_entry = await submit_manual_journal_entry(
            db,
            user_id=user_id,
            entry_date=date(2026, 5, 20),
            memo="Flight Tickets",
            rationale="Travel expense on credit card",
            lines_data=[
                {
                    "account_id": expense_acc.id,
                    "direction": Direction.DEBIT,
                    "amount": Decimal("1000.00"),
                    "currency": "SGD",
                },
                {
                    "account_id": cc_liability_acc.id,
                    "direction": Direction.CREDIT,
                    "amount": Decimal("1000.00"),
                    "currency": "SGD",
                },
            ],
            base_currency="SGD",
        )
        await db.refresh(charge_entry, ["lines"])
        await validate_manual_journal_entry_for_post(db, user_id=user_id, entry=charge_entry, base_currency="SGD")
        await post_journal_entry(db, charge_entry.id, user_id, base_currency="SGD")
        await db.flush()

        assert await calculate_account_balance(db, cc_liability_acc.id, user_id) == Decimal("1000.00")

        # Partial repayment of $400.00
        repay_out = await create_transfer_out_entry(
            db,
            user_id=user_id,
            source_account_id=checking_acc.id,
            amount=Decimal("400.00"),
            txn_date=date(2026, 6, 5),
            description="CREDIT CARD REPAYMENT",
            currency="SGD",
        )
        repay_in = await create_transfer_in_entry(
            db,
            user_id=user_id,
            dest_account_id=cc_liability_acc.id,
            amount=Decimal("400.00"),
            txn_date=date(2026, 6, 5),
            description="CREDIT CARD REPAYMENT",
            currency="SGD",
        )
        await db.flush()

        # Find transfer pairs and verify pairing
        pairs = await find_transfer_pairs(
            db,
            user_id,
            currency="SGD",
            description_scorer=score_description,
            threshold=80,
        )
        assert len(pairs) == 1
        assert pairs[0].confidence >= 80

        # Persist pairing
        _ = await persist_transfer_pairs(db, pairs)
        # Note: persist_transfer_pairs links ReconciliationMatch dispositions.
        # Regardless of match row linking, the ledger entries are posted and valid.

        # Invariant 1: Processing account 1199 net balance is strictly 0.00
        processing_bal = await get_processing_balance(db, user_id, currency="SGD")
        assert processing_bal == Decimal("0.00")

        # Invariant 2: Credit card liability accurately reduced by 400.00 -> exactly 600.00 remains
        updated_liability = await calculate_account_balance(db, cc_liability_acc.id, user_id)
        assert updated_liability == Decimal("600.00")

        # Invariant 3: Validate journal balance for repayment legs
        await db.refresh(repay_out, ["lines"])
        await db.refresh(repay_in, ["lines"])
        validate_journal_balance(repay_out.lines, base_currency="SGD")
        validate_journal_balance(repay_in.lines, base_currency="SGD")

    async def test_flow16_unpaired_in_transit_transfer_preserves_residue(
        self,
        db: AsyncSession,
        test_user,
    ) -> None:
        """Flow 16: Outflow clears bank before card statement posts -> Processing 1199 retains in-transit funds.

        When the second leg posts later, Processing clears to Decimal('0.00').
        """
        user_id = test_user.id

        checking_acc = Account(
            user_id=user_id,
            name="Bank Checking",
            code="1003",
            type=AccountType.ASSET,
            currency="SGD",
        )
        cc_liability_acc = Account(
            user_id=user_id,
            name="Mastercard Liability",
            code="2003",
            type=AccountType.LIABILITY,
            currency="SGD",
        )
        db.add_all([checking_acc, cc_liability_acc])
        await db.flush()

        # Leg 1: Bank outflow clears on Day 1 ($350.00)
        _ = await create_transfer_out_entry(
            db,
            user_id=user_id,
            source_account_id=checking_acc.id,
            amount=Decimal("350.00"),
            txn_date=date(2026, 6, 1),
            description="FAST PAYMENT TO MASTERCARD",
            currency="SGD",
        )
        await db.flush()

        # Funds are in-transit in virtual account 1199
        in_transit_bal = await get_processing_balance(db, user_id, currency="SGD")
        assert in_transit_bal == Decimal("350.00")

        # Leg 2: Card statement processes payment on Day 3 ($350.00)
        _ = await create_transfer_in_entry(
            db,
            user_id=user_id,
            dest_account_id=cc_liability_acc.id,
            amount=Decimal("350.00"),
            txn_date=date(2026, 6, 3),
            description="FAST PAYMENT FROM BANK RECEIVED",
            currency="SGD",
        )
        await db.flush()

        # After second leg clears, in-transit residue collapses to strictly 0.00
        final_bal = await get_processing_balance(db, user_id, currency="SGD")
        assert final_bal == Decimal("0.00")

    async def test_flow16_mismatched_amount_leaves_processing_residue(
        self,
        db: AsyncSession,
        test_user,
    ) -> None:
        """Flow 16: Mismatched amounts (e.g. fee deduction or bank dispute) leave non-zero residue and reject auto-pair."""
        user_id = test_user.id

        checking = Account(user_id=user_id, name="Checking", code="1004", type=AccountType.ASSET, currency="SGD")
        card = Account(user_id=user_id, name="Card", code="2004", type=AccountType.LIABILITY, currency="SGD")
        db.add_all([checking, card])
        await db.flush()

        # Bank transfers $500.00
        await create_transfer_out_entry(
            db,
            user_id=user_id,
            source_account_id=checking.id,
            amount=Decimal("500.00"),
            txn_date=date(2026, 6, 10),
            description="TRANSFER TO CARD",
            currency="SGD",
        )
        # Card only received $480.00 ($20 discrepancy)
        await create_transfer_in_entry(
            db,
            user_id=user_id,
            dest_account_id=card.id,
            amount=Decimal("480.00"),
            txn_date=date(2026, 6, 10),
            description="TRANSFER TO CARD",
            currency="SGD",
        )
        await db.flush()

        # Auto-pair at default threshold 85 should reject the mismatched pair
        pairs = await find_transfer_pairs(
            db,
            user_id,
            currency="SGD",
            description_scorer=score_description,
            threshold=85,
        )
        assert len(pairs) == 0

        # Processing account holds exactly the $20.00 unsettled residue
        residue = await get_processing_balance(db, user_id, currency="SGD")
        assert residue == Decimal("20.00")
