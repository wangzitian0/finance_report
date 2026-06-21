"""SQLAlchemy-backed counter persistence (the only role that touches the ORM).

``CounterTally`` is the table model; ``SqlCounterRepository`` is the async
adapter that implements the persistence contract against an ``AsyncSession``. The
bump is a single atomic upsert-increment (``INSERT ... ON CONFLICT DO UPDATE SET
count = count + 1 RETURNING count``), so concurrent increments of the same
(user, key) cannot lose updates.

The repository *port* in ``store/repository.py`` is a sync ``Protocol`` for the
in-memory fake that makes ops unit-testable without a DB; this async adapter is
the production implementation that the boundary (``api``) awaits. Both speak raw
``int`` — the storage shape — and the counter value types stay out of the ORM.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import String, func, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID, insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.counter.types.key import CounterKey
from src.database import Base


class CounterTally(Base):
    """One per-(user, key) tally row. Unique on (user_id, key)."""

    __tablename__ = "counter_tally"

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, nullable=False)
    key: Mapped[str] = mapped_column(String(255), primary_key=True, nullable=False)
    count: Mapped[int] = mapped_column(nullable=False, server_default="0")


class SqlCounterRepository:
    """Async, atomic counter store backed by an :class:`AsyncSession`."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def bump(self, user_id: UUID, key: CounterKey) -> int:
        """Atomic upsert-increment; returns the new per-(user, key) tally."""
        stmt = (
            postgresql_insert(CounterTally)
            .values(user_id=user_id, key=key.value, count=1)
            .on_conflict_do_update(
                index_elements=[CounterTally.user_id, CounterTally.key],
                set_={"count": CounterTally.count + 1},
            )
            .returning(CounterTally.count)
        )
        result = await self._db.execute(stmt)
        return int(result.scalar_one())

    async def total(self, key: CounterKey) -> int:
        """GLOBAL tally for ``key`` (sum across all users); 0 if none."""
        result = await self._db.execute(
            select(func.coalesce(func.sum(CounterTally.count), 0)).where(CounterTally.key == key.value)
        )
        return int(result.scalar_one())

    async def for_user(self, user_id: UUID, key: CounterKey) -> int:
        """Per-user tally for (``user_id``, ``key``); 0 if none."""
        result = await self._db.execute(
            select(CounterTally.count).where(
                CounterTally.user_id == user_id,
                CounterTally.key == key.value,
            )
        )
        row = result.scalar_one_or_none()
        return int(row) if row is not None else 0
