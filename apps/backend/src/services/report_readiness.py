"""Report package readiness derivation."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import (
    Account,
    AccountType,
    AtomicPosition,
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    CheckStatus,
    ConsistencyCheck,
    Direction,
    DividendIncome,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ManualValuationSnapshot,
    MarketDataOverride,
    ReconciliationMatch,
    ReconciliationStatus,
    ReportSnapshot,
    Stage1Status,
    StockPrice,
)
from src.models.layer2 import AssetType
from src.schemas.reporting import (
    FrameworkPolicyResult,
    PersonalReportingFrameworkId,
    PolicyDimension,
    PolicyProvenance,
    PolicyReviewState,
)
from src.services.framework_policy import derive_user_framework_policy_result
from src.services.fx import FxRateError, convert_amount

PACKAGE_ID = "personal-financial-report-package"
MARKET_DATA_STALE_AFTER_DAYS = 90
FRAMEWORK_POLICY_ACTION_HREF = "/reports/package"


def _sorted(values: set[str]) -> list[str]:
    return sorted(values)


def _blocker(
    code: str,
    label: str,
    count: int,
    reason: str,
    action_href: str,
    severity: str = "blocking",
) -> dict[str, str | int]:
    return {
        "code": code,
        "label": label,
        "severity": severity,
        "count": count,
        "reason": reason,
        "action_href": action_href,
    }


async def _count(db: AsyncSession, statement) -> int:
    return int(await db.scalar(statement) or 0)


async def _max_updated_at(db: AsyncSession, statement) -> datetime | None:
    return await db.scalar(statement)


async def _processing_account_balance(db: AsyncSession, user_id: UUID) -> Decimal:
    result = await db.execute(
        select(Account).where(
            Account.user_id == user_id,
            Account.is_system == True,  # noqa: E712
            Account.code == "1199",
        )
    )
    processing_account = result.scalar_one_or_none()
    if processing_account is None:
        return Decimal("0.00")

    result = await db.execute(
        select(JournalLine.direction, JournalLine.amount, JournalLine.currency, JournalEntry.entry_date)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == processing_account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )
    target_currency = settings.base_currency.strip().upper()
    total = Decimal("0.00")
    for direction, amount, source_currency, entry_date in result.all():
        signed_amount = amount if direction == Direction.DEBIT else -amount
        total += await convert_amount(
            db,
            amount=signed_amount,
            currency=source_currency or processing_account.currency or target_currency,
            target_currency=target_currency,
            rate_date=entry_date,
            lazy_load=True,
        )
    return total


def _normalize_framework_id(
    framework_id: PersonalReportingFrameworkId | str | None,
) -> PersonalReportingFrameworkId | None:
    if framework_id is None:
        return None
    if isinstance(framework_id, PersonalReportingFrameworkId):
        return framework_id
    return PersonalReportingFrameworkId(framework_id)


def framework_policy_readiness_blockers(
    *,
    framework_id: PersonalReportingFrameworkId | str | None,
    policy_result: FrameworkPolicyResult | None,
    report_input_count: int,
    missing_valuation_basis_count: int,
    stale_market_data_count: int,
) -> list[dict[str, str | int]]:
    """Translate selected-framework policy deficiencies into readiness blockers."""
    blockers: list[dict[str, str | int]] = []
    try:
        selected_framework_id = _normalize_framework_id(framework_id)
    except ValueError:
        return [
            _blocker(
                "unsupported_framework",
                "Unsupported framework",
                1,
                "The selected reporting framework is not supported for personal report generation.",
                "/reports/package",
            )
        ]

    if selected_framework_id is None:
        return blockers

    if policy_result is None:
        if report_input_count:
            blockers.append(
                _blocker(
                    "missing_framework_policy_result",
                    "Missing framework policy result",
                    1,
                    "A selected framework requires a structured policy result before trusted output can be generated.",
                    FRAMEWORK_POLICY_ACTION_HREF,
                )
            )
        return blockers

    if policy_result.framework_id != selected_framework_id:
        blockers.append(
            _blocker(
                "missing_framework_policy_result",
                "Framework policy result mismatch",
                1,
                "The available policy result does not match the selected reporting framework.",
                FRAMEWORK_POLICY_ACTION_HREF,
            )
        )

    if report_input_count and not policy_result.decisions and not policy_result.gaps:
        blockers.append(
            _blocker(
                "missing_framework_policy_result",
                "Missing framework policy result",
                1,
                "The selected framework produced no structured policy decisions or explicit policy gaps for the available package inputs.",
                FRAMEWORK_POLICY_ACTION_HREF,
            )
        )

    gap_counts: dict[str, int] = {}
    for gap in policy_result.gaps:
        if gap.blocker:
            gap_counts[gap.code] = gap_counts.get(gap.code, 0) + 1
    for code, count in sorted(gap_counts.items()):
        blockers.append(
            _blocker(
                code,
                "Unsupported policy domain" if code == "unsupported_policy_domain" else "Framework policy gap",
                count,
                "A selected-framework policy gap must be remediated before the package can be trusted.",
                FRAMEWORK_POLICY_ACTION_HREF,
            )
        )

    missing_dimension_count = sum(
        1
        for decision in policy_result.decisions
        if any(not getattr(decision, dimension.value, None) for dimension in PolicyDimension)
    )
    if missing_dimension_count:
        blockers.append(
            _blocker(
                "framework_policy_missing_dimensions",
                "Incomplete framework policy decision",
                missing_dimension_count,
                "Every policy decision must include recognition, measurement, classification, presentation, and disclosure.",
                FRAMEWORK_POLICY_ACTION_HREF,
            )
        )

    unreviewed_ai_count = sum(
        1
        for decision in policy_result.decisions
        if decision.provenance == PolicyProvenance.REVIEWED_AI_SUGGESTION
        and (
            decision.review_state != PolicyReviewState.ACCEPTED
            or not decision.policy_field_name
            or not decision.accepted_value
            or not decision.evidence_anchors
        )
    )
    if unreviewed_ai_count:
        blockers.append(
            _blocker(
                "framework_ai_suggestion_unreviewed",
                "Unreviewed AI policy suggestion",
                unreviewed_ai_count,
                "AI-suggested measurement or disclosure fields require source anchors, review acceptance, and accepted structured values.",
                "/review",
            )
        )

    if missing_valuation_basis_count:
        blockers.append(
            _blocker(
                "missing_valuation_basis",
                "Missing valuation basis",
                missing_valuation_basis_count,
                "Manual or private valuation facts need an explicit valuation basis before trusted totals can be generated.",
                "/assets/manual-valuations",
            )
        )

    if stale_market_data_count:
        blockers.append(
            _blocker(
                "stale_market_data",
                "Stale market data",
                stale_market_data_count,
                f"Listed security and fund positions need market prices dated within {MARKET_DATA_STALE_AFTER_DAYS} days of the report date.",
                "/portfolio/market-data",
            )
        )

    return blockers


async def _missing_valuation_basis_count(db: AsyncSession, user_id: UUID, *, as_of_date: date) -> int:
    rows = await db.execute(
        select(ManualValuationSnapshot.notes)
        .where(ManualValuationSnapshot.user_id == user_id)
        .where(ManualValuationSnapshot.as_of_date <= as_of_date)
    )
    return sum(1 for notes in rows.scalars().all() if notes is None or not notes.strip())


async def _stale_market_data_count(db: AsyncSession, user_id: UUID, *, as_of_date: date) -> int:
    investable_asset_types = [
        AssetType.STOCK,
        AssetType.ETF,
        AssetType.MUTUAL_FUND,
        AssetType.BOND,
    ]
    position_rows = await db.execute(
        select(AtomicPosition.asset_identifier)
        .where(AtomicPosition.user_id == user_id)
        .where(AtomicPosition.snapshot_date <= as_of_date)
        .where(AtomicPosition.asset_type.in_(investable_asset_types))
        .distinct()
    )
    asset_identifiers = list(position_rows.scalars().all())
    if not asset_identifiers:
        return 0
    normalized_asset_identifiers = [asset_identifier.strip().upper() for asset_identifier in asset_identifiers]

    override_rows = await db.execute(
        select(MarketDataOverride)
        .where(MarketDataOverride.user_id == user_id)
        .where(func.upper(MarketDataOverride.asset_identifier).in_(normalized_asset_identifiers))
        .where(MarketDataOverride.price_date <= as_of_date)
        .order_by(MarketDataOverride.price_date.desc(), MarketDataOverride.created_at.desc())
    )
    latest_price_date_by_identifier: dict[str, date] = {}
    for override in override_rows.scalars().all():
        latest_price_date_by_identifier.setdefault(override.asset_identifier.strip().upper(), override.price_date)

    stock_price_rows = await db.execute(
        select(StockPrice)
        .where(func.upper(StockPrice.symbol).in_(normalized_asset_identifiers))
        .where(StockPrice.price_date <= as_of_date)
        .order_by(StockPrice.price_date.desc(), StockPrice.created_at.desc())
    )
    for stock_price in stock_price_rows.scalars().all():
        matching_identifier = stock_price.symbol.strip().upper()
        current_price_date = latest_price_date_by_identifier.get(matching_identifier)
        if current_price_date is None or stock_price.price_date > current_price_date:
            latest_price_date_by_identifier[matching_identifier] = stock_price.price_date

    freshness_cutoff = as_of_date - timedelta(days=MARKET_DATA_STALE_AFTER_DAYS)
    return sum(
        1
        for asset_identifier in normalized_asset_identifiers
        if latest_price_date_by_identifier.get(asset_identifier) is None
        or latest_price_date_by_identifier[asset_identifier] < freshness_cutoff
    )


async def get_personal_report_package_readiness(
    db: AsyncSession,
    user_id: UUID,
    *,
    framework_id: PersonalReportingFrameworkId | str | None = None,
    report_period_start: date | None = None,
    report_period_end: date | None = None,
    as_of_date: date | None = None,
) -> dict:
    """Return deterministic readiness for the personal financial-report package."""
    report_as_of = as_of_date or report_period_end or date.today()
    report_end = report_period_end or report_as_of
    report_start = report_period_start or report_end - timedelta(days=365)
    statement_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(BankStatement.user_id == user_id),
    )
    active_account_count = await _count(
        db,
        select(func.count(Account.id)).where(
            Account.user_id == user_id,
            Account.is_active == True,  # noqa: E712
            Account.is_system == False,  # noqa: E712
        ),
    )
    journal_entry_count = await _count(
        db,
        select(func.count(JournalEntry.id)).where(
            JournalEntry.user_id == user_id,
            JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]),
        ),
    )
    position_count = await _count(
        db,
        select(func.count(AtomicPosition.id)).where(AtomicPosition.user_id == user_id),
    )
    manual_valuation_count = await _count(
        db,
        select(func.count(ManualValuationSnapshot.id)).where(ManualValuationSnapshot.user_id == user_id),
    )
    dividend_count = await _count(
        db,
        select(func.count(DividendIncome.id)).where(DividendIncome.user_id == user_id),
    )
    market_price_count = await _count(
        db,
        select(func.count(MarketDataOverride.id)).where(MarketDataOverride.user_id == user_id),
    )
    policy_account_count = await _count(
        db,
        select(func.count(Account.id)).where(
            Account.user_id == user_id,
            Account.is_active == True,  # noqa: E712
            Account.is_system == False,  # noqa: E712
            Account.type.in_([AccountType.ASSET, AccountType.LIABILITY, AccountType.INCOME]),
        ),
    )

    source_summary = {
        "statements": statement_count,
        "active_accounts": active_account_count,
        "posted_journal_entries": journal_entry_count,
        "positions": position_count,
        "manual_valuations": manual_valuation_count,
        "dividends": dividend_count,
        "market_prices": market_price_count,
    }
    framework_policy_input_count = policy_account_count + position_count + manual_valuation_count + dividend_count
    source_classes: set[str] = set()
    deterministic_pr_source_classes: set[str] = set()
    post_merge_llm_ocr_source_classes: set[str] = set()
    manual_trusted_source_classes: set[str] = set()
    gap_source_classes: set[str] = set()
    if statement_count:
        source_classes.update({"bank_statement", "csv_export"})
        deterministic_pr_source_classes.update({"bank_statement", "csv_export"})
        post_merge_llm_ocr_source_classes.add("bank_statement")
    if position_count:
        source_classes.add("brokerage_statement")
        deterministic_pr_source_classes.add("brokerage_statement")
        post_merge_llm_ocr_source_classes.add("brokerage_statement")
    if manual_valuation_count:
        source_classes.update({"property_statement", "liability_statement", "esop_rsu_plan", "manual_record"})
        deterministic_pr_source_classes.update(
            {"property_statement", "liability_statement", "esop_rsu_plan", "manual_record"}
        )
        manual_trusted_source_classes.update(
            {"property_statement", "liability_statement", "esop_rsu_plan", "manual_record"}
        )
    if journal_entry_count:
        source_classes.add("manual_record")
        deterministic_pr_source_classes.add("manual_record")
    report_input_count = (
        statement_count
        + journal_entry_count
        + position_count
        + manual_valuation_count
        + dividend_count
        + market_price_count
    )

    blockers: list[dict[str, str | int]] = []
    processing_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(
            BankStatement.user_id == user_id,
            BankStatement.status.in_([BankStatementStatus.UPLOADED, BankStatementStatus.PARSING]),
        ),
    )

    failed_parsing_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(
            BankStatement.user_id == user_id,
            BankStatement.status == BankStatementStatus.REJECTED,
        ),
    )
    if failed_parsing_count:
        blockers.append(
            _blocker(
                "failed_parsing",
                "Failed statement parsing",
                failed_parsing_count,
                "One or more uploaded statements failed parsing and cannot support a trusted package.",
                "/statements",
            )
        )

    pending_review_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(
            BankStatement.user_id == user_id,
            BankStatement.stage1_status == Stage1Status.PENDING_REVIEW,
        ),
    )
    if pending_review_count:
        blockers.append(
            _blocker(
                "pending_review",
                "Pending source review",
                pending_review_count,
                "Statement review must be completed before the package can be marked ready.",
                "/review",
            )
        )

    balance_mismatch_count = await _count(
        db,
        select(func.count(BankStatement.id)).where(
            BankStatement.user_id == user_id,
            (BankStatement.balance_validated == False) | (BankStatement.validation_error.is_not(None)),  # noqa: E712
        ),
    )
    if balance_mismatch_count:
        blockers.append(
            _blocker(
                "balance_mismatch",
                "Balance validation mismatch",
                balance_mismatch_count,
                "Opening and closing balances must validate before report totals are trusted.",
                "/review",
            )
        )

    reconciliation_blocker_count = await _count(
        db,
        select(func.count(ReconciliationMatch.id))
        .join(BankStatementTransaction, ReconciliationMatch.bank_txn_id == BankStatementTransaction.id)
        .join(BankStatement, BankStatementTransaction.statement_id == BankStatement.id)
        .where(BankStatement.user_id == user_id)
        .where(ReconciliationMatch.status == ReconciliationStatus.PENDING_REVIEW),
    )
    if reconciliation_blocker_count:
        blockers.append(
            _blocker(
                "reconciliation_blocked",
                "Reconciliation blockers",
                reconciliation_blocker_count,
                "Pending reconciliation matches must be accepted or rejected before report readiness.",
                "/reconciliation/review-queue",
            )
        )

    consistency_blocker_count = await _count(
        db,
        select(func.count(ConsistencyCheck.id)).where(
            ConsistencyCheck.user_id == user_id,
            ConsistencyCheck.status == CheckStatus.PENDING,
        ),
    )
    if consistency_blocker_count:
        blockers.append(
            _blocker(
                "consistency_check_blocked",
                "Consistency checks pending",
                consistency_blocker_count,
                "Duplicate, transfer-pair, or anomaly checks must be resolved before package output is trusted.",
                "/review",
            )
        )

    try:
        processing_balance = (await _processing_account_balance(db, user_id)).quantize(Decimal("0.01"))
    except FxRateError as exc:
        blockers.append(
            _blocker(
                "processing_account_unresolved",
                "Processing account unresolved",
                1,
                f"Processing account balance cannot be converted to {settings.base_currency.strip().upper()}: {exc}",
                "/accounts/processing",
            )
        )
    else:
        if processing_balance != Decimal("0.00"):
            blockers.append(
                _blocker(
                    "processing_account_unresolved",
                    "Processing account unresolved",
                    1,
                    f"Processing account balance is {processing_balance} {settings.base_currency.strip().upper()}; in-transit transfer legs must net to zero.",
                    "/accounts/processing",
                )
            )

    approved_statement_accounts = select(BankStatement.account_id).where(
        BankStatement.user_id == user_id,
        BankStatement.account_id.is_not(None),
        BankStatement.status == BankStatementStatus.APPROVED,
    )
    missing_coverage_count = await _count(
        db,
        select(func.count(Account.id)).where(
            Account.user_id == user_id,
            Account.is_active == True,  # noqa: E712
            Account.is_system == False,  # noqa: E712
            Account.type.in_([AccountType.ASSET, AccountType.LIABILITY]),
            ~Account.id.in_(approved_statement_accounts),
        ),
    )
    if report_input_count and missing_coverage_count:
        blockers.append(
            _blocker(
                "missing_source_coverage",
                "Missing source coverage",
                missing_coverage_count,
                "Active asset or liability accounts need approved statement coverage or explicit source anchoring.",
                "/accounts/coverage",
            )
        )

    selected_framework_id: PersonalReportingFrameworkId | None = None
    policy_result: FrameworkPolicyResult | None = None
    missing_valuation_basis_count = 0
    stale_market_data_count = 0
    try:
        selected_framework_id = _normalize_framework_id(framework_id)
    except ValueError:
        pass
    if selected_framework_id is not None:
        policy_result = await derive_user_framework_policy_result(
            db,
            user_id,
            framework_id=selected_framework_id,
            report_period_start=report_start,
            report_period_end=report_end,
            as_of_date=report_as_of,
        )
        missing_valuation_basis_count = await _missing_valuation_basis_count(db, user_id, as_of_date=report_as_of)
        stale_market_data_count = await _stale_market_data_count(db, user_id, as_of_date=report_as_of)
        source_summary.update(
            {
                "selected_framework_id": selected_framework_id.value,
                "framework_policy_inputs": framework_policy_input_count,
                "framework_policy_decisions": len(policy_result.decisions),
                "framework_policy_gaps": len(policy_result.gaps),
            }
        )
    blockers.extend(
        framework_policy_readiness_blockers(
            framework_id=framework_id,
            policy_result=policy_result,
            report_input_count=framework_policy_input_count,
            missing_valuation_basis_count=missing_valuation_basis_count,
            stale_market_data_count=stale_market_data_count,
        )
    )
    blocker_codes = {str(blocker["code"]) for blocker in blockers}
    if "missing_source_coverage" in blocker_codes:
        gap_source_classes.add("manual_record")
    if "pending_review" in blocker_codes or "balance_mismatch" in blocker_codes:
        gap_source_classes.add("bank_statement")
    if "stale_market_data" in blocker_codes:
        gap_source_classes.add("brokerage_statement")

    latest_snapshot_count = await _count(
        db,
        select(func.count(ReportSnapshot.id)).where(
            ReportSnapshot.user_id == user_id,
            ReportSnapshot.is_latest == True,  # noqa: E712
        ),
    )
    latest_snapshot_updated_at = await _max_updated_at(
        db,
        select(func.max(ReportSnapshot.updated_at)).where(
            ReportSnapshot.user_id == user_id,
            ReportSnapshot.is_latest == True,  # noqa: E712
        ),
    )

    source_updated_at_candidates = [
        await _max_updated_at(db, select(func.max(BankStatement.updated_at)).where(BankStatement.user_id == user_id)),
        await _max_updated_at(db, select(func.max(JournalEntry.updated_at)).where(JournalEntry.user_id == user_id)),
        await _max_updated_at(db, select(func.max(AtomicPosition.updated_at)).where(AtomicPosition.user_id == user_id)),
        await _max_updated_at(
            db, select(func.max(ManualValuationSnapshot.updated_at)).where(ManualValuationSnapshot.user_id == user_id)
        ),
        await _max_updated_at(db, select(func.max(DividendIncome.updated_at)).where(DividendIncome.user_id == user_id)),
        await _max_updated_at(
            db, select(func.max(MarketDataOverride.updated_at)).where(MarketDataOverride.user_id == user_id)
        ),
    ]
    source_updated_at = max((value for value in source_updated_at_candidates if value is not None), default=None)

    if processing_count and not blockers:
        state = "processing"
        label = "Processing"
        action_href = "/statements"
    elif blockers:
        state = "blocked"
        label = "Blocked"
        action_href = str(blockers[0]["action_href"])
    elif (
        latest_snapshot_count
        and latest_snapshot_updated_at
        and source_updated_at
        and source_updated_at > latest_snapshot_updated_at
    ):
        state = "stale"
        label = "Stale"
        action_href = "/reports/package"
    elif latest_snapshot_count:
        state = "generated"
        label = "Generated"
        action_href = "/reports/package"
    elif report_input_count:
        state = "ready"
        label = "Ready"
        action_href = "/reports/package"
    else:
        state = "draft"
        label = "Draft"
        action_href = "/statements/upload"

    return {
        "package_id": PACKAGE_ID,
        "state": state,
        "label": label,
        "action_href": action_href,
        "blocking_count": sum(int(blocker["count"]) for blocker in blockers),
        "blockers": blockers,
        "source_summary": source_summary,
        "source_trust_summary": {
            "source_classes": _sorted(source_classes),
            "deterministic_pr_source_classes": _sorted(deterministic_pr_source_classes),
            "post_merge_llm_ocr_source_classes": _sorted(post_merge_llm_ocr_source_classes),
            "manual_trusted_source_classes": _sorted(manual_trusted_source_classes),
            "gap_source_classes": _sorted(gap_source_classes),
            "blocker_codes": sorted(blocker_codes),
        },
        "generated_at": latest_snapshot_updated_at,
        "stale_since": source_updated_at if state == "stale" else None,
    }
