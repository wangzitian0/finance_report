"""EPIC-018 Phase 2: Correction Log for feedback learning loop."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.account import Account
    from src.models.statement import BankStatementTransaction


class CorrectionLog(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Track user corrections to AI-suggested categories for few-shot learning.

    Every time a user overrides an AI-suggested category, we record the
    original and corrected values. These corrections feed back into the
    extraction prompt as few-shot examples, improving future suggestions.
    """

    __tablename__ = "correction_logs"

    transaction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bank_statement_transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    original_category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="AI-suggested category before correction",
    )
    corrected_category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="User-corrected category",
    )

    original_account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    corrected_account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    transaction_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Cached transaction description for few-shot prompt building",
    )

    # Relationships
    transaction: Mapped["BankStatementTransaction"] = relationship(
        "BankStatementTransaction",
    )
    original_account: Mapped["Account | None"] = relationship(
        "Account",
        foreign_keys=[original_account_id],
    )
    corrected_account: Mapped["Account | None"] = relationship(
        "Account",
        foreign_keys=[corrected_account_id],
    )
