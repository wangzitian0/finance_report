"""Check an extracted closing balance against the numbers in the document text (#2394).

The model sometimes stores the closing balance that it computed from the rows, not the
closing balance that the document prints. The balance chain then ties out and hides the
mismatch. A PDF text layer holds the printed numbers. A stored closing balance that is
not one of them did not come from the document.

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

_GROUP_SEPARATORS = " ,.'  "
# A run of digits with the separators that money uses: ``4,837.55`` ``4.837,55`` ``4 837.55``.
_RUN = re.compile(rf"\d(?:[\d{re.escape(_GROUP_SEPARATORS)}]*\d)?")
_PLAIN = re.compile(r"\d+(?:[.,]\d{1,2})?")
_GROUPED = re.compile(rf"(\d{{1,3}}(?:[{re.escape(_GROUP_SEPARATORS)}]\d{{3}})+)([.,]\d{{1,2}})?")
_GROUP_SEPARATOR_CHARS = re.compile(rf"[{re.escape(_GROUP_SEPARATORS)}]")


class SourceBalanceVerdict(StrEnum):
    VERIFIED = "verified"
    CLOSING_NOT_IN_TEXT = "closing_not_in_text"
    TEXT_UNUSABLE = "text_unusable"


def _piece_values(piece: str) -> Iterable[Decimal]:
    if _PLAIN.fullmatch(piece):
        yield Decimal(piece.replace(",", "."))
    grouped = _GROUPED.fullmatch(piece)
    if grouped:
        integer_part = _GROUP_SEPARATOR_CHARS.sub("", grouped.group(1))
        fraction = grouped.group(2)
        yield Decimal(integer_part + (f".{fraction[1:]}" if fraction else ""))


def text_money_values(text: str) -> frozenset[Decimal]:
    """Return every number in ``text`` that a layout could print as money.

    A run such as ``85.40 4837.55`` yields both numbers. A run such as ``4 837.55``
    yields 4837.55. The set can hold extra values. A superset only makes a match more
    likely, so it never raises a false flag.
    """
    values: set[Decimal] = set()
    for run in _RUN.findall(text):
        values.update(_piece_values(run))
        pieces = run.split()
        if len(pieces) > 1:
            for piece in pieces:
                values.update(_piece_values(piece))
    return frozenset(values)


def check_closing_balance_against_text(
    text: str | None,
    *,
    opening: Decimal | None,
    closing: Decimal | None,
    amounts: Iterable[Decimal],
) -> SourceBalanceVerdict:
    """Return whether the stored closing balance is a number that the document prints.

    Signs are ignored: a layout prints a negative balance with a minus sign, with
    parentheses, or with a trailing ``-``.
    """
    amount_list = list(amounts)
    if not text or not text.strip() or closing is None or not amount_list:
        return SourceBalanceVerdict.TEXT_UNUSABLE
    values = text_money_values(text)
    if opening is not None and abs(opening) not in values:
        return SourceBalanceVerdict.TEXT_UNUSABLE
    matched = sum(1 for amount in amount_list if abs(amount) in values)
    if matched * MIN_AMOUNT_MATCH_DENOMINATOR < len(amount_list) * MIN_AMOUNT_MATCH_NUMERATOR:
        return SourceBalanceVerdict.TEXT_UNUSABLE
    if abs(closing) in values:
        return SourceBalanceVerdict.VERIFIED
    return SourceBalanceVerdict.CLOSING_NOT_IN_TEXT
