"""Portfolio management models - dividend income and market data overrides."""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Date, Enum as SQLEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    pass


class DividendType(str, Enum):
    """Dividend income tax classification."""

    ORDINARY = "ordinary"
    QUALIFIED = "qualified"


class DividendIncome(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Dividend income tracking for portfolio holdings.

    Links dividend payments to managed positions for portfolio performance
    and tax reporting.
    """

    __tablename__ = "dividend_income"

    position_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("managed_positions.id", ondelete="CASCADE"),
        nullable=False,
    )

    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    dividend_type: Mapped[DividendType] = mapped_column(
        SQLEnum(
            DividendType,
            name="dividend_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=DividendType.ORDINARY,
    )

    # Relationship removed - position_id FK is sufficient for queries

    def __repr__(self) -> str:
        return f"<DividendIncome {self.payment_date} {self.amount} {self.currency}>"


class PriceSource(str, Enum):
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
