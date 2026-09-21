"""TDD Test Suite for Flow 20 & Flow 22: Specialized Accounting Splits.

Verifies:
1. Flow 20: Gross-to-Net Dividend Split with Withholding Tax (WHT).
   - Dr Asset:Cash (net_amount)
   - Dr Expense:WithholdingTax (tax_amount)
   - Cr Income:Dividend (gross_amount)
   - Invariant: net_amount + tax_amount == gross_amount (exact decimal balance).

2. Flow 22: Mortgage Payment Split (Principal Amortization + Interest).
   - Dr Expense:MortgageInterest (interest_amount)
   - Dr Liability:MortgagePrincipal (principal_amount)
   - Cr Asset:Cash (total_payment)
   - Invariant: interest_amount + principal_amount == total_payment (exact decimal balance).
"""

from decimal import Decimal

import pytest

from src.ledger.splits import (
    AccountKind,
    Direction,
    DividendSplit,
    MortgageSplit,
    calculate_dividend_split,
    calculate_mortgage_split,
    calculate_payroll_split,
    calculate_reconciliation_adjustment,
    calculate_transfer_fx_split,
)


def test_flow_20_dividend_split_derived_from_rate():
    """AC-splits.dividend.1: Compute net and 30% withholding tax from gross dividend."""
    gross = Decimal("1000.00")
    rate = Decimal("0.30")

    result = calculate_dividend_split(gross_amount=gross, withholding_tax_rate=rate)

    assert isinstance(result, DividendSplit)
    assert result.gross_amount == Decimal("1000.00")
    assert result.net_amount == Decimal("700.00")
    assert result.tax_amount == Decimal("300.00")
    assert result.effective_tax_rate == Decimal("0.300000")

    # Invariants
    assert result.net_amount + result.tax_amount == result.gross_amount

    # Line breakdown
    lines = result.lines
    assert len(lines) == 3

    cash_line = next(item for item in lines if item.role == "net_cash_received")
    assert cash_line.account_kind == AccountKind.ASSET
    assert cash_line.direction == Direction.DEBIT
    assert cash_line.amount == Decimal("700.00")

    tax_line = next(item for item in lines if item.role == "withholding_tax_expense")
    assert tax_line.account_kind == AccountKind.EXPENSE
    assert tax_line.direction == Direction.DEBIT
    assert tax_line.amount == Decimal("300.00")

    income_line = next(item for item in lines if item.role == "dividend_income")
    assert income_line.account_kind == AccountKind.INCOME
    assert income_line.direction == Direction.CREDIT
    assert income_line.amount == Decimal("1000.00")


def test_flow_20_dividend_split_explicit_net_override():
    """AC-splits.dividend.2: Explicit net amount overrides default tax rate and prevents rounding drift."""
    gross = Decimal("100.00")
    # Suppose bank statement shows net cash received 72.45
    result = calculate_dividend_split(gross_amount=gross, net_amount=Decimal("72.45"))

    assert result.gross_amount == Decimal("100.00")
    assert result.net_amount == Decimal("72.45")
    assert result.tax_amount == Decimal("27.55")
    assert result.net_amount + result.tax_amount == result.gross_amount
    assert result.effective_tax_rate == Decimal("0.275500")


def test_flow_20_dividend_split_fractional_cent_rounding():
    """AC-splits.dividend.3: Half-up quantization guarantees exact balance on fractional cents."""
    gross = Decimal("100.00")
    rate = Decimal("0.3333")  # 33.33%

    result = calculate_dividend_split(gross_amount=gross, withholding_tax_rate=rate)

    assert result.net_amount == Decimal("66.67")
    assert result.tax_amount == Decimal("33.33")
    assert result.net_amount + result.tax_amount == Decimal("100.00")


def test_flow_20_dividend_split_invalid_amounts():
    """AC-splits.dividend.4: Reject negative amounts or net exceeding gross."""
    with pytest.raises(ValueError, match="gross_amount must be >= 0"):
        calculate_dividend_split(gross_amount=Decimal("-50.00"))

    with pytest.raises(ValueError, match="exceeds gross_amount"):
        calculate_dividend_split(gross_amount=Decimal("100.00"), net_amount=Decimal("120.00"))


