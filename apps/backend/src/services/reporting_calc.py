"""Pure reporting calculation primitives (EPIC-025 AC25.1.1 / #1158).

DB-free money, currency, accounting-sign, provenance, confidence-tier, and
period math extracted verbatim from ``reporting.py`` so calculation has a single
owner separate from query orchestration and API shaping. ``reporting`` imports
what it needs from here; callers that only need the pure helpers (routers/income,
annualized_income, tests) import them directly from this module. The extracted
functions are byte-for-byte identical, so existing semantics are unchanged.

Money is always ``Decimal`` (never ``float`` — see the money decimal rule).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import ClassVar

from src.config import settings
from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntrySourceType,
    JournalLine,
)
from src.schemas.base import normalize_currency_code
from src.schemas.provenance import DataProvenance
from src.services.source_type_priority import normalize_source_type
from src.utils.money import to_money

_IMPORTED_SOURCE_TYPES = {
    JournalEntrySourceType.AUTO_PARSED,
    JournalEntrySourceType.AUTO_MATCHED,
    JournalEntrySourceType.USER_CONFIRMED,
}
_MANUAL_SOURCE_TYPES = {JournalEntrySourceType.MANUAL}
_DERIVED_SOURCE_TYPES = {JournalEntrySourceType.SYSTEM, JournalEntrySourceType.FX_REVALUATION}

# Limit to ~1 year of daily data to ensure report performance and prevent memory issues.
MAX_TREND_POINTS = 366
MAX_NET_WORTH_DAILY_POINTS = 366

# Confidence tiers ranked by trust (vision Axiom B). The worst-input rule rolls a
# line/aggregate down to its least-trusted contributor — a defined rollup, never
# an invented number.
_CONFIDENCE_TIER_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "TRUSTED": 3}


class ReportError(Exception):
    """Raised when report generation fails or input is invalid."""

    pass


@dataclass
class PeriodSpan:
    start: date
    end: date


def _normalize_currency(code: str | None) -> str:
    if not code:
        return normalize_currency_code(settings.base_currency)
    return normalize_currency_code(code)


def resolve_line_currency(line: JournalLine, account: Account, *, base_currency: str) -> str:
    """Resolve a journal line's effective currency via the canonical fallback chain.

    Centralizes the previously inline ``line.currency || account.currency ||
    base_currency`` resolution so callers no longer re-implement (and re-normalize)
    it. The returned code is normalized through :func:`normalize_currency_code`.
    """
    return _normalize_currency(line.currency or account.currency or base_currency)


def _signed_amount(account_type: AccountType, direction: Direction, amount: Decimal) -> Decimal:
    if account_type in (AccountType.ASSET, AccountType.EXPENSE):
        return amount if direction == Direction.DEBIT else -amount
    return amount if direction == Direction.CREDIT else -amount


def income_bucket(account_name: str) -> str | None:
    normalized = account_name.casefold()
    if "salary" in normalized or "payroll" in normalized:
        return "salary"
    if "bonus" in normalized:
        return "bonus"
    if "dividend" in normalized:
        return "dividend"
    return None


@dataclass
class AnnualizedIncomeTotals:
    """Typed intermediate accumulator for annualized income aggregation.

    Replaces the string-keyed ``dict[str, Decimal]`` so the response model can be
    constructed directly from typed attributes instead of a manual dict hop. All
    amounts are ``Decimal`` (never ``float`` — see the money decimal rule).
    """

    salary: Decimal = Decimal("0.00")
    bonus: Decimal = Decimal("0.00")
    dividend: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")

    # Per-line buckets that may be accumulated individually. ``total`` is the
    # running sum maintained by ``add()`` itself and is deliberately excluded so
    # passing ``bucket="total"`` cannot double-count.
    _BUCKETS: ClassVar[frozenset[str]] = frozenset({"salary", "bonus", "dividend"})

    def add(self, bucket: str | None, signed_amount: Decimal) -> None:
        """Accumulate a signed line amount into its bucket and the running total.

        ``bucket`` must be one of the per-line buckets (or ``None`` for amounts
        that only affect the running total). Unknown bucket names — including
        ``"total"`` — raise ``ValueError`` rather than silently double-counting.
        """
        if bucket is not None:
            if bucket not in self._BUCKETS:
                raise ValueError(f"Unknown income bucket {bucket!r}; expected one of {sorted(self._BUCKETS)} or None")
            setattr(self, bucket, getattr(self, bucket) + signed_amount)
        self.total += signed_amount


def _quantize_money(amount: Decimal | int) -> Decimal:
    if isinstance(amount, int):
        amount = Decimal(amount)
    return to_money(amount)


def _provenance_from_source_type(source_type: JournalEntrySourceType | str | None) -> DataProvenance | None:
    if source_type is None:
        return None
    try:
        # normalize_source_type folds retired legacy values (e.g. the
        # bank_statement text retired in 0040) back into the live hierarchy.
        normalized = normalize_source_type(source_type)
    except ValueError:
        return None
    if normalized in _MANUAL_SOURCE_TYPES:
        return "manual"
    if normalized in _IMPORTED_SOURCE_TYPES:
        return "imported"
    if normalized in _DERIVED_SOURCE_TYPES:
        return "derived"
    return None


def _combine_provenance(values: Sequence[DataProvenance | None]) -> DataProvenance | None:
    known = {value for value in values if value is not None}
    if not known:
        return None
    if len(known) == 1:
        return next(iter(known))
    return "derived"


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _month_end(value: date) -> date:
    next_month = value.replace(day=28) + timedelta(days=4)
    return next_month.replace(day=1) - timedelta(days=1)


def _quarter_start(value: date) -> date:
    month = ((value.month - 1) // 3) * 3 + 1
    return date(year=value.year, month=month, day=1)


def _add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = min(value.day, _month_end(date(year, month, 1)).day)
    return date(year, month, day)


def _iter_periods(start: date, end: date, period: str) -> list[PeriodSpan]:
    spans: list[PeriodSpan] = []
    cursor = start

    while cursor <= end:
        if period == "daily":
            span_start = cursor
            span_end = cursor
            next_cursor = cursor + timedelta(days=1)
        elif period == "weekly":
            span_start = cursor - timedelta(days=cursor.weekday())
            span_end = span_start + timedelta(days=6)
            next_cursor = span_start + timedelta(days=7)
        elif period == "monthly":
            span_start = _month_start(cursor)
            span_end = _month_end(cursor)
            next_cursor = _add_months(span_start, 1)
        else:
            raise ReportError(f"Unsupported period: {period}")

        spans.append(PeriodSpan(start=span_start, end=min(span_end, end)))
        cursor = next_cursor
        if len(spans) > MAX_TREND_POINTS:
            break

    return spans


def _worst_confidence_tier(tiers: Iterable[str | None]) -> str | None:
    """Return the least-trusted tier among the inputs, or None if none are rated."""
    present = [tier for tier in tiers if tier]
    if not present:
        return None
    return min(present, key=lambda tier: _CONFIDENCE_TIER_RANK.get(tier, 0))
