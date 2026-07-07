"""App-level configuration endpoints (#1340, Phase D).

Exposes the effective base reporting currency for reading and updating. The
update validates the code against ISO 4217 (via the request schema, which reuses
``src.audit.money.Currency``) so an invalid code returns HTTP 422 and is never
persisted.
"""

from fastapi import APIRouter

from src.config_app import get_effective_base_currency, set_base_currency
from src.deps import CurrentUserId, DbSession
from src.schemas.app_config import BaseCurrencyResponse, BaseCurrencyUpdate

router = APIRouter(prefix="/app-config", tags=["app-config"])


@router.get("/base-currency", response_model=BaseCurrencyResponse)
async def get_base_currency(
    db: DbSession,
    user_id: CurrentUserId,
) -> BaseCurrencyResponse:
    """Return the effective base currency (persisted override else env default)."""
    return BaseCurrencyResponse(base_currency=await get_effective_base_currency(db))


@router.put("/base-currency", response_model=BaseCurrencyResponse)
async def update_base_currency(
    payload: BaseCurrencyUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> BaseCurrencyResponse:
    """Persist a new effective base currency. Invalid ISO 4217 code -> HTTP 422."""
    stored = await set_base_currency(db, payload.base_currency)
    await db.commit()  # router owns the transaction boundary
    return BaseCurrencyResponse(base_currency=stored)
