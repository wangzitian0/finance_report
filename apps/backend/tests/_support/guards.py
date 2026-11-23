"""The guard of the tests against external I/O inside an open application transaction (#3156, #3153).

A guard error must not be swallowable. ``UnexpectedExternalIO`` derives from ``BaseException``, as pytest's own
``Failed`` does, so no ``except Exception`` of product code can turn it into a fallback. Each violation is also
recorded, and the fixture that installs the guard fails the test at teardown when a violation was recorded and the
test did not acknowledge it: this holds when something catches ``BaseException`` too.
"""

from __future__ import annotations

import pytest


class UnexpectedExternalIO(BaseException):
    """A call reached external I/O while an application AsyncSession transaction was open."""


_VIOLATIONS: list[str] = []


def record_violation(operation: str) -> None:
    _VIOLATIONS.append(operation)


def acknowledge_violations() -> list[str]:
    """Return the recorded violations and forget them. A test that triggers the guard on purpose calls this."""
    seen = list(_VIOLATIONS)
    _VIOLATIONS.clear()
    return seen


def unacknowledged_violations() -> list[str]:
    return list(_VIOLATIONS)


def fail_on_unacknowledged_violations() -> None:
    """The check of the guard fixture at teardown: fail the test that went on after a refusal."""
    if violations := unacknowledged_violations():
        acknowledge_violations()
        pytest.fail(f"A guard refused external I/O inside an open transaction and the test went on: {violations}")
