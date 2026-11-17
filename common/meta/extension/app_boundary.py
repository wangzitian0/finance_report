"""L4 ``backend`` super-package boundary — edge computation (pure).

The un-migrated remainder of ``apps/backend/src`` (``services/`` / ``routers/`` /
``prompts/``) is the L4 ``backend`` app-layer super-package. This module computes
the two kinds of cross-boundary edge between that remainder and the already-carved
packages, in a stable canonical form so a baseline can freeze them and only allow
the set to shrink. It is pure (AST over the filesystem, no I/O beyond reads, no
pydantic) so it runs in the lightweight CI lint env and is trivially testable with
a synthetic tree.

Canonical edge string: ``"<in|out>::<repo-rel path>::<module>::<name>"`` — file +
imported symbol granularity, so a fix that removes one leaked symbol shrinks the
baseline by exactly one entry.
"""

from __future__ import annotations

import ast
from pathlib import Path

from common.meta.base.gate_util import parse_ast_cached

#: The app-domain-logic subdirs the ``backend`` super-package owns. Shared infra
#: leaves (``database`` / ``config`` / ``models`` / ``schemas`` / ``migrations``)
#: are a *different* concern (they are candidates for their own low packages) and
#: are deliberately out of scope here — this gate governs the domain-logic edge,
#: not every ``src.*`` import.
APP_REMAINDER_SUBDIRS: frozenset[str] = frozenset({"services", "routers", "prompts"})
L4_DELIVERY_PATHS: frozenset[str] = frozenset({"routers", "schemas"})


def l4_deep_import_edges(backend_src: Path, package_names: set[str]) -> list[str]:
    """Return statement-level deep imports from L4 delivery code to packages.

    Root imports (``from src.audit import Money``) are the stable boundary. A
    deeper path remains migration debt even when its symbol is publicly exported.
    """
    edges: list[str] = []
    for py in sorted(backend_src.rglob("*.py")):
        rel = py.relative_to(backend_src)
        if rel.parts[0] not in L4_DELIVERY_PATHS and rel.name != "composition.py":
            continue
        try:
            tree = parse_ast_cached(py)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if len(parts) > 2 and parts[0] == "src" and parts[1] in package_names:
                    names = ", ".join(alias.name for alias in node.names)
                    edges.append(f"{rel}::from {node.module} import {names}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if (
                        len(parts) > 2
                        and parts[0] == "src"
                        and parts[1] in package_names
                    ):
                        edges.append(f"{rel}::import {alias.name}")
    return sorted(set(edges))


def discover_l4_deep_import_edges(repo_root: Path) -> list[str]:
    """Discover current L4 deep imports against the canonical package names."""
    from common.meta.base.layering import PACKAGE_LAYER

    return l4_deep_import_edges(
        (repo_root / "apps/backend/src").resolve(), set(PACKAGE_LAYER)
    )


def _iter_src_imports(tree: ast.AST) -> list[tuple[str, str | None]]:
    """Every ``src.*`` import in a module as (module_path, imported_name|None)."""
    pairs: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] == "src"
        ):
            pairs.extend((node.module, alias.name) for alias in node.names)
        elif isinstance(node, ast.Import):
            pairs.extend(
                (alias.name, None)
                for alias in node.names
                if alias.name.split(".")[0] == "src"
            )
    return pairs


def cross_boundary_edges(
    *,
    backend_src: Path,
    carved: dict[str, str],
    published: dict[str, set[str]],
    repo_root: Path,
) -> list[str]:
    """Compute the sorted canonical cross-boundary edges.

    ``carved`` maps a ``src`` subdir name → owning carved package name (e.g.
    ``{"extraction": "extraction"}``). ``published`` maps package name → its
    ``__all__``. An edge is emitted when:

    - **inbound**: a file *outside* any carved subdir imports
      ``src.<carved>.<...>.<name>`` where ``<name>`` is not in that package's
      ``__all__`` (an unpublished-internal reach);
    - **outbound**: a file *inside* a carved subdir imports
      ``src.<app-remainder-subdir>...`` (a carved package reaching up into the app
      layer).
    """
    carved_names = set(carved)
    inbound: list[str] = []
    outbound: list[str] = []
    for py in sorted(backend_src.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        top = py.relative_to(backend_src).parts[0]
        rel = py.relative_to(repo_root)
        in_carved = top in carved_names
        try:
            tree = parse_ast_cached(py)
        except SyntaxError:
            continue
        for module, name in _iter_src_imports(tree):
            parts = module.split(".")
            if len(parts) < 2:
                continue
            target = parts[1]
            if not in_carved and target in carved_names:
                # Inbound: the remainder reaching a carved package. Mirror the core
                # deep-import rule uniformly (root or deep path):
                #   - `from src.<carved>[.sub] import N`  → N must be published;
                #     a wildcard or an unpublished name (incl. a root import of a
                #     submodule) is a leak.
                #   - `import src.<carved>.<sub>`          → a plain deep module
                #     import can never name a published symbol, so it is a leak;
                #     only the bare `import src.<carved>` root is allowed.
                pub = published.get(carved[target], set())
                if name is not None:
                    if name == "*" or name not in pub:
                        inbound.append(f"in::{rel}::{module}::{name}")
                elif len(parts) > 2:
                    inbound.append(f"in::{rel}::{module}::<import>")
            elif in_carved and target in APP_REMAINDER_SUBDIRS:
                outbound.append(f"out::{rel}::{module}::{name or '*'}")
    return sorted(set(inbound)) + sorted(set(outbound))


def _package_all(src_dir: Path) -> list[str]:
    tree = parse_ast_cached(src_dir / "__init__.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if not isinstance(node.value, (ast.List, ast.Tuple)):
                        return []
                    return [
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant)
                        and isinstance(elt.value, str)
                    ]
    return []


def _carved_and_published(
    repo_root: Path,
) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Resolve carved src-subdir -> package and package -> ``__all__`` from ``apps/backend/src``."""
    backend_src = (repo_root / "apps/backend/src").resolve()
    common_root = (repo_root / "common").resolve()
    carved: dict[str, str] = {}
    published: dict[str, set[str]] = {}
    if not backend_src.is_dir():
        return carved, published
    for impl in sorted(backend_src.iterdir()):
        if not impl.is_dir():
            continue
        sub = impl.name
        if sub in APP_REMAINDER_SUBDIRS:
            continue
        if not (impl / "__init__.py").exists() or not (common_root / sub).is_dir():
            continue
        carved[sub] = sub
        published[sub] = set(_package_all(impl))
    return carved, published


def discover_and_compute_edges(repo_root: Path) -> list[str]:
    """The real-repo edge set: wire :func:`cross_boundary_edges` to the registry."""
    carved, published = _carved_and_published(repo_root)
    return cross_boundary_edges(
        backend_src=(repo_root / "apps/backend/src").resolve(),
        carved=carved,
        published=published,
        repo_root=repo_root.resolve(),
    )
