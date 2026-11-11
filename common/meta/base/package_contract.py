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

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

# The tier vocabulary + matrix and the five-layer topology each live in one
# stdlib-only sibling source. Import only what this model uses.
from common.meta.base.authority_matrix import (
    ACProofKind,
    PackageTier,
    TIER_DEFAULT_PROOF_KIND,
    TIER_VALID_PROOF_KINDS,
)
from common.meta.base.layering import LAYER_RANK, PACKAGE_LAYER, PackageClass
from common.meta.base.gate_util import expand_test_path, parse_acs_table
from common.meta.base.governance_control import (
    GovernanceGuarantee,
    GovernanceInitiative,
)

__all__ = [
    "ACRecord",
    "ac",
    "acs",
    "ConceptRecord",
    "concepts",
    "ContextRelation",
    "ContextScope",
    "GovernanceInitiative",
    "GovernanceGuarantee",
    "Invariant",
    "invs",
    "Kind",
    "KIND_LAYER",
    "LAYER_RANK",
    "PACKAGE_LAYER",
    "PackageClass",
    "PackageContract",
    "rels",
    "SPLIT",
    "suite",
    "Unit",
    "units",
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
    #: Canonical semantic identity for cross-package ownership. ``None`` keeps
    #: the concise default of ``name``; a same-spelled but distinct concept must
    #: opt into a distinct key rather than silently bypassing duplicate checks.
    semantic_key: str | None = None
    module: str | None = None
    impl: str | None = None

    @property
    def layer(self) -> str:
        """The canonical layer for this unit's kind (``"split"`` for repository)."""
        return KIND_LAYER[self.kind]

    @property
    def semantic_identity(self) -> str:
        """Canonical key used by the cross-package semantic-owner projection."""
        return self.semantic_key or self.name

    @field_validator("semantic_key")
    @classmethod
    def _semantic_key_is_nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("semantic_key must be non-empty when declared")
        return normalized

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
    priority: Priority = "P0"
    status: ACStatus = "done"
    #: Proof kind the AC's test provides. The AC inherits its authority tier from
    #: the owning :class:`PackageContract` (tier is a module-design property, not a
    #: per-AC one), so ``proof_kind`` is the only tier-related attribute an AC
    #: carries. ``None`` resolves to the package tier's canonical kind
    #: (:data:`TIER_DEFAULT_PROOF_KIND`); an explicit value MUST be valid for the
    #: package tier per :data:`TIER_VALID_PROOF_KINDS` (e.g. under an LLM-LED/LLM-ONLY package
    #: an AC can never be ``exact``). Enforced by the owning ``PackageContract``.
    proof_kind: ACProofKind | None = None
    #: Optional direct edge from this package-owned AC to one ``vision.md``
    #: anchor. The pure data-layer projection exposes these declarations to
    #: cross-cutting proof tooling; the vision matrix validates that the anchor
    #: exists in the checkout it is building.
    vision_anchor: str | None = None

    @field_validator("vision_anchor")
    @classmethod
    def _validate_vision_anchor(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", normalized):
            raise ValueError(
                "vision_anchor must be a non-empty lowercase vision.md anchor id"
            )
        return normalized


def ac(
    id: str,
    statement: str,
    test: str,
    priority: Priority = "P0",
    status: ACStatus = "done",
    proof_kind: ACProofKind | None = None,
    vision_anchor: str | None = None,
) -> ACRecord:
    """Compact positional builder for ACRecord."""
    return ACRecord(
        id=id,
        statement=statement,
        test=test,
        priority=priority,
        status=status,
        proof_kind=proof_kind,
        vision_anchor=vision_anchor,
    )


def suite(
    file: str,
    *rows: tuple[object, ...],
    priority: Priority = "P0",
    status: ACStatus = "done",
    proof_kind: ACProofKind | None = None,
) -> list[ACRecord]:
    """Build ACRecords sharing ``file`` and default metadata from row tuples."""
    expanded_file = expand_test_path(file)
    records: list[ACRecord] = []
    for row in rows:
        rid, stmt, test_ref = str(row[0]), str(row[1]), expand_test_path(str(row[2]))
        full_test = (
            f"{expanded_file}::{test_ref}"
            if expanded_file and "::" not in test_ref
            else test_ref
        )
        prio = row[3] if len(row) > 3 and row[3] is not None else priority
        st = row[4] if len(row) > 4 and row[4] is not None else status
        pk = row[5] if len(row) > 5 and row[5] is not None else proof_kind
        va = row[6] if len(row) > 6 else None
        records.append(
            ACRecord(
                id=rid,
                statement=stmt,
                test=full_test,
                priority=prio,  # type: ignore[arg-type]
                status=st,  # type: ignore[arg-type]
                proof_kind=pk,  # type: ignore[arg-type]
                vision_anchor=va,  # type: ignore[arg-type]
            )
        )
    return records


def acs(pkg: str, *items: str | ACRecord | list[ACRecord]) -> list[ACRecord]:
    """Flatten ACRecord items/suites or pipe-delimited tables for ``pkg``."""
    prefix = f"AC-{pkg}."
    out: list[ACRecord] = []
    for item in items:
        if isinstance(item, str):
            for rec_dict in parse_acs_table(pkg, item):
                out.append(
                    ACRecord(
                        id=str(rec_dict["id"]),
                        statement=str(rec_dict["statement"] or ""),
                        test=str(rec_dict["test"] or ""),
                        priority=rec_dict["priority"] or "P0",  # type: ignore[arg-type]
                        status=rec_dict["status"] or "done",  # type: ignore[arg-type]
                        proof_kind=rec_dict["proof_kind"],  # type: ignore[arg-type]
                        vision_anchor=rec_dict["vision_anchor"],
                    )
                )
            continue
        batch = item if isinstance(item, list) else [item]
        for rec in batch:
            if not rec.id.startswith("AC"):
                rec = rec.model_copy(update={"id": prefix + rec.id})
            out.append(rec)
    return out


_KIND_ALIASES: dict[str, Kind] = {
    "vo": Kind.VALUE_OBJECT,
    "ent": Kind.ENTITY,
    "agg": Kind.AGGREGATE_ROOT,
    "fac": Kind.FACTORY,
    "ev": Kind.DOMAIN_EVENT,
    "repo": Kind.REPOSITORY,
    "svc": Kind.DOMAIN_SERVICE,
    "bus": Kind.EVENT_BUS,
    "proj": Kind.PROJECTION,
    **{k.value: k for k in Kind},
}


def _resolve_kind(value: Kind | str) -> Kind:
    return value if isinstance(value, Kind) else _KIND_ALIASES[value]


def _opt_col(cols: list[str], idx: int) -> str | None:
    return cols[idx] if len(cols) > idx and cols[idx] and cols[idx] != "-" else None


def units(*specs: str | Unit | tuple[object, ...]) -> list[Unit]:
    """Build Unit declarations from pipe tables, tuples, or ``(kind, module, names)`` groups."""
    out: list[Unit] = []
    for spec in specs:
        if isinstance(spec, str):
            for raw in spec.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("@"):
                    cols = [c.strip() for c in line[1:].split("|")]
                    kind = _resolve_kind(cols[0])
                    mod = None if cols[1] == "-" or not cols[1] else cols[1]
                    for name in cols[2].split():
                        out.append(Unit(name=name, kind=kind, module=mod))
                    continue
                cols = [c.strip() for c in line.split("|")]
                out.append(
                    Unit(
                        name=cols[0],
                        kind=_resolve_kind(cols[1]),
                        module=_opt_col(cols, 2),
                        impl=_opt_col(cols, 3),
                        semantic_key=_opt_col(cols, 4),
                    )
                )
            continue
        if isinstance(spec, Unit):
            out.append(spec)
            continue
        if len(spec) == 3 and isinstance(spec[2], (tuple, list)):
            kind = _resolve_kind(spec[0])  # type: ignore[arg-type]
            mod = spec[1]
            for name in spec[2]:
                out.append(Unit(name=str(name), kind=kind, module=mod))  # type: ignore[arg-type]
            continue
        name = str(spec[0])
        kind = _resolve_kind(spec[1])  # type: ignore[arg-type]
        mod = spec[2] if len(spec) > 2 else None
        impl = spec[3] if len(spec) > 3 else None
        sem = spec[4] if len(spec) > 4 else None
        out.append(
            Unit(
                name=name,
                kind=kind,
                module=mod,  # type: ignore[arg-type]
                impl=impl,  # type: ignore[arg-type]
                semantic_key=sem,  # type: ignore[arg-type]
            )
        )
    return out


def invs(*specs: str | Invariant | tuple[object, ...]) -> list[Invariant]:
    """Build Invariant declarations from pipe tables, ``(id, statement, test)``, or file groups."""
    out: list[Invariant] = []
    for spec in specs:
        if isinstance(spec, str):
            cur_file = ""
            for raw in spec.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("@"):
                    f = line[1:].strip()
                    cur_file = "" if f == "-" else expand_test_path(f)
                    continue
                cols = [c.strip() for c in line.split("|")]
                tref = expand_test_path(cols[2])
                test = f"{cur_file}::{tref}" if cur_file and "::" not in tref else tref
                out.append(Invariant(id=cols[0], statement=cols[1], test=test))
            continue
        if isinstance(spec, Invariant):
            out.append(spec)
            continue
        if len(spec) == 2 and isinstance(spec[1], (tuple, list)):
            file = str(spec[0])
            for row in spec[1]:
                iid, stmt, fn = str(row[0]), str(row[1]), str(row[2])
                test = f"{file}::{fn}" if file and "::" not in fn else fn
                out.append(Invariant(id=iid, statement=stmt, test=test))
            continue
        out.append(
            Invariant(id=str(spec[0]), statement=str(spec[1]), test=str(spec[2]))
        )
    return out


def rels(
    consumer: str, *rows: str | ContextRelation | tuple[str, str, str]
) -> list[ContextRelation]:
    """Build outgoing ContextRelation records for ``consumer``."""
    out: list[ContextRelation] = []
    for row in rows:
        if isinstance(row, str):
            for raw in row.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                cols = [c.strip() for c in line.split("|")]
                out.append(
                    ContextRelation(
                        provider=cols[0],
                        consumer=consumer,
                        mode=cols[1],  # type: ignore[arg-type]
                        reason=cols[2],
                    )
                )
        elif isinstance(row, ContextRelation):
            out.append(row)
        else:
            out.append(
                ContextRelation(
                    provider=row[0],
                    consumer=consumer,
                    mode=row[1],  # type: ignore[arg-type]
                    reason=row[2],
                )
            )
    return out


def concepts(*rows: str | ConceptRecord | tuple[object, ...]) -> list[ConceptRecord]:
    """Build ConceptRecord declarations from pipe tables or positional tuples."""
    out: list[ConceptRecord] = []
    for row in rows:
        if isinstance(row, str):
            for raw in row.splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                cols = [c.strip() for c in line.split("|")]
                refs = [x for x in (_opt_col(cols, 3) or "").split(",") if x]
                proofs = [x for x in (_opt_col(cols, 4) or "").split(",") if x]
                out.append(
                    ConceptRecord(
                        key=cols[0],
                        owner=cols[1],
                        description=cols[2],
                        cross_refs=refs,
                        proofs=proofs,
                        family=_opt_col(cols, 5),
                        kind=_opt_col(cols, 6),
                        authority=_opt_col(cols, 7),
                        parent=_opt_col(cols, 8),
                    )
                )
            continue
        if isinstance(row, ConceptRecord):
            out.append(row)
            continue
        out.append(
            ConceptRecord(
                key=str(row[0]),
                owner=str(row[1]),
                description=str(row[2]),
                cross_refs=list(row[3]) if len(row) > 3 and row[3] else [],  # type: ignore[call-overload]
                proofs=list(row[4]) if len(row) > 4 and row[4] else [],  # type: ignore[call-overload]
                family=row[5] if len(row) > 5 else None,  # type: ignore[arg-type]
                kind=row[6] if len(row) > 6 else None,  # type: ignore[arg-type]
                authority=row[7] if len(row) > 7 else None,  # type: ignore[arg-type]
                parent=row[8] if len(row) > 8 else None,  # type: ignore[arg-type]
            )
        )
    return out


class ConceptRecord(BaseModel):
    """One SSOT concept this package owns, in the package-model concept registry.

    The package-owned half of ``common/meta/data/MANIFEST.yaml`` (#1799): a
    concept whose owner file lives inside this package declares itself here
    instead of being hand-copied into the central manifest, so
    ``concept_index`` (the ``data``-layer mirror of ``ac_index``) can compute
    the registry from contracts. ``owner`` is a repo-relative path with an
    optional ``#anchor``, exactly like ``MarketDataOverride``'s MANIFEST
    entry — ``check_manifest.py``'s existing checks (duplicate-owner,
    file-exists, anchor-resolves) run unchanged against the computed union of
    every package's ``concepts`` plus the residual (no-owning-package) entries
    still hand-kept in ``MANIFEST.yaml``.

    ``family``/``kind``/``authority``/``parent`` mirror the optional
    classification fields the hand-authored manifest already carries (used by
    the SSOT governance report, not by the structural checks) — kept optional
    so a package can adopt the field without inventing values it doesn't have
    an opinion on yet.
    """

    key: str
    owner: str
    description: str
    cross_refs: list[str] = []
    proofs: list[str] = []
    family: str | None = None
    kind: str | None = None
    authority: str | None = None
    parent: str | None = None


class ContextScope(BaseModel):
    """One bounded context's purpose and explicit responsibility boundary."""

    purpose: str
    in_scope: list[str]
    out_of_scope: list[str]

    @model_validator(mode="after")
    def _is_non_vacuous(self) -> ContextScope:
        if not self.purpose.strip():
            raise ValueError("context purpose must be non-empty")
        if not self.in_scope or not self.out_of_scope:
            raise ValueError("context scope must declare in_scope and out_of_scope")
        if set(self.in_scope) & set(self.out_of_scope):
            raise ValueError("context in_scope and out_of_scope must not overlap")
        return self


class ContextRelation(BaseModel):
    """A declared inter-context coupling with an explicit justification."""

    provider: str
    consumer: str
    mode: Literal[
        "published-language", "consumer-port", "event", "projection", "composition"
    ]
    reason: str

    @model_validator(mode="after")
    def _is_explicit(self) -> ContextRelation:
        if self.provider == self.consumer:
            raise ValueError("context relation provider and consumer must be different")
        if not self.reason.strip():
            raise ValueError("context relation reason must be non-empty")
        return self


class CommandBoundary(BaseModel):
    """One package-owned, decision-authorized public command boundary."""

    symbol: str
    version: str
    proof: str

    @field_validator("symbol", "version", "proof")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("command boundary fields must be non-empty")
        return normalized


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
        concepts:        the SSOT concepts this package owns (the package-model
                         concept registry, #1799) — the computed counterpart to
                         the hand-authored ``common/meta/data/MANIFEST.yaml``.
        context:         the bounded-context purpose and responsibility boundary.
        relationships:   this package's outgoing, justified context relationships.
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
    concepts: list[ConceptRecord] = []
    context: ContextScope | None = None
    relationships: list[ContextRelation] = []
    command_boundaries: list[CommandBoundary] = []
    governance: list[GovernanceInitiative] = []

    @model_validator(mode="after")
    def _governance_is_unique_and_package_owned(self) -> PackageContract:
        ac_ids = [ac.id for ac in self.roadmap]
        if len(ac_ids) != len(set(ac_ids)):
            raise ValueError(f"package {self.name!r}: duplicate roadmap AC id")

        initiative_ids = [initiative.id for initiative in self.governance]
        if len(initiative_ids) != len(set(initiative_ids)):
            raise ValueError(
                f"package {self.name!r}: duplicate governance initiative id"
            )

        guarantee_ids: set[str] = set()
        owned_acs = set(ac_ids)
        for initiative in self.governance:
            for guarantee in initiative.guarantees:
                if guarantee.id in guarantee_ids:
                    raise ValueError(
                        f"package {self.name!r}: duplicate governance guarantee id "
                        f"{guarantee.id!r}"
                    )
                guarantee_ids.add(guarantee.id)
                unknown = sorted(set(guarantee.affected_acs) - owned_acs)
                if unknown:
                    raise ValueError(
                        f"package {self.name!r}: governance guarantee "
                        f"{guarantee.id!r} references unowned ACs {unknown}"
                    )
        return self

    @model_validator(mode="after")
    def _command_boundaries_are_public_and_unique(self) -> PackageContract:
        symbols = [boundary.symbol for boundary in self.command_boundaries]
        if len(symbols) != len(set(symbols)):
            raise ValueError(
                f"package {self.name!r}: duplicate command boundary symbol"
            )
        unknown = sorted(set(symbols) - set(self.interface))
        if unknown:
            raise ValueError(
                f"package {self.name!r}: command boundaries must be public interface "
                f"symbols (unknown: {unknown})"
            )
        return self

    @model_validator(mode="after")
    def _context_relationships_are_owned_and_declared(self) -> PackageContract:
        """Keep relationship semantics with their consumer package contract.

        A relationship is an outgoing dependency declaration: the consumer is
        this contract, and its provider must already be a declared dependency.
        This prevents a central map from inventing semantics or silently adding
        topology not represented by the package contract.
        """
        if self.context is None and self.relationships:
            raise ValueError(
                f"package {self.name!r}: relationships require a context declaration"
            )
        providers = {relation.provider for relation in self.relationships}
        undeclared = sorted(providers - set(self.depends_on))
        if undeclared:
            raise ValueError(
                f"package {self.name!r}: context relationship providers must be "
                f"declared dependencies (undeclared: {undeclared})"
            )
        foreign_consumers = sorted(
            {relation.consumer for relation in self.relationships} - {self.name}
        )
        if foreign_consumers:
            raise ValueError(
                f"package {self.name!r}: context relationships must be owned by "
                f"their consumer (found: {foreign_consumers})"
            )
        return self

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
