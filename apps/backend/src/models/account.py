"""Account model for double-entry bookkeeping."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.journal import JournalLine


class AccountType(str, enum.Enum):
    """Account type classification."""

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class Account(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Account represents a ledger account in the chart of accounts.

    Follows the accounting equation:
    Assets = Liabilities + Equity + (Income - Expenses)
    """

    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    type: Mapped[AccountType] = mapped_column(Enum(AccountType, name="account_type_enum"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="SGD")
    parent_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    journal_lines: Mapped[list[JournalLine]] = relationship("JournalLine", back_populates="account")
    parent: Mapped[Account | None] = relationship("Account", remote_side="Account.id", back_populates="children")
    children: Mapped[list[Account]] = relationship("Account", back_populates="parent")

    def __repr__(self) -> str:
        return f"<Account {self.name} ({self.type.value})>"
