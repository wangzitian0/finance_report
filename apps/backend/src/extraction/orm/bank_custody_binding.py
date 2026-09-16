"""Extraction-owned DIM binding from available bank identity to ledger custody."""

from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.platform.orm.base import TimestampMixin, UUIDMixin


class BankCustodyBinding(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "bank_custody_bindings"
    __table_args__ = (
        UniqueConstraint("user_id", "institution", "account_last4", "currency", name="uq_bank_custody_identity"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    institution: Mapped[str] = mapped_column(String(100), nullable=False)
    account_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
