"""AI suggestion feedback ORM model owned by the extraction classification loop."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.platform.orm.base import TimestampMixin, UUIDMixin


class AiFeedback(Base, UUIDMixin, TimestampMixin):
    """User feedback for AI classification suggestions within extraction."""

    __tablename__ = "ai_feedback"

    suggestion_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    corrected_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
