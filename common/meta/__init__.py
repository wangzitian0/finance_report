"""``common.meta`` — structural architecture and migration gates."""

from __future__ import annotations

__all__ = ["DependencyEdge", "DependencyKind"]


def __getattr__(name: str):
    if name in {"DependencyEdge", "DependencyKind"}:
        from common.meta.base import dependency_graph

        return getattr(dependency_graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
