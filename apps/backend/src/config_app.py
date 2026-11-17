"""App-level configuration accessors (#1340, Phase D; user scope #2539).

The base reporting currency has three levels. A user may store an own value
(``users.base_currency``). The operator may store a default for all users in the
``app_config`` table. The env-only ``settings.base_currency`` applies when neither
exists. ``get_effective_base_currency`` queries both levels cleanly, and HTTP
request handlers memoize it per request via ``src.request_context.RequestContext``.
"""

from inspect import isawaitable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

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
    sync_session = getattr(db, "sync_session", None)
    own: str | None = None
    operator_default: str | None = None
    if user_id is not None and isinstance(sync_session, Session):
        row = (
            await db.execute(
                select(
                    select(User.base_currency).where(User.id == user_id).scalar_subquery(),
                    select(AppConfig.value).where(AppConfig.key == BASE_CURRENCY_KEY).scalar_subquery(),
                )
            )
        ).first()
        if row is not None:
            own = row[0] if isinstance(row[0], str) else None
            operator_default = row[1] if isinstance(row[1], str) else None
    elif user_id is not None:
        own = await _scalar_str(db, select(User.base_currency).where(User.id == user_id))
        if own is None:
            operator_default = await _scalar_str(db, select(AppConfig.value).where(AppConfig.key == BASE_CURRENCY_KEY))
    else:
        operator_default = await _scalar_str(db, select(AppConfig.value).where(AppConfig.key == BASE_CURRENCY_KEY))

    if own is not None:
        return Currency(own).code
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
