"""Income analytics API router."""

from datetime import date
from http import HTTPStatus

from fastapi import APIRouter, Query

from src.deps import CurrentUserId, DbSession
from src.reporting import generate_annualized_income_schedule
from src.schemas.income import AnnualizedIncomeResponse, FxConversionErrorResponse

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
    schedule = await generate_annualized_income_schedule(
        db,
        user_id,
        as_of_date=as_of,
        include_restricted_holdings=False,
    )
    return AnnualizedIncomeResponse(
        annualized_salary=schedule.income.annualized_salary,
        annualized_bonus=schedule.income.annualized_bonus,
        annualized_dividend=schedule.income.annualized_dividend,
        annualized_total=schedule.income.annualized_total,
        currency=schedule.income.currency,
        as_of=schedule.as_of_date,
    )