def test_flow_22_mortgage_split_derived_principal():
    """AC-splits.mortgage.1: Derive principal reduction from total payment and interest."""
    total = Decimal("3500.00")
    interest = Decimal("1850.25")

    result = calculate_mortgage_split(total_payment=total, interest_amount=interest)

    assert isinstance(result, MortgageSplit)
    assert result.total_payment == Decimal("3500.00")
    assert result.interest_amount == Decimal("1850.25")
    assert result.principal_amount == Decimal("1649.75")
    assert result.interest_amount + result.principal_amount == result.total_payment

    lines = result.lines
    assert len(lines) == 3

    interest_line = next(item for item in lines if item.role == "interest_expense")
    assert interest_line.account_kind == AccountKind.EXPENSE
    assert interest_line.direction == Direction.DEBIT
    assert interest_line.amount == Decimal("1850.25")

    principal_line = next(item for item in lines if item.role == "principal_reduction")
    assert principal_line.account_kind == AccountKind.LIABILITY
    assert principal_line.direction == Direction.DEBIT
    assert principal_line.amount == Decimal("1649.75")

    cash_line = next(item for item in lines if item.role == "cash_paid")
    assert cash_line.account_kind == AccountKind.ASSET
    assert cash_line.direction == Direction.CREDIT
    assert cash_line.amount == Decimal("3500.00")


def test_flow_22_mortgage_split_explicit_principal_validation():
    """AC-splits.mortgage.2: If explicit principal is provided, it must strictly sum to total."""
    # Valid
    result = calculate_mortgage_split(
        total_payment=Decimal("3000.00"),
        interest_amount=Decimal("1000.00"),
        principal_amount=Decimal("2000.00"),
    )
    assert result.total_payment == Decimal("3000.00")

    # Invalid mismatch
    with pytest.raises(ValueError, match="!= total"):
        calculate_mortgage_split(
            total_payment=Decimal("3000.00"),
            interest_amount=Decimal("1000.00"),
            principal_amount=Decimal("1999.00"),
        )


def test_flow_14_payroll_split_derived_net():
    """Flow 14: Salary gross-to-net derivation and double-entry balance."""
    result = calculate_payroll_split(
        gross_salary=Decimal("10000.00"),
        income_tax=Decimal("1500.00"),
        employee_deductions=Decimal("2000.00"),
    )
    assert result.net_payout == Decimal("6500.00")
    assert result.gross_salary == Decimal("10000.00")
    assert result.net_payout + result.income_tax + result.employee_deductions == result.gross_salary

    lines = result.lines
    assert len(lines) == 4

    gross_line = next(item for item in lines if item.role == "gross_salary_expense")
    assert gross_line.account_kind == AccountKind.EXPENSE
    assert gross_line.direction == Direction.DEBIT
    assert gross_line.amount == Decimal("10000.00")

    net_line = next(item for item in lines if item.role == "net_cash_payout")
    assert net_line.account_kind == AccountKind.ASSET
    assert net_line.direction == Direction.CREDIT
    assert net_line.amount == Decimal("6500.00")

    tax_line = next(item for item in lines if item.role == "income_tax_withholding")
    assert tax_line.account_kind == AccountKind.LIABILITY
    assert tax_line.direction == Direction.CREDIT
    assert tax_line.amount == Decimal("1500.00")

    pension_line = next(item for item in lines if item.role == "employee_pension_deduction")
    assert pension_line.account_kind == AccountKind.LIABILITY
    assert pension_line.direction == Direction.CREDIT
    assert pension_line.amount == Decimal("2000.00")


def test_flow_14_payroll_split_with_employer_contributions():
    """Flow 14: Payroll split including employer-side pension/CPF contributions."""
    result = calculate_payroll_split(
        gross_salary=Decimal("10000.00"),
        income_tax=Decimal("1500.00"),
        employee_deductions=Decimal("2000.00"),
        employer_contributions=Decimal("1700.00"),
    )
    assert result.employer_contributions == Decimal("1700.00")
    lines = result.lines
    assert len(lines) == 6

    er_exp = next(item for item in lines if item.role == "employer_pension_expense")
    assert er_exp.account_kind == AccountKind.EXPENSE
    assert er_exp.direction == Direction.DEBIT
    assert er_exp.amount == Decimal("1700.00")

    er_liab = next(item for item in lines if item.role == "employer_pension_payable")
    assert er_liab.account_kind == AccountKind.LIABILITY
    assert er_liab.direction == Direction.CREDIT
    assert er_liab.amount == Decimal("1700.00")


def test_flow_14_payroll_split_validation_failure():
    """Flow 14: Rejects mismatched explicit net payout."""
    with pytest.raises(ValueError, match="!= gross salary"):
        calculate_payroll_split(
            gross_salary=Decimal("10000.00"),
            income_tax=Decimal("1500.00"),
            employee_deductions=Decimal("2000.00"),
            net_payout=Decimal("6499.00"),
        )


