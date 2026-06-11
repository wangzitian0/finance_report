"""User model."""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin):
    """Application user (authentication handled elsewhere)."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    __table_args__ = (Index("uq_users_email_normalized", func.lower(email), unique=True),)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    ai_settings: Mapped[dict[str, bool]] = mapped_column(JSONB, nullable=False, default=dict)


class AiFeedback(Base, UUIDMixin, TimestampMixin):
    """User feedback for AI classification and reconciliation suggestions."""

    __tablename__ = "ai_feedback"

    suggestion_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    corrected_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
