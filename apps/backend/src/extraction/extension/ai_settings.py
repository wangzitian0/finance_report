"""The AI settings of a user: the user override on top of the process default.

Both readers load the user row. A user without an override gets the process default.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings


async def _overrides(db: AsyncSession, user_id: UUID) -> dict:
    from src.identity import User

    user = await db.get(User, user_id)
    return user.ai_settings if user is not None and isinstance(user.ai_settings, dict) else {}


def effective_classification(overrides: Mapping[str, object] | None) -> bool:
    """The EPIC-018 flag, with the per-user ``ai_settings`` override on top."""
    return bool((overrides or {}).get("enable_ai_classification", settings.enable_ai_classification))


def effective_auto_accept(overrides: Mapping[str, object] | None) -> bool:
    """The setting ``auto_accept_ai_suggestions`` (#2405) as the user sees it.

    The process flag is a ceiling: when the operator sets ``AUTO_ACCEPT_AI_SUGGESTIONS=false``, no user gets the
    automatic path, whatever a stored preference says. When the flag is on, the user can still turn it off.
    The setting needs AI classification: without proposals there is nothing to accept.
    """
    wanted = bool((overrides or {}).get("auto_accept_ai_suggestions", True))
    return settings.auto_accept_ai_suggestions and wanted and effective_classification(overrides)


async def classification_enabled(db: AsyncSession, user_id: UUID) -> bool:
    return effective_classification(await _overrides(db, user_id))


async def auto_accept_enabled(db: AsyncSession, user_id: UUID) -> bool:
    return effective_auto_accept(await _overrides(db, user_id))
