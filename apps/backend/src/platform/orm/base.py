"""Base ORM mixins shared by every package's models (moved from src/models, #1675 D6).

Pure structural mixins with no platform-specific behavior — a natural fit for
``platform`` (L1 infra, business-agnostic foundations). Every package that owns
ORM entities imports these directly (a deep import of a published name is
allowed, see ``common/meta/extension/check_package_contract.py``).
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDMixin:
    """Mixin for UUID primary key."""

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)


class UserOwnedMixin:
    """Mixin for user ownership tracking."""

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


class TimestampMixin:
    """Mixin for created_at/updated_at timestamps with UTC timezone."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
