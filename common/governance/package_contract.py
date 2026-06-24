"""``PackageContract`` — the machine-checkable contract a package publishes.

A package = bounded context declares one :class:`PackageContract` instance in its
``contract.py``. The contract is the single source of truth for the package's
*published language* (``interface`` mirrors ``__init__.__all__``), its emitted
domain ``events``, the ``invariants`` it guarantees, and its ``roadmap`` (the
ACs it owns). ``tools/check_package_contract.py`` validates the live package
against this contract, so governance is *computed*, not hand-maintained.

stdlib + pydantic only by design: importable from the governance gate and from a
package's ``contract.py`` without pulling app/framework dependencies.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

#: A package class. The three orthogonal kinds in the model:
#: - ``kernel``   — leaf value-language reused everywhere (e.g. ``money``);
#:                  depends on nothing in the app.
#: - ``platform`` — a reusable horizontal capability (e.g. ``counter``);
#:                  depends only on kernels.
#: - ``core``     — a vertical domain slice (e.g. ``ledger``);
#:                  may depend on platform + kernel packages.
PackageClass = Literal["core", "platform", "kernel"]

#: AC priority, mirroring the EPIC AC tables (P0 highest).
Priority = Literal["P0", "P1", "P2"]

#: AC lifecycle status within a package roadmap.
ACStatus = Literal["open", "done"]

#: Package lifecycle status. ``draft`` = still being designed; ``active`` =
#: governed and shipped; ``deprecated`` = on the way out (still checked, but
#: flagged).
PackageStatus = Literal["draft", "active", "deprecated"]

class Invariant(BaseModel):
    """A property the package guarantees, pinned to the test that proves it.

    ``test`` is a ``"path::func"`` reference (pytest node-id style, module path
    relative to the repo root) so the governance gate can resolve it to a real
    test function — an invariant with no executable proof is not an invariant.
    """

    id: str
    statement: str
    test: str


class ACRecord(BaseModel):
    """One acceptance criterion the package owns, in the package-model registry.

    The package roadmap is the *new* home for a package's ACs (the model where
    governance is computed from contracts). ``test`` is a ``"path::func"``
    reference, exactly like :class:`Invariant.test`, so each AC resolves to the
    test that anchors it.
    """

    id: str
    statement: str
    test: str
    priority: Priority
    status: ACStatus


class PackageContract(BaseModel):
    """The contract a package publishes — the unit the governance gate checks.

    Fields:
        name:            the package name (matches its ``common/<name>/`` dir).
        klass:           ``core`` / ``platform`` / ``kernel`` (the dependency tier).
        status:          ``draft`` / ``active`` / ``deprecated`` (package lifecycle).
        depends_on:      names of packages this one may import (down-only edges).
        roles:           the role folders the implementation converges into
                         (e.g. ``["types", "ops", "store", "api"]``).
        implementations: where each implementation lives, by surface key
                         (``"be"`` / ``"fe"``); ``None`` means "no implementation
                         on that surface yet". The governance gate resolves
                         ``__all__`` against ``implementations["be"]``.
        interface:       the published language — must equal the BE
                         implementation's ``__init__.__all__``.
        events:          domain event type names this package publishes.
        invariants:      guaranteed properties, each pinned to a proving test.
        roadmap:         the ACs this package owns (the package-model AC registry).
    """

    name: str
    klass: PackageClass
    depends_on: list[str]
    interface: list[str]
    events: list[str]
    invariants: list[Invariant]
    roadmap: list[ACRecord]
    status: PackageStatus = "active"
    roles: list[str] = []
    implementations: dict[str, str | None] = {}
