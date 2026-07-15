"""Manual market-price overrides — a pricing observation store.

Moved from ``src/models/portfolio.py`` (#1675 D5): the ``market_data_override``
table is one of the legacy observation stores ``SqlObservationRepository``
resolves over (see ``common/pricing/contract.py``), so ``pricing`` — not
``portfolio`` — owns it. Schema-neutral move (table/enum identity unchanged).
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, Enum as SQLEnum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class PriceSource(StrEnum):
    """Source of market price data."""

    MANUAL = "manual"
    API = "api"


class MarketDataOverride(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Manual price updates for portfolio valuation.

    Users update prices every few months via UI. This table stores manual
    price overrides that take precedence over API data.
    """

    __tablename__ = "market_data_override"
    __table_args__ = (CheckConstraint("price > 0", name="ck_market_data_override_price_positive"),)

    asset_identifier: Mapped[str] = mapped_column(String(100), nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    source: Mapped[PriceSource] = mapped_column(
        SQLEnum(
            PriceSource,
            name="price_source_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=PriceSource.MANUAL,
    )

    # Relationship removed - user_id from UserOwnedMixin is sufficient for queries

    def __repr__(self) -> str:
        return f"<MarketDataOverride {self.asset_identifier} {self.price} on {self.price_date}>"
