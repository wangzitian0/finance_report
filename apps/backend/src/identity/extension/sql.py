"""SQLAlchemy-backed identity persistence (the only role that touches the ORM).

``User`` (the aggregate root) and ``AiFeedback`` (its child entity) are the ORM
table models; ``SqlUserRepository`` is the async adapter implementing the
``UserRepository`` port against an ``AsyncSession``. The table definitions are
unchanged from the pre-migration ``src/models/user.py`` — same table names
(``users``/``ai_feedback``), columns, and the unique case-insensitive email index
(the aggregate's invariant) — so this is a pure code move with no schema change.

The repository *port* lives in ``base/repository.py`` (the abstraction the pure
core depends on); this async adapter is the production implementation
(dependency inversion, mechanism B). The session/ORM never leaks above this line.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    """Application user — the identity aggregate root (authentication core).

    Invariant: ``email`` is unique case-insensitively, enforced by the
    ``func.lower(email)`` unique index ``uq_users_email_normalized`` (a duplicate
    in any case is unrepresentable at the DB level).
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    __table_args__ = (Index("uq_users_email_normalized", func.lower(email), unique=True),)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    ai_settings: Mapped[dict[str, bool]] = mapped_column(JSONB, nullable=False, default=dict)


class AiFeedback(Base, UUIDMixin, TimestampMixin):
    """User feedback for AI classification and reconciliation suggestions.

    A child entity of the ``User`` aggregate (FK to ``users.id`` with cascade
    delete); persisted by the identity package.
    """

    __tablename__ = "ai_feedback"

    suggestion_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    corrected_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class SqlUserRepository:
    """Async identity store backed by an :class:`AsyncSession` (the port adapter)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def exists(self, user_id: UUID) -> bool:
        """True iff a user row with ``user_id`` exists."""
        result = await self._db.execute(select(User.id).where(User.id == user_id))
        return result.scalar_one_or_none() is not None

    async def get_by_normalized_email(self, normalized_email: str) -> User | None:
        """The ``User`` whose normalized (lowercased) email matches, or None."""
        result = await self._db.execute(select(User).where(func.lower(User.email) == normalized_email))
        return result.scalar_one_or_none()

    async def add(self, user: User) -> None:
        """Stage a new ``User`` for persistence; the caller owns the commit."""
        self._db.add(user)