def test_flow_18_reconciliation_adjustment_loss():
    """Flow 18: Negative difference (bank < book) posts BankRoundingDifference expense."""
    result = calculate_reconciliation_adjustment(
        bank_balance=Decimal("1000.00"),
        book_balance=Decimal("1000.03"),
        threshold=Decimal("0.05"),
    )
    assert result.difference == Decimal("-0.03")
    assert result.is_gain is False
    assert len(result.lines) == 2

    exp_line = next(item for item in result.lines if item.role == "rounding_expense")
    assert exp_line.account_kind == AccountKind.EXPENSE
    assert exp_line.direction == Direction.DEBIT
    assert exp_line.amount == Decimal("0.03")

    asset_line = next(item for item in result.lines if item.role == "bank_adjustment")
    assert asset_line.account_kind == AccountKind.ASSET
    assert asset_line.direction == Direction.CREDIT
    assert asset_line.amount == Decimal("0.03")


def test_flow_18_reconciliation_adjustment_gain():
    """Flow 18: Positive difference (bank > book) posts RoundingGain income."""
    result = calculate_reconciliation_adjustment(
        bank_balance=Decimal("1000.02"),
        book_balance=Decimal("1000.00"),
        threshold=Decimal("0.05"),
    )
    assert result.difference == Decimal("0.02")
    assert result.is_gain is True
    assert len(result.lines) == 2

    asset_line = next(item for item in result.lines if item.role == "bank_adjustment")
    assert asset_line.account_kind == AccountKind.ASSET
    assert asset_line.direction == Direction.DEBIT
    assert asset_line.amount == Decimal("0.02")

    gain_line = next(item for item in result.lines if item.role == "rounding_income")
    assert gain_line.account_kind == AccountKind.INCOME
    assert gain_line.direction == Direction.CREDIT
    assert gain_line.amount == Decimal("0.02")


def test_flow_18_reconciliation_adjustment_threshold_exceeded():
    """Flow 18: Rejects differences exceeding immaterial threshold."""
    with pytest.raises(ValueError, match="exceeds immaterial threshold"):
        calculate_reconciliation_adjustment(
            bank_balance=Decimal("1000.00"),
            book_balance=Decimal("1000.10"),
            threshold=Decimal("0.05"),
        )


def test_flow_17_transfer_fx_split_loss():
    """Flow 17: Inter-currency transfer with realized FX loss."""
    # 1000 EUR -> 1080 USD (base is USD). EUR rate: 1.10. 1000 EUR out = 1100 USD base. Inflow = 1080 USD base.
    # Realized FX loss = 20 USD.
    result = calculate_transfer_fx_split(
        source_amount=Decimal("1000.00"),
        source_currency="EUR",
        source_to_base_rate=Decimal("1.10"),
        target_amount=Decimal("1080.00"),
        target_currency="USD",
        target_to_base_rate=Decimal("1.00"),
        base_currency="USD",
    )
    assert result.source_base_value == Decimal("1100.00")
    assert result.target_base_value == Decimal("1080.00")
    assert result.realized_gain_loss == Decimal("-20.00")
    assert result.is_gain is False
    assert len(result.lines) == 3

    tgt_line = next(item for item in result.lines if item.role == "target_asset")
    assert tgt_line.direction == Direction.DEBIT
    assert tgt_line.amount == Decimal("1080.00")

    loss_line = next(item for item in result.lines if item.role == "realized_fx_loss")
    assert loss_line.direction == Direction.DEBIT
    assert loss_line.amount == Decimal("20.00")

    src_line = next(item for item in result.lines if item.role == "source_asset")
    assert src_line.direction == Direction.CREDIT
    assert src_line.amount == Decimal("1100.00")


def test_flow_17_transfer_fx_split_gain():
    """Flow 17: Inter-currency transfer with realized FX gain."""
    # 1000 EUR -> 1120 USD (base is USD). EUR rate: 1.10. 1000 EUR out = 1100 USD base. Inflow = 1120 USD base.
    # Realized FX gain = 20 USD.
    result = calculate_transfer_fx_split(
        source_amount=Decimal("1000.00"),
        source_currency="EUR",
        source_to_base_rate=Decimal("1.10"),
        target_amount=Decimal("1120.00"),
        target_currency="USD",
        target_to_base_rate=Decimal("1.00"),
        base_currency="USD",
    )
    assert result.source_base_value == Decimal("1100.00")
    assert result.target_base_value == Decimal("1120.00")
    assert result.realized_gain_loss == Decimal("20.00")
    assert result.is_gain is True
    assert len(result.lines) == 3

    tgt_line = next(item for item in result.lines if item.role == "target_asset")
    assert tgt_line.direction == Direction.DEBIT
    assert tgt_line.amount == Decimal("1120.00")

    gain_line = next(item for item in result.lines if item.role == "realized_fx_gain")
    assert gain_line.direction == Direction.CREDIT
    assert gain_line.amount == Decimal("20.00")

    src_line = next(item for item in result.lines if item.role == "source_asset")
    assert src_line.direction == Direction.CREDIT
    assert src_line.amount == Decimal("1100.00")
