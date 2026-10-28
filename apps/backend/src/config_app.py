"""App-level configuration accessors (#1340, Phase D; user scope #2539).

The base reporting currency has three levels. A user may store an own value
(``users.base_currency``). The operator may store a default for all users in the
``app_config`` table. The env-only ``settings.base_currency`` applies when neither
exists. ``get_effective_base_currency`` is the single accessor every caller
should use. ``set_base_currency`` writes only the caller's own value: one user
cannot change the base currency of another user (#2539). The operator default
has no API writer.
"""

import re
from inspect import isawaitable
from typing import Any
from uuid import UUID

from sqlalchemy import event, inspect as sa_inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.audit.money import Currency
from src.config import settings
from src.identity import User
from src.platform.orm.app_config import BASE_CURRENCY_KEY, AppConfig

_user_base_currency_cache: dict[UUID, str | None] = {}
_operator_base_currency_cache: dict[str, str | None] = {BASE_CURRENCY_KEY: None}
_WRITE_SQL_RE = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|TRUNCATE|DROP|CREATE)\b", re.IGNORECASE)


@event.listens_for(Engine, "before_cursor_execute")
def _invalidate_base_currency_cache_on_sql(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    if not _WRITE_SQL_RE.match(statement):
        return
    lower = statement.lower()
    if "drop schema" in lower or "create schema" in lower:
        _user_base_currency_cache.clear()
        _operator_base_currency_cache[BASE_CURRENCY_KEY] = None
        return
    if "users" in lower:
        _user_base_currency_cache.clear()
    if "app_config" in lower:
        if lower.lstrip().startswith(("delete", "truncate", "create")):
            _operator_base_currency_cache[BASE_CURRENCY_KEY] = None
        else:
            _operator_base_currency_cache.pop(BASE_CURRENCY_KEY, None)


@event.listens_for(Session, "after_flush")
def _sync_base_currency_cache_after_flush(session: Session, flush_context: Any) -> None:
    for obj in (*session.new, *session.dirty):
        state = sa_inspect(obj)
        data = state.dict
        if isinstance(obj, User):
            uid = data.get("id")
            if isinstance(uid, UUID) and "base_currency" in data:
                _user_base_currency_cache[uid] = data["base_currency"]
        elif isinstance(obj, AppConfig) and data.get("key") == BASE_CURRENCY_KEY and "value" in data:
            _operator_base_currency_cache[BASE_CURRENCY_KEY] = data["value"]
    for obj in session.deleted:
        state = sa_inspect(obj)
        data = state.dict
        if isinstance(obj, User):
            uid = data.get("id")
            if isinstance(uid, UUID):
                _user_base_currency_cache.pop(uid, None)
        elif isinstance(obj, AppConfig) and data.get("key") == BASE_CURRENCY_KEY:
            _operator_base_currency_cache[BASE_CURRENCY_KEY] = None


@event.listens_for(Session, "after_rollback")
def _clear_base_currency_cache_after_rollback(session: Session) -> None:
    _user_base_currency_cache.clear()
    _operator_base_currency_cache.pop(BASE_CURRENCY_KEY, None)


async def _scalar_str(db: AsyncSession, stmt: Any) -> str | None:
    scalar = getattr(db, "scalar", None)
    if scalar is None:
        return None
    res = scalar(stmt)
    val = await res if isawaitable(res) else res
    return val if isinstance(val, str) else None


def _session_user_base_currency(sync_session: Session, user_id: UUID) -> tuple[bool, str | None]:
    for obj in (*sync_session.new, *sync_session.dirty):
        if isinstance(obj, User):
            data = sa_inspect(obj).dict
            if data.get("id") == user_id and "base_currency" in data:
                return True, data["base_currency"]
    return False, None


def _session_operator_base_currency(sync_session: Session) -> tuple[bool, str | None]:
    for obj in (*sync_session.new, *sync_session.dirty):
        if isinstance(obj, AppConfig):
            data = sa_inspect(obj).dict
            if data.get("key") == BASE_CURRENCY_KEY and "value" in data:
                return True, data["value"]
    return False, None


async def get_effective_base_currency(db: AsyncSession, *, user_id: UUID | None = None) -> str:
    """Return the user's own value, else the operator default, else the env default."""
    sync_session = getattr(db, "sync_session", None)
    if user_id is not None:
        if isinstance(sync_session, Session):
            found, own = _session_user_base_currency(sync_session, user_id)
            if not found:
                if user_id in _user_base_currency_cache:
                    own = _user_base_currency_cache[user_id]
                else:
                    own = await _scalar_str(db, select(User.base_currency).where(User.id == user_id))
                    _user_base_currency_cache[user_id] = own
        else:
            own = await _scalar_str(db, select(User.base_currency).where(User.id == user_id))
        if own is not None:
            return Currency(own).code
    if isinstance(sync_session, Session):
        found_op, operator_default = _session_operator_base_currency(sync_session)
        if not found_op:
            if BASE_CURRENCY_KEY in _operator_base_currency_cache:
                operator_default = _operator_base_currency_cache[BASE_CURRENCY_KEY]
            else:
                operator_default = await _scalar_str(
                    db, select(AppConfig.value).where(AppConfig.key == BASE_CURRENCY_KEY)
                )
                _operator_base_currency_cache[BASE_CURRENCY_KEY] = operator_default
    else:
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
