"""The AI settings of a user: the user override on top of the process default.

Both readers load the user row. A user without an override gets the process default.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings


async def _overrides(db: AsyncSession, user_id: UUID) -> dict:
    from src.identity import User

    user = await db.get(User, user_id)
    return user.ai_settings if user is not None and isinstance(user.ai_settings, dict) else {}


async def classification_enabled(db: AsyncSession, user_id: UUID) -> bool:
    """The EPIC-018 flag, with the per-user ``ai_settings`` override on top."""
    overrides = await _overrides(db, user_id)
    return bool(overrides.get("enable_ai_classification", settings.enable_ai_classification))


async def auto_accept_enabled(db: AsyncSession, user_id: UUID) -> bool:
    """The setting ``auto_accept_ai_suggestions`` (#2405): the user override on top of the process default.

    It needs AI classification: without proposals there is nothing to accept.
    """
    overrides = await _overrides(db, user_id)
    wanted = bool(overrides.get("auto_accept_ai_suggestions", settings.auto_accept_ai_suggestions))
    return wanted and await classification_enabled(db, user_id)
