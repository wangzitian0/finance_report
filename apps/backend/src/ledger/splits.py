"""Composite-transaction split helpers for specialized accounting flows.

Flow 20 — Gross-to-Net Dividend with Tax Withholding (WHT)
    Dr Asset:Cash            net_amount
    Dr Expense:WHT           tax_amount  (= gross - net)
    Cr Income:Dividends      gross_amount
    Invariant: net_amount + tax_amount == gross_amount

Flow 22 — Mortgage Payment (Principal + Interest)
    Dr Expense:Interest      interest_amount
    Dr Liability:Mortgage    principal_amount
    Cr Asset:Cash            total_payment
    Invariant: interest_amount + principal_amount == total_payment

All arithmetic is Decimal, quantized to 2 dp (ROUND_HALF_UP). Derived sides
are computed by subtraction from the authoritative total so debits == credits
exactly with zero rounding drift.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "Direction",
    "AccountKind",
    "SplitLine",
    "DividendSplit",
    "MortgageSplit",
    "PayrollSplit",
    "ReconciliationAdjustment",
    "TransferFxSplit",
    "calculate_dividend_split",
    "calculate_mortgage_split",
    "calculate_payroll_split",
    "calculate_reconciliation_adjustment",
    "calculate_transfer_fx_split",
]

ZERO = Decimal("0")
ONE = Decimal("1")
MONEY_Q = Decimal("0.01")
RATE_Q = Decimal("0.000001")  # 6 dp, reporting only


def quantize_money(v: Decimal) -> Decimal:
    """Quantize to standard two decimal places using ROUND_HALF_UP."""
    return v.quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def quantize_rate(v: Decimal) -> Decimal:
    """Quantize tax/interest rate to 6 decimal places."""
    return v.quantize(RATE_Q, rounding=ROUND_HALF_UP)


class Direction(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class AccountKind(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    INCOME = "income"
    EXPENSE = "expense"


class SplitLine(BaseModel):
    """One double-entry line in a composite split."""

    model_config = ConfigDict(frozen=True)

    role: str
    account_kind: AccountKind
    direction: Direction
    amount: Decimal = Field(ge=ZERO)
    account_code: str | None = None

    @field_validator("amount")
    @classmethod
    def _quantized(cls, v: Decimal) -> Decimal:
        return quantize_money(v)


def _assert_balanced(lines: Sequence[SplitLine]) -> None:
    debits = sum((line.amount for line in lines if line.direction is Direction.DEBIT), ZERO)
    credits = sum((line.amount for line in lines if line.direction is Direction.CREDIT), ZERO)
    if debits != credits:
        raise ValueError(f"split unbalanced: debit {debits} != credit {credits}")


class DividendSplit(BaseModel):
    """Result of dividend gross-to-net withholding tax split."""

    model_config = ConfigDict(frozen=True)

    gross_amount: Decimal
    net_amount: Decimal
    tax_amount: Decimal
    requested_tax_rate: Decimal
    effective_tax_rate: Decimal
    lines: tuple[SplitLine, ...]

    @model_validator(mode="after")
    def _invariants(self) -> DividendSplit:
        if self.net_amount + self.tax_amount != self.gross_amount:
            raise ValueError(f"dividend unbalanced: {self.net_amount} + {self.tax_amount} != {self.gross_amount}")
        _assert_balanced(self.lines)
        return self


class MortgageSplit(BaseModel):
    """Result of mortgage principal and interest payment split."""

    model_config = ConfigDict(frozen=True)

    total_payment: Decimal
    interest_amount: Decimal
    principal_amount: Decimal
    lines: tuple[SplitLine, ...]

    @model_validator(mode="after")
    def _invariants(self) -> MortgageSplit:
        if self.interest_amount + self.principal_amount != self.total_payment:
            raise ValueError(
                f"mortgage unbalanced: {self.interest_amount} + {self.principal_amount} != {self.total_payment}"
            )
        _assert_balanced(self.lines)
        return self


def calculate_dividend_split(
    gross_amount: Decimal,
    withholding_tax_rate: Decimal = Decimal("0.30"),
    net_amount: Decimal | None = None,
) -> DividendSplit:
    """Calculate gross dividend, withholding tax, and net cash received.

    If `net_amount` is provided, it overrides `withholding_tax_rate` to match
    the exact statement figure; tax is derived as gross - net to ensure zero drift.
    """
    gross = quantize_money(gross_amount)
    if gross < ZERO:
        raise ValueError("gross_amount must be >= 0")
    if not (ZERO <= withholding_tax_rate <= ONE):
        raise ValueError("withholding_tax_rate must be within [0, 1]")

    if net_amount is None:
        net = quantize_money(gross * (ONE - withholding_tax_rate))
    else:
        net = quantize_money(net_amount)

    tax = gross - net
    if tax < ZERO:
        raise ValueError(f"net_amount ({net}) exceeds gross_amount ({gross})")

    effective_rate = quantize_rate(tax / gross) if gross > ZERO else ZERO

    return DividendSplit(
        gross_amount=gross,
        net_amount=net,
        tax_amount=tax,
        requested_tax_rate=withholding_tax_rate,
        effective_tax_rate=effective_rate,
        lines=(
            SplitLine(
                role="net_cash_received",
                account_kind=AccountKind.ASSET,
                direction=Direction.DEBIT,
                amount=net,
            ),
            SplitLine(
                role="withholding_tax_expense",
                account_kind=AccountKind.EXPENSE,
                direction=Direction.DEBIT,
                amount=tax,
            ),
            SplitLine(
                role="dividend_income",
                account_kind=AccountKind.INCOME,
                direction=Direction.CREDIT,
                amount=gross,
            ),
        ),
    )


def calculate_mortgage_split(
    total_payment: Decimal,
    interest_amount: Decimal,
    principal_amount: Decimal | None = None,
) -> MortgageSplit:
    """Calculate mortgage payment split into principal amortization and interest expense.

    If `principal_amount` is None, it is derived as total - interest.
    If both are supplied, they must sum to total exactly.
    """
    total = quantize_money(total_payment)
    interest = quantize_money(interest_amount)

    if total < ZERO:
        raise ValueError("total_payment must be >= 0")
    if interest < ZERO:
        raise ValueError("interest_amount must be >= 0")
    if interest > total:
        raise ValueError(f"interest_amount ({interest}) exceeds total_payment ({total})")

    principal = quantize_money(principal_amount) if principal_amount is not None else total - interest
    if principal < ZERO:
        raise ValueError(f"principal_amount must be >= 0 (got {principal})")
    if interest + principal != total:
        raise ValueError(f"interest + principal ({interest} + {principal}) != total ({total})")

    return MortgageSplit(
        total_payment=total,
        interest_amount=interest,
        principal_amount=principal,
        lines=(
            SplitLine(
                role="interest_expense",
                account_kind=AccountKind.EXPENSE,
                direction=Direction.DEBIT,
                amount=interest,
            ),
            SplitLine(
                role="principal_reduction",
                account_kind=AccountKind.LIABILITY,
                direction=Direction.DEBIT,
                amount=principal,
            ),
            SplitLine(
                role="cash_paid",
                account_kind=AccountKind.ASSET,
                direction=Direction.CREDIT,
                amount=total,
            ),
        ),
    )


class PayrollSplit(BaseModel):
    """Result of payroll gross-to-net deduction split."""

    model_config = ConfigDict(frozen=True)

    gross_salary: Decimal
    net_payout: Decimal
    income_tax: Decimal
    employee_deductions: Decimal
    employer_contributions: Decimal = ZERO
    lines: tuple[SplitLine, ...]

    @model_validator(mode="after")
    def _invariants(self) -> PayrollSplit:
        if self.net_payout + self.income_tax + self.employee_deductions != self.gross_salary:
            raise ValueError(
                f"net payout ({self.net_payout}) + tax ({self.income_tax}) + deductions ({self.employee_deductions}) "
                f"!= gross salary ({self.gross_salary})"
            )
        _assert_balanced(self.lines)
        return self


def calculate_payroll_split(
    gross_salary: Decimal,
    income_tax: Decimal,
    employee_deductions: Decimal,
    net_payout: Decimal | None = None,
    employer_contributions: Decimal = ZERO,
) -> PayrollSplit:
    """Calculate payroll split with gross, tax withholding, employee deductions, and net payout."""
    gross = quantize_money(gross_salary)
    tax = quantize_money(income_tax)
    ee_ded = quantize_money(employee_deductions)
    er_contrib = quantize_money(employer_contributions)

    if gross < ZERO or tax < ZERO or ee_ded < ZERO or er_contrib < ZERO:
        raise ValueError("All payroll amounts must be >= 0")

    expected_net = gross - tax - ee_ded
    if expected_net < ZERO:
        raise ValueError("Tax and employee deductions exceed gross salary")

    actual_net = quantize_money(net_payout) if net_payout is not None else expected_net
    if actual_net + tax + ee_ded != gross:
        raise ValueError(f"net payout + tax + deductions ({actual_net + tax + ee_ded}) != gross salary ({gross})")

    lines_list = [
        SplitLine(
            role="gross_salary_expense",
            account_kind=AccountKind.EXPENSE,
            direction=Direction.DEBIT,
            amount=gross,
        ),
        SplitLine(
            role="net_cash_payout",
            account_kind=AccountKind.ASSET,
            direction=Direction.CREDIT,
            amount=actual_net,
        ),
        SplitLine(
            role="income_tax_withholding",
            account_kind=AccountKind.LIABILITY,
            direction=Direction.CREDIT,
            amount=tax,
        ),
        SplitLine(
            role="employee_pension_deduction",
            account_kind=AccountKind.LIABILITY,
            direction=Direction.CREDIT,
            amount=ee_ded,
        ),
    ]

    if er_contrib > ZERO:
        lines_list.extend(
            [
                SplitLine(
                    role="employer_pension_expense",
                    account_kind=AccountKind.EXPENSE,
                    direction=Direction.DEBIT,
                    amount=er_contrib,
                ),
                SplitLine(
                    role="employer_pension_payable",
                    account_kind=AccountKind.LIABILITY,
                    direction=Direction.CREDIT,
                    amount=er_contrib,
                ),
            ]
        )

    return PayrollSplit(
        gross_salary=gross,
        net_payout=actual_net,
        income_tax=tax,
        employee_deductions=ee_ded,
        employer_contributions=er_contrib,
        lines=tuple(lines_list),
    )


class ReconciliationAdjustment(BaseModel):
    """Result of immaterial rounding / penny discrepancy write-off."""

    model_config = ConfigDict(frozen=True)

    bank_balance: Decimal
    book_balance: Decimal
    difference: Decimal
    is_gain: bool
    lines: tuple[SplitLine, ...]

    @model_validator(mode="after")
    def _invariants(self) -> ReconciliationAdjustment:
        _assert_balanced(self.lines)
        return self


def calculate_reconciliation_adjustment(
    bank_balance: Decimal,
    book_balance: Decimal,
    threshold: Decimal = Decimal("0.05"),
) -> ReconciliationAdjustment:
    """Calculate small penny rounding adjustment between bank and book balance."""
    bank = quantize_money(bank_balance)
    book = quantize_money(book_balance)
    diff = quantize_money(bank - book)

    if abs(diff) > quantize_money(threshold):
        raise ValueError(f"difference {diff} exceeds immaterial threshold {threshold}")

    is_gain = diff > ZERO
    abs_diff = abs(diff)

    if diff == ZERO:
        lines: tuple[SplitLine, ...] = ()
    elif is_gain:
        lines = (
            SplitLine(
                role="bank_adjustment",
                account_kind=AccountKind.ASSET,
                direction=Direction.DEBIT,
                amount=abs_diff,
            ),
            SplitLine(
                role="rounding_income",
                account_kind=AccountKind.INCOME,
                direction=Direction.CREDIT,
                amount=abs_diff,
            ),
        )
    else:
        lines = (
            SplitLine(
                role="rounding_expense",
                account_kind=AccountKind.EXPENSE,
                direction=Direction.DEBIT,
                amount=abs_diff,
            ),
            SplitLine(
                role="bank_adjustment",
                account_kind=AccountKind.ASSET,
                direction=Direction.CREDIT,
                amount=abs_diff,
            ),
        )

    return ReconciliationAdjustment(
        bank_balance=bank,
        book_balance=book,
        difference=diff,
        is_gain=is_gain,
        lines=lines,
    )


class TransferFxSplit(BaseModel):
    """Result of cross-currency transfer realized FX gain/loss decomposition."""

    model_config = ConfigDict(frozen=True)

    source_amount: Decimal
    source_currency: str
    source_base_value: Decimal
    target_amount: Decimal
    target_currency: str
    target_base_value: Decimal
    realized_gain_loss: Decimal
    is_gain: bool
    lines: tuple[SplitLine, ...]

    @model_validator(mode="after")
    def _invariants(self) -> TransferFxSplit:
        _assert_balanced(self.lines)
        return self


def calculate_transfer_fx_split(
    source_amount: Decimal,
    source_currency: str,
    source_to_base_rate: Decimal,
    target_amount: Decimal,
    target_currency: str,
    target_to_base_rate: Decimal,
    base_currency: str = "USD",
) -> TransferFxSplit:
    """Calculate multi-currency transfer with realized FX gain or loss."""
    src_amt = quantize_money(source_amount)
    tgt_amt = quantize_money(target_amount)
    src_val = quantize_money(src_amt * source_to_base_rate)
    tgt_val = quantize_money(tgt_amt * target_to_base_rate)

    diff = tgt_val - src_val
    is_gain = diff >= ZERO
    abs_diff = abs(diff)

    lines: tuple[SplitLine, ...]
    if diff == ZERO:
        lines = (
            SplitLine(
                role="target_asset",
                account_kind=AccountKind.ASSET,
                direction=Direction.DEBIT,
                amount=tgt_val,
            ),
            SplitLine(
                role="source_asset",
                account_kind=AccountKind.ASSET,
                direction=Direction.CREDIT,
                amount=src_val,
            ),
        )
    elif is_gain:
        lines = (
            SplitLine(
                role="target_asset",
                account_kind=AccountKind.ASSET,
                direction=Direction.DEBIT,
                amount=tgt_val,
            ),
            SplitLine(
                role="realized_fx_gain",
                account_kind=AccountKind.INCOME,
                direction=Direction.CREDIT,
                amount=abs_diff,
            ),
            SplitLine(
                role="source_asset",
                account_kind=AccountKind.ASSET,
                direction=Direction.CREDIT,
                amount=src_val,
            ),
        )
    else:
        lines = (
            SplitLine(
                role="target_asset",
                account_kind=AccountKind.ASSET,
                direction=Direction.DEBIT,
                amount=tgt_val,
            ),
            SplitLine(
                role="realized_fx_loss",
                account_kind=AccountKind.EXPENSE,
                direction=Direction.DEBIT,
                amount=abs_diff,
            ),
            SplitLine(
                role="source_asset",
                account_kind=AccountKind.ASSET,
                direction=Direction.CREDIT,
                amount=src_val,
            ),
        )

    return TransferFxSplit(
        source_amount=src_amt,
        source_currency=source_currency,
        source_base_value=src_val,
        target_amount=tgt_amt,
        target_currency=target_currency,
        target_base_value=tgt_val,
        realized_gain_loss=diff,
        is_gain=is_gain,
        lines=lines,
    )
