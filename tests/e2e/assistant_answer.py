"""AC-advisor.grounding.3: read the amounts in an answer of the assistant, for journey U14 (#2461).

The journey compares each amount in the answer with the reports. A set of all numbers in the
answer is not sufficient: an answer that swaps the income and the expenses still holds both
numbers. Correct prose after a wrong headline must not hide the headline either. So the stated
amount of a metric is the first amount after the first label of that metric that states one. An
amount is a number with a currency, a number with thousands separators or two decimals, or a bare
number of three digits or more that is not a year.

The text of a label is the rest of its line, up to the next label. When that rest holds only
markup or a parenthesis (a heading such as "### Income this month (October 2026)"), the text is
the next non-empty line. A horizontal markdown table is not read.

Known limit of the out-of-data check: a real amount of the user that the answer reuses as an
estimate in a sentence that does not name the subject ("I have no dining records for March 2019.
It was probably SGD 1,500.00.") passes. To find it, the check must read the meaning of the text.

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

_CODES = (
    r"SGD|USD|CNY|RMB|HKD|MYR|EUR|GBP|JPY|AUD|CAD|NZD|CHF|INR|THB|IDR|PHP|KRW|TWD|VND"
)
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
# The number ends here: no more digits, no percent sign and no decimal part follow.
_END = r"(?![\d%]|[.,]\d)"
# An amount has a currency before or after it, or it is a bare number with thousands
# separators, exactly two decimals, or three digits or more that is not a year.
# A percentage, a year, a small count and a rate with more decimals are not amounts.
_AMOUNT = re.compile(
    rf"(?:(?<![A-Za-z])(?i:{_CODES})|S\$|US\$|HK\$|\$|¥|€|£)\s*({_NUMBER}){_END}"
    rf"|(?<![\d.,])({_NUMBER})\s*(?:(?i:{_CODES})\b|(?i:dollars?)\b)"
    r"|(?<![\d.,$])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2}|(?!(?:19|20)\d\d(?!\d))\d{3,})"
    rf"{_END}"
)
_LABEL = re.compile(
    "|".join(
        f"(?P<{metric}_{index}>{re.escape(label).replace(chr(39), '[' + chr(39) + '’]')})"
        for metric, labels in METRIC_LABELS.items()
        for index, label in enumerate(labels)
    ),
    re.IGNORECASE,
)
_MARKUP = re.compile(r"\([^)]*\)|[\s*:#|_\-–—]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# A sentence does not end after these abbreviations.
_ABBREVIATIONS = ("approx.", "e.g.", "i.e.", "etc.", "vs.", "est.", "ca.", "avg.")
# Words that tell the user that the data holds no answer.
_NO_DATA = re.compile(
    r"\bno\b[^.\n]{0,60}\b(?:data|records?|transactions?|information|statements?|details?|entries|history)\b"
    r"|\b(?:don['’]t|do not|doesn['’]t|does not|didn['’]t|did not) (?:have|show|include|contain|cover|extend|see|find)\b"
    r"|\b(?:is|are|was|were)(?:n['’]t| not) (?:available|recorded|included|covered|present|shown|listed|found|part of|in (?:your|the|my))\b"
    r"|\bnot (?:available|recorded|included|covered|present|found)\b|\bunavailable\b|\boutside\b"
    r"|\b(?:cannot|can['’]t|unable to)\b",
    re.IGNORECASE,
)


def _decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


def _first_amount(text: str) -> Decimal | None:
    match = _AMOUNT.search(text)
    if match is None:
        return None
    return _decimal(next(group for group in match.groups() if group))


def _label_text(answer: str, start: int, end: int) -> str:
    line, _, rest = answer[start:end].partition("\n")
    if _AMOUNT.search(line) or _MARKUP.sub("", line):
        return line
    return next((other for other in rest.split("\n") if other.strip()), "")


def stated_amounts(answer: str) -> dict[str, Decimal | None]:
    """Return, for each metric, the first amount after the first label that states one."""
    stated: dict[str, Decimal | None] = dict.fromkeys(METRIC_LABELS)
    labels = list(_LABEL.finditer(answer))
    for position, match in enumerate(labels):
        metric = match.lastgroup.rsplit("_", 1)[0] if match.lastgroup else ""
        if stated[metric] is not None:
            continue
        end = (
            labels[position + 1].start() if position + 1 < len(labels) else len(answer)
        )
        stated[metric] = _first_amount(_label_text(answer, match.end(), end))
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
    """Return every amount in the answer."""
    return {
        _decimal(next(group for group in groups if group))
        for groups in _AMOUNT.findall(answer)
    }


def _sentences(answer: str) -> list[str]:
    sentences: list[str] = []
    for line in answer.split("\n"):
        pending = ""
        for piece in _SENTENCE_END.split(line):
            pending = f"{pending} {piece}" if pending else piece
            if not pending.lower().endswith(_ABBREVIATIONS):
                sentences.append(pending)
                pending = ""
        if pending:
            sentences.append(pending)
    return [sentence for sentence in sentences if sentence.strip()]


def topic_sentences_with_amounts(answer: str) -> list[str]:
    """Return the sentences that name the out-of-data subject and state an amount."""
    return [
        sentence
        for sentence in _sentences(answer)
        if OUT_OF_DATA_TOPIC.search(sentence) and _AMOUNT.search(sentence)
    ]


def says_no_data(answer: str) -> bool:
    """Return True when a sentence that names the out-of-data subject says that the data holds no answer."""
    return any(
        OUT_OF_DATA_TOPIC.search(sentence) and _NO_DATA.search(sentence)
        for sentence in _sentences(answer)
    )
