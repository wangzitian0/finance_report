"""Order the collected E2E tests so that each parse journey starts at t=0 on its own pytest-xdist worker (#3241).

A parse journey waits for a server-side statement parse and takes most of the stage time. The xdist `load`
scheduler gives each worker a chunk of consecutive tests, and a worker starts a test only when it holds the next
test too. Thus each parse journey must be followed by a short test, and two parse journeys must not be adjacent.
This module changes only the order of the tests, never the set of tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

PARSE_JOURNEY_MARKER = "parse_journey"
"""Marker of a journey that uploads a statement and waits for its server-side parse."""

BROWSER_FIXTURE = "page"


class _Item(Protocol):
    fixturenames: Sequence[str]

    def get_closest_marker(self, name: str) -> object | None: ...


def parse_journeys_first[ItemT: _Item](items: Sequence[ItemT]) -> list[ItemT]:
    """Return the items with each parse journey first, followed by one API-only test (no browser).

    The API-only partners come from the end of the collection: pytest-playwright puts the tests without a
    browser last. The other tests keep their collection order after the pairs.
    """
    journeys = [
        item
        for item in items
        if item.get_closest_marker(PARSE_JOURNEY_MARKER) is not None
    ]
    if not journeys:
        return list(items)
    rest = [
        item for item in items if item.get_closest_marker(PARSE_JOURNEY_MARKER) is None
    ]
    api_only = [
        item for item in reversed(rest) if BROWSER_FIXTURE not in item.fixturenames
    ]
    partners = api_only[: len(journeys)]
    ordered: list[ItemT] = []
    for index, journey in enumerate(journeys):
        ordered.append(journey)
        if index < len(partners):
            ordered.append(partners[index])
    paired = {id(item) for item in partners}
    ordered.extend(item for item in rest if id(item) not in paired)
    return ordered
