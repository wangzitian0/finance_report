"""Domain service for calculating per-user data quality and invariant proofs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.ratio import Ratio
from src.config_app import get_effective_base_currency
from src.extraction import BankStatementStatus, StatementSummary
from src.ledger import Account, JournalEntry, JournalEntryStatus, account_service
from src.observability import get_logger
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

__all__ = ["compute_personal_data_quality"]

ContinuityStatus = Literal["HEALTHY", "GAP_DETECTED", "PENDING_PROCESSING", "NO_DATA"]

logger = get_logger(__name__)


def _shift_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """Calculate year and month shifted by delta months."""
    total_months = year * 12 + (month - 1) + delta
    return total_months // 12, (total_months % 12) + 1


def _months_between_exclusive(start_month: str, end_month: str) -> list[str]:
    """Return YYYY-MM months strictly between start_month and end_month."""
    cur_y, cur_m = _shift_months(int(start_month[:4]), int(start_month[5:7]), 1)
    end_pair = (int(end_month[:4]), int(end_month[5:7]))
    months: list[str] = []
    while (cur_y, cur_m) < end_pair:
        months.append(f"{cur_y:04d}-{cur_m:02d}")
        cur_y, cur_m = _shift_months(cur_y, cur_m, 1)
    return months


def _action(
    action_id: str,
    priority: Literal["P0", "P1", "P2"],
    title: str,
    description: str,
    score_boost: int,
    action_type: Literal[
        "UPLOAD_STATEMENT",
        "REVIEW_STATEMENT",
        "RECONCILE_TRANSACTIONS",
        "RESOLVE_EQUATION",
        "RESOLVE_FX_RATE",
    ],
    action_url: str,
) -> QualityActionItem:
    return QualityActionItem(
        id=action_id,
        priority=priority,
        title=title,
        description=description,
        score_boost=score_boost,
        action_type=action_type,
        action_url=action_url,
    )


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
    relative_ratio: Ratio
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

    fx_gap: FxGap | None = None
    try:
        diag_result = await run_balance_sheet_diagnostics(
            db, user_id, as_of_date=report_date, currency=report_currency
        )
    except ReportError as exc:
        if not isinstance(exc.__cause__, PricingError):
            raise
        fx_gap = FxGap(message=str(exc), rate_missing=isinstance(exc.__cause__, NoObservationError))
        diag_result = await run_balance_sheet_diagnostics(
            db, user_id, as_of_date=report_date, currency=report_currency, include_restricted=False
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

    stmt_query = (
        select(StatementSummary)
        .where(
            StatementSummary.user_id == user_id,
            StatementSummary.status.not_in((BankStatementStatus.RETIRED, BankStatementStatus.REJECTED)),
        )
        .order_by(StatementSummary.period_start.asc().nulls_last(), StatementSummary.created_at.asc())
    )
    raw_statements = (await db.scalars(stmt_query)).all()
    pending_statuses = {BankStatementStatus.UPLOADED, BankStatementStatus.PARSING, BankStatementStatus.PARSED}
    pending_count = sum(1 for s in raw_statements if s.status in pending_statuses)

    earliest_statement_month: str | None = None
    latest_statement_month: str | None = None
    anchor_date = report_date
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

    window_months = [
        f"{y:04d}-{m:02d}"
        for i in range(11, -1, -1)
        for y, m in (_shift_months(anchor_date.year, anchor_date.month, -i),)
    ]

    account_ids = {s.account_id for s in raw_statements if s.account_id is not None}
    account_names_by_id: dict[UUID, str] = (
        {
            aid: name
            for aid, name in (
                await db.execute(
                    select(Account.id, Account.name).where(Account.id.in_(account_ids), Account.user_id == user_id)
                )
            ).all()
        }
        if account_ids
        else {}
    )

    statements_by_account: dict[str, list[StatementSummary]] = {}
    for st in raw_statements:
        if st.status != BankStatementStatus.APPROVED or st.period_start is None:
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
        ordered = sorted(acc_stmts, key=StatementSummary.chain_sort_key)
        for s_prev, s_next in zip(ordered, ordered[1:], strict=False):
            if s_prev.period_end is None or s_next.period_start is None:
                continue
            prev_month = s_prev.period_end.strftime("%Y-%m")
            next_month = s_next.period_start.strftime("%Y-%m")
            missing_months = tuple(_months_between_exclusive(prev_month, next_month))
            has_date_gap = (s_next.period_start - s_prev.period_end).days > 1 or bool(missing_months)
            prev_close = s_prev.closing_balance
            next_open = s_next.effective_opening_balance()
            if prev_close is not None and next_open is not None:
                delta = next_open - prev_close
                abs_delta = abs(delta)
                scale = max(abs(prev_close), abs(next_open), Decimal("100"))
                rel_ratio = Ratio.fraction(abs_delta, scale)
            else:
                delta = abs_delta = Decimal("0")
                scale = Decimal("100")
                rel_ratio = Ratio.zero()

            if not has_date_gap and abs_delta <= account_service.CROSS_PERIOD_GAP_PLUG_TOLERANCE:
                continue

            if abs_delta <= account_service.CROSS_PERIOD_GAP_PLUG_TOLERANCE:
                tier: Literal["zero_change", "tiny_plug", "material_gap"] = "zero_change"
                zero_change_verified_months.update(missing_months)
            elif rel_ratio.value < Decimal("0.001"):
                tier = "tiny_plug"
                tiny_plug_months.update(missing_months or (next_month,))
            else:
                tier = "material_gap"
                material_gap_months.update(missing_months or (next_month,))

            st_acc_id = s_next.account_id or s_prev.account_id
            label = (
                account_names_by_id.get(st_acc_id) or s_next.institution or "Account"
                if st_acc_id
                else (s_next.institution or s_prev.institution or "Account")
            )
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
        (g for g in gap_diagnostics if g.tier == "material_gap"),
        key=lambda g: (g.abs_delta, g.relative_ratio.value),
        reverse=True,
    )
    tiny_gaps = [g for g in gap_diagnostics if g.tier == "tiny_plug"]

    month_buckets: list[MonthContinuityBucket] = []
    total_gaps = 0
    first_gap_month: str | None = None

    for m_key in window_months:
        st_list = statements_by_month.get(m_key, [])
        if st_list:
            open_bal = st_list[0].effective_opening_balance()
            close_bal = st_list[-1].closing_balance
            month_buckets.append(
                MonthContinuityBucket(
                    month=m_key,
                    statement_count=len(st_list),
                    has_gap=False,
                    opening_balance=open_bal,
                    closing_balance=close_bal,
                    net_movement=close_bal - open_bal if open_bal is not None and close_bal is not None else None,
                    status="PENDING_PROCESSING" if any(s.status in pending_statuses for s in st_list) else "HEALTHY",
                )
            )
        else:
            in_span = (
                earliest_statement_month is not None
                and latest_statement_month is not None
                and earliest_statement_month <= m_key <= latest_statement_month
            )
            is_verified = m_key in (zero_change_verified_months | tiny_plug_months) and m_key not in material_gap_months
            is_gap = in_span and not is_verified
            if is_gap:
                total_gaps += 1
                first_gap_month = first_gap_month or m_key
                status_missing: ContinuityStatus = "GAP_DETECTED"
            else:
                status_missing = "HEALTHY" if in_span and is_verified else "NO_DATA"
            month_buckets.append(
                MonthContinuityBucket(
                    month=m_key,
                    statement_count=0,
                    has_gap=is_gap,
                    opening_balance=None,
                    closing_balance=None,
                    net_movement=None,
                    status=status_missing,
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
            .where(JournalEntry.user_id == user_id, JournalEntry.status == JournalEntryStatus.POSTED)
        )
        or 0
    )
    has_unanchored_activity = not raw_statements and (stats.total_transactions > 0 or posted_entry_count > 0)

    temporal_healthy = total_gaps == 0 and not has_unanchored_activity
    temporal_delta = total_gaps if not has_unanchored_activity else 1
    gap_code = account_service.UNEXPLAINED_GAP_EQUITY_CODE
    if temporal_healthy:
        if tiny_gaps:
            tiny_total = sum((g.abs_delta for g in tiny_gaps), Decimal("0"))
            temporal_summary = (
                f"Statement anchors verified (minor cross-period rounding absorbed in {gap_code} Gap Equity)"
            )
            temporal_detail = (
                f"Minor cross-period variance ({tiny_total:.2f}) is within 0.1% materiality and absorbed in "
                f"Unexplained Statement Gap Equity ({gap_code}); no missing statement upload required."
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
        temporal_summary = f"{total_gaps} missing month gap(s) detected in financial timeline"
        temporal_detail = (
            f"Statement missing for {gap_period_str} on {top_gap.account_label} "
            f"(unexplained movement {top_gap.delta:+.2f} {top_gap.currency}, {top_gap.relative_ratio.format_percent()} of balance; "
            f"currently parked in {gap_code} Unexplained Statement Gap Equity). "
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

    recon_healthy = stats.pending_review == 0 and stats.unmatched_transactions == 0 and not has_unanchored_activity
    recon_delta = (
        stats.pending_review
        or stats.unmatched_transactions
        or (max(1, posted_entry_count) if has_unanchored_activity else 0)
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

    equation_pts = 40 if equation_healthy else 0
    temporal_pts = (
        25 if temporal_healthy else (15 if has_unanchored_activity or total_gaps == 1 else max(0, 25 - total_gaps * 10))
    )
    if stats.total_transactions == 0:
        recon_pts = 10 if has_unanchored_activity else 20
    else:
        recon_pts = int(round(20 * min(1.0, stats.matched_transactions / max(1, stats.total_transactions))))
        if stats.pending_review > 0:
            recon_pts = max(0, recon_pts - min(10, stats.pending_review * 2))
    lineage_pts = 15 if lineage_healthy else 5

    total_score = max(0, min(100, equation_pts + temporal_pts + recon_pts + lineage_pts))
    grade = (
        QualityGrade.A_AUDIT_READY
        if total_score >= 95
        else QualityGrade.B_BALANCED_GAPS
        if total_score >= 80
        else QualityGrade.C_ATTENTION_NEEDED
        if total_score >= 60
        else QualityGrade.D_OUT_OF_BALANCE
    )

    action_items: list[QualityActionItem] = []
    if not equation_healthy:
        action_items.append(
            _action(
                "resolve_equation_delta",
                "P0",
                "Resolve Balance Sheet Imbalance",
                diag_result.suggested_action,
                40,
                "RESOLVE_EQUATION",
                "/journal",
            )
        )
    if fx_gap is not None:
        action_items.append(
            _action(
                "resolve_valuation_fx_rate",
                "P1",
                (
                    "A Restricted Holding Has No FX Rate"
                    if fx_gap.rate_missing
                    else f"A Restricted Holding Did Not Convert to {report_currency}"
                ),
                (
                    f"The full net worth cannot convert a restricted or illiquid valuation: {fx_gap.message}. "
                    + (
                        "The rate sync adds the rate; "
                        if fx_gap.rate_missing
                        else "The stored rate does not convert this amount; "
                    )
                    + f"you can also record the valuation in {report_currency}."
                ),
                0,
                "RESOLVE_FX_RATE",
                "/portfolio?panel=evidence",
            )
        )
    if pending_count > 0:
        action_items.append(
            _action(
                "review_pending_statements",
                "P1",
                f"Review {pending_count} Pending Statement(s)",
                "Approve or confirm parsed statements so balances reflect in your ledger.",
                min(20, pending_count * 5),
                "REVIEW_STATEMENT",
                "/upload",
            )
        )

    if has_unanchored_activity:
        action_items.append(
            _action(
                "upload_statements_for_ledger",
                "P1",
                "Upload Bank Statements to Anchor Ledger Activity",
                "Ledger entries exist without uploaded bank statement evidence. Upload statements to verify rollforward and lineage.",
                min(30, 100 - total_score),
                "UPLOAD_STATEMENT",
                "/upload",
            )
        )
    elif material_gaps:
        total_unexplained = sum((g.abs_delta for g in material_gaps), Decimal("0"))
        for gap_diag in material_gaps:
            first_m = gap_diag.missing_months[0]
            period_label = first_m if len(gap_diag.missing_months) == 1 else f"{first_m}..{gap_diag.missing_months[-1]}"
            share_pct = (
                Ratio.fraction(gap_diag.abs_delta, total_unexplained)
                if total_unexplained > 0
                else Ratio.from_percent(100)
            ).to_percent(dp=0)
            action_items.append(
                _action(
                    f"upload_statement_{gap_diag.account_key}_{first_m}",
                    "P1" if gap_diag.relative_ratio.value >= Decimal("0.01") else "P2",
                    f"Upload Statement for {period_label} ({gap_diag.account_label})",
                    (
                        f"Missing statement for {period_label} on {gap_diag.account_label} leaves "
                        f"{gap_diag.delta:+.2f} {gap_diag.currency} ({gap_diag.relative_ratio.to_percent()}% of balance) in "
                        f"3198 Unexplained Statement Gap Equity. Uploading it resolves {share_pct}% "
                        "of unexplained cash flow and P&L variance."
                    ),
                    10,
                    "UPLOAD_STATEMENT",
                    f"/upload?month={first_m}",
                )
            )
    elif total_gaps > 0 and first_gap_month is not None:
        action_items.append(
            _action(
                f"upload_statement_{first_gap_month}",
                "P1",
                f"Upload Statement for {first_gap_month}",
                f"Missing statement for {first_gap_month} breaks temporal cash rollforward continuity.",
                10,
                "UPLOAD_STATEMENT",
                f"/upload?month={first_gap_month}",
            )
        )

    if stats.pending_review > 0:
        action_items.append(
            _action(
                "confirm_reconciliation_matches",
                "P2",
                f"Confirm {stats.pending_review} Reconciliation Match(es)",
                "Confirm transfer and credit card settlement matches to ensure zero P&L leakage.",
                min(10, stats.pending_review * 2),
                "RECONCILE_TRANSACTIONS",
                "/reconciliation",
            )
        )
    elif stats.unmatched_transactions > 0:
        action_items.append(
            _action(
                "reconcile_unmatched_transactions",
                "P2",
                f"Reconcile {stats.unmatched_transactions} Unmatched Transaction(s)",
                "Match or classify unmatched statement transactions in the reconciliation workbench.",
                min(15, max(2, 20 - recon_pts)),
                "RECONCILE_TRANSACTIONS",
                "/reconciliation?tab=unmatched",
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
