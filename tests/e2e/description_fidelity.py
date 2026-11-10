"""AC-testing.e2e-description-fidelity.1: count the rows whose description the model misread (#2932).

The vision model reads some descriptions of a fixture wrongly, for example
the interest description of the Ping An fixture. The statement totals still match.
The approval step fails later on a description that the journey table does not know,
and the message does not say that the model misread the PDF.

A journey matches each extracted row to the fixture event with the same balance after.
The row date is not a key: the rows that the journey reads can have no date.
A row with a description that differs from the event is a misread.
A row that cannot be matched with one event is also reported. The module never guesses.
The journey fails when the count is above the known count.

This module uses only the standard library, like the path-quality module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

# The printed line lists at most this many differences, then "...".
MAX_LISTED = 5

REASON_DIFFERS = "differs"
REASON_NO_BALANCE = "no_balance"
REASON_NO_EVENT = "no_event"
REASON_AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Misread:
    """One extracted row that does not equal its fixture event.

    `want` is the description of the matched event. It is None when no single event matched.
    `reason` is `differs` for a matched row, and `no_balance`, `no_event` or `ambiguous` otherwise.
    `balance_after` is the text of the row value, or None when the row has none.
    """

    got: str
    want: str | None
    balance_after: str | None
    reason: str


def _normalize(value: object) -> str:
    return " ".join(("" if value is None else str(value)).split())


def _decimal(value: object) -> Decimal | None:
    """Return the value as a finite Decimal, or None when it is missing or not a finite number."""
    if value is None:
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def description_misreads(
    transactions: Iterable[Mapping[str, Any]],
    expected_events: Iterable[Mapping[str, Any]],
) -> list[Misread]:
    """Return the rows whose description differs from the fixture event with the same balance after.

    A row is reported without a `want` when it has no usable balance after (`no_balance`),
    when no event has its balance after (`no_event`), or when more than one event has it,
    or more than one row shares it with the same event (`ambiguous`).
    A row that equals its event after whitespace normalization is not reported.
    """
    events_by_balance: dict[Decimal, list[Mapping[str, Any]]] = {}
    for event in expected_events:
        balance = _decimal(event.get("balance_after"))
        if balance is not None:
            events_by_balance.setdefault(balance, []).append(event)

    rows = list(transactions)
    rows_by_balance: dict[Decimal, int] = {}
    for row in rows:
        balance = _decimal(row.get("balance_after"))
        if balance is not None:
            rows_by_balance[balance] = rows_by_balance.get(balance, 0) + 1

    misreads: list[Misread] = []
    for row in rows:
        got = _normalize(row.get("description"))
        raw = row.get("balance_after")
        shown = None if raw is None else str(raw)
        balance = _decimal(raw)
        if balance is None:
            misreads.append(Misread(got, None, shown, REASON_NO_BALANCE))
            continue
        events = events_by_balance.get(balance, [])
        if not events:
            misreads.append(Misread(got, None, shown, REASON_NO_EVENT))
        elif len(events) > 1 or rows_by_balance[balance] > 1:
            misreads.append(Misread(got, None, shown, REASON_AMBIGUOUS))
        else:
            want = _normalize(events[0].get("description"))
            if got != want:
                misreads.append(Misread(got, want, shown, REASON_DIFFERS))
    return misreads


def _describe(misread: Misread) -> str:
    if misread.reason == REASON_DIFFERS:
        return f"{misread.got!r} for {misread.want!r} (balance after {misread.balance_after})"
    if misread.reason == REASON_NO_BALANCE:
        return f"{misread.got!r} with no usable balance after"
    if misread.reason == REASON_NO_EVENT:
        return f"{misread.got!r} with no fixture event for balance after {misread.balance_after}"
    return f"{misread.got!r} with an ambiguous fixture match (balance after {misread.balance_after})"


def format_misread_line(misreads: Sequence[Misread], known: int, rows: int) -> str:
    """Return the one line that the journey prints, also for 0 differences.

    `rows` is the number of extracted rows. The line lists at most MAX_LISTED differences.
    """
    line = (
        f"description fidelity: {len(misreads)} of {rows} rows differ "
        f"from the fixture (known {known})"
    )
    if not misreads:
        return line
    listed = [_describe(misread) for misread in misreads[:MAX_LISTED]]
    if len(misreads) > MAX_LISTED:
        listed.append("...")
    return f"{line}: {', '.join(listed)}"
