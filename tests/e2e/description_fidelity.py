"""Count the rows whose description the model misread (#2932)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_LISTED = 5
REASON_DIFFERS, REASON_NO_BALANCE, REASON_NO_EVENT, REASON_AMBIGUOUS = (
    "differs",
    "no_balance",
    "no_event",
    "ambiguous",
)


@dataclass(frozen=True)
class Misread:
    got: str
    want: str | None
    balance_after: str | None
    reason: str


def _normalize(value: object) -> str:
    return " ".join(("" if value is None else str(value)).split())


def _decimal(value: object) -> Decimal | None:
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
    events_by_balance: dict[Decimal, list[Mapping[str, Any]]] = {}
    for event in expected_events:
        if (bal := _decimal(event.get("balance_after"))) is not None:
            events_by_balance.setdefault(bal, []).append(event)
    rows = list(transactions)
    rows_by_balance: dict[Decimal, int] = {}
    for row in rows:
        if (bal := _decimal(row.get("balance_after"))) is not None:
            rows_by_balance[bal] = rows_by_balance.get(bal, 0) + 1
    misreads: list[Misread] = []
    for row in rows:
        got, raw = _normalize(row.get("description")), row.get("balance_after")
        shown, bal = None if raw is None else str(raw), _decimal(raw)
        if bal is None:
            misreads.append(Misread(got, None, shown, REASON_NO_BALANCE))
        elif not (events := events_by_balance.get(bal, [])):
            misreads.append(Misread(got, None, shown, REASON_NO_EVENT))
        elif len(events) > 1 or rows_by_balance[bal] > 1:
            misreads.append(Misread(got, None, shown, REASON_AMBIGUOUS))
        elif got != (want := _normalize(events[0].get("description"))):
            misreads.append(Misread(got, want, shown, REASON_DIFFERS))
    return misreads


def _describe(misread: Misread) -> str:
    templates = {
        REASON_DIFFERS: f"{misread.got!r} for {misread.want!r} (balance after {misread.balance_after})",
        REASON_NO_BALANCE: f"{misread.got!r} with no usable balance after",
        REASON_NO_EVENT: f"{misread.got!r} with no fixture event for balance after {misread.balance_after}",
        REASON_AMBIGUOUS: f"{misread.got!r} with an ambiguous fixture match (balance after {misread.balance_after})",
    }
    return templates[misread.reason]


def format_misread_line(misreads: Sequence[Misread], known: int, rows: int) -> str:
    line = f"description fidelity: {len(misreads)} of {rows} rows differ from the fixture (known {known})"
    if not misreads:
        return line
    listed = [_describe(m) for m in misreads[:MAX_LISTED]] + (
        ["..."] if len(misreads) > MAX_LISTED else []
    )
    return f"{line}: {', '.join(listed)}"
