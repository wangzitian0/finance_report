"""AC-advisor.grounding.3: read the amounts in an answer of the assistant, for journey U14 (#2461).

The journey compares each amount in the answer with the reports. A set of all numbers in the
answer is not sufficient: an answer that swaps the income and the expenses still holds both
numbers. So each amount is read from the text that follows its label. That text ends at the
next label, or at the end of the first line that holds a money amount.

The module is pure: ``tests/tooling/test_assistant_answer.py`` runs it with no deployment.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

# Each chat request of the journey waits at most this time. The staging gate budget
# (tests/tooling/test_post_merge_e2e_gates.py) counts these waits.
ANSWER_TIMEOUT_SECONDS = 120
ANSWERS_PER_JOURNEY = 2

# The words that name each amount. The question asks for the first label of each metric.
# The other labels are wordings that the model used on staging.
METRIC_LABELS: dict[str, tuple[str, ...]] = {
    "net_worth": ("net worth",),
    "income": (
        "income this month",
        "monthly income",
        "income for this month",
        "income (this month)",
        "earned this month",
        "total income",
    ),
    "expenses": (
        "expenses this month",
        "monthly expenses",
        "expenses for this month",
        "expenses (this month)",
        "spent this month",
        "total expenses",
    ),
}

QUESTION = (
    "What is my net worth today, and what are my total income and my total expenses this month? "
    "Start your answer with three lines in this form: 'Net worth: <amount>', "
    "'Income this month: <amount>', 'Expenses this month: <amount>'. Use the exact amounts."
)
OUT_OF_DATA_QUESTION = "How much did I spend on dining in March 2019?"

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# A money amount has a currency code or symbol before it, or exactly two decimals.
# A percentage, a year and a count are not money amounts.
_MONEY = re.compile(
    r"(?:\b[A-Z]{3}|S?\$)\s?(\d[\d,]*(?:\.\d+)?)(?![\d%])|(?<![\d.])(\d[\d,]*\.\d{2})(?![\d%.])"
)
_LABEL = re.compile(
    "|".join(
        f"(?P<{metric}_{index}>{re.escape(label)})"
        for metric, labels in METRIC_LABELS.items()
        for index, label in enumerate(labels)
    ),
    re.IGNORECASE,
)
# Words that tell the user that the data holds no answer.
_NO_DATA = re.compile(
    r"\bno\b[^.\n]{0,60}\b(?:data|records?|transactions?|information|statements?|details?)\b"
    r"|\b(?:don['’]t|do not|doesn['’]t|does not) (?:have|show|include|contain|cover)\b"
    r"|\bnot (?:available|recorded|included|covered)\b|\bunavailable\b"
    r"|\b(?:cannot|can['’]t|unable to)\b",
    re.IGNORECASE,
)


def _decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


def stated_amounts(answer: str) -> dict[str, list[Decimal]]:
    """Return, for each metric, the amounts that follow one of its labels in the answer."""
    found: dict[str, list[Decimal]] = {metric: [] for metric in METRIC_LABELS}
    labels = list(_LABEL.finditer(answer))
    for position, match in enumerate(labels):
        metric = match.lastgroup.rsplit("_", 1)[0] if match.lastgroup else ""
        end = (
            labels[position + 1].start() if position + 1 < len(labels) else len(answer)
        )
        for line in answer[match.end() : end].split("\n"):
            found[metric].extend(_decimal(number) for number in _NUMBER.findall(line))
            if _MONEY.search(line):
                break
    return found


def misstated_metrics(
    answer: str, expected: Mapping[str, Decimal]
) -> dict[str, list[Decimal]]:
    """Return the metrics whose labels are not followed by the expected amount, with the amounts found."""
    found = stated_amounts(answer)
    return {
        metric: found[metric]
        for metric, amount in expected.items()
        if amount not in found[metric]
    }


def money_amounts(answer: str) -> set[Decimal]:
    """Return every money amount in the answer."""
    return {_decimal(prefixed or plain) for prefixed, plain in _MONEY.findall(answer)}


def says_no_data(answer: str) -> bool:
    """Return True when the answer tells the user that the data holds no answer."""
    return _NO_DATA.search(answer) is not None
