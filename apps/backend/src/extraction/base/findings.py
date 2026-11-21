"""The typed result of the checks of one statement reading, and the feedback that a model gets from it (#2964).

A reading is the JSON answer of the model for one account. Each failed check gives one finding. The findings of
a pass become one block of the next prompt, so the model reads the document again with the errors in view.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from src.extraction.base.source_balance_check import (
    SourceBalanceVerdict,
    check_closing_balance_against_text,
    rows_missing_from_text,
)
from src.extraction.base.validation import (
    _safe_parse_decimal,
    balance_is_evaluable,
    bank_currency_balances,
    evaluate_statement_balance,
)

# A feedback line names at most this many rows.
MAX_ROWS_NAMED_IN_FEEDBACK = 20

_FEEDBACK_HEADER = """

Check results of your previous answer:
Code compared your previous answer for this document with the document. Each line below is one check that failed.
Read the document again and correct the answer. Copy only what the document prints.
Never change a value only to make a check pass.
"""
_FEEDBACK_END = "End of check results. Every rule above stays in force.\n"


class FindingCode(StrEnum):
    """The check that failed."""

    MISSING_FACT = "missing_fact"
    ROW_INVALID = "row_invalid"
    BALANCE_MISMATCH = "balance_mismatch"
    OPENING_NOT_IN_TEXT = "opening_not_in_text"
    CLOSING_NOT_IN_TEXT = "closing_not_in_text"
    ROWS_NOT_IN_TEXT = "rows_not_in_text"


@dataclass(frozen=True, slots=True)
class Finding:
    """One failed check of a reading. ``feedback`` is the sentence that the model gets."""

    code: FindingCode
    feedback: str
    rows: tuple[int, ...] = ()


def _name_rows(transactions: list[dict[str, Any]], numbers: list[int]) -> str:
    named = [
        f"row {number} ({transactions[number - 1].get('date')}, {transactions[number - 1].get('amount')})"
        for number in numbers[:MAX_ROWS_NAMED_IN_FEEDBACK]
    ]
    more = len(numbers) - MAX_ROWS_NAMED_IN_FEEDBACK
    return ", ".join(named) + (f" and {more} more" if more > 0 else "")


def _missing_fact_names(reading: dict[str, Any], *, institution_given: bool) -> list[str]:
    statement = reading.get("statement")
    nested_currency = statement.get("currency") if isinstance(statement, dict) else None
    present = {
        "institution": institution_given or bool(str(reading.get("institution") or "").strip()),
        "period_start": bool(reading.get("period_start")),
        "period_end": bool(reading.get("period_end")),
        "currency": bool(reading.get("currency") or nested_currency or reading.get("balances")),
    }
    return [name for name, has_value in present.items() if not has_value]


def _balance_finding(
    reading: dict[str, Any], transactions: list[dict[str, Any]], per_currency: list[dict[str, str]] | None
) -> Finding | None:
    opening, closing = reading.get("opening_balance"), reading.get("closing_balance")
    if not balance_is_evaluable(opening, closing, per_currency):
        return None
    result = evaluate_statement_balance(
        opening=_safe_parse_decimal(opening),
        closing=_safe_parse_decimal(closing),
        currency=reading.get("currency"),
        currency_balances=per_currency,
        transactions=transactions,
    )
    if result.get("balance_valid"):
        return None
    if per_currency or not result.get("balance_computable", True):
        return Finding(
            FindingCode.BALANCE_MISMATCH,
            "The opening balance plus the rows does not give the closing balance for each currency. "
            "Look for a missing row, a row read twice, or a wrong direction.",
        )
    gap = Decimal(str(result["raw_difference"]))
    amounts = [_safe_parse_decimal(txn.get("amount")) for txn in transactions]
    same = [number for number, amount in enumerate(amounts, start=1) if amount is not None and abs(amount) == gap]
    half = [number for number, amount in enumerate(amounts, start=1) if amount is not None and abs(amount) * 2 == gap]
    feedback = (
        f"The opening balance {opening} plus the rows gives {result['expected_closing']}. "
        f"The closing balance of the answer is {closing}. The difference is {result['difference']}. "
        "Look for a missing row, a row read twice, or a wrong direction."
    )
    if same:
        feedback += f" An amount equal to the difference: {_name_rows(transactions, same)}."
    if half:
        feedback += f" An amount equal to half of the difference (a wrong direction): {_name_rows(transactions, half)}."
    return Finding(FindingCode.BALANCE_MISMATCH, feedback, rows=tuple(same + half))


def reading_findings(
    reading: dict[str, Any], *, source_text: str | None, institution_given: bool = False
) -> list[Finding]:
    """Return one finding for each check that the reading of one bank account fails.

    ``source_text`` is the text layer of the PDF, or None when the source has none. ``institution_given`` is
    True when the caller supplied the institution, so the reading does not have to state it.
    """
    raw_rows = reading.get("transactions")
    transactions = [txn for txn in raw_rows if isinstance(txn, dict)] if isinstance(raw_rows, list) else []
    per_currency = bank_currency_balances(reading)
    findings: list[Finding] = []

    missing = _missing_fact_names(reading, institution_given=institution_given)
    if missing:
        findings.append(
            Finding(
                FindingCode.MISSING_FACT,
                f"The answer has no value for: {', '.join(missing)}. "
                "Return each of them when the document prints it. Keep null when the document does not print it.",
            )
        )

    invalid = [
        number
        for number, txn in enumerate(transactions, start=1)
        if not txn.get("date") or _safe_parse_decimal(txn.get("amount")) is None
    ]
    if invalid:
        findings.append(
            Finding(
                FindingCode.ROW_INVALID,
                f"These rows have no date, or an amount that is not a number: {_name_rows(transactions, invalid)}. "
                "Return the printed date as YYYY-MM-DD and the printed amount as a number.",
                rows=tuple(invalid),
            )
        )

    balance = _balance_finding(reading, transactions, per_currency)
    if balance is not None:
        findings.append(balance)

    if not source_text or not transactions:
        return findings
    opening = _safe_parse_decimal(reading.get("opening_balance"))
    closing = _safe_parse_decimal(reading.get("closing_balance"))
    amounts = [_safe_parse_decimal(txn.get("amount")) for txn in transactions]
    if per_currency is None:
        verdict = check_closing_balance_against_text(
            source_text, opening=opening, closing=closing, amounts=[a for a in amounts if a is not None]
        )
        if verdict is SourceBalanceVerdict.OPENING_NOT_IN_TEXT:
            findings.append(
                Finding(
                    FindingCode.OPENING_NOT_IN_TEXT,
                    f"The opening balance {reading.get('opening_balance')} is not a number that the document prints. "
                    "Return the printed opening balance, or null when the document prints none.",
                )
            )
        elif verdict is SourceBalanceVerdict.CLOSING_NOT_IN_TEXT:
            findings.append(
                Finding(
                    FindingCode.CLOSING_NOT_IN_TEXT,
                    f"The closing balance {reading.get('closing_balance')} is not a number that the document prints. "
                    "Return the printed closing balance, or null when the document prints none.",
                )
            )
    not_printed = rows_missing_from_text(
        source_text,
        [(amount, _safe_parse_decimal(txn.get("balance_after"))) for amount, txn in zip(amounts, transactions)],
    )
    if not_printed:
        findings.append(
            Finding(
                FindingCode.ROWS_NOT_IN_TEXT,
                "The amount or the running balance of these rows is not a number that the document prints: "
                f"{_name_rows(transactions, not_printed)}. Read these rows again.",
                rows=tuple(not_printed),
            )
        )
    return findings


def check_feedback_block(findings: list[Finding]) -> str:
    """Return the findings as one block of a prompt, or "" when there is no finding."""
    if not findings:
        return ""
    lines = [f"{number}. {finding.feedback}\n" for number, finding in enumerate(findings, start=1)]
    return "".join([_FEEDBACK_HEADER, *lines, _FEEDBACK_END])
