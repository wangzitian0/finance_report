"""Income statement generation."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config_app import get_effective_base_currency
from src.ledger import Account, AccountType, JournalEntry, JournalEntryAuthorityState, JournalLine
from src.ledger.orm.journal import active_journal_entry_filter
from src.observability import ErrorIds, get_logger
from src.pricing import FxWarning, PrefetchedFxRates, PricingError, convert_money
from src.reporting.base.income_statement_calculator import calculate_income_statement_totals
from src.reporting.base.l1_registry import economic_category_line
from src.reporting.extension._core import _build_account_lines, _load_accounts, _prefetch_fx_rates
from src.reporting.extension.balance_sheet import _compute_unrealized_fx_gain_loss
from src.reporting.extension.internal_transfer import _internal_transfer_adjustment
from src.reporting.extension.reporting_calc import (
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
from src.schemas.provenance import DataProvenance

logger = get_logger(__name__)


def _category_lines(lines: list[dict[str, Any]], balances: dict[tuple[UUID, str], Decimal]) -> list[dict[str, Any]]:
    """Split account totals while allocating FX rounding deterministically within each account."""
    by_account: dict[UUID, list[tuple[str, Decimal]]] = defaultdict(list)
    for (account_id, line_id), amount in balances.items():
        by_account[account_id].append((line_id, amount))
    result: list[dict[str, Any]] = []
    for line in lines:
        parts = sorted(by_account.get(line["account_id"], []), key=lambda part: (-abs(part[1]), part[0]))
        if not parts:
            parts = [(economic_category_line(None, line["type"].value).value, Decimal("0"))]
        rounded = [_quantize_money(amount) for _, amount in parts]
        rounded[0] += line["amount"] - sum(rounded, Decimal("0"))
        result.extend(
            {**line, "amount": amount, "economic_report_line_id": line_id}
            for (line_id, _), amount in zip(parts, rounded, strict=True)
        )
    return result


def _fold_and_deduplicate_lines(
    lines: list[dict[str, Any]],
    *,
    filter_zero: bool = True,
) -> list[dict[str, Any]]:
    """Aggregate lines by canonical name, type, currency, and economic category."""
    aggregated: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}
    for line in lines:
        amount = Decimal(str(line.get("amount", "0")))
        name = str(line.get("name", "")).strip()
        key = (name, str(line.get("type", "")), str(line.get("source_currency", "")).upper(), line.get("economic_report_line_id"))
        if key not in aggregated:
            aggregated[key] = {**line, "name": name, "amount": amount}
        else:
            aggregated[key]["amount"] += amount

    return sorted(
        (
            {**line, "amount": _quantize_money(line["amount"])}
            for line in aggregated.values()
            if not (filter_zero and line["amount"] == Decimal("0.00"))
        ),
        key=lambda x: str(x.get("name", "")).lower(),
    )


async def generate_income_statement(
    db: AsyncSession,
    user_id: UUID,
    *,
    start_date: date,
    end_date: date,
    currency: str | None = None,
    tags: list[str] | None = None,
    account_type: AccountType | None = None,
    include_economic_categories: bool = False,
    ending_unrealized_fx_gain_loss: Decimal | None = None,
) -> dict[str, object]:
    """Generate income statement report for a date range."""
    if start_date > end_date:
        raise ReportError("start_date must be before end_date")

    target_currency = _normalize_currency(currency or await get_effective_base_currency(db, user_id=user_id))
    fx_warnings: list[FxWarning] = []
    account_types: tuple[AccountType, ...] = (account_type,) if account_type else (AccountType.INCOME, AccountType.EXPENSE)

    accounts = await _load_accounts(db, user_id, account_types)
    balances: dict[UUID, Decimal] = {account.id: Decimal("0") for account in accounts}
    period_totals: dict[date, dict[str, Decimal]] = {}
    category_balances: dict[tuple[UUID, str], Decimal] = defaultdict(lambda: Decimal("0"))

    stmt = (
        select(JournalLine, Account, JournalEntry)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(
            Account.user_id == user_id,
            Account.type.in_(account_types),
            JournalEntry.user_id == user_id,
            active_journal_entry_filter(JournalEntry),
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
        )
    )
    entries_by_id: dict[UUID, list[tuple[JournalLine, Account, JournalEntry]]] = {}
    fx_needs: list[tuple[str, str, date, date | None, date | None]] = []

    for line, account, entry in (await db.execute(stmt)).all():
        entries_by_id.setdefault(entry.id, []).append((line, account, entry))
        if line.currency != target_currency:
            fx_needs.append((line.currency, target_currency, end_date, start_date, end_date))
            period_key = _month_start(entry.entry_date)
            month_end = _add_months(period_key, 1) - timedelta(days=1)
            fx_needs.append((line.currency, target_currency, entry.entry_date, period_key, month_end))

    fx_rates = await _prefetch_fx_rates(
        db, fx_needs, "income statement", fx_warnings=fx_warnings, prefetched_cls=PrefetchedFxRates
    )
    transfer_adjustment = await _internal_transfer_adjustment(
        db, user_id, target_currency, end_date, start_date=start_date
    )

    if tags:
        wanted = {t.lower() for t in tags}
        entries_to_include = {
            entry_id
            for entry_id, items in entries_by_id.items()
            if any(line.tags and any(k.lower() in wanted for k in line.tags) for line, _, _ in items)
        }
    else:
        entries_to_include = set(entries_by_id)
    entries_to_include -= transfer_adjustment.excluded_entry_ids

    provenance_inputs_by_account: dict[UUID, list[DataProvenance | None]] = {}
    for entry_id, lines_and_accounts in entries_by_id.items():
        if entry_id not in entries_to_include:
            continue
        for line, account, entry in lines_and_accounts:
            provenance_inputs_by_account.setdefault(account.id, []).append(
                _provenance_from_source_type(entry.source_type)
            )
            converted_total = await _convert_line_total_with_fallback(
                db,
                line=line,
                account=account,
                target_currency=target_currency,
                start_date=start_date,
                end_date=end_date,
                fx_rates=fx_rates,
                fx_warnings=fx_warnings,
            )
            signed_total = _signed_amount(account.type, line.direction, converted_total)
            balances[account.id] += signed_total
            if include_economic_categories:
                category = (
                    (line.tags or {}).get("economic_category")
                    if entry.decision_authority_state == JournalEntryAuthorityState.ANCHORED
                    and entry.decision_anchor_id is not None
                    else None
                )
                report_line = economic_category_line(
                    category if isinstance(category, str) else None, account.type.value
                )
                category_balances[(account.id, report_line.value)] += signed_total

            period_key = _month_start(entry.entry_date)
            month_end = _add_months(period_key, 1) - timedelta(days=1)
            rate_monthly = fx_rates.get_rate(line.currency, target_currency, entry.entry_date, period_key, month_end)
            if rate_monthly is None:
                logger.warning(
                    "Monthly average FX rate unavailable for trend, using period average",
                    error_id=ErrorIds.REPORT_FX_FALLBACK,
                    currency=line.currency,
                    month_start=period_key,
                )
                converted_monthly = converted_total
            else:
                converted_monthly = line.amount * rate_monthly

            bucket = period_totals.setdefault(period_key, {"income": Decimal("0"), "expense": Decimal("0")})
            bucket["income" if account.type == AccountType.INCOME else "expense"] += _signed_amount(
                account.type, line.direction, converted_monthly
            )

    provenance_by_account = {aid: _combine_provenance(vals) for aid, vals in provenance_inputs_by_account.items()}
    income_lines = _build_account_lines(accounts, balances, AccountType.INCOME, provenance_by_account=provenance_by_account)
    expense_lines = _build_account_lines(accounts, balances, AccountType.EXPENSE, provenance_by_account=provenance_by_account)
    if include_economic_categories:
        income_lines = _category_lines(income_lines, category_balances)
        expense_lines = _category_lines(expense_lines, category_balances)

    fee_account_name_by_id = {account.id: account.name for account in accounts}
    for from_account_id, converted_fee in transfer_adjustment.fee_by_account.items():
        expense_lines.append(
            {
                "account_id": from_account_id,
                "name": fee_account_name_by_id.get(from_account_id, "Internal transfer fee"),
                "type": AccountType.EXPENSE,
                "parent_id": None,
                "amount": _quantize_money(converted_fee),
                "provenance": None,
                "source_currency": target_currency,
                "allocation_asset_class": None,
                "allocation_liquidity_class": None,
                "allocation_source_type": "internal_transfer_fee",
                **(
                    {"economic_report_line_id": economic_category_line("FEES", "EXPENSE").value}
                    if include_economic_categories
                    else {}
                ),
            }
        )

    totals = calculate_income_statement_totals(income_lines, expense_lines)
    income_lines = _fold_and_deduplicate_lines(income_lines, filter_zero=True)
    expense_lines = _fold_and_deduplicate_lines(expense_lines, filter_zero=True)

    if transfer_adjustment.fee_total > 0 and transfer_adjustment.fee_trend_date is not None:
        fee_period_key = _month_start(min(max(transfer_adjustment.fee_trend_date, start_date), end_date))
        period_totals.setdefault(fee_period_key, {"income": Decimal("0"), "expense": Decimal("0")})["expense"] += (
            transfer_adjustment.fee_total
        )

    unrealized_fx_change = await _calculate_unrealized_fx_change(
        db,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        target_currency=target_currency,
        ending_unrealized_fx_gain_loss=ending_unrealized_fx_gain_loss,
    )
    trend_items = [
        {
            "period_start": period_start,
            "period_end": min(_month_end(period_start), end_date),
            "total_income": (inc_tot := _quantize_money(period_totals[period_start]["income"])),
            "total_expenses": (exp_tot := _quantize_money(period_totals[period_start]["expense"])),
            "net_income": _quantize_money(inc_tot - exp_tot),
        }
        for period_start in sorted(period_totals)
    ]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "currency": target_currency,
        "income": income_lines,
        "expenses": expense_lines,
        "total_income": totals.total_income,
        "total_expenses": totals.total_expenses,
        "net_income": totals.net_income,
        "unrealized_fx_gain_loss": unrealized_fx_change,
        "comprehensive_income": _quantize_money(totals.net_income + unrealized_fx_change),
        "fx_warnings": fx_warnings,
        "trends": trend_items,
        "classification_breakdown": await _load_classification_breakdown(
            db, user_id=user_id, account_types=account_types, start_date=start_date, end_date=end_date
        ),
    }


async def _convert_line_total_with_fallback(
    db: AsyncSession,
    *,
    line: JournalLine,
    account: Account,
    target_currency: str,
    start_date: date,
    end_date: date,
    fx_rates: PrefetchedFxRates,
    fx_warnings: list[FxWarning],
) -> Decimal:
    """Resolve total converted amount for a journal line, falling back from pre-fetched average to spot rate."""
    rate_total = fx_rates.get_rate(line.currency, target_currency, end_date, start_date, end_date)
    if rate_total is not None:
        return line.amount * rate_total

    try:
        return (
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
    except PricingError as exc:
        logger.warning(
            "Average FX rate unavailable, falling back to spot",
            error_id=ErrorIds.REPORT_FX_FALLBACK,
            account_id=str(account.id),
            currency=line.currency,
            start_date=start_date,
            end_date=end_date,
            error=str(exc),
        )
        try:
            return (await convert_money(db, line.money, target_currency, end_date, lazy_load=True)).amount
        except PricingError as final_exc:
            logger.error(
                "All FX rate fallbacks failed for income statement",
                error_id=ErrorIds.REPORT_GENERATION_FAILED,
                account_id=str(account.id),
                error=str(final_exc),
            )
            raise ReportError(f"FX conversion failed: {final_exc}") from final_exc


async def _calculate_unrealized_fx_change(
    db: AsyncSession,
    *,
    user_id: UUID,
    start_date: date,
    end_date: date,
    target_currency: str,
    ending_unrealized_fx_gain_loss: Decimal | None = None,
) -> Decimal:
    """Calculate Unrealized FX Gain/Loss change for the period without full balance-sheet assembly."""
    start_fx = await _compute_unrealized_fx_gain_loss(
        db, user_id, as_of_date=start_date - timedelta(days=1), target_currency=target_currency
    )
    end_fx = (
        _quantize_money(Decimal(str(ending_unrealized_fx_gain_loss)))
        if ending_unrealized_fx_gain_loss is not None
        else await _compute_unrealized_fx_gain_loss(db, user_id, as_of_date=end_date, target_currency=target_currency)
    )
    return _quantize_money(end_fx - start_fx)


async def _load_classification_breakdown(
    db: AsyncSession,
    *,
    user_id: UUID,
    account_types: tuple[AccountType, ...],
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Build classification breakdown for applied layer-3 categorizations."""
    try:
        from src.extraction import ClassificationStatus
        from src.extraction.orm.layer2 import AtomicTransaction
        from src.extraction.orm.layer3 import TransactionClassification

        cls_stmt = (
            select(
                Account.name.label("account_name"),
                Account.type.label("account_type"),
                func.count(TransactionClassification.id).label("count"),
                func.avg(TransactionClassification.confidence_score).label("avg_confidence"),
            )
            .join(Account, TransactionClassification.account_id == Account.id)
            .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
            .where(
                TransactionClassification.status == ClassificationStatus.APPLIED,
                Account.user_id == user_id,
                AtomicTransaction.user_id == user_id,
                Account.type.in_(account_types),
                AtomicTransaction.txn_date >= start_date,
                AtomicTransaction.txn_date <= end_date,
            )
            .group_by(Account.name, Account.type)
            .order_by(func.count(TransactionClassification.id).desc())
            .limit(50)
        )
        return [
            {
                "account_name": row.account_name,
                "account_type": row.account_type.value if hasattr(row.account_type, "value") else str(row.account_type),
                "classified_count": row.count,
                "avg_confidence": round(float(row.avg_confidence or 0), 1),
            }
            for row in (await db.execute(cls_stmt)).all()
        ]
    except Exception as e:
        logger.warning("Failed to build classification breakdown, skipping", error=str(e), error_type=type(e).__name__)
        return []
