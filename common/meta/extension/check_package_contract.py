"""``check_package_contract`` — the gate that validates packages against contracts.

Governance in the package model is *computed from contracts*, not hand-kept. The
authoritative spec for each package lives in ``common/<pkg>/`` (its ``readme.md``
+ ``contract.py``); the running code lives in the *implementations* the contract
points at. ``implementations["be"]`` is a **repo-relative** path — usually
``apps/backend/src/<pkg>``, but not required (the meta package points its BE
implementation at ``common/meta`` itself). For every registered package this gate
asserts:

  (a) ``contract.interface`` equals the BE implementation's ``__init__.__all__``
      (the published language and the contract agree);
  (b) every ``invariants[].test`` and ``roadmap[].test`` (``"path::func"``)
      resolves to a real test function in the repo;
  (c) ``depends_on`` introduces no forbidden edge — a package's implementation
      modules must not import a higher layer of the five-layer topology
      (``meta < infra < middleware < domain < app``; mirrors the spirit of
      ``tests/tooling/test_ledger_module.py``: down only);
  (d) the building-block layering holds for any package that adopts the
      ``base/extension/`` split — base stays pure (mechanism A), each declared
      ``unit`` sits in the layer its ``kind`` dictates (``KIND_LAYER``), a
      ``repository`` unit splits into a base port + an extension adapter
      (mechanism B), and ``data`` is a sink nothing else imports (the read-model);
  (e) one transaction belongs to exactly one domain (issue #1460, Decision B): a
      cross-domain reference goes through the *published* interface or by id + a
      domain event — never a shared cross-domain transaction. Two static edges are
      enforced. The **import edge** (``_check_cross_domain_deep_import``,
      AC-meta.txn.1/.2): an impl module may reach another registered package only
      via its bare published root (``import src.<other>``) or a symbol in that
      package's ``__all__`` (``from src.<other>... import <published name>``); an
      import of an *unpublished* internal (a submodule, another aggregate's object,
      or another domain's ORM/models written in-transaction) is rejected — whether
      the module path is the package root or a deep submodule. The **FK edge**
      (``_check_cross_domain_fk``, AC-meta.txn.3): a ``ForeignKey`` /
      ``relationship`` whose target table/model is owned by another registered
      package is rejected — the reference must be an id column resolved via the
      interface/event. The runtime atomicity of the outbox (AC-meta.event.1) is a
      behavioural property proven by the platform package's own tests, not by this
      structural gate.

      *Port-exception decision (counter):* counter imports the platform bus port
      ``from src.platform import OutboxEventBus`` and the base ports
      ``from src.platform.base import EventBus`` / ``DomainEvent`` — each name is in
      ``platform.__all__``, so the imports resolve to *published* symbols and are
      allowed (the same exception lets ``unit_price`` import the published ``Money``
      / ``Quantity`` value types from their defining modules, and how ``money`` /
      ``quantity`` import the published ``Ratio`` via its root ``from src.audit.ratio
      import Ratio``). The rule rejects imports of *unpublished* internals (including
      a root import of a submodule), not paths to published symbols — so no current
      package regresses.

This module is the meta package's ``extension`` layer (the impure edge: it walks
the filesystem and parses ASTs). It imports the ``base`` model
(:mod:`common.meta.base.package_contract`) — never ``data``.

Packages are discovered by scanning ``common/*/contract.py`` for a module-level
``CONTRACT = PackageContract(...)``; that single registry keeps the gate additive
— a new package is governed the moment it ships a ``common/<pkg>/contract.py``.
The meta package ``common/meta`` self-hosts: it ships its own contract and
is validated by this very gate.

stdlib + pydantic only (no app/framework imports) so the gate runs anywhere.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

from common.meta.base.package_contract import (
    KIND_LAYER,
    LAYER_RANK,
    SPLIT,
    PackageContract,
    Unit,
)

# This module lives at common/meta/extension/check_package_contract.py, so the
# repo root is four parents up (extension -> meta -> common -> repo).
REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_GLOB = "common/*/contract.py"

# Layer rank for the DAG rule: a package may never import a HIGHER layer (no
# upward edges), and same-layer (sideways) edges are allowed only when declared in
# ``depends_on`` AND acyclic — "never up, never sideways-cyclic". The upward guard
# is ``_check_no_forbidden_edge``'s ``target_rank > my_rank``; acyclicity is
# enforced globally by ``_check_no_dependency_cycle``. So a cohesive family (e.g.
# the value types money/ratio/quantity/unit_price) can share one ``middleware``
# layer and depend on each other acyclically, instead of being spread up the
# ladder. The rank table is the five-layer topology owned by meta's base
# (``meta < infra < middleware < domain < app``).
_CLASS_RANK = LAYER_RANK

# Packages a given class is forbidden to import, by the import prefix
# ``src.<pkg>``. We enforce the strongest, statically-checkable edge: a
# non-``core`` package must not import another *registered* package of a higher
# class. This mirrors test_ledger_module.py's "no upward edge" guard.


@dataclass(frozen=True)
class DiscoveredPackage:
    """A package found by the registry scan.

    ``spec_dir`` is the authoritative ``common/<pkg>/`` directory (where the
    contract + readme live). ``impl_dir`` is the BE implementation directory the
    contract points at via ``implementations["be"]`` — the code whose ``__all__``
    must equal ``contract.interface`` and whose modules the DAG rule scans. A
    package with no BE implementation has ``impl_dir is None``.
    """

    name: str
    spec_dir: Path
    impl_dir: Path | None
    contract: PackageContract

    @property
    def src_dir(self) -> Path:
        """Back-compat alias: the directory whose ``__all__`` the gate checks."""
        return self.impl_dir or self.spec_dir


def _contained_impl_dir(be_rel: str | None, repo_root: Path) -> Path | None:
    """Resolve ``implementations["be"]`` to a repo-contained directory, or None.

    ``be_rel`` must be a *repo-relative* path. We reject an absolute path or one
    that escapes ``repo_root`` (``..``) and return ``None`` — so the gate never
    reads or scans outside the repo, and ``check_package`` reports the missing BE
    implementation as a contract violation instead of crashing on a later
    ``relative_to(repo_root)``.
    """
    if not be_rel:
        return None
    candidate = Path(be_rel)
    if candidate.is_absolute():
        return None
    resolved = (repo_root / candidate).resolve()
    root = repo_root.resolve()
    if resolved != root and root not in resolved.parents:
        return None
    return resolved


def _impl_module_prefix(impl_dir: Path, repo_root: Path) -> str:
    """The dotted import prefix the implementation dir is importable under.

    The gate's layering checks need to recognise a package's *own* layer imports
    (``...extension`` / ``...data``) by their absolute module path. That path
    depends on which ``sys.path`` root contains the implementation:
    ``apps/backend/src/counter`` is importable as ``src.counter`` (``apps/backend``
    is on the path), while ``common/meta`` is importable as ``common.meta`` (the
    repo root is on the path). We derive the prefix from the dir location instead
    of assuming ``src.<name>``, so meta self-hosts correctly.
    """
    backend = (repo_root / "apps" / "backend").resolve()
    impl = impl_dir.resolve()
    root = repo_root.resolve()
    if impl == backend or backend in impl.parents:
        rel = impl.relative_to(backend)
    else:
        rel = impl.relative_to(root)
    return ".".join(rel.parts)


def discover_packages(repo_root: Path = REPO_ROOT) -> list[DiscoveredPackage]:
    """Scan ``common/*/contract.py`` for ``CONTRACT`` instances."""
    found: list[DiscoveredPackage] = []
    for contract_path in sorted(repo_root.glob(PACKAGE_GLOB)):
        spec_dir = contract_path.parent
        contract = _load_contract(contract_path, repo_root)
        if contract is None:
            continue
        impl_dir = _contained_impl_dir(contract.implementations.get("be"), repo_root)
        found.append(
            DiscoveredPackage(
                name=contract.name,
                spec_dir=spec_dir,
                impl_dir=impl_dir,
                contract=contract,
            )
        )
    return found


def _load_contract(
    contract_path: Path, repo_root: Path = REPO_ROOT
) -> PackageContract | None:
    """Import ``contract.py`` and return its module-level ``CONTRACT``, if any.

    ``repo_root`` and ``repo_root/apps/backend`` are placed on ``sys.path`` so a
    ``contract.py``'s ``from common.meta...`` import and any BE-package
    import (``src.*``) it needs both resolve.
    """
    backend_root = repo_root / "apps" / "backend"
    for path in (str(repo_root), str(backend_root)):
        if path not in sys.path:
            sys.path.insert(0, path)

    rel = contract_path.relative_to(repo_root)
    # e.g. common.counter.contract / common.meta.contract
    module_name = ".".join(rel.with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(module_name, contract_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    contract = getattr(module, "CONTRACT", None)
    if isinstance(contract, PackageContract):
        return contract
    return None


def _package_all(src_dir: Path) -> list[str]:
    """Statically read ``__all__`` from a package ``__init__.py`` (no import)."""
    init_path = src_dir / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    # Only a literal list/tuple has ``.elts``; a computed
                    # ``__all__`` (e.g. ``sorted(...)``) is not statically
                    # readable, so return [] (an interface mismatch the gate
                    # reports) instead of crashing on the missing attribute.
                    if not isinstance(node.value, (ast.List, ast.Tuple)):
                        return []
                    return [
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
    return []


def _resolve_test(ref: str, repo_root: Path) -> str | None:
    """Return an error string if ``"path::func"`` does not resolve, else None."""
    if "::" not in ref:
        return f"test ref {ref!r} is not in 'path::func' form"
    rel_path, func = ref.split("::", 1)
    test_path = repo_root / rel_path
    if not test_path.exists():
        return f"test file does not exist: {rel_path}"
    tree = ast.parse(test_path.read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if func not in names:
        return f"test function {func!r} not found in {rel_path}"
    return None


def _check_no_forbidden_edge(
    pkg: DiscoveredPackage, registered: dict[str, str]
) -> list[str]:
    """No module in ``pkg`` may import a registered package of a higher class.

    ``registered`` maps package name -> class. We scan every ``.py`` under the
    package for ``import src.<other>`` / ``from src.<other> import`` and flag any
    target package whose rank exceeds this package's rank (an upward edge), or an
    import of a package not declared in ``depends_on`` (a sideways/undeclared
    edge). Self-imports are always allowed.
    """
    offenders: list[str] = []
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return offenders
    my_rank = _CLASS_RANK[pkg.contract.klass]
    allowed = set(pkg.contract.depends_on)
    for py in sorted(pkg.impl_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for mod in mods:
                if not mod.startswith("src."):
                    continue
                target = mod.split(".")[1]
                if target == pkg.name or target not in registered:
                    continue
                target_rank = _CLASS_RANK[registered[target]]
                rel = py.relative_to(REPO_ROOT)
                if target_rank > my_rank:
                    offenders.append(
                        f"{rel}: upward import of '{target}' "
                        f"(class {registered[target]}) from '{pkg.name}' "
                        f"(class {pkg.contract.klass})"
                    )
                elif target not in allowed:
                    offenders.append(
                        f"{rel}: imports '{target}' which is not in "
                        f"depends_on={sorted(allowed)}"
                    )
    return offenders


def _check_cross_domain_deep_import(
    pkg: DiscoveredPackage,
    registered: dict[str, str],
    published: dict[str, list[str]],
) -> list[str]:
    """One-transaction-per-domain, the import edge (AC-meta.txn.1 / .2).

    A package's implementation may reference another *registered* package only
    through that package's **published interface** — either the bare package root
    (``import src.<other>``) or a symbol the target publishes in its ``__all__``
    (``published[<other>]``). Every name in a ``from src.<other>... import N1,
    N2, ...`` must itself be in the target's ``__all__``; an import that reaches an
    **unpublished internal** of another domain is rejected: cross-domain references
    go through the published language (or by id + a domain event), never by reaching
    into another aggregate's internals (txn.1) or writing another domain's
    ORM/models in the same transaction (txn.2).

    The published-symbol rule is uniform across the module path: a ``from`` import
    is allowed iff each imported name is in the target's ``__all__``, whether the
    module is the package root or a deep submodule. This is how ``counter`` imports
    the platform base ports (``from src.platform.base import EventBus`` —
    ``EventBus`` ∈ ``platform.__all__``) and how ``unit_price`` imports the
    published ``Money`` / ``Quantity`` value types from their defining modules — and
    why a *root* import of an unpublished name (``from src.<other> import
    <submodule>``) is rejected just like a deep reach. A plain ``import
    src.<other>.<sub>`` names no symbol and so can never be a published reference —
    it is always rejected; only the bare ``import src.<other>`` root is allowed.

    ``published`` maps package name -> its ``__all__`` (computed once by
    :func:`run`). Imports of *unregistered* modules (shared infra such as
    ``src.database``) are out of scope — only edges between registered packages are
    governed.
    """
    offenders: list[str] = []
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return offenders
    for py in sorted(pkg.impl_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if len(parts) < 2 or parts[0] != "src":
                    continue
                target = parts[1]
                if target == pkg.name or target not in registered:
                    continue
                # Every name in a `from src.<other> import N1, N2, ...` must be a
                # symbol the target publishes in its __all__ — whether the module is
                # the package root (`from src.<other> import N`) or a deep path
                # (`from src.<other>.<mod> import N`). A root import is NOT waved
                # through: `from src.<other> import <submodule>` or an unpublished
                # name bypasses the published interface just as a deep reach does.
                pub = set(published.get(target, []))
                rel = py.relative_to(REPO_ROOT)
                for alias in node.names:
                    if alias.name == "*" or alias.name not in pub:
                        offenders.append(
                            f"{rel}: cross-domain import "
                            f"'from {node.module} import {alias.name}' reaches an "
                            f"unpublished internal of package '{target}' (a name not "
                            f"in its __all__ — a submodule or another aggregate's "
                            f"object). A cross-domain reference must go through the "
                            f"published interface ('from src.{target} import <symbol "
                            f"in __all__>') or by id + a domain event."
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if len(parts) < 2 or parts[0] != "src":
                        continue
                    target = parts[1]
                    if target == pkg.name or target not in registered:
                        continue
                    if len(parts) > 2:
                        rel = py.relative_to(REPO_ROOT)
                        offenders.append(
                            f"{rel}: deep cross-domain import 'import {alias.name}' "
                            f"targets a submodule of package '{target}'. Import the "
                            f"package root ('import src.{target}') and use its "
                            f"published interface, or reference by id + a domain event."
                        )
    return offenders


def _classdef_tablename(node: ast.ClassDef) -> str | None:
    """The ``__tablename__`` string literal a SQLAlchemy model class declares, if any."""
    for stmt in node.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        for t in targets:
            if (
                isinstance(t, ast.Name)
                and t.id == "__tablename__"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                return value.value
    return None


def _collect_orm_ownership(
    packages: list[DiscoveredPackage],
) -> tuple[dict[str, str], dict[str, str]]:
    """Map every ORM table name and model class name to its owning package.

    A package owns a table/model when one of its implementation modules declares a
    class with ``__tablename__ = "<table>"``. The two maps (table name -> package,
    model class name -> package) let :func:`_check_cross_domain_fk` decide whether a
    ``ForeignKey`` string or a ``relationship`` target crosses a domain boundary.
    First declaration wins (``setdefault``) so the maps are deterministic.
    """
    table_owner: dict[str, str] = {}
    model_owner: dict[str, str] = {}
    for pkg in packages:
        if pkg.impl_dir is None or not pkg.impl_dir.exists():
            continue
        for py in sorted(pkg.impl_dir.rglob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    table = _classdef_tablename(node)
                    if table is not None:
                        table_owner.setdefault(table, pkg.name)
                        model_owner.setdefault(node.name, pkg.name)
    return table_owner, model_owner


def _call_func_name(func: ast.expr) -> str | None:
    """The bare callable name of a call target (``ForeignKey`` / ``sa.ForeignKey``)."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _check_cross_domain_fk(
    pkg: DiscoveredPackage,
    registered: dict[str, str],
    table_owner: dict[str, str],
    model_owner: dict[str, str],
) -> list[str]:
    """One-transaction-per-domain, the FK edge (AC-meta.txn.3).

    A SQLAlchemy ``ForeignKey("<table>.<col>")`` or ``relationship(...)`` whose
    target table/model belongs to **another** registered package is rejected — a
    cross-domain reference must become an id column resolved via the interface/event,
    never a database-enforced FK that ties two domains into one transaction.

    Detection is **AST-only and best-effort**, scoped to the reliably-decidable
    forms:
      * ``ForeignKey("<table>.<col>")`` — the target table is read from the string
        literal's first segment (the load-bearing, reliable case).
      * ``relationship("<ClassName>")`` / ``relationship(<ClassName>)`` — the target
        model class name is read from a string or bare ``Name`` argument.

    It deliberately does NOT resolve dynamic targets (a ``ForeignKey`` whose table
    comes from a variable/callable, or a ``relationship`` given an imported alias or
    an expression) — those are left to runtime/migration review rather than flagged
    here, to avoid false positives. ``table_owner`` / ``model_owner`` come from
    :func:`_collect_orm_ownership`.
    """
    offenders: list[str] = []
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return offenders
    for py in sorted(pkg.impl_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_func_name(node.func)
            if name == "ForeignKey" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    table = arg.value.split(".")[0]
                    owner = table_owner.get(table)
                    if owner and owner in registered and owner != pkg.name:
                        rel = py.relative_to(REPO_ROOT)
                        offenders.append(
                            f"{rel}: cross-domain ForeignKey('{arg.value}') targets "
                            f"table '{table}' owned by package '{owner}'. A "
                            f"cross-domain reference must be an id column resolved "
                            f"via the interface/event, not a database FK."
                        )
            elif name == "relationship" and node.args:
                arg = node.args[0]
                cls: str | None = None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    cls = arg.value
                elif isinstance(arg, ast.Name):
                    cls = arg.id
                owner = model_owner.get(cls) if cls else None
                if owner and owner in registered and owner != pkg.name:
                    rel = py.relative_to(REPO_ROOT)
                    offenders.append(
                        f"{rel}: cross-domain relationship('{cls}') targets a model "
                        f"owned by package '{owner}'. A cross-domain reference must "
                        f"be an id column resolved via the interface/event, not an "
                        f"ORM relationship."
                    )
    return offenders


def _check_no_dependency_cycle(packages: list[DiscoveredPackage]) -> list[str]:
    """Detect any cycle in the declared ``depends_on`` graph.

    Same-class (sideways) edges are allowed when declared, so the no-cycle rule is
    enforced globally here rather than by a strict rank ordering ("never up, never
    sideways-cyclic"). A cycle in ``depends_on`` is a hard error.
    """
    graph = {p.name: list(p.contract.depends_on) for p in packages}
    color = dict.fromkeys(graph, 0)  # 0=unvisited, 1=on-stack, 2=done
    offenders: list[str] = []

    def visit(node: str, path: list[str]) -> None:
        color[node] = 1
        for dep in graph.get(node, []):
            if dep not in graph:
                continue  # unregistered dep; the edge rule handles declared-ness
            if color[dep] == 1:
                cycle = path[path.index(dep) :] + [dep] if dep in path else [node, dep]
                offenders.append("dependency cycle: " + " -> ".join(cycle))
            elif color[dep] == 0:
                visit(dep, path + [dep])
        color[node] = 2

    for name in sorted(graph):
        if color[name] == 0:
            visit(name, [name])
    return sorted(set(offenders))


def _sibling_import_hit(node: ast.AST, prefix: str, sibling: str) -> str | None:
    """If ``node`` imports the package's own ``<sibling>`` layer, describe it.

    Recognises the package's own sibling-layer import in every form — relative
    (``from ..<sibling> import x`` / ``from .. import <sibling>``) and absolute
    (``from <prefix>.<sibling>... import x`` / ``from <prefix> import <sibling>`` /
    ``import <prefix>.<sibling>...``). ``prefix`` is the implementation's dotted
    import path (see :func:`_impl_module_prefix`). Returns ``None`` when the node
    does not reach the sibling layer.
    """
    own = f"{prefix}.{sibling}"
    if isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        names = node.names
        if node.level and (
            mod.split(".")[0] == sibling
            or any(a.name == sibling or a.name.startswith(f"{sibling}.") for a in names)
        ):
            return (
                f"(relative level {node.level}) "
                f"{mod or '.'.join(a.name for a in names)}"
            )
        if mod.startswith(own):
            return mod
        if mod == prefix and any(
            a.name == sibling or a.name.startswith(f"{sibling}.") for a in names
        ):
            return f"{mod}.{sibling}"
    elif isinstance(node, ast.Import):
        for a in node.names:
            if a.name.startswith(own):
                return a.name
    return None


def _layer_imports(
    layer_dir: Path, prefix: str, sibling: str
) -> list[tuple[Path, str]]:
    """Every ``.py`` under ``layer_dir`` that imports the own ``<sibling>`` layer."""
    hits: list[tuple[Path, str]] = []
    for py in sorted(layer_dir.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            hit = _sibling_import_hit(node, prefix, sibling)
            if hit:
                hits.append((py, hit))
    return hits


def _check_layer_purity(pkg: DiscoveredPackage) -> list[str]:
    """If a package's implementation uses ``base/`` + ``extension/`` layers, the
    ``base/`` layer must not import the package's own ``extension/`` — base is the
    pure, downward-only core; the edges live in extension (base down / extension
    up). This is mechanism A applied within the package.

    Additive: a package that does not use the two-layer split is skipped, so the
    role-folder packages keep passing unchanged.
    """
    offenders: list[str] = []
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return offenders
    base_dir, ext_dir = pkg.impl_dir / "base", pkg.impl_dir / "extension"
    if not (base_dir.exists() and ext_dir.exists()):
        return offenders
    prefix = _impl_module_prefix(pkg.impl_dir, REPO_ROOT)
    for py, hit in _layer_imports(base_dir, prefix, "extension"):
        offenders.append(
            f"{py.relative_to(REPO_ROOT)}: base/ imports the package's own "
            f"extension/ ('{hit}') — base must stay pure"
        )
    return offenders


def _check_data_is_sink(pkg: DiscoveredPackage) -> list[str]:
    """If a package has a ``data/`` layer, nothing in ``base/`` or ``extension/``
    may import it — ``data`` is the read-model / projection, a leaf sink computed
    FROM the write side. Keeping it a sink is what makes the projection safe: the
    write side never depends on its own read model.

    Additive: a package without a ``data/`` layer is skipped.
    """
    offenders: list[str] = []
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return offenders
    if not (pkg.impl_dir / "data").exists():
        return offenders
    prefix = _impl_module_prefix(pkg.impl_dir, REPO_ROOT)
    for layer in ("base", "extension"):
        layer_dir = pkg.impl_dir / layer
        if not layer_dir.exists():
            continue
        for py, hit in _layer_imports(layer_dir, prefix, "data"):
            offenders.append(
                f"{py.relative_to(REPO_ROOT)}: {layer}/ imports the package's own "
                f"data/ ('{hit}') — data is a read-model sink; nothing may import it"
            )
    return offenders


def _check_repository_unit(pkg: DiscoveredPackage, unit: Unit) -> list[str]:
    """A ``repository`` unit must split: port in ``base/``, adapter in ``extension/``.

    This is mechanism B (dependency inversion) made checkable: the abstract port
    the pure core depends on lives in ``base``; the concrete adapter that touches
    I/O lives in ``extension`` and depends back on the port.
    """
    offenders: list[str] = []
    port, impl = unit.module, unit.impl
    if port is not None and port.split("/")[0] != "base":
        offenders.append(
            f"repository unit {unit.name!r}: port {port!r} must live in 'base/' "
            "(the abstract port the pure core depends on)"
        )
    if impl is not None and impl.split("/")[0] != "extension":
        offenders.append(
            f"repository unit {unit.name!r}: adapter {impl!r} must live in "
            "'extension/' (the concrete I/O adapter — dependency inversion)"
        )
    for path in (port, impl):
        if path is not None and not (pkg.impl_dir / path).exists():
            offenders.append(
                f"repository unit {unit.name!r}: declared path {path!r} does not exist"
            )
    return offenders


def _check_kind_placement(pkg: DiscoveredPackage) -> list[str]:
    """Each declared ``unit`` must live in the layer its ``kind`` dictates.

    The building-block table is :data:`KIND_LAYER`; this check enforces it. A
    value-object/entity/aggregate/factory/domain-event belongs in ``base``, a
    domain-service/event-bus in ``extension``, a projection in ``data``, and a
    repository splits across ``base`` + ``extension`` (see
    :func:`_check_repository_unit`).

    Additive on two axes: a package that has not adopted the physical
    ``base/extension/`` split is skipped entirely, and within an adopted package a
    unit with no ``module`` path (kind declared for the taxonomy only) is skipped.
    """
    offenders: list[str] = []
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return offenders
    base_dir, ext_dir = pkg.impl_dir / "base", pkg.impl_dir / "extension"
    if not (base_dir.exists() and ext_dir.exists()):
        return offenders
    for unit in pkg.contract.units:
        expected = KIND_LAYER[unit.kind]
        if expected == SPLIT:
            offenders.extend(_check_repository_unit(pkg, unit))
            continue
        if unit.module is None:
            continue
        top = unit.module.split("/")[0]
        if top != expected:
            offenders.append(
                f"unit {unit.name!r} (kind {unit.kind.value!r}) declares module "
                f"{unit.module!r} but its kind belongs in '{expected}/'"
            )
            continue
        if not (pkg.impl_dir / unit.module).exists():
            offenders.append(
                f"unit {unit.name!r}: declared module {unit.module!r} does not exist"
            )
    return offenders


def check_package(
    pkg: DiscoveredPackage,
    registered: dict[str, str],
    repo_root: Path = REPO_ROOT,
    *,
    published: dict[str, list[str]] | None = None,
    table_owner: dict[str, str] | None = None,
    model_owner: dict[str, str] | None = None,
) -> list[str]:
    """Return the list of contract violations for one package (empty == OK).

    The one-transaction-per-domain checks (e) need cross-package maps and so are
    additive on their inputs: they run only when :func:`run` supplies ``published``
    (the import edge) / ``table_owner`` (the FK edge). A direct ``check_package``
    call without them skips those checks, exactly as before.
    """
    errors: list[str] = []

    # (a) interface == the BE implementation's __init__.__all__
    impl_dir = pkg.impl_dir
    if impl_dir is None:
        if pkg.contract.interface:
            errors.append(
                f"[{pkg.name}] declares interface {sorted(pkg.contract.interface)} "
                "but implementations['be'] is missing — no __all__ to check it against"
            )
    elif not (impl_dir / "__init__.py").exists():
        errors.append(
            f"[{pkg.name}] implementations['be'] points at {impl_dir} "
            "which has no __init__.py"
        )
    else:
        declared_all = _package_all(impl_dir)
        if sorted(pkg.contract.interface) != sorted(declared_all):
            errors.append(
                f"[{pkg.name}] interface != __all__\n"
                f"    contract.interface: {sorted(pkg.contract.interface)}\n"
                f"    __init__.__all__:   {sorted(declared_all)}"
            )

    # (b) every invariant/roadmap test resolves to a real test function
    for inv in pkg.contract.invariants:
        err = _resolve_test(inv.test, repo_root)
        if err:
            errors.append(f"[{pkg.name}] invariant '{inv.id}': {err}")
    for ac in pkg.contract.roadmap:
        err = _resolve_test(ac.test, repo_root)
        if err:
            errors.append(f"[{pkg.name}] roadmap '{ac.id}': {err}")

    # (c) no forbidden dependency edge (DAG rule)
    errors.extend(
        f"[{pkg.name}] {e}" for e in _check_no_forbidden_edge(pkg, registered)
    )

    # (d) building-block layering (additive — only for packages using the split):
    #     base stays pure (A), each unit sits in its kind's layer + repository
    #     splits (B), and data is a read-model sink nothing imports.
    errors.extend(f"[{pkg.name}] {e}" for e in _check_layer_purity(pkg))
    errors.extend(f"[{pkg.name}] {e}" for e in _check_kind_placement(pkg))
    errors.extend(f"[{pkg.name}] {e}" for e in _check_data_is_sink(pkg))

    # (e) one-transaction-per-domain (issue #1460): a cross-domain reference goes
    #     through the published interface or by id + event — never a deep reach
    #     into another domain's internals (txn.1/.2) or a cross-domain FK (txn.3).
    #     Additive: each sub-check runs only when run() supplies its cross-package map.
    if published is not None:
        errors.extend(
            f"[{pkg.name}] {e}"
            for e in _check_cross_domain_deep_import(pkg, registered, published)
        )
    if table_owner is not None:
        errors.extend(
            f"[{pkg.name}] {e}"
            for e in _check_cross_domain_fk(
                pkg, registered, table_owner, model_owner or {}
            )
        )

    return errors


def run(repo_root: Path = REPO_ROOT) -> tuple[bool, list[str]]:
    """Validate every discovered package; return (ok, messages)."""
    packages = discover_packages(repo_root)
    registered = {p.name: p.contract.klass for p in packages}
    # Cross-package maps for the one-transaction-per-domain checks (issue #1460):
    # each package's published __all__ (the import edge) and the ORM table/model
    # ownership (the FK edge).
    published = {
        p.name: _package_all(p.impl_dir)
        for p in packages
        if p.impl_dir is not None and (p.impl_dir / "__init__.py").exists()
    }
    table_owner, model_owner = _collect_orm_ownership(packages)
    messages: list[str] = []
    all_errors: list[str] = []
    for pkg in packages:
        errs = check_package(
            pkg,
            registered,
            repo_root,
            published=published,
            table_owner=table_owner,
            model_owner=model_owner,
        )
        if errs:
            all_errors.extend(errs)
        else:
            messages.append(
                f"  {pkg.name} (class {pkg.contract.klass}): "
                f"{len(pkg.contract.interface)} interface symbol(s), "
                f"{len(pkg.contract.invariants)} invariant(s), "
                f"{len(pkg.contract.roadmap)} roadmap AC(s) — OK"
            )
    all_errors.extend(_check_no_dependency_cycle(packages))
    if not packages:
        all_errors.append("no packages discovered (expected at least 'counter')")
    return (not all_errors, messages + all_errors)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: print results and exit non-zero on any violation."""
    parser = argparse.ArgumentParser(description="Validate package contracts.")
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="repo root (defaults to the detected root)",
    )
    args = parser.parse_args(argv)
    ok, messages = run(Path(args.repo_root))
    header = "PACKAGE CONTRACT"
    if ok:
        print(f"[{header}] PASSED")
        for line in messages:
            print(line)
        return 0
    print(f"[{header}] FAILED")
    for line in messages:
        print(line)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
