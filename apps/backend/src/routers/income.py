"""Income analytics API router."""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import select

from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.models import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.schemas.income import AnnualizedIncomeResponse
from src.services.fx import FxRateError, convert_amount
from src.services.reporting import income_bucket
from src.utils import raise_bad_request
from src.utils.money import to_money

router = APIRouter(prefix="/income", tags=["income"])


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
    currency = settings.base_currency.strip().upper()
    for line, account in result.all():
        signed_amount = line.amount if line.direction == Direction.CREDIT else -line.amount
        source_currency = (line.currency or account.currency or currency).strip().upper()
        try:
            signed_amount = await convert_amount(
                db,
                amount=signed_amount,
                currency=source_currency,
                target_currency=currency,
                rate_date=report_date,
                average_start=start_date,
                average_end=report_date,
                lazy_load=True,
            )
        except FxRateError as exc:
            raise_bad_request(str(exc), cause=exc)
        bucket = income_bucket(account.name)
        if bucket:
            totals[bucket] += signed_amount
        totals["total"] += signed_amount

    return AnnualizedIncomeResponse(
        annualized_salary=to_money(totals["salary"]),
        annualized_bonus=to_money(totals["bonus"]),
        annualized_dividend=to_money(totals["dividend"]),
        annualized_total=to_money(totals["total"]),
        currency=currency,
        as_of=report_date,
    )
