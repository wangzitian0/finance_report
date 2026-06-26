"""Current-user settings endpoints."""

from fastapi import APIRouter
from sqlalchemy import select

from src.config import settings
from src.deps import CurrentUserId, DbSession
from src.models.user import User
from src.schemas.user import UserAiSettingsResponse, UserAiSettingsUpdate
from src.utils import raise_not_found

router = APIRouter(prefix="/users/me/settings", tags=["user-settings"])


def _effective_settings(ai_settings: dict[str, bool] | None) -> UserAiSettingsResponse:
    overrides = ai_settings or {}
    return UserAiSettingsResponse(
        enable_ai_reconciliation=overrides.get("enable_ai_reconciliation", settings.enable_ai_reconciliation),
        enable_ai_classification=overrides.get("enable_ai_classification", settings.enable_ai_classification),
    )


@router.get("", response_model=UserAiSettingsResponse)
async def get_current_user_settings(
    db: DbSession,
    user_id: CurrentUserId,
) -> UserAiSettingsResponse:
    """Return effective current-user AI settings."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise_not_found("User")
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
        raise_not_found("User")

    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    user.ai_settings = {**(user.ai_settings or {}), **updates}
    await db.commit()
    await db.refresh(user)
    return _effective_settings(user.ai_settings)
