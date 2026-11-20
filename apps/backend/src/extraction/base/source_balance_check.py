"""Check an extracted closing balance against the numbers in the document text (#2394).

The model sometimes stores the closing balance that it computed from the rows, not the
closing balance that the document prints. The balance chain then ties out and hides the
mismatch. A PDF text layer holds the printed numbers. A stored closing balance that is
not one of them did not come from the document.

``rows_missing_from_text`` applies the same idea to each row: a row amount or running balance that
the text does not print did not come from the document (#2987).

Pure functions. The caller reads the text layer. A text layer that does not hold the
opening balance and most row amounts says nothing about the closing balance. The check
then returns ``TEXT_UNUSABLE`` and the caller changes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum

# A text layer is usable when it holds at least this share of the row amounts (4 of 5).
MIN_AMOUNT_MATCH_NUMERATOR = 4
MIN_AMOUNT_MATCH_DENOMINATOR = 5

# A spaced number has at most this many groups (``1 234 567 890,12``).
_MAX_SPACED_GROUPS = 4
_GROUP_SEPARATORS = " ,.'\u00a0\u202f\u2009\u2019"
# A run of digits with the separators that money uses: ``4,837.55`` ``4.837,55`` ``4 837.55``.
_RUN = re.compile(rf"\d(?:[\d{re.escape(_GROUP_SEPARATORS)}]*\d)?")
_PLAIN = re.compile(r"\d+(?:[.,]\d{1,2})?")
_GROUPED = re.compile(rf"(\d{{1,3}}(?:[{re.escape(_GROUP_SEPARATORS)}]\d{{3}})+)([.,]\d{{1,2}})?")
# Indian grouping: one or two digits, then pairs, then three digits (``1,03,450.00``).
_INDIAN_GROUPED = re.compile(r"(\d{1,2}(?:,\d{2})+,\d{3})([.,]\d{1,2})?")
_GROUP_SEPARATOR_CHARS = re.compile(rf"[{re.escape(_GROUP_SEPARATORS)}]")


class SourceBalanceVerdict(StrEnum):
    VERIFIED = "verified"
    CLOSING_NOT_IN_TEXT = "closing_not_in_text"
    OPENING_NOT_IN_TEXT = "opening_not_in_text"
    TEXT_UNUSABLE = "text_unusable"


def _piece_values(piece: str) -> Iterable[Decimal]:
    if _PLAIN.fullmatch(piece):
        yield Decimal(piece.replace(",", "."))
    grouped = _GROUPED.fullmatch(piece) or _INDIAN_GROUPED.fullmatch(piece)
    if grouped:
        integer_part = _GROUP_SEPARATOR_CHARS.sub("", grouped.group(1))
        fraction = grouped.group(2)
        yield Decimal(integer_part + (f".{fraction[1:]}" if fraction else ""))


def text_money_values(text: str) -> frozenset[Decimal]:
    """Return every number in ``text`` that a layout could print as money.

    A run such as ``85.40 4837.55`` yields both numbers. A run such as ``4 837.55``
    yields 4837.55 and its parts 4 and 837.55. A run such as ``3,000.00 5 000,00`` yields 3000.00 and
    5000.00: each window of adjacent pieces is read as one number too. The set can hold extra values. A superset
    only makes a match more likely, so it never raises a false flag. It can verify a
    closing balance that equals a part of a spaced number (a known limit, #2419).
    """
    values: set[Decimal] = set()
    for run in _RUN.findall(text):
        values.update(_piece_values(run))
        pieces = run.split()
        for start in range(len(pieces)):
            for end in range(start + 1, min(len(pieces), start + _MAX_SPACED_GROUPS) + 1):
                if (start, end) != (0, len(pieces)):
                    values.update(_piece_values(" ".join(pieces[start:end])))
    return frozenset(values)


def text_prints_money(text: str) -> bool:
    """Return True when the text prints at least one amount with a fraction, as a statement row does.

    A scanned page with a page number as its only text prints none.
    """
    for value in text_money_values(text):
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < 0:
            return True
    return False


def _mostly_printed(candidates: Iterable[Decimal | None], printed: frozenset[Decimal]) -> bool:
    """Return whether the text prints at least 4 of 5 of the non-zero candidates. No candidate counts as printed."""
    checked = [abs(value) for value in candidates if value is not None and value != 0]
    matched = sum(1 for value in checked if value in printed)
    return matched * MIN_AMOUNT_MATCH_DENOMINATOR >= len(checked) * MIN_AMOUNT_MATCH_NUMERATOR


def rows_missing_from_text(
    text: str | None,
    rows: Iterable[tuple[Decimal | None, Decimal | None]],
) -> list[int] | None:
    """Return the 1-based numbers of the rows whose amount or balance_after the text does not print.

    Each row is ``(amount, balance_after)``. Signs are ignored. A zero or missing value is not checked:
    a layout prints zero as a word or a dash.

    Return None when the text says nothing about the rows: it prints no money, or it prints fewer than
    4 of 5 of the row amounts (a cover page with text, and scanned transaction pages). The check of the
    closing balance treats such a text as unusable too.

    The balance_after of a row is checked only when the text prints at least 4 of 5 of the balances. A
    statement without a balance column (a credit card) prints none, and the model may compute them.
    """
    if not text or not text_prints_money(text):
        return None
    row_list = list(rows)
    printed = text_money_values(text)
    if not _mostly_printed((amount for amount, _balance in row_list), printed):
        return None
    check_balances = _mostly_printed((balance for _amount, balance in row_list), printed)
    missing: list[int] = []
    for number, (amount, balance) in enumerate(row_list, start=1):
        checked = (amount, balance) if check_balances else (amount,)
        if any(value is not None and value != 0 and abs(value) not in printed for value in checked):
            missing.append(number)
    return missing


def check_closing_balance_against_text(
    text: str | None,
    *,
    opening: Decimal | None,
    closing: Decimal | None,
    amounts: Iterable[Decimal],
) -> SourceBalanceVerdict:
    """Return whether the stored closing balance is a number that the document prints.

    Signs are ignored: a layout prints a negative balance with a minus sign, with
    parentheses, or with a trailing ``-``. A zero closing balance cannot be checked: a layout
    prints it as a word or a dash, and ``0.00`` occurs elsewhere in a statement.
    """
    amount_list = list(amounts)
    if not text or not text.strip() or closing is None or closing == 0 or not amount_list:
        return SourceBalanceVerdict.TEXT_UNUSABLE
    values = text_money_values(text)
    matched = sum(1 for amount in amount_list if abs(amount) in values)
    if matched * MIN_AMOUNT_MATCH_DENOMINATOR < len(amount_list) * MIN_AMOUNT_MATCH_NUMERATOR:
        return SourceBalanceVerdict.TEXT_UNUSABLE
    opening_missing = opening is not None and opening != 0 and abs(opening) not in values
    closing_in_text = abs(closing) in values
    if opening_missing and not closing_in_text:
        return SourceBalanceVerdict.TEXT_UNUSABLE
    if not closing_in_text:
        return SourceBalanceVerdict.CLOSING_NOT_IN_TEXT
    if opening_missing:
        return SourceBalanceVerdict.OPENING_NOT_IN_TEXT
    return SourceBalanceVerdict.VERIFIED
