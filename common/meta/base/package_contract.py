"""``PackageContract`` — the machine-checkable contract a package publishes.

A package = bounded context declares one :class:`PackageContract` instance in its
``contract.py``. The contract is the single source of truth for the package's
*published language* (``interface`` mirrors ``__init__.__all__``), its emitted
domain ``events``, the ``invariants`` it guarantees, its ``roadmap`` (the
ACs it owns), and — for a package modelled with DDD building blocks — its
``units`` (each tactical building block and the layer it lives in).
``check_package_contract`` validates the live package against this contract, so
governance is *computed*, not hand-maintained.

This module is the meta package's ``base`` layer: pure model, stdlib + pydantic
only by design (importable from the governance gate and from a package's
``contract.py`` without pulling app/framework dependencies). The authority-tier
vocabulary and the tier->proof matrix come from the stdlib-only sibling
:mod:`common.meta.base.authority_matrix`, and the five-layer topology from
:mod:`common.meta.base.layering` (both single machine sources, also imported by
the lightweight SSOT tooling that must NOT pull pydantic).

DDD building-block taxonomy
---------------------------
The eight DDD tactical building blocks each map to one canonical layer, and the
layering keeps the dependency graph acyclic via three mechanisms (A/B/C). That
mapping is the single source of truth in :data:`KIND_LAYER`:

==================  ====================  ============================
Building block      Layer                 Cycle-breaking mechanism
==================  ====================  ============================
Value Object        base                  A (leaf, only depended-on)
Entity              base                  A (composes VOs, one-way)
Aggregate Root      base                  A + C (refer by id)
Factory (pure)      base                  A
Domain Event        base                  C (both sides depend on the event type)
Repository          port=base/impl=ext    B (dependency inversion)
Domain Service      extension             A (extension -> base, one-way)
Event Bus           extension             C (runtime registry, no compile edge)
Projection          data                  read-model, leaf sink
==================  ====================  ============================
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, model_validator

# The tier vocabulary + matrix and the five-layer topology each live in one
# stdlib-only sibling source. Import only what this model uses.
from common.meta.base.authority_matrix import (
    ACProofKind,
    PackageTier,
    TIER_DEFAULT_PROOF_KIND,
    TIER_VALID_PROOF_KINDS,
)
from common.meta.base.layering import LAYER_RANK, PACKAGE_LAYER, PackageClass

__all__ = [
    "ACRecord",
    "Invariant",
    "Kind",
    "KIND_LAYER",
    "LAYER_RANK",
    "PACKAGE_LAYER",
    "PackageClass",
    "PackageContract",
    "SPLIT",
    "Unit",
]

#: AC priority, mirroring the EPIC AC tables (P0 highest).
Priority = Literal["P0", "P1", "P2"]

#: AC lifecycle status within a package roadmap.
ACStatus = Literal["open", "done"]

#: Package lifecycle status. ``draft`` = still being designed (its authority
#: tier may be undecided); ``active`` = governed and shipped (tier MUST be
#: decided); ``deprecated`` = on the way out (still checked, but flagged).
PackageStatus = Literal["draft", "active", "deprecated"]

#: The three internal layers a package converges into (the universal purity
#: axis, applied to every package — domain or tooling):
#: - ``base``      — pure, self-contained core; no I/O, no cross-package edges;
#:                   imports only other packages' ``base`` (a downward DAG).
#: - ``extension`` — the impure edges: cross-package wiring, I/O, ORM, bus.
#: - ``data``      — the read-model / projection: a leaf sink computed FROM the
#:                   write side; nothing in ``base``/``extension`` imports it.
Layer = Literal["base", "extension", "data"]


class Kind(str, Enum):
    """The eight DDD tactical building blocks (+ ``projection``, the read-model).

    A :class:`Unit`'s ``kind`` decides which :data:`Layer` it must live in via
    :data:`KIND_LAYER` — that mapping is the executable form of the building-block
    table. ``str`` mixin so the value is a plain string in dumps / AST views.
    """

    VALUE_OBJECT = "value-object"
    ENTITY = "entity"
    AGGREGATE_ROOT = "aggregate-root"
    FACTORY = "factory"
    DOMAIN_EVENT = "domain-event"
    REPOSITORY = "repository"
    DOMAIN_SERVICE = "domain-service"
    EVENT_BUS = "event-bus"
    PROJECTION = "projection"


#: ``"split"`` marks the one building block (``REPOSITORY``) that straddles two
#: layers: its port (the abstract interface) lives in ``base`` and its adapter
#: (the concrete impl) lives in ``extension`` — dependency inversion (mechanism
#: B). Every other kind resolves to a single :data:`Layer`.
SPLIT = "split"

#: The building-block table, as code: each :class:`Kind` -> its canonical layer.
#: The governance gate enforces unit placement against this single map, so the
#: table can never drift from what is checked.
KIND_LAYER: dict[Kind, str] = {
    Kind.VALUE_OBJECT: "base",
    Kind.ENTITY: "base",
    Kind.AGGREGATE_ROOT: "base",
    Kind.FACTORY: "base",
    Kind.DOMAIN_EVENT: "base",
    Kind.REPOSITORY: SPLIT,
    Kind.DOMAIN_SERVICE: "extension",
    Kind.EVENT_BUS: "extension",
    Kind.PROJECTION: "data",
}


class Unit(BaseModel):
    """One DDD building block a package owns, pinned to where its code lives.

    ``kind`` decides the canonical layer via :data:`KIND_LAYER`; ``module`` is the
    unit's file path **relative to the BE implementation dir** (e.g.
    ``"base/types/key.py"``) so the gate can check it sits in the right layer.
    ``module`` is optional: a package that has not adopted the physical
    ``base/extension/`` split (e.g. a value-type package still using
    ``types/ops``) may declare its units' kinds for the taxonomy without a path,
    and the gate skips placement for it (additive).

    A ``REPOSITORY`` unit is the one split block: ``module`` is its port (in
    ``base``) and ``impl`` is its adapter (in ``extension``) — mechanism B. ``impl``
    is meaningful only for a repository.
    """

    name: str
    kind: Kind
    module: str | None = None
    impl: str | None = None

    @property
    def layer(self) -> str:
        """The canonical layer for this unit's kind (``"split"`` for repository)."""
        return KIND_LAYER[self.kind]

    @model_validator(mode="after")
    def _impl_only_for_repository(self) -> Unit:
        """``impl`` (the extension adapter) is a repository-only concept.

        A non-repository unit lives in exactly one layer, so an ``impl`` second
        path is meaningless and almost certainly a mis-declaration. A repository
        that pins its port (``module``) must also pin its adapter (``impl``) — the
        split is the whole point of the kind.
        """
        if self.kind != Kind.REPOSITORY and self.impl is not None:
            raise ValueError(
                f"unit {self.name!r}: 'impl' is only valid for a repository unit "
                f"(kind={self.kind.value!r} resolves to layer {self.layer!r})."
            )
        if (
            self.kind == Kind.REPOSITORY
            and self.module is not None
            and self.impl is None
        ):
            raise ValueError(
                f"repository unit {self.name!r}: a pinned port ('module') requires "
                "a pinned adapter ('impl') — a repository is a base port + an "
                "extension adapter (dependency inversion)."
            )
        return self


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
    #: Proof kind the AC's test provides. The AC inherits its authority tier from
    #: the owning :class:`PackageContract` (tier is a module-design property, not a
    #: per-AC one), so ``proof_kind`` is the only tier-related attribute an AC
    #: carries. ``None`` resolves to the package tier's canonical kind
    #: (:data:`TIER_DEFAULT_PROOF_KIND`); an explicit value MUST be valid for the
    #: package tier per :data:`TIER_VALID_PROOF_KINDS` (e.g. under an LLM-LED/LLM-ONLY package
    #: an AC can never be ``exact``). Enforced by the owning ``PackageContract``.
    proof_kind: ACProofKind | None = None


