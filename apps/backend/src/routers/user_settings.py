"""Current-user settings endpoints."""

from fastapi import APIRouter
from sqlalchemy import select

from src.deps import CurrentUserId, DbSession, ReadDbSession
from src.extraction import (
    auto_accept_preference,
    effective_auto_accept,
    effective_classification,
    effective_reconciliation,
)
from src.identity import User, UserAiSettingsResponse, UserAiSettingsUpdate
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
    db: ReadDbSession,
    user_id: CurrentUserId,
) -> UserAiSettingsResponse:
    """Return effective current-user AI settings."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ResourceNotFoundError("User not found")
    return _effective_settings(user.ai_settings)


@router.patch("", response_model=UserAiSettingsResponse)
async def patch_current_user_settings(
    payload: UserAiSettingsUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> UserAiSettingsResponse:
    """Persist current-user AI setting overrides."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ResourceNotFoundError("User not found")

    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    user.ai_settings = {**(user.ai_settings or {}), **updates}
    await db.flush()
    await db.refresh(user)
    return _effective_settings(user.ai_settings)
