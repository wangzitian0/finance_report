"""App-level configuration endpoints (#1340, Phase D; user scope #2539).

Exposes the caller's effective base reporting currency for reading and updating.
The update writes only the caller's own value, so one user cannot change the
base currency of another user (#2539). The update validates the code against
ISO 4217 (via the request schema, which reuses ``src.audit.money.Currency``) so
an invalid code returns HTTP 422 and is never persisted.
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
    """Return the caller's effective base currency (own value, operator default, env default)."""
    return BaseCurrencyResponse(base_currency=await get_effective_base_currency(db, user_id=user_id))


@router.put("/base-currency", response_model=BaseCurrencyResponse)
async def update_base_currency(
    payload: BaseCurrencyUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> BaseCurrencyResponse:
    """Persist the caller's own base currency. Invalid ISO 4217 code -> HTTP 422."""
    stored = await set_base_currency(db, payload.base_currency, user_id=user_id)
    await db.commit()  # router owns the transaction boundary
    return BaseCurrencyResponse(base_currency=stored)
