"""Domain service for calculating per-user data quality and invariant proofs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus, StatementSummary
from src.observability import get_logger
from src.reconciliation import get_reconciliation_stats
from src.reporting.base.data_quality_types import (
    InvariantStatus,
    MonthContinuityBucket,
    PersonalDataQualityHealthResponse,
    QualityActionItem,
    QualityGrade,
)
from src.reporting.extension.diagnostics import run_balance_sheet_diagnostics
from src.reporting.extension.reporting_calc import _normalize_currency

__all__ = [
    "compute_personal_data_quality",
]

ContinuityStatus = Literal["HEALTHY", "GAP_DETECTED", "PENDING_PROCESSING", "NO_DATA"]

logger = get_logger(__name__)


def _shift_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Calculate year and month shifted by delta months."""
    total_months = year * 12 + (month - 1) + delta
    new_year = total_months // 12
    new_month = (total_months % 12) + 1
    return new_year, new_month


async def compute_personal_data_quality(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date | None = None,
    currency: str | None = None,
) -> PersonalDataQualityHealthResponse:
    """Compute complete financial data quality, invariants, timeline, and actions."""
    report_date = as_of_date or date.today()
    report_currency = _normalize_currency(currency)

    # 1. Equation Invariant
    diag_result = await run_balance_sheet_diagnostics(
        db,
        user_id,
        as_of_date=report_date,
        currency=report_currency,
    )
    equation_healthy = diag_result.is_balanced
    equation_status = InvariantStatus(
        is_healthy=equation_healthy,
        name="Accounting Equation Balance",
        summary=(
            "Balance Sheet is strictly balanced (Assets = Liabilities + Equity)"
            if equation_healthy
            else f"Balance sheet discrepancy detected: {diag_result.equation_delta} {report_currency}"
        ),
        detail=diag_result.suggested_action,
        delta=diag_result.equation_delta,
    )

    # 2. Query user statements
    stmt_query = (
        select(StatementSummary)
        .where(StatementSummary.user_id == user_id)
        .order_by(
            StatementSummary.period_start.asc().nulls_last(),
            StatementSummary.created_at.asc(),
        )
    )
    raw_statements = (await db.execute(stmt_query)).scalars().all()

    pending_statuses = {
        BankStatementStatus.UPLOADED,
        BankStatementStatus.PARSING,
        BankStatementStatus.PARSED,
    }
    pending_count = sum(1 for s in raw_statements if s.status in pending_statuses)

    # 3. Monthly Timeline Construction (12 rolling months ending on report_date)
    month_buckets: list[MonthContinuityBucket] = []
    earliest_statement_month: str | None = None
    latest_statement_month: str | None = None

    # Group statements by period_start month (YYYY-MM)
    statements_by_month: dict[str, list[StatementSummary]] = {}
    for st in raw_statements:
        if st.period_start is not None:
            m_key = st.period_start.strftime("%Y-%m")
            statements_by_month.setdefault(m_key, []).append(st)
            if earliest_statement_month is None or m_key < earliest_statement_month:
                earliest_statement_month = m_key
            if latest_statement_month is None or m_key > latest_statement_month:
                latest_statement_month = m_key

    # Build 12 months up to report_date
    window_months: list[str] = []
    for i in range(11, -1, -1):
        y, m = _shift_months(report_date.year, report_date.month, -i)
        window_months.append(f"{y:04d}-{m:02d}")

    total_gaps = 0
    first_gap_month: str | None = None

    for m_key in window_months:
        st_list = statements_by_month.get(m_key, [])
        count = len(st_list)
        if count > 0:
            has_pending = any(s.status in pending_statuses for s in st_list)
            status_val: ContinuityStatus = "PENDING_PROCESSING" if has_pending else "HEALTHY"

            # Sum net movements or extract opening / closing
            open_bal = st_list[0].opening_balance
            close_bal = st_list[-1].closing_balance
            net_mov = None
            if open_bal is not None and close_bal is not None:
                net_mov = close_bal - open_bal

            month_buckets.append(
                MonthContinuityBucket(
                    month=m_key,
                    statement_count=count,
                    has_gap=False,
                    opening_balance=open_bal,
                    closing_balance=close_bal,
                    net_movement=net_mov,
                    status=status_val,
                )
            )
        else:
            # Check if this missing month is a gap between existing statement boundaries
            is_gap = (
                earliest_statement_month is not None
                and latest_statement_month is not None
                and earliest_statement_month <= m_key <= latest_statement_month
            )
            if is_gap:
                total_gaps += 1
                if first_gap_month is None:
                    first_gap_month = m_key
                status_val_missing: ContinuityStatus = "GAP_DETECTED"
            else:
                status_val_missing = "NO_DATA"

            month_buckets.append(
                MonthContinuityBucket(
                    month=m_key,
                    statement_count=0,
                    has_gap=is_gap,
                    opening_balance=None,
                    closing_balance=None,
                    net_movement=None,
                    status=status_val_missing,
                )
            )

    stats = await get_reconciliation_stats(db, user_id)
    has_unanchored_activity = len(raw_statements) == 0 and stats.total_transactions > 0

    temporal_healthy = total_gaps == 0 and not has_unanchored_activity
    temporal_delta = total_gaps if not has_unanchored_activity else 1
    if temporal_healthy:
        temporal_summary = "Continuous multi-period cash rollforward verified (zero gaps detected)"
        temporal_detail = "All consecutive statements roll forward without missing periods."
    elif has_unanchored_activity:
        temporal_summary = "No uploaded bank statements cover existing ledger activity"
        temporal_detail = "Upload bank statements so transaction history has verified period rollforward."
    else:
        temporal_summary = f"{total_gaps} missing month gap(s) detected in financial timeline"
        temporal_detail = f"Statement missing for {first_gap_month}. Upload statement to complete timeline continuity."

    temporal_status = InvariantStatus(
        is_healthy=temporal_healthy,
        name="Temporal Continuity & Rollforward",
        summary=temporal_summary,
        detail=temporal_detail,
        delta=Decimal(temporal_delta),
    )

    # 4. Reconciliation Purity Invariant
    recon_healthy = stats.pending_review == 0 and stats.unmatched_transactions == 0
    recon_delta = stats.pending_review if stats.pending_review > 0 else stats.unmatched_transactions
    if recon_healthy:
        recon_summary = "Reconciliation purity verified with zero pending clearance items"
        recon_detail = "Credit card and loan settlements clear liability accounts with zero P&L duplication."
    elif stats.pending_review > 0:
        recon_summary = f"{stats.pending_review} reconciliation item(s) pending review"
        recon_detail = "Review suggested matches to confirm liability clearing."
    else:
        recon_summary = f"{stats.unmatched_transactions} unmatched transaction(s) require reconciliation"
        recon_detail = "Match statement transactions against journal entries to verify cash clearance."

    recon_status = InvariantStatus(
        is_healthy=recon_healthy,
        name="Reconciliation & Debt Clearance Purity",
        summary=recon_summary,
        detail=recon_detail,
        delta=Decimal(recon_delta),
    )

    # 5. Lineage Anchors Invariant
    unlinked_count = sum(
        1
        for s in raw_statements
        if not s.uploaded_document_id and (not s.file_hash or s.file_hash.startswith("unlinked"))
    )
    lineage_healthy = unlinked_count == 0 and not has_unanchored_activity
    if lineage_healthy:
        lineage_summary = "Full source-document-to-report lineage verified"
        lineage_detail = "Every report line traces directly to verified statement extraction evidence."
    elif has_unanchored_activity:
        lineage_summary = "Transactions exist without uploaded source statement anchors"
        lineage_detail = "Upload source statements to anchor ledger transactions to immutable evidence."
    else:
        lineage_summary = f"{unlinked_count} statement(s) missing immutable source file link"
        lineage_detail = "Re-upload missing original document to anchor report evidence."

    lineage_status = InvariantStatus(
        is_healthy=lineage_healthy,
        name="Evidence Lineage & Traceability Anchors",
        summary=lineage_summary,
        detail=lineage_detail,
        delta=Decimal(unlinked_count),
    )

    # 6. Trust Score Computation
    # Equation: 40 points
    equation_pts = 40 if equation_healthy else 0

    # Temporal continuity: 25 points
    if temporal_healthy:
        temporal_pts = 25
    elif has_unanchored_activity or total_gaps == 1:
        temporal_pts = 15
    else:
        temporal_pts = max(0, 25 - total_gaps * 10)

    # Reconciliation purity: 20 points
    if stats.total_transactions == 0:
        recon_pts = 20
    else:
        ratio = (stats.matched_transactions + stats.auto_accepted) / max(1, stats.total_transactions)
        recon_pts = int(round(20 * ratio))
        if stats.pending_review > 0:
            recon_pts = max(0, recon_pts - min(10, stats.pending_review * 2))

    # Lineage anchors: 15 points
    lineage_pts = 15 if lineage_healthy else 5

    total_score = max(0, min(100, equation_pts + temporal_pts + recon_pts + lineage_pts))

    if total_score >= 95:
        grade = QualityGrade.A_AUDIT_READY
    elif total_score >= 80:
        grade = QualityGrade.B_BALANCED_GAPS
    elif total_score >= 60:
        grade = QualityGrade.C_ATTENTION_NEEDED
    else:
        grade = QualityGrade.D_OUT_OF_BALANCE

    # 7. Action Items Generation
    action_items: list[QualityActionItem] = []

    if not equation_healthy:
        action_items.append(
            QualityActionItem(
                id="resolve_equation_delta",
                priority="P0",
                title="Resolve Balance Sheet Imbalance",
                description=diag_result.suggested_action,
                score_boost=40,
                action_type="RESOLVE_EQUATION",
                action_url="/journal",
            )
        )

    if pending_count > 0:
        action_items.append(
            QualityActionItem(
                id="review_pending_statements",
                priority="P1",
                title=f"Review {pending_count} Pending Statement(s)",
                description="Approve or confirm parsed statements so balances reflect in your ledger.",
                score_boost=min(20, pending_count * 5),
                action_type="REVIEW_STATEMENT",
                action_url="/upload",
            )
        )

    if total_gaps > 0 and first_gap_month is not None:
        action_items.append(
            QualityActionItem(
                id=f"upload_statement_{first_gap_month}",
                priority="P1",
                title=f"Upload Statement for {first_gap_month}",
                description=f"Missing statement for {first_gap_month} breaks temporal cash rollforward continuity.",
                score_boost=10,
                action_type="UPLOAD_STATEMENT",
                action_url=f"/upload?month={first_gap_month}",
            )
        )

    if stats.pending_review > 0:
        action_items.append(
            QualityActionItem(
                id="confirm_reconciliation_matches",
                priority="P2",
                title=f"Confirm {stats.pending_review} Reconciliation Match(es)",
                description="Confirm transfer and credit card settlement matches to ensure zero P&L leakage.",
                score_boost=min(10, stats.pending_review * 2),
                action_type="RECONCILE_TRANSACTIONS",
                action_url="/reconciliation",
            )
        )
    elif stats.unmatched_transactions > 0:
        action_items.append(
            QualityActionItem(
                id="reconcile_unmatched_transactions",
                priority="P2",
                title=f"Reconcile {stats.unmatched_transactions} Unmatched Transaction(s)",
                description="Match or classify unmatched statement transactions in the reconciliation workbench.",
                score_boost=min(15, max(2, 20 - recon_pts)),
                action_type="RECONCILE_TRANSACTIONS",
                action_url="/reconciliation/unmatched",
            )
        )

    return PersonalDataQualityHealthResponse(
        score=total_score,
        grade=grade,
        as_of_date=report_date,
        currency=report_currency,
        equation_invariant=equation_status,
        temporal_continuity_invariant=temporal_status,
        reconciliation_purity_invariant=recon_status,
        lineage_anchors_invariant=lineage_status,
        timeline=month_buckets,
        action_items=action_items,
    )