class PackageContract(BaseModel):
    """The contract a package publishes — the unit the governance gate checks.

    Fields:
        name:            the package name (matches its ``common/<name>/`` dir).
        klass:           the five-layer placement (``meta`` < ``infra`` <
                         ``middleware`` < ``domain`` < ``app``), resolved from
                         :data:`PACKAGE_LAYER`; declared only for packages
                         outside the central map.
        status:          ``draft`` / ``active`` / ``deprecated`` (package lifecycle).
        tier:            the package's permanent authority tier (:data:`PackageTier`);
                         ``None`` = undecided, allowed only while ``status="draft"``.
        depends_on:      names of packages this one may import (down-only edges).
        roles:           (legacy) the role folders the implementation converges into
                         (e.g. ``["types", "ops", "store", "api"]``). Superseded by
                         ``units`` but still accepted during migration.
        units:           the DDD building blocks this package owns, each carrying its
                         kind (hence layer) and, when the physical base/extension
                         split is adopted, the path it lives at.
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
    #: The package's layer in the five-layer topology. Placement is global
    #: topology owned by L0: a package in :data:`PACKAGE_LAYER` needs no
    #: declaration (the map resolves it, and a declared value must agree); a
    #: package not in the map (synthetic/test contracts) must declare one.
    klass: PackageClass | None = None
    depends_on: list[str]
    interface: list[str]
    events: list[str]
    invariants: list[Invariant]
    roadmap: list[ACRecord]
    status: PackageStatus = "active"
    #: The package's permanent authority tier. ``None`` means "undecided" and is
    #: legal only for a ``draft`` package; an ``active``/``deprecated`` package
    #: must have resolved its tier to a concrete :data:`PackageTier`.
    tier: PackageTier | None = None
    roles: list[str] = []
    units: list[Unit] = []
    implementations: dict[str, str | None] = {}

    @model_validator(mode="after")
    def _layer_resolves_from_the_central_map(self) -> PackageContract:
        """Resolve ``klass`` from :data:`PACKAGE_LAYER` (L0 owns placement).

        Three cases: mapped + undeclared -> the map fills it in; mapped +
        declared -> the declaration must agree (a self-claim never outranks the
        topology); unmapped + undeclared -> unplaceable, rejected.
        """
        mapped = PACKAGE_LAYER.get(self.name)
        if self.klass is None:
            if mapped is None:
                raise ValueError(
                    f"package {self.name!r}: no layer. Add the package to "
                    "PACKAGE_LAYER (common/meta/base/layering.py) — placement "
                    "is global topology owned by L0 — or declare klass "
                    "explicitly for a package outside the map."
                )
            self.klass = mapped
        elif mapped is not None and self.klass != mapped:
            raise ValueError(
                f"package {self.name!r}: declared klass {self.klass!r} "
                f"contradicts PACKAGE_LAYER ({mapped!r}). The central map in "
                "common/meta/base/layering.py is the single placement source; "
                "fix the map or drop the declaration."
            )
        return self

    @model_validator(mode="after")
    def _tier_decided_and_proofs_match(self) -> PackageContract:
        """Enforce the module-design tier rules at construction.

        1. A shipped package has a decided tier: ``status != "draft"`` requires a
           concrete :data:`PackageTier` (a ``draft`` may stay ``tier=None`` — the
           "undecided" state that the legacy EPIC source spelled ``HU``).
        2. Every roadmap AC's proof kind is valid for the package's tier per the
           single matrix (:data:`TIER_VALID_PROOF_KINDS`); a missing kind resolves
           to the tier's canonical default and is materialized on the record. An
           undecided (``None``) tier skips the proof check — there is no tier to
           validate against yet.
        """
        if self.tier is None:
            if self.status != "draft":
                raise ValueError(
                    f"package {self.name!r}: status {self.status!r} requires a "
                    "decided authority tier (one of CODE-ONLY/CODE-LED/LLM-LED/LLM-ONLY); only a 'draft' "
                    "package may leave tier undecided (the legacy 'HU' state)."
                )
            return self

        valid = TIER_VALID_PROOF_KINDS[self.tier]
        for ac in self.roadmap:
            kind = ac.proof_kind or TIER_DEFAULT_PROOF_KIND[self.tier]
            if kind not in valid:
                raise ValueError(
                    f"package {self.name!r} AC {ac.id}: proof_kind {kind!r} is "
                    f"not valid for the package tier {self.tier} "
                    f"(valid: {sorted(valid)}). Under an LLM-LED/LLM-ONLY package an AC can "
                    "never be proven by an exact golden assertion."
                )
            ac.proof_kind = kind
        return self
