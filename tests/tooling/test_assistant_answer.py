"""AC-advisor.grounding.3: the assistant chat journey reads each amount after its label (#2461).

The journey U14 (`tests/e2e/test_assistant_chat_journey.py`) runs only on staging. These tests run
its answer checks with no deployment. Each mutated answer below must fail the check that the
journey uses, so a wrong, swapped or invented amount cannot pass the journey.

The two real answers are from staging v0.2.2 (2026-10-15), from the probe of #2461.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.e2e.assistant_answer import (
    METRIC_LABELS,
    QUESTION,
    misstated_metrics,
    money_amounts,
    says_no_data,
    stated_amounts,
)

ORACLE = {
    "net_worth": Decimal("13500.00"),
    "income": Decimal("5000.00"),
    "expenses": Decimal("1500.00"),
}
DATA_AMOUNTS = {
    Decimal("0"),
    Decimal("10000"),
    Decimal("13500"),
    Decimal("5000"),
    Decimal("1500"),
    Decimal("3500"),
}

STAGING_ANSWER = """Based on your financial data:

**Net Worth:** SGD 13,500.00
- Total Assets: SGD 13,500.00
- Total Liabilities: SGD 0.00
- Net Worth = Assets − Liabilities = SGD 13,500.00 ✓ (consistent with Opening Equity SGD 10,000.00 + Cumulative Net Income SGD 3,500.00)

**Monthly Income (earned):** SGD 5,000.00

**Monthly Expenses (spent):** SGD 1,500.00
- Your largest expense category is Housing at SGD 1,500.00

This means your monthly surplus is approximately SGD 3,500.00 (income minus expenses), which aligns with your cumulative net income figure.

Please note: Your report readiness is currently blocked (1 blocker related to opening coverage), and you have 2 unmatched transactions with a 0.0% reconciliation match rate.

The above analysis is for reference only."""

STAGING_REFUSAL = """I don't have that information available. Here's why:

**What I can see in your records:**
- The expense data currently available only covers a recent monthly summary, with the top (and only listed) expense category being **Housing: SGD 1,500.00**
- There is no dining category breakdown, and no transaction-level detail for March 2019 in the accessible data
- The market data observations in your records date from October 2026, which suggests your current data set does not extend back to March 2019

**What I cannot do:**
- I cannot fabricate or estimate a dining figure for that period, as it isn't supported by any data in your records

Your report package is currently **blocked** (1 blocker), and there are **2 unmatched transactions**.

The above analysis is for reference only."""

LAYOUT_ANSWER = (
    "Net worth: SGD 13,500.00\n"
    "Income this month: SGD 5,000.00\n"
    "Expenses this month: SGD 1,500.00\n\n"
    "Your surplus this month is SGD 3,500.00."
)


def test_AC_advisor_grounding_3_the_question_asks_for_the_first_label_of_each_metric() -> (
    None
):
    for labels in METRIC_LABELS.values():
        assert labels[0] in QUESTION.lower()


@pytest.mark.parametrize("answer", [STAGING_ANSWER, LAYOUT_ANSWER])
def test_AC_advisor_grounding_3_a_correct_answer_states_each_report_amount(
    answer: str,
) -> None:
    assert misstated_metrics(answer, ORACLE) == {}


def test_AC_advisor_grounding_3_swapped_income_and_expenses_fail() -> None:
    swapped = (
        "Net worth: SGD 13,500.00\n"
        "Income this month: SGD 1,500.00\n"
        "Expenses this month: SGD 5,000.00"
    )
    assert misstated_metrics(swapped, ORACLE) == {
        "income": [Decimal("1500.00")],
        "expenses": [Decimal("5000.00")],
    }


def test_AC_advisor_grounding_3_a_wrong_amount_fails() -> None:
    wrong = LAYOUT_ANSWER.replace("13,500.00", "13,600.00")
    assert misstated_metrics(wrong, ORACLE) == {"net_worth": [Decimal("13600.00")]}


def test_AC_advisor_grounding_3_a_label_reads_up_to_the_next_label_only() -> None:
    one_line = "Net worth: 13,500.00; Income this month: 1,500.00; Expenses this month: 5,000.00"
    assert stated_amounts(one_line) == {
        "net_worth": [Decimal("13500.00")],
        "income": [Decimal("1500.00")],
        "expenses": [Decimal("5000.00")],
    }
    assert set(misstated_metrics(one_line, ORACLE)) == {"income", "expenses"}


def test_AC_advisor_grounding_3_an_answer_without_the_labels_fails() -> None:
    bare = "You have SGD 13,500.00. You got SGD 5,000.00 and paid SGD 1,500.00."
    assert set(misstated_metrics(bare, ORACLE)) == {"net_worth", "income", "expenses"}


def test_AC_advisor_grounding_3_the_next_line_holds_the_amount_of_a_heading() -> None:
    heading = (
        "### Net worth\nSGD 13,500.00\n"
        "### Income this month (October 2026)\nSGD 5,000.00\n"
        "### Expenses this month\nSGD 1,600.00"
    )
    # A year is a number but not a money amount, so the read goes on to the next line.
    assert stated_amounts(heading) == {
        "net_worth": [Decimal("13500.00")],
        "income": [Decimal("2026"), Decimal("5000.00")],
        "expenses": [Decimal("1600.00")],
    }
    assert misstated_metrics(heading, ORACLE) == {"expenses": [Decimal("1600.00")]}


def test_AC_advisor_grounding_3_the_staging_refusal_invents_no_amount() -> None:
    assert says_no_data(STAGING_REFUSAL)
    assert money_amounts(STAGING_REFUSAL) == {Decimal("1500.00")}
    assert money_amounts(STAGING_REFUSAL) <= DATA_AMOUNTS


def test_AC_advisor_grounding_3_an_invented_amount_fails() -> None:
    invented = "You spent SGD 245.30 on dining in March 2019, mostly at restaurants."
    assert not says_no_data(invented)
    assert money_amounts(invented) - DATA_AMOUNTS == {Decimal("245.30")}
    hedged = "There is no dining data for March 2019, but it was about $180.00."
    assert says_no_data(hedged)
    assert money_amounts(hedged) - DATA_AMOUNTS == {Decimal("180.00")}


def test_AC_advisor_grounding_3_percentages_years_and_counts_are_not_money() -> None:
    assert (
        money_amounts(
            "A 0.0% match rate, 66.67% coverage, 2 unmatched rows, March 2019."
        )
        == set()
    )
    assert money_amounts("An FX rate of 1.3456 and version v0.2.9.") == set()
    assert money_amounts("S$1,200 and USD 40 and 12.50") == {
        Decimal("1200"),
        Decimal("40"),
        Decimal("12.50"),
    }
