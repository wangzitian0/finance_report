"""Pure calculation core for Income Statement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.audit.money import to_money


@dataclass(frozen=True)
class IncomeStatementTotals:
    """Immutable calculation outcome of an income statement evaluation."""

    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal


def calculate_line_total(lines: Sequence[Mapping[str, Any] | Any]) -> Decimal:
    """Sum amounts from report lines with 2-decimal money quantization."""
    total = sum(
        (Decimal(str(line["amount"] if isinstance(line, Mapping) else getattr(line, "amount"))) for line in lines),
        Decimal("0.00"),
    )
    return to_money(total)


def calculate_income_statement_totals(
    income_lines: Sequence[Mapping[str, Any] | Any],
    expense_lines: Sequence[Mapping[str, Any] | Any],
) -> IncomeStatementTotals:
    """Calculate total income, total expenses, and net income (income - expenses)."""
    total_income = calculate_line_total(income_lines)
    total_expenses = calculate_line_total(expense_lines)
    net_income = to_money(total_income - total_expenses)
    return IncomeStatementTotals(
        total_income=total_income,
        total_expenses=total_expenses,
        net_income=net_income,
    )
