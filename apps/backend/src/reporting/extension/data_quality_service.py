"""Domain service for calculating per-user data quality and invariant proofs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config_app import get_effective_base_currency
from src.extraction import BankStatementStatus, StatementSummary
from src.ledger import Account, JournalEntry, JournalEntryStatus
from src.observability import get_logger

# PricingError is the FX error family; NoObservationError (no rate) is the subclass that
# this module tells apart.
from src.pricing import NoObservationError, PricingError
from src.reconciliation import get_reconciliation_stats
from src.reporting.base.data_quality_types import (
    InvariantStatus,
    MonthContinuityBucket,
    PersonalDataQualityHealthResponse,
    QualityActionItem,
    QualityGrade,
)
from src.reporting.extension.diagnostics import run_balance_sheet_diagnostics
from src.reporting.extension.reporting_calc import ReportError, _normalize_currency

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


def _months_between_exclusive(start_month: str, end_month: str) -> list[str]:
    """Return YYYY-MM months strictly between start_month and end_month."""
    sy, sm = int(start_month[:4]), int(start_month[5:7])
    ey, em = int(end_month[:4]), int(end_month[5:7])
    months: list[str] = []
    cur_y, cur_m = _shift_months(sy, sm, 1)
    while (cur_y, cur_m) < (ey, em):
        months.append(f"{cur_y:04d}-{cur_m:02d}")
        cur_y, cur_m = _shift_months(cur_y, cur_m, 1)
    return months


@dataclass(frozen=True)
class AccountGapDiagnostic:
    """Materiality diagnostic for an adjacent statement pair on one account (#2832)."""

    account_key: str
    account_label: str
    currency: str
    prev_end: date
    next_start: date
    missing_months: tuple[str, ...]
    delta: Decimal
    abs_delta: Decimal
    scale: Decimal
    relative_ratio: Decimal
    tier: Literal["zero_change", "tiny_plug", "material_gap"]


@dataclass(frozen=True)
class FxGap:
    """An FX error of the full scope that the equation check worked around (#2645)."""

    message: str
    rate_missing: bool


async def compute_personal_data_quality(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of_date: date | None = None,
    currency: str | None = None,
) -> PersonalDataQualityHealthResponse:
    """Compute complete financial data quality, invariants, timeline, and actions."""
    report_date = as_of_date or date.today()
    report_currency = _normalize_currency(currency or await get_effective_base_currency(db, user_id=user_id))

    # 1. Equation Invariant
    # The default (full) scope converts each restricted and illiquid valuation. When one has
    # no FX rate, the check runs again without restricted holdings (#2645). The result of the
    # equation does not depend on the scope: a manual valuation adds the same amount to the
    # assets or liabilities and to net_worth_adjustment_gain_loss. The FX gap becomes an
    # action item, so the page stays available. Only a pricing-family FX error falls back;
    # any other error, and an error of the second run, fails as before.
    fx_gap: FxGap | None = None
    try:
        diag_result = await run_balance_sheet_diagnostics(
            db,
            user_id,
            as_of_date=report_date,
            currency=report_currency,
        )
    except ReportError as exc:
        if not isinstance(exc.__cause__, PricingError):
            raise
        fx_gap = FxGap(message=str(exc), rate_missing=isinstance(exc.__cause__, NoObservationError))
        diag_result = await run_balance_sheet_diagnostics(
            db,
            user_id,
            as_of_date=report_date,
            currency=report_currency,
            include_restricted=False,
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

    # 3. Monthly Timeline Construction (12 rolling months anchored to latest statement end or report_date)
    month_buckets: list[MonthContinuityBucket] = []
    earliest_statement_month: str | None = None
    latest_statement_month: str | None = None
    anchor_date = report_date

    # Group statements by period_start/period_end month (YYYY-MM)
    statements_by_month: dict[str, list[StatementSummary]] = {}
    for st in raw_statements:
        st_date = st.period_end or st.period_start
        if st.period_start is not None:
            m_key = st.period_start.strftime("%Y-%m")
            statements_by_month.setdefault(m_key, []).append(st)
            if earliest_statement_month is None or m_key < earliest_statement_month:
                earliest_statement_month = m_key
            if latest_statement_month is None or m_key > latest_statement_month:
                latest_statement_month = m_key
        if st_date is not None and st_date <= report_date:
            end_key = st_date.strftime("%Y-%m")
            if latest_statement_month is None or end_key >= latest_statement_month:
                latest_statement_month = end_key
                anchor_date = st_date

    # Build 12 months up to anchor_date (#2726)
    window_months: list[str] = []
    for i in range(11, -1, -1):
        y, m = _shift_months(anchor_date.year, anchor_date.month, -i)
        window_months.append(f"{y:04d}-{m:02d}")

    # Evaluate per-account adjacent approved statement pairs for gap materiality (#2832)
    account_ids = {s.account_id for s in raw_statements if s.account_id is not None}
    account_names_by_id: dict[UUID, str] = {}
    if account_ids:
        acc_rows = (
            await db.execute(
                select(Account.id, Account.name).where(Account.id.in_(account_ids), Account.user_id == user_id)
            )
        ).all()
        account_names_by_id = {row[0]: row[1] for row in acc_rows}

    statements_by_account: dict[str, list[StatementSummary]] = {}
    for st in raw_statements:
        if st.status == BankStatementStatus.RETIRED or st.period_start is None:
            continue
        acc_key = (
            str(st.account_id)
            if st.account_id is not None
            else f"unlinked:{st.institution or 'Bank'}:{st.account_last4 or ''}"
        )
        statements_by_account.setdefault(acc_key, []).append(st)

    gap_diagnostics: list[AccountGapDiagnostic] = []
    zero_change_verified_months: set[str] = set()
    tiny_plug_months: set[str] = set()
    material_gap_months: set[str] = set()

    for acc_key, acc_stmts in statements_by_account.items():
        ordered = sorted(
            acc_stmts,
            key=lambda s: (s.period_start or date.min, s.period_end or s.period_start or date.min),
        )
        for idx in range(len(ordered) - 1):
            s_prev = ordered[idx]
            s_next = ordered[idx + 1]
            if s_prev.period_end is None or s_next.period_start is None:
                continue
            prev_month = s_prev.period_end.strftime("%Y-%m")
            next_month = s_next.period_start.strftime("%Y-%m")
            missing_months = tuple(_months_between_exclusive(prev_month, next_month))
            has_date_gap = (s_next.period_start - s_prev.period_end).days > 1 or len(missing_months) > 0
            prev_close = s_prev.closing_balance
            next_open = (
                s_next.manual_opening_balance if s_next.manual_opening_balance is not None else s_next.opening_balance
            )
            if prev_close is not None and next_open is not None:
                delta = next_open - prev_close
                abs_delta = abs(delta)
                scale = max(abs(prev_close), abs(next_open), Decimal("100"))
                rel_ratio = abs_delta / scale
            else:
                delta = Decimal("0")
                abs_delta = Decimal("0")
                scale = Decimal("100")
                rel_ratio = Decimal("0")

            if not has_date_gap and abs_delta <= Decimal("0.10"):
                continue

            if abs_delta <= Decimal("0.10"):
                tier: Literal["zero_change", "tiny_plug", "material_gap"] = "zero_change"
                zero_change_verified_months.update(missing_months)
            elif rel_ratio < Decimal("0.001"):
                tier = "tiny_plug"
                tiny_plug_months.update(missing_months or (next_month,))
            else:
                tier = "material_gap"
                material_gap_months.update(missing_months or (next_month,))

            if st_acc_id := s_next.account_id or s_prev.account_id:
                label = account_names_by_id.get(st_acc_id) or s_next.institution or "Account"
            else:
                label = s_next.institution or s_prev.institution or "Account"
            if s_next.account_last4 and s_next.account_last4 not in label:
                label = f"{label} (*{s_next.account_last4})"

            gap_diagnostics.append(
                AccountGapDiagnostic(
                    account_key=acc_key,
                    account_label=label,
                    currency=(s_next.currency or s_prev.currency or report_currency).upper(),
                    prev_end=s_prev.period_end,
                    next_start=s_next.period_start,
                    missing_months=missing_months or (next_month,),
                    delta=delta,
                    abs_delta=abs_delta,
                    scale=scale,
                    relative_ratio=rel_ratio,
                    tier=tier,
                )
            )

    material_gaps = sorted(
        [g for g in gap_diagnostics if g.tier == "material_gap"],
        key=lambda g: (g.abs_delta, g.relative_ratio),
        reverse=True,
    )
    tiny_gaps = [g for g in gap_diagnostics if g.tier == "tiny_plug"]

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
            # Check if this missing month is a material gap between existing statement boundaries (#2832)
            in_statement_span = (
                earliest_statement_month is not None
                and latest_statement_month is not None
                and earliest_statement_month <= m_key <= latest_statement_month
            )
            is_zero_or_tiny_verified = (
                m_key in (zero_change_verified_months | tiny_plug_months) and m_key not in material_gap_months
            )
            is_gap = in_statement_span and not is_zero_or_tiny_verified
            if is_gap:
                total_gaps += 1
                if first_gap_month is None:
                    first_gap_month = m_key
                status_val_missing: ContinuityStatus = "GAP_DETECTED"
            elif in_statement_span and is_zero_or_tiny_verified:
                status_val_missing = "HEALTHY"
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

    if material_gaps and total_gaps == 0:
        total_gaps = len(material_gaps)
        first_gap_month = material_gaps[0].missing_months[0]

    stats = await get_reconciliation_stats(db, user_id)
    posted_entry_count = (
        await db.scalar(
            select(func.count())
            .select_from(JournalEntry)
            .where(
                JournalEntry.user_id == user_id,
                JournalEntry.status == JournalEntryStatus.POSTED,
            )
        )
        or 0
    )
    has_unanchored_activity = len(raw_statements) == 0 and (stats.total_transactions > 0 or posted_entry_count > 0)

    temporal_healthy = total_gaps == 0 and not has_unanchored_activity
    temporal_delta = total_gaps if not has_unanchored_activity else 1
    if temporal_healthy:
        if tiny_gaps:
            tiny_total = sum((g.abs_delta for g in tiny_gaps), Decimal("0"))
            temporal_summary = "Statement anchors verified (minor cross-period rounding absorbed in 3198 Gap Equity)"
            temporal_detail = (
                f"Minor cross-period variance ({tiny_total:.2f}) is within 0.1% materiality and absorbed in "
                "Unexplained Statement Gap Equity (3198); no missing statement upload required."
            )
        elif zero_change_verified_months:
            temporal_summary = "Continuous multi-period cash rollforward verified (zero-change gaps verified)"
            temporal_detail = (
                "Intermediate months with zero balance change between statements are automatically verified without "
                "requiring redundant statement uploads."
            )
        else:
            temporal_summary = "Continuous multi-period cash rollforward verified (zero gaps detected)"
            temporal_detail = "All consecutive statements roll forward without missing periods."
    elif has_unanchored_activity:
        temporal_summary = "No uploaded bank statements cover existing ledger activity"
        temporal_detail = "Upload bank statements so transaction history has verified period rollforward."
    elif material_gaps:
        top_gap = material_gaps[0]
        gap_period_str = (
            top_gap.missing_months[0]
            if len(top_gap.missing_months) == 1
            else f"{top_gap.missing_months[0]}..{top_gap.missing_months[-1]}"
        )
        pct_str = f"{(top_gap.relative_ratio * Decimal('100')):.2f}%"
        temporal_summary = f"{total_gaps} missing month gap(s) detected in financial timeline"
        temporal_detail = (
            f"Statement missing for {gap_period_str} on {top_gap.account_label} "
            f"(unexplained movement {top_gap.delta:+.2f} {top_gap.currency}, {pct_str} of balance; "
            "currently parked in 3198 Unexplained Statement Gap Equity). "
            "Upload statement to improve Income Statement and Cash Flow precision."
        )
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
    # get_reconciliation_stats excludes unapproved Stage-1 statements at the source filter (#2826).
    recon_healthy = stats.pending_review == 0 and stats.unmatched_transactions == 0 and not has_unanchored_activity
    recon_delta = (
        stats.pending_review
        if stats.pending_review > 0
        else (
            stats.unmatched_transactions
            if stats.unmatched_transactions > 0
            else (max(1, posted_entry_count) if has_unanchored_activity else 0)
        )
    )
    if recon_healthy:
        recon_summary = "Reconciliation purity verified with zero pending clearance items"
        recon_detail = "Credit card and loan settlements clear liability accounts with zero P&L duplication."
    elif stats.pending_review > 0:
        recon_summary = f"{stats.pending_review} reconciliation item(s) pending review"
        recon_detail = "Review suggested matches to confirm liability clearing."
    elif stats.unmatched_transactions > 0:
        recon_summary = f"{stats.unmatched_transactions} unmatched transaction(s) require reconciliation"
        recon_detail = "Match statement transactions against journal entries to verify cash clearance."
    else:
        recon_summary = f"{recon_delta} ledger entry(s) have zero bank statement reconciliation coverage"
        recon_detail = "Upload bank statements and run matching to verify cash and liability clearance."

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
    lineage_delta = unlinked_count if not has_unanchored_activity else max(1, posted_entry_count)
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
        delta=Decimal(lineage_delta),
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
        recon_pts = 10 if has_unanchored_activity else 20
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

    if fx_gap is not None:
        action_items.append(
            QualityActionItem(
                id="resolve_valuation_fx_rate",
                priority="P1",
                title=(
                    "A Restricted Holding Has No FX Rate"
                    if fx_gap.rate_missing
                    else f"A Restricted Holding Did Not Convert to {report_currency}"
                ),
                description=(
                    f"The full net worth cannot convert a restricted or illiquid valuation: {fx_gap.message}. "
                    + (
                        "The rate sync adds the rate; "
                        if fx_gap.rate_missing
                        else "The stored rate does not convert this amount; "
                    )
                    + f"you can also record the valuation in {report_currency}."
                ),
                score_boost=0,
                action_type="RESOLVE_FX_RATE",
                action_url="/portfolio?panel=evidence",
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

    if has_unanchored_activity:
        action_items.append(
            QualityActionItem(
                id="upload_statements_for_ledger",
                priority="P1",
                title="Upload Bank Statements to Anchor Ledger Activity",
                description="Ledger entries exist without uploaded bank statement evidence. Upload statements to verify rollforward and lineage.",
                score_boost=min(30, 100 - total_score),
                action_type="UPLOAD_STATEMENT",
                action_url="/upload",
            )
        )
    elif material_gaps:
        total_unexplained = sum((g.abs_delta for g in material_gaps), Decimal("0"))
        for gap_diag in material_gaps:
            first_m = gap_diag.missing_months[0]
            period_label = first_m if len(gap_diag.missing_months) == 1 else f"{first_m}..{gap_diag.missing_months[-1]}"
            share_pct = (
                (gap_diag.abs_delta / total_unexplained * Decimal("100")) if total_unexplained > 0 else Decimal("100")
            )
            rel_pct = gap_diag.relative_ratio * Decimal("100")
            priority_val: Literal["P0", "P1", "P2"] = "P1" if gap_diag.relative_ratio >= Decimal("0.01") else "P2"
            action_items.append(
                QualityActionItem(
                    id=f"upload_statement_{gap_diag.account_key}_{first_m}",
                    priority=priority_val,
                    title=f"Upload Statement for {period_label} ({gap_diag.account_label})",
                    description=(
                        f"Missing statement for {period_label} on {gap_diag.account_label} leaves "
                        f"{gap_diag.delta:+.2f} {gap_diag.currency} ({rel_pct:.2f}% of balance) in "
                        f"3198 Unexplained Statement Gap Equity. Uploading it resolves {share_pct:.0f}% "
                        "of unexplained cash flow and P&L variance."
                    ),
                    score_boost=10,
                    action_type="UPLOAD_STATEMENT",
                    action_url=f"/upload?month={first_m}",
                )
            )
    elif total_gaps > 0 and first_gap_month is not None:
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
                action_url="/reconciliation?tab=unmatched",
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
