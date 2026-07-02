"""Shared query helpers for router handlers.

Two patterns were re-implemented inline across the routers:

- "load a user-owned row by id, or 404" — ``select(...).where(id).where(user_id)``
  → ``scalar_one_or_none()`` → ``raise_not_found(...)``;
- "paginate a filtered query" — count the full set via a ``func.count`` subquery,
  then apply eager-load options / ordering / offset / limit and materialise rows.

Centralising them keeps the 404 contract and the count-then-page contract in one
place so they cannot drift between endpoints.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.base import ExecutableOption

from src.platform.extension.http_errors import raise_not_found


async def get_owned_or_404[M](
    db: AsyncSession,
    model: type[M],
    entity_id: Any,
    user_id: Any,
    *,
    name: str,
    options: Sequence[ExecutableOption] = (),
) -> M:
    """Return the ``model`` row owned by ``user_id`` with ``entity_id``, or raise 404.

    ``name`` is the human resource label passed to :func:`raise_not_found`.
    ``options`` are eager-load options (e.g. ``selectinload(...)``).
    """
    stmt = select(model).where(model.id == entity_id).where(model.user_id == user_id)
    if options:
        stmt = stmt.options(*options)
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise_not_found(name)
    return obj


async def paginate(
    db: AsyncSession,
    query: Select[Any],
    *,
    limit: int,
    offset: int,
    options: Sequence[ExecutableOption] = (),
    order_by: Sequence[Any] = (),
) -> tuple[list[Any], int]:
    """Return ``(rows, total)`` for a filtered base ``query``.

    ``total`` is the count of the full filtered set (before paging), computed via a
    ``func.count`` subquery so it is independent of ``limit``/``offset``. Eager-load
    ``options`` and ``order_by`` are applied before slicing.

    Any ``ORDER BY`` / ``LIMIT`` / ``OFFSET`` already on the incoming ``query`` is
    stripped before counting, so a pre-sliced or pre-ordered query still yields the
    true total rather than a clamped/paged count.
    """
    count_source = query.order_by(None).limit(None).offset(None).subquery()
    total = (await db.execute(select(func.count()).select_from(count_source))).scalar() or 0
    paged = query
    if options:
        paged = paged.options(*options)
    if order_by:
        paged = paged.order_by(*order_by)
    rows = (await db.execute(paged.offset(offset).limit(limit))).scalars().all()
    return list(rows), total
