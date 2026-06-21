"""``check_package_contract`` — the gate that validates packages against contracts.

Governance in the package model is *computed from contracts*, not hand-kept. For
every registered package this gate asserts:

  (a) ``contract.interface`` equals the package's ``__init__.__all__`` (the
      published language and the contract agree);
  (b) every ``invariants[].test`` and ``roadmap[].test`` (``"path::func"``)
      resolves to a real test function in the repo;
  (c) ``depends_on`` introduces no forbidden edge — a ``platform``/``kernel``
      package's modules must not import a higher layer (mirrors the spirit of
      ``tests/tooling/test_ledger_module.py``: dependencies point down only).

Packages are discovered by scanning ``apps/backend/src/*/contract.py`` for a
module-level ``CONTRACT = PackageContract(...)``; that single registry keeps the
gate additive — a new package is governed the moment it ships a ``contract.py``.

stdlib + pydantic only (no app/framework imports) so the gate runs anywhere.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

from common.governance.package_contract import PackageContract

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_GLOB = "apps/backend/src/*/contract.py"

# Layer rank for the DAG rule: a package may only import packages of a STRICTLY
# LOWER class (dependencies point strictly downward; same-rank edges are
# rejected by ``_check_no_forbidden_edge``'s ``target_rank >= my_rank`` guard).
# ``core`` (vertical slice) may use ``platform`` + ``kernel``; ``platform`` may
# use ``kernel``; ``kernel`` is a leaf.
_CLASS_RANK = {"kernel": 0, "platform": 1, "core": 2}

# Packages a given class is forbidden to import, by the import prefix
# ``src.<pkg>``. We enforce the strongest, statically-checkable edge: a
# non-``core`` package must not import another *registered* package of a higher
# class. This mirrors test_ledger_module.py's "no upward edge" guard.


@dataclass(frozen=True)
class DiscoveredPackage:
    """A package found by the registry scan."""

    name: str
    src_dir: Path
    contract: PackageContract


def discover_packages(repo_root: Path = REPO_ROOT) -> list[DiscoveredPackage]:
    """Scan ``apps/backend/src/*/contract.py`` for ``CONTRACT`` instances."""
    found: list[DiscoveredPackage] = []
    for contract_path in sorted(repo_root.glob(PACKAGE_GLOB)):
        src_dir = contract_path.parent
        contract = _load_contract(contract_path)
        if contract is None:
            continue
        found.append(
            DiscoveredPackage(name=contract.name, src_dir=src_dir, contract=contract)
        )
    return found


def _load_contract(contract_path: Path) -> PackageContract | None:
    """Import ``contract.py`` and return its module-level ``CONTRACT``, if any.

    The backend ``src`` package must be importable as ``src.*``; ensure
    ``apps/backend`` is on ``sys.path`` so ``contract.py``'s ``from
    common.governance...`` and the package's own imports resolve.
    """
    backend_root = REPO_ROOT / "apps" / "backend"
    for path in (str(REPO_ROOT), str(backend_root)):
        if path not in sys.path:
            sys.path.insert(0, path)

    rel = contract_path.relative_to(REPO_ROOT / "apps" / "backend")
    module_name = ".".join(rel.with_suffix("").parts)  # e.g. src.counter.contract
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
    my_rank = _CLASS_RANK[pkg.contract.klass]
    allowed = set(pkg.contract.depends_on)
    for py in sorted(pkg.src_dir.rglob("*.py")):
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
                if target_rank >= my_rank:
                    offenders.append(
                        f"{rel}: upward/sideways import of '{target}' "
                        f"(class {registered[target]}) from '{pkg.name}' "
                        f"(class {pkg.contract.klass})"
                    )
                elif target not in allowed:
                    offenders.append(
                        f"{rel}: imports '{target}' which is not in "
                        f"depends_on={sorted(allowed)}"
                    )
    return offenders


def check_package(
    pkg: DiscoveredPackage, registered: dict[str, str], repo_root: Path = REPO_ROOT
) -> list[str]:
    """Return the list of contract violations for one package (empty == OK)."""
    errors: list[str] = []

    # (a) interface == __init__.__all__
    declared_all = _package_all(pkg.src_dir)
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

    return errors


def run(repo_root: Path = REPO_ROOT) -> tuple[bool, list[str]]:
    """Validate every discovered package; return (ok, messages)."""
    packages = discover_packages(repo_root)
    registered = {p.name: p.contract.klass for p in packages}
    messages: list[str] = []
    all_errors: list[str] = []
    for pkg in packages:
        errs = check_package(pkg, registered, repo_root)
        if errs:
            all_errors.extend(errs)
        else:
            messages.append(
                f"  {pkg.name} (class {pkg.contract.klass}): "
                f"{len(pkg.contract.interface)} interface symbol(s), "
                f"{len(pkg.contract.invariants)} invariant(s), "
                f"{len(pkg.contract.roadmap)} roadmap AC(s) — OK"
            )
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
