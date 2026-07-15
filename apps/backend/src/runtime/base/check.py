"""`DependencyCheck` — the port a dependency's presence probe implements.

Formalises the ad-hoc `ServiceStatus` + `_check_*` methods in
`apps/backend/src/boot.py`. A dependency is either **present** or **absent**;
there is no `skipped` (a declared dependency that cannot be reached is `ABSENT`
and must fail — invariant 2 in `common/runtime/readme.md`). Adapters that
implement this port are wired in the *switch* phase; this module only defines the
port + its result value language.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class DependencyStatus(str, Enum):
    """The outcome of probing a dependency. Deliberately binary — no `skipped`."""

    PRESENT = "present"
    ABSENT = "absent"


@dataclass(frozen=True)
class ProbeResult:
    """One probe's outcome: the binary status plus human detail + timing.

    The binary `status` is the enforcement signal (present ⇒ ok, absent ⇒ the
    dependency is unreachable and, if declared-required for the tier, fatal);
    `detail` carries the reason for logs / `ServiceStatus`.
    """

    name: str
    status: DependencyStatus
    detail: str
    duration_ms: float = 0.0

    @property
    def present(self) -> bool:
        return self.status is DependencyStatus.PRESENT


@runtime_checkable
class DependencyCheck(Protocol):
    """A probe that reports whether one declared dependency is reachable.

    `name` matches the dependency's name in the `DependencyManifest`; `probe`
    returns a `ProbeResult` and never raises for an ordinary outage (an
    unreachable dependency is `ABSENT`, not an exception).
    """

    name: str

    async def probe(self) -> ProbeResult: ...
