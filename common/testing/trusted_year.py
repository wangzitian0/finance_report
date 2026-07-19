"""Small, independent annual scenario for terminal report-package proof (#696)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class TrustedYearError(ValueError):
    """Raised when scenario truth or its proof binding is ambiguous."""


def _text(value: str, field: str) -> None:
    if not value.strip():
        raise TrustedYearError(f"{field} is required")


def _money(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal):
        raise TrustedYearError(f"{field} must be Decimal")


class MovementType(StrEnum):
    """Economic meanings required by the v0 oracle, not a product taxonomy."""

    INCOME = "income"
    EXPENSE = "expense"
    INVESTMENT_PURCHASE = "investment_purchase"


@dataclass(frozen=True, slots=True)
class TrustedYearMovement:
    description: str
    occurred_on: date
    type: MovementType
    amount: Decimal

    def __post_init__(self) -> None:
        _text(self.description, "movement.description")
        _money(self.amount, "movement.amount")
        if self.amount <= 0:
            raise TrustedYearError("movement.amount must be positive")


@dataclass(frozen=True, slots=True)
class TrustedYearPosition:
    institution: str
    symbol: str
    quantity: Decimal
    source_value: Decimal
    selected_value: Decimal
    as_of: date

    def __post_init__(self) -> None:
        _text(self.institution, "position.institution")
        _text(self.symbol, "position.symbol")
        for field in ("quantity", "source_value", "selected_value"):
            _money(getattr(self, field), f"position.{field}")
        if self.quantity <= 0 or self.source_value < 0 or self.selected_value < 0:
            raise TrustedYearError("position values are outside their valid range")


@dataclass(frozen=True, slots=True)
class TrustedYearValuation:
    component_type: str
    liquidity_class: str
    value: Decimal
    source: str
    as_of: date

    def __post_init__(self) -> None:
        _text(self.component_type, "valuation.component_type")
        _text(self.liquidity_class, "valuation.liquidity_class")
        _text(self.source, "valuation.source")
        _money(self.value, "valuation.value")
        if self.value < 0:
            raise TrustedYearError("valuation.value must not be negative")


@dataclass(frozen=True, slots=True)
class TrustedYearExpected:
    ending_cash: Decimal
    net_income: Decimal
    investment_purchase: Decimal
    investment_market_value: Decimal
    total_assets: Decimal
    total_liabilities: Decimal
    ledger_equity: Decimal
    net_worth_adjustment: Decimal

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            _money(getattr(self, field), f"expected.{field}")
        if (
            self.total_liabilities
            + self.ledger_equity
            + self.net_income
            + self.net_worth_adjustment
            != self.total_assets
        ):
            raise TrustedYearError("expected balance-sheet equation does not close")


@dataclass(frozen=True, slots=True)
class TrustedYearScenario:
    scenario_id: str
    currency: str
    opening_cash: Decimal
    movements: tuple[TrustedYearMovement, ...]
    position: TrustedYearPosition
    valuation: TrustedYearValuation
    expected_manifest: tuple[str, ...]
    expected: TrustedYearExpected

    def __post_init__(self) -> None:
        _text(self.scenario_id, "scenario_id")
        _text(self.currency, "currency")
        _money(self.opening_cash, "opening_cash")
        if self.opening_cash <= 0:
            raise TrustedYearError("opening_cash must be positive")
        if {movement.type for movement in self.movements} != set(MovementType):
            raise TrustedYearError(
                "scenario requires income, expense, and investment purchase"
            )
        if not self.expected_manifest or len(set(self.expected_manifest)) != len(
            self.expected_manifest
        ):
            raise TrustedYearError("expected_manifest must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class TrustedYearProofBinding:
    proof_id: str
    scenario_ids: tuple[str, ...]
    oracle_kind: str

    def __post_init__(self) -> None:
        _text(self.proof_id, "proof_id")
        _text(self.oracle_kind, "oracle_kind")
        if len(self.scenario_ids) != 1 or not self.scenario_ids[0].strip():
            raise TrustedYearError("a terminal proof must bind exactly one scenario")


TRUSTED_YEAR_SCENARIO = TrustedYearScenario(
    scenario_id="trusted-year-v0",
    currency="SGD",
    opening_cash=Decimal("10000.00"),
    movements=(
        TrustedYearMovement(
            "Salary credit", date(2026, 6, 5), MovementType.INCOME, Decimal("5000.00")
        ),
        TrustedYearMovement(
            "Rent debit", date(2026, 6, 10), MovementType.EXPENSE, Decimal("1000.00")
        ),
        TrustedYearMovement(
            "Buy security",
            date(2026, 6, 15),
            MovementType.INVESTMENT_PURCHASE,
            Decimal("1000.00"),
        ),
    ),
    position=TrustedYearPosition(
        institution="Moomoo",
        symbol="AAPL",
        quantity=Decimal("10"),
        source_value=Decimal("1200.00"),
        selected_value=Decimal("1250.00"),
        as_of=date(2026, 12, 31),
    ),
    valuation=TrustedYearValuation(
        component_type="property_value",
        liquidity_class="illiquid",
        value=Decimal("100000.00"),
        source="trusted-year-reviewed-appraisal",
        as_of=date(2026, 12, 31),
    ),
    expected_manifest=(
        "account",
        "journal_entry",
        "journal_line",
        "pricing_observation",
        "source_document",
        "statement_result",
    ),
    expected=TrustedYearExpected(
        ending_cash=Decimal("13000.00"),
        net_income=Decimal("4000.00"),
        investment_purchase=Decimal("1000.00"),
        investment_market_value=Decimal("1250.00"),
        total_assets=Decimal("115250.00"),
        total_liabilities=Decimal("0.00"),
        ledger_equity=Decimal("10000.00"),
        net_worth_adjustment=Decimal("101250.00"),
    ),
)
