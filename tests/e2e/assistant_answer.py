"""AC-advisor.grounding.3: read the amounts in an answer of the assistant, for journey U14 (#2461).

The journey compares each amount in the answer with the reports. A set of all numbers in the
answer is not sufficient: an answer that swaps the income and the expenses still holds both
numbers. Correct prose after a wrong headline must not hide the headline either. So the stated
amount of a metric is the first money amount after the first label of that metric that states one.

The text of a label is the rest of its line, up to the next label. When that rest holds only
markup or a parenthesis (a heading such as "### Income this month (October 2026)"), the text is
the next non-empty line. A horizontal markdown table is not read.

The module is pure: ``tests/tooling/test_assistant_answer.py`` runs it with no deployment.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

# The wait limits of the journey. The staging gate budget
# (tests/tooling/test_post_merge_e2e_gates.py) counts WAIT_CEILING_MINUTES.
ANSWER_TIMEOUT_SECONDS = 120
ANSWERS_PER_JOURNEY = 2
CSV_PARSE_TIMEOUT_SECONDS = 120
WAIT_CEILING_MINUTES = (
    ANSWERS_PER_JOURNEY * ANSWER_TIMEOUT_SECONDS + CSV_PARSE_TIMEOUT_SECONDS
) / 60

# The words that name each amount. The question asks for the first label of each metric.
# The other labels are wordings that the model used on staging.
METRIC_LABELS: dict[str, tuple[str, ...]] = {
    "net_worth": ("net worth",),
    "income": (
        "income this month",
        "monthly income",
        "income for this month",
        "this month's income",
        "earned this month",
        "total income",
    ),
    "expenses": (
        "expenses this month",
        "monthly expenses",
        "expenses for this month",
        "this month's expenses",
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
# A sentence that names the subject of the out-of-data question.
OUT_OF_DATA_TOPIC = re.compile(r"\bdining\b|\bmarch\s+2019\b", re.IGNORECASE)

_CODES = r"SGD|USD|CNY|RMB|HKD|MYR|EUR|GBP|JPY|AUD"
_AMOUNT = r"\d[\d,]*(?:\.\d+)?"
# A money amount has a currency before or after it, or exactly two decimals.
# A percentage, a year, a count and a rate with more decimals are not money amounts.
_MONEY = re.compile(
    rf"(?:(?<![A-Za-z])(?:{_CODES})|S\$|US\$|HK\$|\$|¥|€|£)\s?({_AMOUNT})(?![\d%])"
    rf"|(?<![\d.,])({_AMOUNT})\s?(?:{_CODES})\b"
    r"|(?<![\d.,])(\d[\d,]*\.\d{2})(?!\d|%|\.\d)"
)
_LABEL = re.compile(
    "|".join(
        f"(?P<{metric}_{index}>{re.escape(label)})"
        for metric, labels in METRIC_LABELS.items()
        for index, label in enumerate(labels)
    ),
    re.IGNORECASE,
)
_MARKUP = re.compile(r"\([^)]*\)|[\s*:#|_\-–—]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
# Words that tell the user that the data holds no answer.
_NO_DATA = re.compile(
    r"\bno\b[^.\n]{0,60}\b(?:data|records?|transactions?|information|statements?|details?)\b"
    r"|\b(?:don['’]t|do not|doesn['’]t|does not) (?:have|show|include|contain|cover|extend)\b"
    r"|\bnot (?:available|recorded|included|covered)\b|\bunavailable\b|\boutside\b"
    r"|\b(?:cannot|can['’]t|unable to)\b",
    re.IGNORECASE,
)


def _decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


def _first_money(text: str) -> Decimal | None:
    match = _MONEY.search(text)
    if match is None:
        return None
    return _decimal(next(group for group in match.groups() if group))


def _label_text(answer: str, start: int, end: int) -> str:
    line, _, rest = answer[start:end].partition("\n")
    if _MARKUP.sub("", line):
        return line
    return next((other for other in rest.split("\n") if other.strip()), "")


def stated_amounts(answer: str) -> dict[str, Decimal | None]:
    """Return, for each metric, the first money amount after the first label that states one."""
    stated: dict[str, Decimal | None] = dict.fromkeys(METRIC_LABELS)
    labels = list(_LABEL.finditer(answer))
    for position, match in enumerate(labels):
        metric = match.lastgroup.rsplit("_", 1)[0] if match.lastgroup else ""
        if stated[metric] is not None:
            continue
        end = (
            labels[position + 1].start() if position + 1 < len(labels) else len(answer)
        )
        stated[metric] = _first_money(_label_text(answer, match.end(), end))
    return stated


def misstated_metrics(
    answer: str, expected: Mapping[str, Decimal]
) -> dict[str, Decimal | None]:
    """Return the metrics whose stated amount is not the expected amount, with the stated amount."""
    stated = stated_amounts(answer)
    return {
        metric: stated[metric]
        for metric, amount in expected.items()
        if stated[metric] != amount
    }


def money_amounts(answer: str) -> set[Decimal]:
    """Return every money amount in the answer."""
    return {
        _decimal(next(group for group in groups if group))
        for groups in _MONEY.findall(answer)
    }


def _sentences(answer: str) -> list[str]:
    return [sentence for sentence in _SENTENCE_END.split(answer) if sentence.strip()]


def topic_sentences_with_amounts(answer: str) -> list[str]:
    """Return the sentences that name the out-of-data subject and state a money amount."""
    return [
        sentence
        for sentence in _sentences(answer)
        if OUT_OF_DATA_TOPIC.search(sentence) and _MONEY.search(sentence)
    ]


def says_no_data(answer: str) -> bool:
    """Return True when a sentence that names the out-of-data subject says that the data holds no answer."""
    return any(
        OUT_OF_DATA_TOPIC.search(sentence) and _NO_DATA.search(sentence)
        for sentence in _sentences(answer)
    )
