"""``PackageContract`` — machine-checkable bounded-context contract model."""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from common.meta.base.authority_matrix import (
    ACProofKind,
    PackageTier,
    TIER_DEFAULT_PROOF_KIND,
    TIER_VALID_PROOF_KINDS,
)
from common.meta.base.gate_util import expand_test_path, parse_acs_table
from common.meta.base.layering import LAYER_RANK, PACKAGE_LAYER, PackageClass

__all__ = [
    "ACRecord",
    "ac",
    "acs",
    "ConceptRecord",
    "concepts",
    "ContextRelation",
    "ContextScope",
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

Priority = Literal["P0", "P1", "P2"]
ACStatus = Literal["open", "done"]
PackageStatus = Literal["draft", "active", "deprecated"]
Layer = Literal["base", "extension", "data"]


class Kind(str, Enum):
    """DDD tactical building blocks plus read-model ``projection``."""

    VALUE_OBJECT = "value-object"
    ENTITY = "entity"
    AGGREGATE_ROOT = "aggregate-root"
    FACTORY = "factory"
    DOMAIN_EVENT = "domain-event"
    REPOSITORY = "repository"
    DOMAIN_SERVICE = "domain-service"
    EVENT_BUS = "event-bus"
    PROJECTION = "projection"


SPLIT = "split"

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
    """One DDD building block owned by a package and pinned to its layer."""

    name: str
    kind: Kind
    semantic_key: str | None = None
    module: str | None = None
    impl: str | None = None

    @property
    def layer(self) -> str:
        return KIND_LAYER[self.kind]

    @property
    def semantic_identity(self) -> str:
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
    """A property guaranteed by the package and pinned to a proving test."""

    id: str
    statement: str
    test: str


class ACRecord(BaseModel):
    """One acceptance criterion owned by a package roadmap."""

    id: str
    statement: str
    test: str
    priority: Priority = "P0"
    status: ACStatus = "done"
    proof_kind: ACProofKind | None = None
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
    return ACRecord(
        id=id,
        statement=statement,
        test=test,
        priority=priority,
        status=status,
        proof_kind=proof_kind,
        vision_anchor=vision_anchor,
    )


def _qualify_test(file_prefix: str, test_ref: str) -> str:
    expanded = expand_test_path(test_ref)
    return (
        f"{file_prefix}::{expanded}"
        if file_prefix and "::" not in expanded
        else expanded
    )


def _iter_table_lines(block: str):
    for raw in block.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            yield line


def suite(
    file: str,
    *rows: tuple[object, ...],
    priority: Priority = "P0",
    status: ACStatus = "done",
    proof_kind: ACProofKind | None = None,
) -> list[ACRecord]:
    expanded_file = expand_test_path(file)
    return [
        ACRecord(
            id=str(row[0]),
            statement=str(row[1]),
            test=_qualify_test(expanded_file, str(row[2])),
            priority=row[3] if len(row) > 3 and row[3] is not None else priority,  # type: ignore[arg-type]
            status=row[4] if len(row) > 4 and row[4] is not None else status,  # type: ignore[arg-type]
            proof_kind=row[5] if len(row) > 5 and row[5] is not None else proof_kind,  # type: ignore[arg-type]
            vision_anchor=row[6] if len(row) > 6 else None,  # type: ignore[arg-type]
        )
        for row in rows
    ]


def acs(pkg: str, *items: str | ACRecord | list[ACRecord]) -> list[ACRecord]:
    prefix = f"AC-{pkg}."
    out: list[ACRecord] = []
    for item in items:
        if isinstance(item, str):
            out.extend(
                ACRecord(
                    id=str(r["id"]),
                    statement=str(r["statement"] or ""),
                    test=str(r["test"] or ""),
                    priority=r["priority"] or "P0",  # type: ignore[arg-type]
                    status=r["status"] or "done",  # type: ignore[arg-type]
                    proof_kind=r["proof_kind"],  # type: ignore[arg-type]
                    vision_anchor=r["vision_anchor"],
                )
                for r in parse_acs_table(pkg, item)
            )
            continue
        for rec in item if isinstance(item, list) else [item]:
            out.append(
                rec
                if rec.id.startswith("AC")
                else rec.model_copy(update={"id": prefix + rec.id})
            )
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
    out: list[Unit] = []
    for spec in specs:
        if isinstance(spec, str):
            for line in _iter_table_lines(spec):
                if line.startswith("@"):
                    cols = [c.strip() for c in line[1:].split("|")]
                    kind, mod = _resolve_kind(cols[0]), _opt_col(cols, 1)
                    out.extend(
                        Unit(name=n, kind=kind, module=mod) for n in cols[2].split()
                    )
                else:
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
        elif isinstance(spec, Unit):
            out.append(spec)
        elif len(spec) == 3 and isinstance(spec[2], (tuple, list)):
            kind = _resolve_kind(spec[0])  # type: ignore[arg-type]
            out.extend(
                Unit(name=str(n), kind=kind, module=spec[1])  # type: ignore[arg-type]
                for n in spec[2]
            )
        else:
            out.append(
                Unit(
                    name=str(spec[0]),
                    kind=_resolve_kind(spec[1]),  # type: ignore[arg-type]
                    module=spec[2] if len(spec) > 2 else None,  # type: ignore[arg-type]
                    impl=spec[3] if len(spec) > 3 else None,  # type: ignore[arg-type]
                    semantic_key=spec[4] if len(spec) > 4 else None,  # type: ignore[arg-type]
                )
            )
    return out


def invs(*specs: str | Invariant | tuple[object, ...]) -> list[Invariant]:
    out: list[Invariant] = []
    for spec in specs:
        if isinstance(spec, str):
            cur_file = ""
            for line in _iter_table_lines(spec):
                if line.startswith("@"):
                    f = line[1:].strip()
                    cur_file = "" if f == "-" else expand_test_path(f)
                else:
                    cols = [c.strip() for c in line.split("|")]
                    out.append(
                        Invariant(
                            id=cols[0],
                            statement=cols[1],
                            test=_qualify_test(cur_file, cols[2]),
                        )
                    )
        elif isinstance(spec, Invariant):
            out.append(spec)
        elif len(spec) == 2 and isinstance(spec[1], (tuple, list)):
            file = expand_test_path(str(spec[0]))
            out.extend(
                Invariant(
                    id=str(r[0]),
                    statement=str(r[1]),
                    test=_qualify_test(file, str(r[2])),
                )
                for r in spec[1]
            )
        else:
            out.append(
                Invariant(id=str(spec[0]), statement=str(spec[1]), test=str(spec[2]))
            )
    return out


def rels(
    consumer: str, *rows: str | ContextRelation | tuple[str, str, str]
) -> list[ContextRelation]:
    out: list[ContextRelation] = []
    for row in rows:
        if isinstance(row, str):
            for line in _iter_table_lines(row):
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
    out: list[ConceptRecord] = []
    for row in rows:
        if isinstance(row, str):
            for line in _iter_table_lines(row):
                cols = [c.strip() for c in line.split("|")]
                out.append(
                    ConceptRecord(
                        key=cols[0],
                        owner=cols[1],
                        description=cols[2],
                        cross_refs=[
                            x for x in (_opt_col(cols, 3) or "").split(",") if x
                        ],
                        proofs=[x for x in (_opt_col(cols, 4) or "").split(",") if x],
                        family=_opt_col(cols, 5),
                        kind=_opt_col(cols, 6),
                        authority=_opt_col(cols, 7),
                        parent=_opt_col(cols, 8),
                    )
                )
        elif isinstance(row, ConceptRecord):
            out.append(row)
        else:
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
    """One SSOT concept owned by a package in the computed concept registry."""

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
    """The machine-checkable contract published by a bounded-context package."""

    name: str
    klass: PackageClass | None = None
    depends_on: list[str]
    interface: list[str]
    events: list[str]
    invariants: list[Invariant]
    roadmap: list[ACRecord]
    status: PackageStatus = "active"
    tier: PackageTier | None = None
    roles: list[str] = []
    units: list[Unit] = []
    implementations: dict[str, str | None] = {}
    concepts: list[ConceptRecord] = []
    context: ContextScope | None = None
    relationships: list[ContextRelation] = []
    command_boundaries: list[CommandBoundary] = []

    @model_validator(mode="after")
    def _governance_is_unique_and_package_owned(self) -> PackageContract:
        ac_ids = [ac.id for ac in self.roadmap]
        if len(ac_ids) != len(set(ac_ids)):
            raise ValueError(f"package {self.name!r}: duplicate roadmap AC id")
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
