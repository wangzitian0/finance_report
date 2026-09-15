"""Immutable initialization evidence; zero stock deliberately has no journal."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DDL, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class OpeningPositionRecord(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "opening_position_records"
    __table_args__ = (UniqueConstraint("account_id", "version", name="uq_opening_position_account_version"),)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    journal_entry_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("journal_entries.id"))
    decision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_decision_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)


OPENING_IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION guard_opening_position_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Opening position facts are immutable';
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER opening_position_immutable BEFORE UPDATE OR DELETE ON opening_position_records
FOR EACH ROW EXECUTE FUNCTION guard_opening_position_immutable();
"""
for statement in OPENING_IMMUTABILITY_SQL.split("CREATE TRIGGER"):
    sql = statement if statement.lstrip().startswith("CREATE OR REPLACE") else "CREATE TRIGGER" + statement
    event.listen(OpeningPositionRecord.__table__, "after_create", DDL(sql).execute_if(dialect="postgresql"))
