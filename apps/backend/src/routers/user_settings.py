"""Current-user settings endpoints."""

from fastapi import APIRouter
from sqlalchemy import select

from src.config_app import set_base_currency
from src.deps import Ctx, ReadCtx
from src.extraction import (
    auto_accept_preference,
    effective_auto_accept,
    effective_classification,
    effective_reconciliation,
)
from src.identity import (
    BaseCurrencyResponse,
    BaseCurrencyUpdate,
    User,
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
)
from src.platform import ResourceNotFoundError

router = APIRouter(prefix="/users/me/settings", tags=["user-settings"])


def _effective_settings(ai_settings: dict[str, bool] | None) -> UserAiSettingsResponse:
    overrides = ai_settings or {}
    return UserAiSettingsResponse(
        enable_ai_reconciliation=effective_reconciliation(overrides),
        enable_ai_classification=effective_classification(overrides),
        # The panel edits the preference. It must not read back the effective value, or a save would store
        # "off" for a user who never chose it (AI classification off, or the operator flag off).
        auto_accept_ai_suggestions=auto_accept_preference(overrides),
        auto_accept_ai_suggestions_active=effective_auto_accept(overrides),
    )


@router.get("", response_model=UserAiSettingsResponse)
async def get_current_user_settings(
    ctx: ReadCtx,
) -> UserAiSettingsResponse:
    """Return effective current-user AI settings."""
    result = await ctx.db.execute(select(User).where(User.id == ctx.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ResourceNotFoundError("User not found")
    return _effective_settings(user.ai_settings)


@router.patch("", response_model=UserAiSettingsResponse)
async def patch_current_user_settings(
    payload: UserAiSettingsUpdate,
    ctx: Ctx,
) -> UserAiSettingsResponse:
    """Persist current-user AI setting overrides."""
    db, user_id = ctx.db, ctx.user_id
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ResourceNotFoundError("User not found")

    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    user.ai_settings = {**(user.ai_settings or {}), **updates}
    await db.flush()
    await db.refresh(user)
    return _effective_settings(user.ai_settings)


@router.get("/base-currency", response_model=BaseCurrencyResponse)
async def get_base_currency(
    ctx: ReadCtx,
) -> BaseCurrencyResponse:
    """Return the caller's effective base currency (own value, operator default, env default)."""
    return BaseCurrencyResponse(base_currency=await ctx.get_base_currency())


@router.put("/base-currency", response_model=BaseCurrencyResponse)
async def update_base_currency(
    payload: BaseCurrencyUpdate,
    ctx: Ctx,
) -> BaseCurrencyResponse:
    """Persist the caller's own base currency. Invalid ISO 4217 code -> HTTP 422."""
    stored = await set_base_currency(ctx.db, payload.base_currency, user_id=ctx.user_id)
    return BaseCurrencyResponse(base_currency=stored)
