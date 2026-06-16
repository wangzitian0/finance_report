"""FX conversion model: a cross-currency transfer as a linked multi-leg event.

#1123 AC2. A cross-currency transfer (money leaves ``from_account`` in
``currency_from`` and arrives in ``to_account`` as ``currency_to`` at a
conversion ``rate``) is **one economic event**, not two independent
income/expense transactions. This additive linking table records the paired
multi-leg event so the accounting layer can treat it as net-zero for net worth
(minus ``fee``) and attribute rate moves to revaluation over time rather than to
the conversion event.

The table is additive and back-compatible: it links existing journal entries /
accounts without altering them. Optional ``from_journal_entry_id`` /
``to_journal_entry_id`` anchor the legs to their ledger entries when known.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DECIMAL, CheckConstraint, Date, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class FxConversion(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """A linked cross-currency transfer event (one out-leg + one in-leg).

    ``rate`` is quoted as ``currency_from / currency_to`` (units of the from
    currency per unit of the to currency), matching
    :func:`src.services.fx.get_exchange_rate`. Monetary amounts are
    ``DECIMAL(18, 2)``; the rate is ``DECIMAL(18, 6)`` like other FX rates.
    """

    __tablename__ = "fx_conversions"
    __table_args__ = (
        CheckConstraint("amount_from > 0", name="ck_fx_conversions_amount_from_positive"),
        CheckConstraint("amount_to > 0", name="ck_fx_conversions_amount_to_positive"),
        CheckConstraint("rate > 0", name="ck_fx_conversions_rate_positive"),
        CheckConstraint("fee >= 0", name="ck_fx_conversions_fee_non_negative"),
        CheckConstraint(
            "from_account_id <> to_account_id",
            name="ck_fx_conversions_distinct_accounts",
        ),
        Index("idx_fx_conversions_user_date", "user_id", "conversion_date"),
    )

    from_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount_from: Mapped[Decimal] = mapped_column(DECIMAL(18, 2), nullable=False)
    currency_from: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_to: Mapped[Decimal] = mapped_column(DECIMAL(18, 2), nullable=False)
    currency_to: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(DECIMAL(18, 6), nullable=False)
    fee: Mapped[Decimal] = mapped_column(DECIMAL(18, 2), nullable=False, default=Decimal("0"))
    fee_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    conversion_date: Mapped[date] = mapped_column(Date, nullable=False)

    from_journal_entry_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_journal_entry_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<FxConversion {self.amount_from} {self.currency_from} -> "
            f"{self.amount_to} {self.currency_to} @ {self.rate}>"
        )
