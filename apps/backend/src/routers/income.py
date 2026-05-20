"""Income analytics API router."""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import select

from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.models import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.schemas.income import AnnualizedIncomeResponse

router = APIRouter(prefix="/income", tags=["income"])


def _income_bucket(account_name: str) -> str | None:
    normalized = account_name.casefold()
    if "salary" in normalized or "payroll" in normalized:
        return "salary"
    if "bonus" in normalized:
        return "bonus"
    if "dividend" in normalized:
        return "dividend"
    return None


@router.get("/annualized", response_model=AnnualizedIncomeResponse)
async def get_annualized_income(
    db: DbSession,
    user_id: CurrentUserId,
    as_of: date | None = Query(default=None),
) -> AnnualizedIncomeResponse:
    """Return annualized salary, bonus, dividend, and total income over the trailing 12 months."""
    report_date = as_of or date.today()
    start_date = report_date - timedelta(days=365)
    result = await db.execute(
        select(JournalLine, Account)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.entry_date > start_date)
        .where(JournalEntry.entry_date <= report_date)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(Account.type == AccountType.INCOME)
    )

    totals = {
        "salary": Decimal("0.00"),
        "bonus": Decimal("0.00"),
        "dividend": Decimal("0.00"),
        "total": Decimal("0.00"),
    }
    currency = settings.base_currency
    for line, account in result.all():
        signed_amount = line.amount if line.direction == Direction.CREDIT else -line.amount
        bucket = _income_bucket(account.name)
        if bucket:
            totals[bucket] += signed_amount
        totals["total"] += signed_amount
        currency = line.currency or account.currency or currency

    return AnnualizedIncomeResponse(
        annualized_salary=totals["salary"].quantize(Decimal("0.01")),
        annualized_bonus=totals["bonus"].quantize(Decimal("0.01")),
        annualized_dividend=totals["dividend"].quantize(Decimal("0.01")),
        annualized_total=totals["total"].quantize(Decimal("0.01")),
        currency=currency,
        as_of=report_date,
    )
