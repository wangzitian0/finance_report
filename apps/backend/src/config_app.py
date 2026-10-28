"""App-level configuration accessors (#1340, Phase D; user scope #2539).

The base reporting currency has three levels. A user may store an own value
(``users.base_currency``). The operator may store a default for all users in the
``app_config`` table. The env-only ``settings.base_currency`` applies when neither
exists. ``get_effective_base_currency`` is the single accessor every caller
should use. ``set_base_currency`` writes only the caller's own value: one user
cannot change the base currency of another user (#2539). The operator default
has no API writer.
"""

from inspect import isawaitable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency
from src.config import settings
from src.identity import User
from src.platform.orm.app_config import BASE_CURRENCY_KEY, AppConfig


async def _scalar_str(db: AsyncSession, stmt: Any) -> str | None:
    scalar = getattr(db, "scalar", None)
    if scalar is None:
        return None
    res = scalar(stmt)
    val = await res if isawaitable(res) else res
    return val if isinstance(val, str) else None


async def get_effective_base_currency(db: AsyncSession, *, user_id: UUID | None = None) -> str:
    """Return the user's own value, else the operator default, else the env default."""
    if user_id is not None:
        own = await _scalar_str(db, select(User.base_currency).where(User.id == user_id))
        if own is not None:
            return own
    operator_default = await _scalar_str(db, select(AppConfig.value).where(AppConfig.key == BASE_CURRENCY_KEY))
    if operator_default is not None:
        return Currency(operator_default).code
    return Currency(settings.base_currency).code


async def set_base_currency(db: AsyncSession, code: str, *, user_id: UUID) -> str:
    """Persist the user's own base currency and return the stored value.

    ``code`` must already be a valid ISO 4217 code (the request schema validates
    it). Only the row of ``user_id`` changes; the operator default stays as is.
    """
    normalized = Currency(code).code
    user = await db.get(User, user_id)
    if user is None:
        raise LookupError(f"user {user_id} does not exist")
    user.base_currency = normalized
    # Service flushes; the router owns the commit (transaction-boundary policy).
    await db.flush()
    return normalized
