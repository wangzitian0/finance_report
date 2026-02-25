from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SQLEnum, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class CheckType(str, Enum):
    DUPLICATE = "duplicate"
    TRANSFER_PAIR = "transfer_pair"
    ANOMALY = "anomaly"


class CheckStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class ConsistencyCheck(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "consistency_checks"

    check_type: Mapped[CheckType] = mapped_column(
        SQLEnum(CheckType, name="check_type_enum"),
        nullable=False,
    )
    status: Mapped[CheckStatus] = mapped_column(
        SQLEnum(CheckStatus, name="check_status_enum"),
        nullable=False,
        default=CheckStatus.PENDING,
    )

    related_txn_ids: Mapped[list] = mapped_column(JSONB, nullable=False)

    details: Mapped[dict] = mapped_column(JSONB, nullable=False)

    severity: Mapped[str] = mapped_column(String(20), default="medium")

    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
