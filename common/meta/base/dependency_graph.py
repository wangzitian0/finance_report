"""Pure package dependency graph vocabulary and computation.

The graph is built only from :class:`PackageContract` declarations. Filesystem
discovery and Git ref handling stay in ``extension``; serializable read-model
projection stays in ``data``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

from infra2_sdk.rules.imports import find_dependency_cycle


class DependencyDeclaration(Protocol):
    """The contract facts required to construct the dependency graph."""

    name: str
    depends_on: Sequence[str]


class DependencyKind(StrEnum):
    """A package-to-package dependency phase."""

    COMPILE = "compile"


@dataclass(frozen=True, order=True)
class DependencyEdge:
    """One directed edge from a consuming package to its provider."""

    consumer: str
    provider: str
    kind: DependencyKind
    detail: str

    def as_dict(self) -> dict[str, str]:
        """Return the stable JSON projection of this edge."""

        return asdict(self)


@dataclass(frozen=True)
class DependencyGraph:
    """Validated dependency topology and its reverse-consumer views."""

    edges: tuple[DependencyEdge, ...]
    direct_consumers: dict[str, tuple[str, ...]]
    transitive_consumers: dict[str, tuple[str, ...]]

    def as_dict(self) -> dict[str, object]:
        """Return deterministic JSON-compatible graph data."""

        return {
            "edges": [edge.as_dict() for edge in self.edges],
            "direct_consumers": {
                name: list(consumers)
                for name, consumers in self.direct_consumers.items()
            },
            "transitive_consumers": {
                name: list(consumers)
                for name, consumers in self.transitive_consumers.items()
            },
        }


def build_dependency_graph(
    contracts: Sequence[DependencyDeclaration],
) -> DependencyGraph:
    """Validate contracts and compute direct plus transitive consumers."""

    by_name: dict[str, DependencyDeclaration] = {}
    for contract in contracts:
        if contract.name in by_name:
            raise ValueError(f"duplicate package {contract.name!r}")
        by_name[contract.name] = contract

    providers: dict[str, tuple[str, ...]] = {}
    edges: list[DependencyEdge] = []
    for name in sorted(by_name):
        dependencies = by_name[name].depends_on
        if len(dependencies) != len(set(dependencies)):
            raise ValueError(f"package {name!r} declares a duplicate dependency")
        for provider in sorted(dependencies):
            if provider == name:
                raise ValueError(f"package {name!r} cannot depend on itself")
            if provider not in by_name:
                raise ValueError(
                    f"package {name!r} depends on unknown package {provider!r}"
                )
            edges.append(
                DependencyEdge(
                    consumer=name,
                    provider=provider,
                    kind=DependencyKind.COMPILE,
                    detail="PackageContract.depends_on",
                )
            )
        providers[name] = tuple(sorted(dependencies))

    cycle = find_dependency_cycle({k: set(v) for k, v in providers.items()})
    if cycle is not None:
        raise ValueError(f"dependency cycle: {' -> '.join(cycle)}")

    direct: dict[str, list[str]] = {name: [] for name in sorted(by_name)}
    for edge in edges:
        direct[edge.provider].append(edge.consumer)

    transitive: dict[str, tuple[str, ...]] = {}
    for provider in sorted(by_name):
        consumers: set[str] = set()
        pending = list(direct[provider])
        while pending:
            consumer = pending.pop()
            if consumer in consumers:
                continue
            consumers.add(consumer)
            pending.extend(direct[consumer])
        transitive[provider] = tuple(sorted(consumers))

    return DependencyGraph(
        edges=tuple(sorted(edges)),
        direct_consumers={
            name: tuple(sorted(consumers)) for name, consumers in direct.items()
        },
        transitive_consumers=transitive,
    )
