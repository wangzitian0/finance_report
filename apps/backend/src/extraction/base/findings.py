"""The typed result of the checks of one statement reading, and the feedback that a model gets from it (#2964).

A reading is the JSON answer of the model for one account. Each failed check gives one finding. The findings of
a pass become one block of the next prompt, so the model reads the document again with the errors in view.
``PassScore`` and ``replaces`` decide which of two passes is kept.
"""

from __future__ import annotations

import json
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
# A value of the reading is cut to this length before it enters the feedback.
MAX_FEEDBACK_VALUE_LENGTH = 40
# One feedback line is cut to this length.
MAX_FEEDBACK_LINE_LENGTH = 2000
# The feedback block holds at most this many findings.
MAX_FEEDBACK_FINDINGS = 30

_FEEDBACK_HEADER = """

Check results of your previous answer:
Code compared your previous answer for this document with the document. Each line below is one check that failed.
Read the document again and correct the answer. Copy only what the document prints.
Never change a value only to make a check pass.
"""
_FEEDBACK_END = "End of check results. Every rule above stays in force.\n"


class FindingCode(StrEnum):
    """The check that failed."""

    NO_ROWS = "no_rows"
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


def _number(value: Any) -> Decimal | None:
    """Return a finite Decimal, or None. ``NaN`` and ``Infinity`` are not amounts."""
    number = _safe_parse_decimal(value)
    return number if number is not None and number.is_finite() else None


def _quoted(value: Any) -> str:
    """Return a value of the reading as a JSON string of bounded length.

    The reading comes from a document that a user uploaded. An ASCII JSON string holds no raw new line and
    no Unicode line separator, so a value cannot end the feedback block or add a line to it.
    """
    return json.dumps(str(value)[:MAX_FEEDBACK_VALUE_LENGTH], ensure_ascii=True)


def _rows_of(reading: dict[str, Any]) -> list[dict[str, Any]]:
    raw_rows = reading.get("transactions")
    return [txn for txn in raw_rows if isinstance(txn, dict)] if isinstance(raw_rows, list) else []


