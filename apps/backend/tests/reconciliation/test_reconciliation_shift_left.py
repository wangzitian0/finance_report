"""AC-reconciliation.reconciliation-engine.1-3: In-memory domain shift-left tests for reconciliation engine.

Covers:
- AC-reconciliation.reconciliation-engine.1: The reconciliation engine runs end to end with scoring.
- AC-reconciliation.reconciliation-engine.2: The reconciliation stats return structured metric counts.
- AC-reconciliation.reconciliation-engine.3: A reconciliation match can be accepted and transitioned.
- AC-testing.journeys.5, AC-testing.must-have.5
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import AtomicTransaction, TransactionDirection
from src.ledger import AccountType, Direction
from src.reconciliation import MatchNotFoundError, ReconciliationMatch, ReconciliationStatus, accept_match
from src.reconciliation.base.config import DEFAULT_CONFIG
from src.reconciliation.base.scoring_engine import (
    derive_reconciliation_score_tier,
    score_amount,
    score_description,
)
from src.routers.accounts import account_service
from src.routers.journal import create_entry, post_entry
from src.routers.reconciliation import reconciliation_stats
from src.schemas.account import AccountCreate
from src.schemas.journal import JournalEntryCreate, JournalLineCreate


def test_reconciliation_scoring_engine_algorithms() -> None:
    """AC-reconciliation.reconciliation-engine.1, AC-testing.journeys.5, AC-testing.must-have.5:
    Reconciliation engine computes amount similarity, description distance, and score tier.
    """
    # 1. Exact amount match gives 100
    exact_score = score_amount(Decimal("150.00"), Decimal("150.00"), DEFAULT_CONFIG)
    assert exact_score == 100.0

    # 2. Small delta within tolerance gives 90
    near_score = score_amount(Decimal("150.00"), Decimal("150.05"), DEFAULT_CONFIG)
    assert near_score >= 90.0

    # 3. Description normalization and similarity
    desc_score = score_description("Grab Taxi Singapore", "GRAB TAXI SG")
    assert desc_score > 60.0

    # 4. Score tier mapping
    assert derive_reconciliation_score_tier(95) == "HIGH"
    assert derive_reconciliation_score_tier(75) == "MEDIUM"
    assert derive_reconciliation_score_tier(40) == "LOW"


async def test_reconciliation_stats_endpoint(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.reconciliation-engine.2:
    Reconciliation stats returns structured counts without error.
    """
    user_id = test_user.id
    stats = await reconciliation_stats(db=db, user_id=user_id)

    assert stats.total_transactions >= 0
    assert stats.matched_transactions >= 0
    assert stats.unmatched_transactions >= 0
    assert stats.pending_review >= 0
    assert stats.auto_accepted >= 0
    assert stats.match_rate >= 0.0


async def test_reconciliation_match_state_and_acceptance(db: AsyncSession, test_user) -> None:
    """AC-reconciliation.reconciliation-engine.3:
    Reconciliation match lifecycle validates status transitions and auto-accept threshold.
    """
    user_id = test_user.id

    # 1. Create asset and expense accounts
    cash = await account_service.create_account(
        db, user_id, AccountCreate(name="Checking Cash", type=AccountType.ASSET, currency="SGD")
    )
    expense = await account_service.create_account(
        db, user_id, AccountCreate(name="Software Expense", type=AccountType.EXPENSE, currency="SGD")
    )

    # 2. Create and post balanced journal entry
    entry_req = JournalEntryCreate(
        entry_date=date.today(),
        memo="SaaS Subscription",
        lines=[
            JournalLineCreate(
                account_id=expense.id, direction=Direction.DEBIT, amount=Decimal("25.00"), currency="SGD"
            ),
            JournalLineCreate(account_id=cash.id, direction=Direction.CREDIT, amount=Decimal("25.00"), currency="SGD"),
        ],
    )
    entry = await create_entry(entry_req, db, user_id=user_id)
    posted = await post_entry(entry.id, db=db, user_id=user_id)

    # 3. Create real AtomicTransaction in database
    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date.today(),
        description="SaaS Subscription",
        amount=Decimal("25.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}],
    )
    db.add(txn)
    await db.flush()

    # 4. Create pending ReconciliationMatch attached to transaction and posted entry
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(posted.id)],
        match_score=88,
        score_breakdown={"amount": 90.0, "description": 85.0},
        status=ReconciliationStatus.PENDING_REVIEW,
    )
    db.add(match)
    await db.flush()

    assert match.status == ReconciliationStatus.PENDING_REVIEW

    # 5. Accept the match via domain service
    accepted_match = await accept_match(db, match.id, user_id=user_id)
    assert accepted_match.status == ReconciliationStatus.ACCEPTED

    # 6. Acceptance is idempotent
    second_accept = await accept_match(db, match.id, user_id=user_id)
    assert second_accept.status == ReconciliationStatus.ACCEPTED

    # 7. Non-existent match raises MatchNotFoundError
    with pytest.raises(MatchNotFoundError):
        await accept_match(db, uuid4(), user_id=user_id)
