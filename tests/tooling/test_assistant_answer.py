"""AC-advisor.grounding.3: the assistant chat journey reads each amount after its label (#2461).

The journey U14 (`tests/e2e/test_assistant_chat_journey.py`) runs only on staging. These tests run
its answer checks with no deployment. Each mutated answer below must fail the check that the
journey uses, so a wrong, swapped or invented amount cannot pass the journey.

The real answers are from staging: v0.2.2 (2026-10-15, the probe of #2461) and v0.2.9
(2026-10-20, a run of the journey). Most mutations change one amount of the v0.2.9 answer, so the
prose that follows the headline is the prose of a real answer.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.e2e.assistant_answer import (
    METRIC_LABELS,
    QUESTION,
    WAIT_CEILING_MINUTES,
    misstated_metrics,
    money_amounts,
    says_no_data,
    stated_amounts,
    topic_sentences_with_amounts,
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

V022_ANSWER = """Based on your financial data:

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

V029_ANSWER = """Net worth: SGD 13500.00
Income this month: SGD 5000.00
Expenses this month: SGD 1500.00

Your net worth of SGD 13,500.00 is consistent with total assets (SGD 13,500.00) minus total liabilities (SGD 0.00), and also equals opening equity (SGD 10,000.00) plus cumulative net income (SGD 3,500.00). With monthly expenses of SGD 1,500.00 entirely in housing, you're saving SGD 3,500.00 per month — a strong 70% savings rate.

The above analysis is for reference only."""

V022_REFUSAL = """I don't have that information available. Here's why:

**What I can see in your records:**
- The expense data currently available only covers a recent monthly summary, with the top (and only listed) expense category being **Housing: SGD 1,500.00**
- There is no dining category breakdown, and no transaction-level detail for March 2019 in the accessible data
- The market data observations in your records date from October 2026, which suggests your current data set does not extend back to March 2019

**What I cannot do:**
- I cannot fabricate or estimate a dining figure for that period, as it isn't supported by any data in your records

The above analysis is for reference only."""

V029_REFUSAL = """I don't have any dining expense data for March 2019 in your records. Your available data only shows:

- Monthly expenses: SGD 1,500.00
- Top expense category: Housing — SGD 1,500.00

This suggests your current recorded expenses are fully accounted for by housing, with no dining category present. It's possible that period's statements aren't loaded — in fact, there's a blocker indicating your statements start after the beginning of the current period, so earlier records (like March 2019) may not be covered.

The above analysis is for reference only."""


def test_AC_advisor_grounding_3_the_question_asks_for_the_first_label_of_each_metric() -> (
    None
):
    for labels in METRIC_LABELS.values():
        assert labels[0] in QUESTION.lower()


def test_AC_advisor_grounding_3_the_wait_ceiling_is_two_answers_and_one_csv_parse() -> (
    None
):
    assert WAIT_CEILING_MINUTES == 6


@pytest.mark.parametrize("answer", [V022_ANSWER, V029_ANSWER])
def test_AC_advisor_grounding_3_a_real_answer_states_each_report_amount(
    answer: str,
) -> None:
    assert misstated_metrics(answer, ORACLE) == {}


@pytest.mark.parametrize(
    ("old", "new", "misstated"),
    [
        # A wrong headline; the prose below still holds the right amount.
        (
            "Net worth: SGD 13500.00",
            "Net worth: SGD 10000.00",
            {"net_worth": Decimal("10000.00")},
        ),
        # Net worth confused with net income, with the right amount later in the line.
        (
            "Net worth: SGD 13500.00",
            "Net worth: SGD 3,500.00 (assets SGD 13,500.00 less liabilities SGD 10,000.00)",
            {"net_worth": Decimal("3500.00")},
        ),
        # Swapped headlines; the prose below still holds "monthly expenses of SGD 1,500.00".
        (
            "Income this month: SGD 5000.00\nExpenses this month: SGD 1500.00",
            "Income this month: SGD 1500.00\nExpenses this month: SGD 5000.00",
            {"income": Decimal("1500.00"), "expenses": Decimal("5000.00")},
        ),
        # A headline with no amount.
        (
            "Income this month: SGD 5000.00",
            "Income this month: see below",
            {"income": None},
        ),
    ],
)
def test_AC_advisor_grounding_3_a_mutated_real_answer_fails(
    old: str, new: str, misstated: dict
) -> None:
    assert V029_ANSWER.count(old) == 1
    assert misstated_metrics(V029_ANSWER.replace(old, new), ORACLE) == misstated


