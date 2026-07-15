"""Account-level statement coverage and balance continuity checks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import STATEMENT_BALANCE_TOLERANCE
from src.ledger.base.types.account import (
    AccountCoverageCadence,
    AccountCoverageIssue,
    AccountCoverageIssueType,
    AccountCoverageListResponse,
    AccountCoverageResponse,
)
from src.ledger.orm.account import Account

if TYPE_CHECKING:
    pass

BALANCE_TOLERANCE = STATEMENT_BALANCE_TOLERANCE

DEFAULT_STALE_AFTER_DAYS = 45
CRITICAL_SEVERITY = "critical"
WARNING_SEVERITY = "warning"


@dataclass(frozen=True)
class StatementCoverageRow:
    """The approved-statement fields account coverage needs (#1675 D6).

    ``extraction`` owns ``StatementSummary`` (L3 domain, same rank as
    ``ledger`` — and extraction already ``depends_on`` ledger, so a direct
    import here would close a dependency cycle). This module may only depend
    on this plain read-model shape, registered from above by ``main.py`` at
    startup — never import the ORM class or its enum types directly (same
    inversion as ``register_uploaded_document_readers``, #1675 D3). The
    registered provider is responsible for filtering to APPROVED statements
    for the given accounts before handing rows across the port — the
    ``BankStatementStatus`` enum comparison stays with its owner.
    """

    id: UUID
    account_id: UUID
    currency: str | None
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    updated_at: datetime


# Called as (db, user_id, account_ids) — see get_account_statement_coverage's
# call site.
StatementCoverageReader = "Callable[[AsyncSession, UUID, Collection[UUID]], Awaitable[list[StatementCoverageRow]]]"

_statement_coverage_reader: StatementCoverageReader | None = None


def register_statement_coverage_reader(reader: StatementCoverageReader) -> None:
    """Wire the approved-statement-coverage lookup (see :class:`StatementCoverageRow`)."""
    global _statement_coverage_reader
    _statement_coverage_reader = reader


def _require_statement_coverage_reader() -> StatementCoverageReader:
    if _statement_coverage_reader is None:
        raise RuntimeError(
            "account_coverage.register_statement_coverage_reader() was never called — "
            "main.py wires it at startup (#1675 D6); a test exercising this path must call it too."
        )
    return _statement_coverage_reader


def _statement_currency(statement: StatementCoverageRow, fallback: str) -> str:
    return statement.currency or fallback


def _is_complete_period(statement: StatementCoverageRow) -> bool:
    return statement.period_start is not None and statement.period_end is not None


def _is_daily_snapshot(statement: StatementCoverageRow) -> bool:
    return _is_complete_period(statement) and statement.period_start == statement.period_end


def _abs_decimal_delta(left: Decimal, right: Decimal) -> Decimal:
    return abs(left - right)


def _latest_statement(statements: list[StatementCoverageRow]) -> StatementCoverageRow | None:
    candidates = [
        statement
        for statement in statements
        if statement.period_end is not None and statement.closing_balance is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda statement: (statement.period_end, statement.updated_at, str(statement.id)))


def _coverage_issues(statements: list[StatementCoverageRow], currency: str) -> list[AccountCoverageIssue]:
    complete_statements = [statement for statement in statements if _is_complete_period(statement)]
    monthly_statements = [statement for statement in complete_statements if not _is_daily_snapshot(statement)]
    monthly_statements.sort(key=lambda statement: (statement.period_start, statement.period_end, str(statement.id)))

    issues: list[AccountCoverageIssue] = []
    seen_periods: dict[tuple[date, date], StatementCoverageRow] = {}

    for statement in monthly_statements:
        assert statement.period_start is not None
        assert statement.period_end is not None
        period = (statement.period_start, statement.period_end)
        previous = seen_periods.get(period)
        if previous is not None:
            issues.append(
                AccountCoverageIssue(
                    type=AccountCoverageIssueType.DUPLICATE_PERIOD,
                    severity=CRITICAL_SEVERITY,
                    currency=currency,
                    period_start=statement.period_start,
                    period_end=statement.period_end,
                    statement_id=statement.id,
                    previous_statement_id=previous.id,
                )
            )
        else:
            seen_periods[period] = statement

    for previous, current in zip(monthly_statements, monthly_statements[1:], strict=False):
        assert previous.period_start is not None
        assert previous.period_end is not None
        assert current.period_start is not None
        assert current.period_end is not None

        expected_start = previous.period_end + timedelta(days=1)
        if current.period_start <= previous.period_end:
            issues.append(
                AccountCoverageIssue(
                    type=AccountCoverageIssueType.OVERLAP,
                    severity=CRITICAL_SEVERITY,
                    currency=currency,
                    period_start=current.period_start,
                    period_end=previous.period_end,
                    statement_id=current.id,
                    previous_statement_id=previous.id,
                )
            )
            continue

        if current.period_start > expected_start:
            issues.append(
                AccountCoverageIssue(
                    type=AccountCoverageIssueType.GAP,
                    severity=WARNING_SEVERITY,
                    currency=currency,
                    period_start=expected_start,
                    period_end=current.period_start - timedelta(days=1),
                    statement_id=current.id,
                    previous_statement_id=previous.id,
                )
            )
            continue

        if previous.closing_balance is None or current.opening_balance is None:
            continue

        delta = _abs_decimal_delta(current.opening_balance, previous.closing_balance)
        if delta > BALANCE_TOLERANCE:
            issues.append(
                AccountCoverageIssue(
                    type=AccountCoverageIssueType.OPENING_BALANCE_MISMATCH,
                    severity=CRITICAL_SEVERITY,
                    currency=currency,
                    period_start=current.period_start,
                    period_end=current.period_end,
                    statement_id=current.id,
                    previous_statement_id=previous.id,
                    expected_opening_balance=previous.closing_balance,
                    actual_opening_balance=current.opening_balance,
                    delta=delta,
                )
            )

    return issues


async def get_account_statement_coverage(
    db: AsyncSession,
    user_id: UUID,
    *,
    as_of: date | None = None,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
) -> AccountCoverageListResponse:
    """Return statement continuity status for every active account/currency pair."""
    coverage_as_of = as_of or date.today()

    account_result = await db.execute(
        select(Account)
        .where(Account.user_id == user_id)
        .where(Account.is_active.is_(True))
        .order_by(Account.name, Account.id)
    )
    accounts = list(account_result.scalars().all())
    account_by_id = {account.id: account for account in accounts}
    account_ids = set(account_by_id)

    if account_ids:
        statements = await _require_statement_coverage_reader()(db, user_id, account_ids)
    else:
        statements = []

    grouped: dict[tuple[UUID, str], list[StatementCoverageRow]] = defaultdict(list)
    for statement in statements:
        assert statement.account_id is not None
        account = account_by_id[statement.account_id]
        grouped[(statement.account_id, _statement_currency(statement, account.currency))].append(statement)

    account_currencies: dict[UUID, set[str]] = {account.id: {account.currency} for account in accounts}
    for account_id, currency in grouped:
        account_currencies.setdefault(account_id, set()).add(currency)

    items: list[AccountCoverageResponse] = []
    for account in accounts:
        for currency in sorted(account_currencies.get(account.id, {account.currency})):
            account_statements = grouped.get((account.id, currency), [])
            latest = _latest_statement(account_statements)
            latest_source_date = latest.period_end if latest is not None else None
            latest_confirmed_balance = latest.closing_balance if latest is not None else None
            has_daily_snapshot_override = latest is not None and _is_daily_snapshot(latest)
            cadence = (
                AccountCoverageCadence.DAILY_SNAPSHOT if has_daily_snapshot_override else AccountCoverageCadence.MONTHLY
            )
            stale_days = None if latest_source_date is None else (coverage_as_of - latest_source_date).days
            is_stale = stale_days is None or stale_days > stale_after_days
            issues = _coverage_issues(account_statements, currency)

            items.append(
                AccountCoverageResponse(
                    account_id=account.id,
                    account_name=account.name,
                    currency=currency,
                    cadence=cadence,
                    latest_source_date=latest_source_date,
                    latest_confirmed_balance=latest_confirmed_balance,
                    stale_after_days=stale_after_days,
                    is_stale=is_stale,
                    has_daily_snapshot_override=has_daily_snapshot_override,
                    coverage_complete=not is_stale and not issues,
                    issues=issues,
                )
            )

    return AccountCoverageListResponse(items=items, total=len(items), as_of=coverage_as_of)
