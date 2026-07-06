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
import json
from pathlib import Path

#: The app-domain-logic subdirs the ``backend`` super-package owns. Shared infra
#: leaves (``database`` / ``config`` / ``models`` / ``schemas`` / ``migrations``)
#: are a *different* concern (they are candidates for their own low packages) and
#: are deliberately out of scope here — this gate governs the domain-logic edge,
#: not every ``src.*`` import.
APP_REMAINDER_SUBDIRS: frozenset[str] = frozenset({"services", "routers", "prompts"})


def _iter_src_imports(tree: ast.AST) -> list[tuple[str, str | None]]:
    """Every ``src.*`` import in a module as (module_path, imported_name|None)."""
    pairs: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "src":
            pairs.extend((node.module, alias.name) for alias in node.names)
        elif isinstance(node, ast.Import):
            pairs.extend((alias.name, None) for alias in node.names if alias.name.split(".")[0] == "src")
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
            tree = ast.parse(py.read_text(encoding="utf-8"))
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


def _carved_and_published(repo_root: Path) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Resolve carved src-subdir → package and package → ``__all__`` from the real
    package registry (deferred import: this keeps the module importable in the lint
    env even if the heavier contract loader is unavailable)."""
    from common.meta.extension.check_package_contract import _package_all, discover_packages

    backend_src = (repo_root / "apps/backend/src").resolve()
    carved: dict[str, str] = {}
    published: dict[str, set[str]] = {}
    for pkg in discover_packages(repo_root):
        impl = pkg.impl_dir.resolve() if pkg.impl_dir else None
        if impl is None or not str(impl).startswith(str(backend_src) + "/"):
            continue
        sub = impl.relative_to(backend_src).parts[0]
        carved[sub] = pkg.name
        if (impl / "__init__.py").exists():
            published[pkg.name] = set(_package_all(impl))
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


def load_baseline(path: Path) -> set[str]:
    """The frozen allowed-edge set. Missing file → empty (a fresh, zero-debt repo)."""
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def dump_baseline(path: Path, edges: list[str]) -> None:
    path.write_text(json.dumps(sorted(set(edges)), indent=2) + "\n", encoding="utf-8")
