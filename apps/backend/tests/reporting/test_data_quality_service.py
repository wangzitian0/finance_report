"""Tests for the personal data quality observatory domain service (#2294)."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus, StatementSummary
from src.identity import User
from src.reconciliation.data.stats import ReconciliationStats
from src.reporting import QualityGrade
from src.reporting.base.diagnostics import (
    EquationDiagnosticCategory,
    EquationDiagnosticResult,
)
from src.reporting.extension.data_quality_service import (
    _shift_months,
    compute_personal_data_quality,
)


def test_shift_months_calculation():
    """Verify month shifting logic across year boundaries."""
    y, m = _shift_months(2026, 1, -1)
    assert y == 2025
    assert m == 12

    y, m = _shift_months(2026, 12, 1)
    assert y == 2027
    assert m == 1


@pytest.mark.asyncio
async def test_compute_personal_data_quality_clean_state(db: AsyncSession, test_user: User):
    """Clean state with no data achieves Grade A (100% score) with zero actions."""
    res = await compute_personal_data_quality(
        db,
        test_user.id,
        as_of_date=date(2026, 10, 1),
        currency="SGD",
    )

    assert res.score == 100
    assert res.grade == QualityGrade.A_AUDIT_READY
    assert res.currency == "SGD"
    assert res.as_of_date == date(2026, 10, 1)
    assert res.equation_invariant.is_healthy is True
    assert res.temporal_continuity_invariant.is_healthy is True
    assert res.reconciliation_purity_invariant.is_healthy is True
    assert res.lineage_anchors_invariant.is_healthy is True
    assert len(res.timeline) == 12
    assert len(res.action_items) == 0


@pytest.mark.asyncio
@patch("src.reporting.extension.data_quality_service.run_balance_sheet_diagnostics")
async def test_compute_personal_data_quality_imbalanced_equation(
    mock_diag: AsyncMock,
    db: AsyncSession,
    test_user: User,
):
    """Imbalanced balance sheet creates a P0 action item and lowers quality score."""
    mock_diag.return_value = EquationDiagnosticResult(
        is_balanced=False,
        equation_delta=Decimal("150.00"),
        primary_category=EquationDiagnosticCategory.UNKNOWN_DISCREPANCY,
        confidence=0.5,
        suggested_action="Review manual journal entries for unbalanced debits and credits.",
    )

    res = await compute_personal_data_quality(
        db,
        test_user.id,
        as_of_date=date(2026, 10, 1),
        currency="SGD",
    )

    assert res.equation_invariant.is_healthy is False
    assert res.equation_invariant.delta == Decimal("150.00")
    assert res.score <= 60
    assert res.grade in (QualityGrade.C_ATTENTION_NEEDED, QualityGrade.D_OUT_OF_BALANCE)

    p0_actions = [a for a in res.action_items if a.priority == "P0"]
    assert len(p0_actions) == 1
    assert p0_actions[0].action_type == "RESOLVE_EQUATION"
    assert p0_actions[0].score_boost == 40


@pytest.mark.asyncio
async def test_compute_personal_data_quality_temporal_gap(
    db: AsyncSession,
    test_user: User,
):
    """A missing month between uploaded statements flags GAP_DETECTED and P1 action."""
    from src.ledger import Account, AccountType

    acc = Account(
        id=uuid4(),
        user_id=test_user.id,
        name="DBS Checking",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(acc)
    await db.flush()

    st1 = StatementSummary(
        id=uuid4(),
        user_id=test_user.id,
        account_id=acc.id,
        file_hash="hash_2026_01",
        institution="DBS",
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1200.00"),
        status=BankStatementStatus.APPROVED,
    )
    st2 = StatementSummary(
        id=uuid4(),
        user_id=test_user.id,
        account_id=acc.id,
        file_hash="hash_2026_03",
        institution="DBS",
        currency="SGD",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 3, 31),
        opening_balance=Decimal("1200.00"),
        closing_balance=Decimal("1500.00"),
        status=BankStatementStatus.APPROVED,
    )
    db.add_all([st1, st2])
    await db.flush()

    res = await compute_personal_data_quality(
        db,
        test_user.id,
        as_of_date=date(2026, 3, 31),
        currency="SGD",
    )

    # 2026-02 should be flagged as GAP_DETECTED
    feb_bucket = next((b for b in res.timeline if b.month == "2026-02"), None)
    assert feb_bucket is not None
    assert feb_bucket.has_gap is True
    assert feb_bucket.status == "GAP_DETECTED"

    assert res.temporal_continuity_invariant.is_healthy is False
    gap_actions = [a for a in res.action_items if a.action_type == "UPLOAD_STATEMENT"]
    assert len(gap_actions) >= 1
    assert "2026-02" in gap_actions[0].title


@pytest.mark.asyncio
async def test_compute_personal_data_quality_pending_statements(
    db: AsyncSession,
    test_user: User,
):
    """Pending parsing statements are flagged as PENDING_PROCESSING with P1 review action."""
    st_pending = StatementSummary(
        id=uuid4(),
        user_id=test_user.id,
        file_hash="hash_pending",
        institution="OCBC",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("500.00"),
        closing_balance=Decimal("600.00"),
        status=BankStatementStatus.PARSED,
    )
    db.add(st_pending)
    await db.flush()

    res = await compute_personal_data_quality(
        db,
        test_user.id,
        as_of_date=date(2026, 5, 31),
        currency="SGD",
    )

    may_bucket = next((b for b in res.timeline if b.month == "2026-05"), None)
    assert may_bucket is not None
    assert may_bucket.status == "PENDING_PROCESSING"

    review_actions = [a for a in res.action_items if a.action_type == "REVIEW_STATEMENT"]
    assert len(review_actions) == 1
    assert "Review 1 Pending Statement" in review_actions[0].title


@pytest.mark.asyncio
@patch("src.reporting.extension.data_quality_service.get_reconciliation_stats")
async def test_compute_personal_data_quality_pending_reconciliation(
    mock_recon: AsyncMock,
    db: AsyncSession,
    test_user: User,
):
    """Pending reconciliation matches create a P2 confirmation action item."""
    mock_recon.return_value = ReconciliationStats(
        total_transactions=20,
        matched_transactions=15,
        unmatched_transactions=2,
        pending_review=3,
        auto_accepted=0,
        match_rate=0.75,
    )

    res = await compute_personal_data_quality(
        db,
        test_user.id,
        as_of_date=date(2026, 10, 1),
        currency="SGD",
    )

    assert res.reconciliation_purity_invariant.is_healthy is False
    assert res.reconciliation_purity_invariant.delta == Decimal("3")

    recon_actions = [a for a in res.action_items if a.action_type == "RECONCILE_TRANSACTIONS"]
    assert len(recon_actions) == 1
    assert "Confirm 3 Reconciliation Match" in recon_actions[0].title


@pytest.mark.asyncio
@patch("src.reporting.extension.data_quality_service.run_balance_sheet_diagnostics")
async def test_compute_personal_data_quality_multi_gap_and_unlinked_documents(
    mock_diag: AsyncMock,
    db: AsyncSession,
    test_user: User,
):
    """Multiple gaps and unlinked documents produce Grade D and test edge branches."""
    from src.ledger import Account, AccountType

    mock_diag.return_value = EquationDiagnosticResult(
        is_balanced=False,
        equation_delta=Decimal("500.00"),
        primary_category=EquationDiagnosticCategory.UNKNOWN_DISCREPANCY,
        confidence=0.5,
        suggested_action="Resolve huge imbalance",
    )

    acc = Account(
        id=uuid4(),
        user_id=test_user.id,
        name="DBS Checking",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(acc)
    await db.flush()

    # Statement 1 in Jan 2026, Statement 2 in Apr 2026 -> Feb and Mar missing (2 gaps)
    # Also leave file_hash empty to test unlinked lineage
    st1 = StatementSummary(
        id=uuid4(),
        user_id=test_user.id,
        account_id=acc.id,
        file_hash="unlinked_hash_1",
        institution="DBS",
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1200.00"),
        status=BankStatementStatus.APPROVED,
    )
    st2 = StatementSummary(
        id=uuid4(),
        user_id=test_user.id,
        account_id=acc.id,
        file_hash="unlinked_hash_2",
        institution="DBS",
        currency="SGD",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        opening_balance=Decimal("1200.00"),
        closing_balance=Decimal("1500.00"),
        status=BankStatementStatus.APPROVED,
    )
    db.add_all([st1, st2])
    await db.flush()

    res = await compute_personal_data_quality(
        db,
        test_user.id,
        as_of_date=date(2026, 4, 30),
        currency="SGD",
    )

    assert res.score < 60
    assert res.grade == QualityGrade.D_OUT_OF_BALANCE
    assert res.lineage_anchors_invariant.is_healthy is False
    assert res.temporal_continuity_invariant.is_healthy is False
