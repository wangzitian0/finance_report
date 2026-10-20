"""AC-advisor.grounding.3: read the amounts in an answer of the assistant, for journey U14 (#2461).

The journey compares each amount in the answer with the reports. A set of all numbers in the
answer is not sufficient: an answer that swaps the income and the expenses still holds both
numbers. Correct prose after a wrong headline must not hide the headline either. So the first
label of a metric whose text holds a number decides: its first number, with a minus sign that
touches the number or its currency, is the stated amount. Dates, percentages and counts ("120
days") are removed first. Any other number decides, also one that is not an amount ("2000", "0").

The out-of-data check reads amounts: a number with a currency, a number with thousands separators
or two decimals, or a bare number of three digits or more that is not a year or a count.

The text of a label is the rest of its line, up to the next label. When that rest holds only
markup or a parenthesis (a heading such as "### Income this month (October 2026)"), the text is
the next non-empty line. A horizontal markdown table is not read.

Known limit of the out-of-data check: a real amount of the user that the answer reuses as an
estimate in a clause that does not name the subject ("I have no dining records for March 2019,
but it was probably SGD 1,500.00.") passes. To find it, the check must read the meaning of the
text. An invented amount in such a clause fails, because it is not an amount of the data.

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
# The failure text of an empty answer body. It names the provider failure, so the staging gate
# classifies it as a provider transient. It lives here, not in the journey source: pytest prints
# that source on any failure of the journey, and the text would classify that failure too.
EMPTY_ANSWER_FAILURE = (
    "the assistant sent HTTP 200 with an empty body after {seconds} s for {question!r}: "
    "the provider stream failed before its first chunk, and the AI service may be unavailable"
)
# A sentence that names the subject of the out-of-data question.
OUT_OF_DATA_TOPIC = re.compile(r"\bdining\b|\bmarch\s+2019\b", re.IGNORECASE)

_CODES = (
    r"SGD|USD|CNY|RMB|HKD|MYR|EUR|GBP|JPY|AUD|CAD|NZD|CHF|INR|THB|IDR|PHP|KRW|TWD|VND"
)
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
# The number ends here: no more digits, no percent sign and no decimal part follow.
_END = r"(?![\d%]|[.,]\d)"
# A bare number before one of these words counts something; it is not an amount.
_UNITS = r"days?|weeks?|months?|years?|hours?|transactions?|entries|rows?|statements?|accounts?|items?"
_UNIT = rf"(?![ \t]*(?i:{_UNITS})\b)"
# An amount has a currency before or after it, or it is a bare number with thousands
# separators, exactly two decimals, or three digits or more that is not a year.
# A percentage, a year, a small count and a rate with more decimals are not amounts.
_AMOUNT = re.compile(
    rf"(?:(?<![A-Za-z])(?i:{_CODES})|S\$|US\$|HK\$|\$|¥|€|£)[ \t]*({_NUMBER})(?![\d%]|\.\d)"
    rf"|(?<![\w.,])({_NUMBER})[ \t]*(?:(?i:{_CODES})\b|(?i:dollars?)\b)"
    r"|(?<![\w.,$])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2}|(?!(?:19|20)\d\d(?!\d))\d{3,})"
    rf"{_END}{_UNIT}"
)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
# A date, a percentage or a count in the text of a label is no amount; it is removed first.
_NOT_AN_AMOUNT = re.compile(
    rf"\b\d{{1,2}}[ \t]+{_MONTH}(?:[ \t]+\d{{4}})?\b|\b{_MONTH}[ \t]+\d{{1,2}}(?:,[ \t]*\d{{4}})?\b"
    rf"|\b{_MONTH}[ \t]+\d{{4}}\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b|\d+(?:\.\d+)?[ \t]*%"
    rf"|\b\d+[ \t]+(?:{_UNITS})\b",
    re.IGNORECASE,
)
# The stated value of a label: the first number, with a minus sign that touches the number or
# its currency. A spaced hyphen ("Net worth - SGD 13,500.00") is a separator, not a sign.
_STATED = re.compile(
    rf"(?P<before>[-−])?(?:(?i:{_CODES})|S\$|US\$|HK\$|[$¥€£])?[ \t]*(?P<after>[-−])?(?P<number>{_NUMBER})"
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
# A clause ends at a comma that is not in a number, a semicolon, a dash, or a joining word.
_CLAUSE_END = re.compile(
    r"(?<!\d),|,(?!\d)|;|\s[—–-]\s|—|\b(?:but|while|whereas|although|however|with)\b",
    re.IGNORECASE,
)
# A sentence does not end after one of these abbreviations, as a whole word.
_ABBREVIATION = re.compile(
    r"(?:^|[\s(])(?:approx|e\.g|i\.e|vs|est|ca|avg)\.$", re.IGNORECASE
)
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


def _stated_value(text: str) -> Decimal | None:
    """Return the first number of the text of a label, or None when the text holds no number.

    Dates, percentages and counts are removed first. Any other number decides, also one that is
    not an amount ("2000", "0", "1.5k"), so a wrong headline cannot be skipped.
    """
    match = _STATED.search(_NOT_AN_AMOUNT.sub(" ", text))
    if match is None:
        return None
    value = _decimal(match["number"])
    return -value if match["before"] or match["after"] else value


def _label_text(answer: str, start: int, end: int) -> str:
    line, _, rest = answer[start:end].partition("\n")
    cleaned = _NOT_AN_AMOUNT.sub(" ", line)
    if any(character.isdigit() for character in cleaned) or _MARKUP.sub("", cleaned):
        return line
    return next((other for other in rest.split("\n") if other.strip()), "")


def stated_amounts(answer: str) -> dict[str, Decimal | None]:
    """Return, for each metric, the first number after the first label that states one."""
    stated: dict[str, Decimal | None] = dict.fromkeys(METRIC_LABELS)
    decided: set[str] = set()
    labels = list(_LABEL.finditer(answer))
    for position, match in enumerate(labels):
        metric = match.lastgroup.rsplit("_", 1)[0] if match.lastgroup else ""
        if metric in decided:
            continue
        end = (
            labels[position + 1].start() if position + 1 < len(labels) else len(answer)
        )
        value = _stated_value(_label_text(answer, match.end(), end))
        if value is not None:
            stated[metric] = value
            decided.add(metric)
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
            if not _ABBREVIATION.search(pending):
                sentences.append(pending)
                pending = ""
        if pending:
            sentences.append(pending)
    return [sentence for sentence in sentences if sentence.strip()]


def topic_claims(answer: str) -> list[str]:
    """Return the clauses that name the out-of-data subject and state an amount.

    A sentence can name the subject and, in another clause, an amount of the data that the user
    has ("your top expense is Housing: SGD 1,500.00, with no dining category"). That is no claim.
    """
    return [
        clause.strip()
        for sentence in _sentences(answer)
        for clause in _CLAUSE_END.split(sentence)
        if OUT_OF_DATA_TOPIC.search(clause) and _AMOUNT.search(clause)
    ]


def says_no_data(answer: str) -> bool:
    """Return True when a sentence that names the out-of-data subject says that the data holds no answer."""
    return any(
        OUT_OF_DATA_TOPIC.search(sentence) and _NO_DATA.search(sentence)
        for sentence in _sentences(answer)
    )
