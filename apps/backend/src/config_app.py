"""App-level configuration accessors (#1340, Phase D; user scope #2539).

The base reporting currency has three levels. A user may store an own value
(``users.base_currency``). The operator may store a default for all users in the
``app_config`` table. The env-only ``settings.base_currency`` applies when neither
exists. ``get_effective_base_currency`` is the single accessor every caller
should use. ``set_base_currency`` writes only the caller's own value: one user
cannot change the base currency of another user (#2539). The operator default
has no API writer.

Repeated reads on the same ``AsyncSession`` reuse a session-scoped cache in
``session.info`` instead of process-global state.
"""

from inspect import isawaitable
from typing import Any
from uuid import UUID

from sqlalchemy import event, inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.audit.money import Currency
from src.config import settings
from src.identity import User
from src.platform.orm.app_config import BASE_CURRENCY_KEY, AppConfig

_CACHE_INFO_KEY = "_base_currency_cache"


def _invalidate_session_cache(session: Session) -> None:
    session.info.pop(_CACHE_INFO_KEY, None)


@event.listens_for(Session, "after_flush")
def _sync_base_currency_cache_after_flush(session: Session, flush_context: Any) -> None:
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, User | AppConfig):
            _invalidate_session_cache(session)
            return


@event.listens_for(Session, "after_commit")
def _clear_base_currency_cache_after_commit(session: Session) -> None:
    _invalidate_session_cache(session)


@event.listens_for(Session, "after_rollback")
def _clear_base_currency_cache_after_rollback(session: Session) -> None:
    _invalidate_session_cache(session)


async def _scalar_str(db: AsyncSession, stmt: Any) -> str | None:
    scalar = getattr(db, "scalar", None)
    if scalar is None:
        return None
    res = scalar(stmt)
    val = await res if isawaitable(res) else res
    return val if isinstance(val, str) else None


def _session_user_base_currency(sync_session: Session, user_id: UUID) -> tuple[bool, bool, str | None]:
    for obj in (*sync_session.new, *sync_session.dirty):
        if isinstance(obj, User):
            data = sa_inspect(obj).dict
            if data.get("id") == user_id and "base_currency" in data:
                return True, True, data["base_currency"]
    for obj in sync_session.identity_map.values():
        if isinstance(obj, User):
            data = sa_inspect(obj).dict
            if data.get("id") == user_id and "base_currency" in data:
                return True, False, data["base_currency"]
    return False, False, None


def _session_operator_base_currency(sync_session: Session) -> tuple[bool, bool, str | None]:
    for obj in (*sync_session.new, *sync_session.dirty):
        if isinstance(obj, AppConfig):
            data = sa_inspect(obj).dict
            if data.get("key") == BASE_CURRENCY_KEY and "value" in data:
                return True, True, data["value"]
    for obj in sync_session.identity_map.values():
        if isinstance(obj, AppConfig):
            data = sa_inspect(obj).dict
            if data.get("key") == BASE_CURRENCY_KEY and "value" in data:
                return True, False, data["value"]
    return False, False, None


async def get_effective_base_currency(db: AsyncSession, *, user_id: UUID | None = None) -> str:
    """Return the user's own value, else the operator default, else the env default."""
    sync_session = getattr(db, "sync_session", None)
    found_user, dirty_user, own = (
        _session_user_base_currency(sync_session, user_id)
        if user_id is not None and isinstance(sync_session, Session)
        else (False, False, None)
    )
    found_op, dirty_op, operator_default = (
        _session_operator_base_currency(sync_session) if isinstance(sync_session, Session) else (False, False, None)
    )
    can_cache = isinstance(sync_session, Session) and not dirty_user and not dirty_op
    if can_cache and isinstance(sync_session, Session):
        cached = sync_session.info.get(_CACHE_INFO_KEY)
        if isinstance(cached, dict) and user_id in cached:
            return cached[user_id]

    if user_id is not None and not found_user and not found_op and isinstance(sync_session, Session):
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
        found_user = True
        found_op = True

    if user_id is not None:
        if not found_user:
            own = await _scalar_str(db, select(User.base_currency).where(User.id == user_id))
        if own is not None:
            resolved = Currency(own).code
            if can_cache and isinstance(sync_session, Session):
                sync_session.info.setdefault(_CACHE_INFO_KEY, {})[user_id] = resolved
            return resolved

    if not found_op:
        operator_default = await _scalar_str(db, select(AppConfig.value).where(AppConfig.key == BASE_CURRENCY_KEY))
    resolved = (
        Currency(operator_default).code if operator_default is not None else Currency(settings.base_currency).code
    )
    if can_cache and isinstance(sync_session, Session):
        sync_session.info.setdefault(_CACHE_INFO_KEY, {})[user_id] = resolved
    return resolved


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
    sync_session = getattr(db, "sync_session", None)
    if isinstance(sync_session, Session):
        _invalidate_session_cache(sync_session)
    return normalized
