"""Typed inputs for portfolio's investment-posting boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from src.audit import Money, Quantity, UnitPrice

INVESTMENT_QUANTITY_UNIT = "units"
CostBasisMethodValue = Literal["FIFO", "LIFO", "AvgCost"]


@dataclass(frozen=True, slots=True)
class TradeOrder:
    """A buy/sell instruction with validated number dimensions."""

    transaction_date: date
    asset_identifier: str
    quantity: Quantity
    unit_price: UnitPrice
    fees: Money
    fx_rate: Decimal | None = None
    source_id: UUID | None = None
    cost_basis_method: CostBasisMethodValue = "FIFO"

    def __post_init__(self) -> None:
        if self.quantity.unit.code != INVESTMENT_QUANTITY_UNIT:
            raise ValueError(f"trade quantity must use {INVESTMENT_QUANTITY_UNIT}")
        if self.unit_price.unit != self.quantity.unit:
            raise ValueError("trade quantity and unit price must use the same unit")
        if self.fees.currency != self.unit_price.currency:
            raise ValueError("trade fees and unit price must use the same currency")

    @classmethod
    def create(
        cls,
        *,
        transaction_date: date,
        asset_identifier: str,
        quantity: Decimal,
        unit_price: Decimal,
        currency: str,
        fees: Decimal = Decimal("0.00"),
        fx_rate: Decimal | None = None,
        source_id: UUID | None = None,
        cost_basis_method: CostBasisMethodValue = "FIFO",
    ) -> TradeOrder:
        """Construct a dimension-safe order from an API/import payload."""
        return cls(
            transaction_date=transaction_date,
            asset_identifier=asset_identifier,
            quantity=Quantity(quantity, INVESTMENT_QUANTITY_UNIT),
            unit_price=UnitPrice(unit_price, currency, INVESTMENT_QUANTITY_UNIT),
            fees=Money(fees, currency),
            fx_rate=fx_rate,
            source_id=source_id,
            cost_basis_method=cost_basis_method,
        )


@dataclass(frozen=True, slots=True)
class TradeAccounts:
    """Ledger accounts participating in one investment posting."""

    cash: UUID
    investment: UUID
    realized_pnl: UUID | None = None
    dividend_income: UUID | None = None
    withholding_tax: UUID | None = None


@dataclass(frozen=True, slots=True)
class DividendEvent:
    """A dividend and its optional withholding, in one currency."""

    payment_date: date
    asset_identifier: str
    gross_amount: Money
    withholding_tax: Money
    fx_rate: Decimal | None = None
    source_id: UUID | None = None
    dividend_type: str = "ordinary"

    def __post_init__(self) -> None:
        if self.gross_amount.currency != self.withholding_tax.currency:
            raise ValueError("dividend and withholding tax must use the same currency")

    @classmethod
    def create(
        cls,
        *,
        payment_date: date,
        asset_identifier: str,
        gross_amount: Decimal,
        currency: str,
        withholding_tax: Decimal = Decimal("0.00"),
        fx_rate: Decimal | None = None,
        source_id: UUID | None = None,
        dividend_type: str = "ordinary",
    ) -> DividendEvent:
        """Construct a dimension-safe dividend from an API/import payload."""
        return cls(
            payment_date=payment_date,
            asset_identifier=asset_identifier,
            gross_amount=Money(gross_amount, currency),
            withholding_tax=Money(withholding_tax, currency),
            fx_rate=fx_rate,
            source_id=source_id,
            dividend_type=dividend_type,
        )
