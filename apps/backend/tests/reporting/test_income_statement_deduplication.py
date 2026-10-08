"""AC-reporting.income-statement.1: Test income statement line deduplication and zero folding."""

from decimal import Decimal

from src.reporting.extension.income_statement import _fold_and_deduplicate_lines


def test_fold_and_deduplicate_income_lines():
    raw_lines = [
        {"name": "Income - Other", "type": "income", "amount": Decimal("0.00"), "source_currency": "SGD"},
        {"name": "Income - Other", "type": "income", "amount": Decimal("150.00"), "source_currency": "SGD"},
        {"name": "Income - Other", "type": "income", "amount": Decimal("0.00"), "source_currency": "SGD"},
        {"name": "Income - Salary", "type": "income", "amount": Decimal("5000.00"), "source_currency": "SGD"},
        {"name": "Expense - Other", "type": "expense", "amount": Decimal("0.00"), "source_currency": "SGD"},
    ]
    folded = _fold_and_deduplicate_lines(raw_lines, filter_zero=True)
    assert len(folded) == 2
    assert folded[0]["name"] == "Income - Other"
    assert folded[0]["amount"] == Decimal("150.00")
    assert folded[1]["name"] == "Income - Salary"
    assert folded[1]["amount"] == Decimal("5000.00")


def test_fold_lines_keeps_single_zero_when_filter_zero_disabled():
    raw_lines = [
        {"name": "Income - Other", "type": "income", "amount": Decimal("0.00"), "source_currency": "SGD"},
        {"name": "Income - Other", "type": "income", "amount": Decimal("0.00"), "source_currency": "SGD"},
    ]
    folded = _fold_and_deduplicate_lines(raw_lines, filter_zero=False)
    assert len(folded) == 1
    assert folded[0]["name"] == "Income - Other"
    assert folded[0]["amount"] == Decimal("0.00")


def test_fold_lines_preserves_distinct_economic_categories():
    raw_lines = [
        {
            "name": "Fee Account",
            "type": "expense",
            "amount": Decimal("10.00"),
            "source_currency": "SGD",
            "economic_report_line_id": "econ-fee-1",
        },
        {
            "name": "Fee Account",
            "type": "expense",
            "amount": Decimal("20.00"),
            "source_currency": "SGD",
            "economic_report_line_id": "econ-fee-2",
        },
        {
            "name": "Fee Account",
            "type": "expense",
            "amount": Decimal("5.00"),
            "source_currency": "SGD",
            "economic_report_line_id": "econ-fee-1",
        },
    ]
    folded = _fold_and_deduplicate_lines(raw_lines, filter_zero=True)
    assert len(folded) == 2
    econ_1 = next(x for x in folded if x["economic_report_line_id"] == "econ-fee-1")
    econ_2 = next(x for x in folded if x["economic_report_line_id"] == "econ-fee-2")
    assert econ_1["amount"] == Decimal("15.00")
    assert econ_2["amount"] == Decimal("20.00")
