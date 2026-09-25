"""AC-reporting.income-statement.1: Pure domain unit tests for income statement totals and net income calculation."""

from decimal import Decimal

import pytest

from src.reporting.base.income_statement_calculator import (
    calculate_income_statement_totals,
    calculate_line_total,
)

pytestmark = pytest.mark.no_db


def test_positive_net_income():
    """AC-reporting.income-statement.1: Revenue exceeding expenses yields positive net income."""
    income_lines = [
        {"name": "Consulting Revenue", "amount": Decimal("5000.00")},
        {"name": "Interest Income", "amount": Decimal("250.50")},
    ]
    expense_lines = [
        {"name": "Office Rent", "amount": Decimal("1500.00")},
        {"name": "Cloud Subscriptions", "amount": Decimal("350.25")},
    ]
    totals = calculate_income_statement_totals(income_lines, expense_lines)

    assert totals.total_income == Decimal("5250.50")
    assert totals.total_expenses == Decimal("1850.25")
    assert totals.net_income == Decimal("3400.25")


def test_negative_net_income_net_loss():
    """AC-reporting.income-statement.1: Expenses exceeding revenue yields negative net income."""
    income_lines = [{"name": "Sales", "amount": Decimal("1200.00")}]
    expense_lines = [
        {"name": "COGS", "amount": Decimal("1500.00")},
        {"name": "Shipping", "amount": Decimal("300.00")},
    ]
    totals = calculate_income_statement_totals(income_lines, expense_lines)

    assert totals.total_income == Decimal("1200.00")
    assert totals.total_expenses == Decimal("1800.00")
    assert totals.net_income == Decimal("-600.00")


def test_empty_lines_zero_totals():
    """AC-reporting.income-statement.1: Empty report lines evaluate to zero without error."""
    totals = calculate_income_statement_totals([], [])
    assert totals.total_income == Decimal("0.00")
    assert totals.total_expenses == Decimal("0.00")
    assert totals.net_income == Decimal("0.00")


def test_line_total_heterogeneous_formats():
    """calculate_line_total handles string and Decimal amounts without precision loss."""
    lines = [
        {"amount": "100.55"},
        {"amount": Decimal("200.45")},
    ]
    assert calculate_line_total(lines) == Decimal("301.00")


def test_mutation_falsification():
    """Falsification test: Mutating an expense line must alter net income by exact difference."""
    income = [{"amount": Decimal("1000.00")}]
    expenses = [{"amount": Decimal("400.00")}]
    base = calculate_income_statement_totals(income, expenses)

    # Mutate expense by +$50.00
    mutated_expenses = [{"amount": Decimal("450.00")}]
    mutated = calculate_income_statement_totals(income, mutated_expenses)

    assert mutated.net_income == base.net_income - Decimal("50.00")