def _name_rows(transactions: list[dict[str, Any]], numbers: list[int]) -> str:
    named = [
        f"row {number} ({_quoted(transactions[number - 1].get('date'))}, "
        f"{_quoted(transactions[number - 1].get('amount'))})"
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


def _balance_result(reading: dict[str, Any]) -> dict[str, Any] | None:
    """Return the balance evaluation of a reading, or None when the reading has no balances to evaluate."""
    per_currency = bank_currency_balances(reading)
    opening, closing = reading.get("opening_balance"), reading.get("closing_balance")
    if not balance_is_evaluable(opening, closing, per_currency):
        return None
    return evaluate_statement_balance(
        opening=_number(opening),
        closing=_number(closing),
        currency=reading.get("currency"),
        currency_balances=per_currency,
        transactions=_rows_of(reading),
    )


def _balance_finding(reading: dict[str, Any], transactions: list[dict[str, Any]]) -> Finding | None:
    result = _balance_result(reading)
    if result is None or result.get("balance_valid"):
        return None
    if bank_currency_balances(reading) or not result.get("balance_computable", True) or "raw_difference" not in result:
        return Finding(
            FindingCode.BALANCE_MISMATCH,
            "The opening balance plus the rows does not give the closing balance for each currency. "
            "Look for a missing row, a row read twice, or a wrong direction.",
        )
    gap = Decimal(str(result["raw_difference"]))
    amounts = [_number(txn.get("amount")) for txn in transactions]
    same = [number for number, amount in enumerate(amounts, start=1) if amount is not None and abs(amount) == gap]
    half = [number for number, amount in enumerate(amounts, start=1) if amount is not None and abs(amount) * 2 == gap]
    feedback = (
        f"The opening balance {_quoted(reading.get('opening_balance'))} plus the rows gives "
        f"{_quoted(result['expected_closing'])}. The closing balance of the answer is "
        f"{_quoted(reading.get('closing_balance'))}. The difference is {_quoted(result['difference'])}. "
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
    True when the caller supplied the institution, so the reading does not have to state it. An account
    without rows is not a finding here: ``document_findings`` judges the rows of the whole document.
    """
    transactions = _rows_of(reading)
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
        if not txn.get("date") or _number(txn.get("amount")) is None
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

    balance = _balance_finding(reading, transactions)
    if balance is not None:
        findings.append(balance)

    if not source_text or not transactions:
        return findings
    opening = _number(reading.get("opening_balance"))
    closing = _number(reading.get("closing_balance"))
    amounts = [_number(txn.get("amount")) for txn in transactions]
    if per_currency is None:
        verdict = check_closing_balance_against_text(
            source_text, opening=opening, closing=closing, amounts=[a for a in amounts if a is not None]
        )
        if verdict is SourceBalanceVerdict.OPENING_NOT_IN_TEXT:
            findings.append(
                Finding(
                    FindingCode.OPENING_NOT_IN_TEXT,
                    f"The opening balance {_quoted(reading.get('opening_balance'))} is not a number that the "
                    "document prints. Return the printed opening balance, or null when the document prints none.",
                )
            )
        elif verdict is SourceBalanceVerdict.CLOSING_NOT_IN_TEXT:
            findings.append(
                Finding(
                    FindingCode.CLOSING_NOT_IN_TEXT,
                    f"The closing balance {_quoted(reading.get('closing_balance'))} is not a number that the "
                    "document prints. Return the printed closing balance, or null when the document prints none.",
                )
            )
    not_printed = rows_missing_from_text(
        source_text,
        [(amount, _number(txn.get("balance_after"))) for amount, txn in zip(amounts, transactions)],
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


def _balance_holds(reading: dict[str, Any]) -> bool:
    result = _balance_result(reading)
    return result is not None and bool(result.get("balance_valid"))


def document_findings(
    readings: list[dict[str, Any]], *, source_text: str | None, institution_given: bool = False
) -> list[Finding]:
    """Return the findings of each account of one document, and ``no_rows`` when the document gave no row.

    An account without activity is correct when its printed balances are equal, so a balance equation
    that holds is the proof that a document without rows is complete.
    """
    findings = [
        finding
        for reading in readings
        for finding in reading_findings(reading, source_text=source_text, institution_given=institution_given)
    ]
    if not any(_rows_of(reading) for reading in readings) and not any(_balance_holds(r) for r in readings):
        findings.insert(
            0,
            Finding(
                FindingCode.NO_ROWS,
                "The answer has no transaction row. Return each transaction row that the document prints.",
            ),
        )
    return findings


def check_feedback_block(findings: list[Finding]) -> str:
    """Return the findings as one block of a prompt, or "" when there is no finding."""
    if not findings:
        return ""
    lines = [
        f"{number}. {finding.feedback[:MAX_FEEDBACK_LINE_LENGTH]}\n"
        for number, finding in enumerate(findings[:MAX_FEEDBACK_FINDINGS], start=1)
    ]
    return "".join([_FEEDBACK_HEADER, *lines, _FEEDBACK_END])


@dataclass(frozen=True, slots=True)
class PassScore:
    """What decides whether one pass replaces another."""

    rows: int
    codes: frozenset[FindingCode]
    finding_count: int
    # True when one account or more has balances that the equation can judge.
    evaluable: bool
    # The sum of the balance differences. A balance that cannot be computed is the largest gap.
    gap: Decimal
    # True when one account or more states the balance.
    has_opening: bool
    has_closing: bool

    @property
    def balance_fails(self) -> bool:
        return FindingCode.BALANCE_MISMATCH in self.codes

    @property
    def balance_proven(self) -> bool:
        """True when the balance equation holds for balances that no text check questions."""
        not_printed = {FindingCode.OPENING_NOT_IN_TEXT, FindingCode.CLOSING_NOT_IN_TEXT}
        return self.evaluable and not self.balance_fails and not (self.codes & not_printed)

    @property
    def unusable(self) -> bool:
        """True when the persist step cannot store the reading: it has no row, or a row is invalid."""
        return bool(self.codes & {FindingCode.NO_ROWS, FindingCode.ROW_INVALID})

    @property
    def rank(self) -> tuple[int, int, Decimal, int, int]:
        """Lower is better: usable, no balance gap, the smaller gap, a proven balance, the fewer findings."""
        return (
            int(self.unusable),
            int(self.balance_fails),
            self.gap,
            int(not self.balance_proven),
            self.finding_count,
        )


def _states_balance(reading: dict[str, Any], field: str, bucket_field: str) -> bool:
    if _number(reading.get(field)) is not None:
        return True
    balances = reading.get("balances")
    return isinstance(balances, list) and any(
        isinstance(bucket, dict) and _number(bucket.get(bucket_field)) is not None for bucket in balances
    )


def score_pass(readings: list[dict[str, Any]], findings: list[Finding]) -> PassScore:
    """Return the score of one pass from its account readings and its findings."""
    gap = Decimal("0")
    evaluable = False
    for reading in readings:
        result = _balance_result(reading)
        if result is None:
            continue
        evaluable = True
        try:
            difference = Decimal(str(result.get("difference", "0") or "0"))
        except ArithmeticError:
            difference = Decimal("Infinity")
        gap += abs(difference) if result.get("balance_computable", True) else Decimal("Infinity")
    return PassScore(
        rows=sum(len(_rows_of(reading)) for reading in readings),
        codes=frozenset(finding.code for finding in findings),
        finding_count=len(findings),
        evaluable=evaluable,
        gap=gap,
        has_opening=any(_states_balance(reading, "opening_balance", "opening") for reading in readings),
        has_closing=any(_states_balance(reading, "closing_balance", "closing") for reading in readings),
    )


def replaces(candidate: PassScore, kept: PassScore) -> bool:
    """Return True when a later pass replaces the kept pass.

    A pass without rows never replaces a pass with rows. A reading that the persist step cannot store loses
    to each reading that it can store. Apart from that, a later pass never loses evidence without proof:
    - It keeps the opening balance, unless the text check showed that the document does not print it. The
      same rule holds for the closing balance.
    - It keeps the number of rows, unless its balance proof is stronger: its balance equation holds for
      balances that no text check questions and that of the kept pass does not, or the kept pass fails the
      balance equation and its gap is smaller.
    Then the lower rank wins. An equal rank keeps the earlier pass.
    """
    if candidate.rows == 0 and kept.rows > 0:
        return False
    if candidate.unusable:
        return kept.unusable and candidate.rank < kept.rank
    if kept.unusable:
        return True
    if kept.has_opening and not candidate.has_opening and FindingCode.OPENING_NOT_IN_TEXT not in kept.codes:
        return False
    if kept.has_closing and not candidate.has_closing and FindingCode.CLOSING_NOT_IN_TEXT not in kept.codes:
        return False
    if candidate.rows < kept.rows:
        stronger_proof = candidate.balance_proven and not kept.balance_proven
        smaller_gap = kept.balance_fails and candidate.evaluable and candidate.gap < kept.gap
        if not (stronger_proof or smaller_gap):
            return False
    return candidate.rank < kept.rank
