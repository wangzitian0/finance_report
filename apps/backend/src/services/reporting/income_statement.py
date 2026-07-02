"""Income statement generation."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.error_ids import ErrorIds
from src.logger import get_logger
from src.models.account import Account, AccountType
from src.models.journal import JournalEntry, JournalLine
from src.schemas.provenance import DataProvenance
from src.services.fx import (
    FxRateError,
    FxWarning,
    PrefetchedFxRates,
    convert_money,
)
from src.services.reporting._core import (
    _REPORT_STATUSES,
    _aggregate_account_confidence_tiers,
    _build_account_lines,
    _line_total,
    _load_accounts,
)
from src.services.reporting.balance_sheet import generate_balance_sheet
from src.services.reporting.internal_transfer import _internal_transfer_adjustment
from src.services.reporting_calc import (
    ReportError,
    _add_months,
    _combine_provenance,
    _month_end,
    _month_start,
    _normalize_currency,
    _provenance_from_source_type,
    _quantize_money,
    _signed_amount,
)

logger = get_logger(__name__)


async def generate_income_statement(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    currency: str | None = None,
    tags: list[str] | None = None,
    account_type: AccountType | None = None,
) -> dict[str, object]:
    """Generate income statement report for a date range."""
    if start_date > end_date:
        raise ReportError("start_date must be before end_date")

    target_currency = _normalize_currency(currency)
    fx_warnings: list[FxWarning] = []

    account_types: tuple[AccountType, ...]
    if account_type:
        account_types = (account_type,)
    else:
        account_types = (AccountType.INCOME, AccountType.EXPENSE)

    accounts = await _load_accounts(db, user_id, account_types)
    balances: dict[UUID, Decimal] = {account.id: Decimal("0") for account in accounts}

    period_totals: dict[date, dict[str, Decimal]] = {}

    stmt = (
        select(JournalLine, Account, JournalEntry)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type.in_(account_types))
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date >= start_date)
        .where(JournalEntry.entry_date <= end_date)
    )
    result = await db.execute(stmt)

    entries_by_id: dict[UUID, list[tuple[JournalLine, Account, JournalEntry]]] = {}
    fx_needs: list[tuple[str, str, date, date | None, date | None]] = []

    for line, account, entry in result.all():
        if entry.id not in entries_by_id:
            entries_by_id[entry.id] = []
        entries_by_id[entry.id].append((line, account, entry))

        # Collect FX needs for pre-fetching
        if line.currency != target_currency:
            # Period average need
            fx_needs.append((line.currency, target_currency, end_date, start_date, end_date))
            # Monthly average need
            period_key = _month_start(entry.entry_date)
            month_end = _add_months(period_key, 1) - timedelta(days=1)
            fx_needs.append((line.currency, target_currency, entry.entry_date, period_key, month_end))

    # Batch pre-fetch all needed FX rates
    fx_rates = PrefetchedFxRates(fx_warnings, lazy_load=True)
    if fx_needs:
        try:
            await fx_rates.prefetch(db, fx_needs)
        except FxRateError as exc:
            logger.error(
                "FX pre-fetch failed for income statement",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                error=str(exc),
            )
            raise ReportError(str(exc)) from exc

    # Matched internal (own-account) transfers (#1123 AC3): exclude their legs from
    # income/expense so they do not double-count; only the fee is a real expense.
    transfer_adjustment = await _internal_transfer_adjustment(
        db, user_id, target_currency, end_date, start_date=start_date
    )
    excluded_entry_ids = transfer_adjustment.excluded_entry_ids

    entries_to_include: set[UUID] = set()
    if tags:
        for entry_id, lines_and_accounts in entries_by_id.items():
            for line, account, entry in lines_and_accounts:
                if line.tags:
                    line_tags = set(k.lower() for k in line.tags.keys())
                    if any(t.lower() in line_tags for t in tags):
                        entries_to_include.add(entry_id)
                        break
    else:
        entries_to_include = set(entries_by_id.keys())
    entries_to_include -= excluded_entry_ids

    provenance_inputs_by_account: dict[UUID, list[DataProvenance | None]] = {}
    for entry_id, lines_and_accounts in entries_by_id.items():
        if entry_id not in entries_to_include:
            continue

        for line, account, entry in lines_and_accounts:
            provenance_inputs_by_account.setdefault(account.id, []).append(
                _provenance_from_source_type(entry.source_type)
            )
            # Use pre-fetched rates
            rate_total = fx_rates.get_rate(line.currency, target_currency, end_date, start_date, end_date)
            if rate_total is None:
                # Fallback to slow path if not pre-fetched (should be rare)
                try:
                    converted_total = (
                        await convert_money(
                            db,
                            line.money,
                            target_currency,
                            end_date,
                            average_start=start_date,
                            average_end=end_date,
                            fx_warnings=fx_warnings,
                            lazy_load=True,
                        )
                    ).amount
                except FxRateError as exc:
                    logger.warning(
                        "Average FX rate unavailable, falling back to spot",
                        error_id=ErrorIds.REPORT_FX_FALLBACK,
                        account_id=str(account.id),
                        currency=line.currency,
                        start_date=start_date,
                        end_date=end_date,
                        error=str(exc),
                    )
                    # Fallback to spot rate at end_date
                    try:
                        converted_total = (
                            await convert_money(
                                db,
                                line.money,
                                target_currency,
                                end_date,
                                lazy_load=True,
                            )
                        ).amount
                    except FxRateError as final_exc:
                        logger.error(
                            "All FX rate fallbacks failed for income statement",
                            error_id=ErrorIds.REPORT_GENERATION_FAILED,
                            account_id=str(account.id),
                            error=str(final_exc),
                        )
                        raise ReportError(f"FX conversion failed: {final_exc}") from final_exc
            else:
                converted_total = line.amount * rate_total

            signed_total = _signed_amount(account.type, line.direction, converted_total)
            balances[account.id] += signed_total

            # For monthly trend buckets, use pre-fetched monthly average rate
            period_key = _month_start(entry.entry_date)
            month_end = _add_months(period_key, 1) - timedelta(days=1)
            rate_monthly = fx_rates.get_rate(line.currency, target_currency, entry.entry_date, period_key, month_end)
            if rate_monthly is None:
                # Fallback to period total rate if monthly rate unavailable
                logger.warning(
                    "Monthly average FX rate unavailable for trend, using period average",
                    error_id=ErrorIds.REPORT_FX_FALLBACK,
                    currency=line.currency,
                    month_start=period_key,
                )
                converted_monthly = converted_total
            else:
                converted_monthly = line.amount * rate_monthly

            signed_monthly = _signed_amount(account.type, line.direction, converted_monthly)
            bucket = period_totals.setdefault(period_key, {"income": Decimal("0"), "expense": Decimal("0")})
            if account.type == AccountType.INCOME:
                bucket["income"] += signed_monthly
            else:
                bucket["expense"] += signed_monthly

    provenance_by_account = {
        account_id: _combine_provenance(provenance_values)
        for account_id, provenance_values in provenance_inputs_by_account.items()
    }
    # Per-line confidence tiers (#1483/#1545): derived from the contributing
    # entries' source_type over the reporting window, same as the balance sheet.
    # Income-statement lines previously always carried confidence_tier=None
    # because the tier aggregation was never wired here.
    tiers = await _aggregate_account_confidence_tiers(
        db,
        user_id,
        (AccountType.INCOME, AccountType.EXPENSE),
        end_date,
        start_date=start_date,
    )
    income_lines = _build_account_lines(
        accounts,
        balances,
        AccountType.INCOME,
        tiers=tiers,
        provenance_by_account=provenance_by_account,
    )
    expense_lines = _build_account_lines(
        accounts,
        balances,
        AccountType.EXPENSE,
        tiers=tiers,
        provenance_by_account=provenance_by_account,
    )

    # The matched internal-transfer fee is the only expense that survives netting
    # (#1123 AC3). Materialise it as a real expense LINE attributed to the account
    # it was paid from, rather than bumping total_expenses out of band, so that
    # ``total_expenses == sum(expense_lines)`` holds and the fee shows up in the
    # drill-down and the monthly trend buckets (#1162 CR2).
    fee_account_name_by_id = {account.id: account.name for account in accounts}
    for from_account_id, converted_fee in transfer_adjustment.fee_by_account.items():
        expense_lines.append(
            {
                "account_id": from_account_id,
                "name": fee_account_name_by_id.get(from_account_id, "Internal transfer fee"),
                "type": AccountType.EXPENSE,
                "parent_id": None,
                "amount": _quantize_money(converted_fee),
                "confidence_tier": None,
                "provenance": None,
                "source_currency": target_currency,
                "allocation_asset_class": None,
                "allocation_liquidity_class": None,
                "allocation_source_type": "internal_transfer_fee",
            }
        )

    total_income = _line_total(income_lines)
    total_expenses = _line_total(expense_lines)
    net_income = _quantize_money(total_income - total_expenses)

    # Add the fee into the correct monthly trend/period bucket so the trends and the
    # expense totals stay coherent (#1162 CR2). Bucket by the earliest contributing
    # conversion date; clamp into the reporting window so it always lands in a bucket.
    if transfer_adjustment.fee_total > 0 and transfer_adjustment.fee_trend_date is not None:
        fee_period_key = _month_start(min(max(transfer_adjustment.fee_trend_date, start_date), end_date))
        fee_bucket = period_totals.setdefault(fee_period_key, {"income": Decimal("0"), "expense": Decimal("0")})
        fee_bucket["expense"] += transfer_adjustment.fee_total

    # Calculate Unrealized FX Gain/Loss for the period
    # This requires balance sheets at both points
    bs_start = await generate_balance_sheet(
        db, user_id, as_of_date=start_date - timedelta(days=1), currency=target_currency, include_trust_signals=False
    )
    bs_end = await generate_balance_sheet(
        db, user_id, as_of_date=end_date, currency=target_currency, include_trust_signals=False
    )

    unrealized_fx_change = _quantize_money(
        Decimal(str(bs_end["unrealized_fx_gain_loss"])) - Decimal(str(bs_start["unrealized_fx_gain_loss"]))
    )

    trend_items: list[dict[str, Any]] = []
    for period_start in sorted(period_totals.keys()):
        period_end = _month_end(period_start)
        income_total = _quantize_money(period_totals[period_start]["income"])
        expense_total = _quantize_money(period_totals[period_start]["expense"])
        trend_items.append(
            {
                "period_start": period_start,
                "period_end": min(period_end, end_date),
                "total_income": income_total,
                "total_expenses": expense_total,
                "net_income": _quantize_money(income_total - expense_total),
            }
        )

    # EPIC-018 Phase 4: Layer 3 classification breakdown
    classification_breakdown: list[dict[str, Any]] = []
    try:
        from src.models.layer2 import AtomicTransaction
        from src.models.layer3 import ClassificationStatus, TransactionClassification

        cls_stmt = (
            select(
                Account.name.label("account_name"),
                Account.type.label("account_type"),
                func.count(TransactionClassification.id).label("count"),
                func.avg(TransactionClassification.confidence_score).label("avg_confidence"),
            )
            .join(Account, TransactionClassification.account_id == Account.id)
            .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
            .where(TransactionClassification.status == ClassificationStatus.APPLIED)
            .where(Account.user_id == user_id)
            .where(Account.type.in_(account_types))
            .where(AtomicTransaction.txn_date >= start_date)
            .where(AtomicTransaction.txn_date <= end_date)
            .group_by(Account.name, Account.type)
            .order_by(func.count(TransactionClassification.id).desc())
            .limit(50)
        )
        cls_result = await db.execute(cls_stmt)
        for row in cls_result.all():
            classification_breakdown.append(
                {
                    "account_name": row.account_name,
                    "account_type": row.account_type.value
                    if hasattr(row.account_type, "value")
                    else str(row.account_type),
                    "classified_count": row.count,
                    "avg_confidence": round(float(row.avg_confidence or 0), 1),
                }
            )
    except Exception as e:
        logger.warning(
            "Failed to build classification breakdown, skipping",
            error=str(e),
            error_type=type(e).__name__,
        )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "currency": target_currency,
        "income": income_lines,
        "expenses": expense_lines,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_income": net_income,
        "unrealized_fx_gain_loss": unrealized_fx_change,
        "comprehensive_income": _quantize_money(net_income + unrealized_fx_change),
        "fx_warnings": fx_warnings,
        "trends": trend_items,
        "classification_breakdown": classification_breakdown,
        "filters_applied": {
            "tags": tags,
            "account_type": account_type.value if account_type else None,
        },
    }