def test_AC_advisor_grounding_3_a_label_reads_up_to_the_next_label_only() -> None:
    one_line = "Net worth: SGD 13,500.00; Income this month: SGD 1,500.00; Expenses this month: SGD 5,000.00"
    assert stated_amounts(one_line) == {
        "net_worth": Decimal("13500.00"),
        "income": Decimal("1500.00"),
        "expenses": Decimal("5000.00"),
    }


def test_AC_advisor_grounding_3_an_answer_without_the_labels_fails() -> None:
    bare = "You have SGD 13,500.00. You got SGD 5,000.00 and paid SGD 1,500.00."
    assert misstated_metrics(bare, ORACLE) == dict.fromkeys(ORACLE)


def test_AC_advisor_grounding_3_the_next_line_holds_the_amount_of_a_heading() -> None:
    heading = (
        "### Net worth\nSGD 13,500.00\n"
        "### Income this month (October 2026)\nSGD 5,000.00\n"
        "### Expenses this month\nSGD 1,600.00"
    )
    assert stated_amounts(heading) == {
        "net_worth": Decimal("13500.00"),
        "income": Decimal("5000.00"),
        "expenses": Decimal("1600.00"),
    }
    # A label in prose with no amount does not take an amount from a later line.
    prose = "Your net worth is healthy.\n\nYou saved SGD 3,500.00.\nNet worth: SGD 13,500.00"
    assert stated_amounts(prose)["net_worth"] == Decimal("13500.00")


@pytest.mark.parametrize("refusal", [V022_REFUSAL, V029_REFUSAL])
def test_AC_advisor_grounding_3_a_real_refusal_passes(refusal: str) -> None:
    assert says_no_data(refusal)
    assert topic_sentences_with_amounts(refusal) == []
    assert money_amounts(refusal) == {Decimal("1500.00")}


@pytest.mark.parametrize(
    "refusal",
    [
        # A real amount reused for the subject of the question.
        "You spent SGD 1,500.00 on dining in March 2019. I cannot show a breakdown.",
        "There is no dining data for March 2019, but it was about $180.00.",
        "Your dining spend in March 2019 would be 245.50.",
        "Dining in March 2019 was roughly 240 SGD, but I do not have the receipts.",
    ],
)
def test_AC_advisor_grounding_3_an_amount_about_the_subject_fails(refusal: str) -> None:
    assert topic_sentences_with_amounts(refusal)


def test_AC_advisor_grounding_3_an_invented_amount_elsewhere_fails() -> None:
    invented = "I don't have dining data for March 2019. A typical household budget is SGD 400.00."
    assert says_no_data(invented)
    assert topic_sentences_with_amounts(invented) == []
    assert money_amounts(invented) - DATA_AMOUNTS == {Decimal("400.00")}


def test_AC_advisor_grounding_3_a_caveat_about_another_subject_is_no_refusal() -> None:
    assert not says_no_data(
        "You spent a lot on dining in March 2019. I cannot show a breakdown."
    )
    assert says_no_data("I cannot see any dining spend for March 2019 in your records.")


def test_AC_advisor_grounding_3_money_needs_a_currency_or_two_decimals() -> None:
    assert (
        money_amounts(
            "A 0.0% match rate, 66.67% coverage, 2 unmatched rows, March 2019."
        )
        == set()
    )
    assert money_amounts("An FX rate of 1.3456, version v0.2.9, OCT 2026.") == set()
    assert money_amounts("S$1,200 and USD 40 and 12.50 and 245.50. And 240 SGD.") == {
        Decimal("1200"),
        Decimal("40"),
        Decimal("12.50"),
        Decimal("245.50"),
        Decimal("240"),
    }
