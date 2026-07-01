"""Income analytics API router."""

from datetime import date, timedelta
from http import HTTPStatus

from fastapi import APIRouter, Query
from sqlalchemy import select

from src.audit.money import to_money
from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.schemas.base import normalize_currency_code
from src.schemas.income import AnnualizedIncomeResponse, FxConversionErrorResponse
from src.services.fx import FxRateError, convert_amount
from src.services.reporting_calc import AnnualizedIncomeTotals, income_bucket, resolve_line_currency
from src.utils import raise_bad_request

router = APIRouter(prefix="/income", tags=["income"])


@router.get(
    "/annualized",
    response_model=AnnualizedIncomeResponse,
    responses={HTTPStatus.BAD_REQUEST: {"model": FxConversionErrorResponse}},
)
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

    currency = normalize_currency_code(settings.base_currency)
    totals = AnnualizedIncomeTotals()
    for line, account in result.all():
        signed_amount = line.amount if line.direction == Direction.CREDIT else -line.amount
        source_currency = resolve_line_currency(line, account, base_currency=currency)
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
        totals.add(income_bucket(account.name), signed_amount)

    return AnnualizedIncomeResponse(
        annualized_salary=to_money(totals.salary),
        annualized_bonus=to_money(totals.bonus),
        annualized_dividend=to_money(totals.dividend),
        annualized_total=to_money(totals.total),
        currency=currency,
        as_of=report_date,
    )
