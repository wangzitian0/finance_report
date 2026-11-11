"""``check_package_contract`` — gate validating packages against contracts."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from common.meta.base.dependency_graph import build_dependency_graph
from common.meta.base.gate_cli import run_cli_command
from common.meta.base.gate_util import (
    call_name,
    clear_source_caches,
    parse_ast_cached,
)
from common.meta.base.package_contract import (
    KIND_LAYER,
    LAYER_RANK,
    SPLIT,
    PackageContract,
    Unit,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_GLOB = "common/*/contract.py"
_CLASS_RANK = LAYER_RANK
_KNOWN_UPWARD_EXCEPTIONS: dict[tuple[str, str], str] = {}
_FRONTEND_TEST_SUFFIXES = (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
_JS_TEST_DECL = re.compile(
    r"""\b(?:it|test)(?:\.(?:only|skip))?\s*\(\s*(['"`])(?P<name>.*?)\1""",
    re.DOTALL,
)
_DYNAMIC_ANNOTATION = re.compile(r"\b(?:dict|Dict)\b|\bCallable\[\s*\.\.\.")
_DYNAMIC_RETURN = re.compile(r"(?:Any|dict|list)\b")
_FINANCIAL_PRIMITIVE_PARAMS = frozenset(
    {"currency", "date", "posted_at", "occurred_at"}
)


@dataclass(frozen=True)
class DiscoveredPackage:
    """A package discovered by the ``common/*/contract.py`` registry scan."""

    name: str
    spec_dir: Path
    impl_dir: Path | None
    contract: PackageContract

    @property
    def src_dir(self) -> Path:
        return self.impl_dir or self.spec_dir


def _parse_py(path: Path) -> ast.Module:
    return parse_ast_cached(path)


def _iter_py_trees(root: Path, *, skip: Path | None = None):
    if not root.exists():
        return
    for py in sorted(root.rglob("*.py")):
        if py != skip:
            yield py, _parse_py(py)


def _contained_impl_dir(be_rel: str | None, repo_root: Path) -> Path | None:
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
    backend = (repo_root / "apps" / "backend").resolve()
    impl = impl_dir.resolve()
    root = repo_root.resolve()
    rel = (
        impl.relative_to(backend)
        if impl == backend or backend in impl.parents
        else impl.relative_to(root)
    )
    return ".".join(rel.parts)


def discover_packages(repo_root: Path = REPO_ROOT) -> list[DiscoveredPackage]:
    found: list[DiscoveredPackage] = []
    for contract_path in sorted(repo_root.glob(PACKAGE_GLOB)):
        contract = _load_contract(contract_path, repo_root)
        if contract is None:
            continue
        found.append(
            DiscoveredPackage(
                name=contract.name,
                spec_dir=contract_path.parent,
                impl_dir=_contained_impl_dir(
                    contract.implementations.get("be"), repo_root
                ),
                contract=contract,
            )
        )
    return found


def _registered_prefixes(
    packages: list[DiscoveredPackage], repo_root: Path
) -> dict[str, str]:
    return {
        p.name: _impl_module_prefix(p.impl_dir, repo_root)
        for p in packages
        if p.impl_dir is not None and p.impl_dir.exists()
    }


def _target_package_from_module(mod: str, prefixes: dict[str, str]) -> str | None:
    for name, prefix in prefixes.items():
        if mod == prefix or mod.startswith(prefix + "."):
            return name
    return None


@lru_cache(maxsize=64)
def _load_contract_cached(
    path_str: str, repo_root_str: str, mtime_ns: int, size: int
) -> PackageContract | None:
    contract_path = Path(path_str)
    repo_root = Path(repo_root_str)
    backend_root = repo_root / "apps" / "backend"
    for path in (str(repo_root), str(backend_root)):
        if path not in sys.path:
            sys.path.insert(0, path)
    rel = contract_path.relative_to(repo_root)
    module_name = ".".join(rel.with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(module_name, contract_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    contract = getattr(module, "CONTRACT", None)
    return contract if isinstance(contract, PackageContract) else None


def _load_contract(
    contract_path: Path, repo_root: Path = REPO_ROOT
) -> PackageContract | None:
    resolved_contract = contract_path.resolve()
    resolved_root = repo_root.resolve()
    st = resolved_contract.stat()
    return _load_contract_cached(
        str(resolved_contract), str(resolved_root), st.st_mtime_ns, st.st_size
    )


def _package_all(src_dir: Path) -> list[str]:
    tree = _parse_py(src_dir / "__init__.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if not isinstance(node.value, (ast.List, ast.Tuple)):
                        return []
                    return [
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
    return []


def _frontend_test_names(text: str) -> set[str]:
    return {m.group("name") for m in _JS_TEST_DECL.finditer(text)}


@lru_cache(maxsize=1024)
def _frontend_test_names_cached(path_str: str, mtime_ns: int, size: int) -> set[str]:
    return _frontend_test_names(Path(path_str).read_text(encoding="utf-8"))


def _frontend_test_names_for_path(path: Path) -> set[str]:
    resolved = path.resolve()
    st = resolved.stat()
    return _frontend_test_names_cached(str(resolved), st.st_mtime_ns, st.st_size)


@lru_cache(maxsize=1024)
def _python_test_names_cached(path_str: str, mtime_ns: int, size: int) -> set[str]:
    return {
        node.name
        for node in ast.walk(parse_ast_cached(Path(path_str)))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _python_test_names(path: Path) -> set[str]:
    resolved = path.resolve()
    st = resolved.stat()
    return _python_test_names_cached(str(resolved), st.st_mtime_ns, st.st_size)


def _resolve_test(ref: str, repo_root: Path) -> str | None:
    if "::" not in ref:
        return f"test ref {ref!r} is not in 'path::func' form"
    rel_path, func = ref.split("::", 1)
    test_path = repo_root / rel_path
    if not test_path.exists():
        return f"test file does not exist: {rel_path}"
    if rel_path.endswith(_FRONTEND_TEST_SUFFIXES):
        if func not in _frontend_test_names_for_path(test_path):
            return f"test title {func!r} not found in {rel_path}"
        return None
    if func not in _python_test_names(test_path):
        return f"test function {func!r} not found in {rel_path}"
    return None


def _iter_cross_package_imports(pkg: DiscoveredPackage, prefixes: dict[str, str]):
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return
    for py, tree in _iter_py_trees(pkg.impl_dir, skip=pkg.impl_dir / "contract.py"):
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            targets: list[str] = []
            for mod in mods:
                target = _target_package_from_module(mod, prefixes)
                if target and target != pkg.name and target not in targets:
                    targets.append(target)
                    yield py, target


def _check_no_forbidden_edge(
    pkg: DiscoveredPackage,
    registered: dict[str, str],
    prefixes: dict[str, str] | None = None,
) -> list[str]:
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return []
    offenders: list[str] = []
    my_rank = _CLASS_RANK[pkg.contract.klass]
    allowed = set(pkg.contract.depends_on)
    resolved_prefixes = (
        prefixes if prefixes is not None else {n: f"src.{n}" for n in registered}
    )
    for py, target in _iter_cross_package_imports(pkg, resolved_prefixes):
        if target not in registered:
            continue
        target_rank = _CLASS_RANK[registered[target]]
        rel = py.relative_to(REPO_ROOT)
        if target_rank > my_rank:
            if (pkg.name, target) not in _KNOWN_UPWARD_EXCEPTIONS:
                offenders.append(
                    f"{rel}: upward import of '{target}' "
                    f"(class {registered[target]}) from '{pkg.name}' "
                    f"(class {pkg.contract.klass})"
                )
        elif target not in allowed:
            offenders.append(
                f"{rel}: imports '{target}' which is not in depends_on={sorted(allowed)}"
            )
    return offenders


def _check_unused_dependency(
    pkg: DiscoveredPackage,
    registered: dict[str, str],
    prefixes: dict[str, str] | None = None,
) -> list[str]:
    if (
        pkg.contract.status != "active"
        or pkg.impl_dir is None
        or not pkg.impl_dir.exists()
    ):
        return []
    resolved_prefixes = (
        prefixes if prefixes is not None else {n: f"src.{n}" for n in registered}
    )
    used = {target for _, target in _iter_cross_package_imports(pkg, resolved_prefixes)}
    impl_rel = pkg.impl_dir.relative_to(REPO_ROOT)
    return [
        f"depends_on includes '{dep}' but no import of it exists under "
        f"{impl_rel} — wire the dependency or remove the declaration"
        for dep in sorted(pkg.contract.depends_on)
        if dep not in used
    ]


def _check_cross_domain_deep_import(
    pkg: DiscoveredPackage,
    registered: dict[str, str],
    published: dict[str, list[str]],
) -> list[str]:
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return []
    offenders: list[str] = []
    for py, tree in _iter_py_trees(pkg.impl_dir):
        rel = py.relative_to(REPO_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if (
                    len(parts) < 2
                    or parts[0] != "src"
                    or parts[1] == pkg.name
                    or parts[1] not in registered
                ):
                    continue
                target = parts[1]
                pub = set(published.get(target, []))
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
                    if (
                        len(parts) > 2
                        and parts[0] == "src"
                        and parts[1] != pkg.name
                        and parts[1] in registered
                    ):
                        target = parts[1]
                        offenders.append(
                            f"{rel}: deep cross-domain import 'import {alias.name}' "
                            f"targets a submodule of package '{target}'. Import the "
                            f"package root ('import src.{target}') and use its "
                            f"published interface, or reference by id + a domain event."
                        )
    return offenders


def _classdef_tablename(node: ast.ClassDef) -> str | None:
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
    table_owner: dict[str, str] = {}
    model_owner: dict[str, str] = {}
    for pkg in packages:
        if pkg.impl_dir is None or not pkg.impl_dir.exists():
            continue
        for _, tree in _iter_py_trees(pkg.impl_dir):
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    table = _classdef_tablename(node)
                    if table is not None:
                        table_owner.setdefault(table, pkg.name)
                        model_owner.setdefault(node.name, pkg.name)
    return table_owner, model_owner


def _check_cross_domain_fk(
    pkg: DiscoveredPackage,
    registered: dict[str, str],
    _table_owner: dict[str, str],
    model_owner: dict[str, str],
) -> list[str]:
    if pkg.impl_dir is None or not pkg.impl_dir.exists():
        return []
    offenders: list[str] = []
    for py, tree in _iter_py_trees(pkg.impl_dir):
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or call_name(node.func) != "relationship"
                or not node.args
            ):
                continue
            arg = node.args[0]
            cls = (
                arg.value
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                else (arg.id if isinstance(arg, ast.Name) else None)
            )
            owner = model_owner.get(cls) if cls else None
            if owner and owner in registered and owner != pkg.name:
                offenders.append(
                    f"{py.relative_to(REPO_ROOT)}: cross-domain relationship('{cls}') targets a model "
                    f"owned by package '{owner}'. A cross-domain reference must "
                    f"be an id column resolved via the interface/event, not an "
                    f"ORM relationship."
                )
    return offenders


def _check_no_dependency_cycle(packages: list[DiscoveredPackage]) -> list[str]:
    try:
        build_dependency_graph([package.contract for package in packages])
    except ValueError as exc:
        return [str(exc)]
    return []


def _sibling_import_hit(node: ast.AST, prefix: str, sibling: str) -> str | None:
    own = f"{prefix}.{sibling}"
    if isinstance(node, ast.ImportFrom):
        mod, names = node.module or "", node.names
        if node.level and (
            mod.split(".")[0] == sibling
            or any(a.name == sibling or a.name.startswith(f"{sibling}.") for a in names)
        ):
            return f"(relative level {node.level}) {mod or '.'.join(a.name for a in names)}"
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
    hits: list[tuple[Path, str]] = []
    for py, tree in _iter_py_trees(layer_dir):
        for node in ast.walk(tree):
            hit = _sibling_import_hit(node, prefix, sibling)
            if hit:
                hits.append((py, hit))
    return hits


def _has_base_extension_split(pkg: DiscoveredPackage) -> bool:
    return bool(
        pkg.impl_dir
        and pkg.impl_dir.exists()
        and (pkg.impl_dir / "base").exists()
        and (pkg.impl_dir / "extension").exists()
    )


def _check_layer_purity(pkg: DiscoveredPackage) -> list[str]:
    if not _has_base_extension_split(pkg) or pkg.impl_dir is None:
        return []
    prefix = _impl_module_prefix(pkg.impl_dir, REPO_ROOT)
    return [
        f"{py.relative_to(REPO_ROOT)}: base/ imports the package's own "
        f"extension/ ('{hit}') — base must stay pure"
        for py, hit in _layer_imports(pkg.impl_dir / "base", prefix, "extension")
    ]


def _check_data_is_sink(pkg: DiscoveredPackage) -> list[str]:
    if (
        pkg.impl_dir is None
        or not pkg.impl_dir.exists()
        or not (pkg.impl_dir / "data").exists()
    ):
        return []
    prefix = _impl_module_prefix(pkg.impl_dir, REPO_ROOT)
    return [
        f"{py.relative_to(REPO_ROOT)}: {layer}/ imports the package's own "
        f"data/ ('{hit}') — data is a read-model sink; nothing may import it"
        for layer in ("base", "extension")
        if (pkg.impl_dir / layer).exists()
        for py, hit in _layer_imports(pkg.impl_dir / layer, prefix, "data")
    ]


def _check_repository_unit(pkg: DiscoveredPackage, unit: Unit) -> list[str]:
    assert pkg.impl_dir is not None
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
    if not _has_base_extension_split(pkg) or pkg.impl_dir is None:
        return []
    offenders: list[str] = []
    for unit in pkg.contract.units:
        expected = KIND_LAYER[unit.kind]
        if expected == SPLIT:
            offenders.extend(_check_repository_unit(pkg, unit))
        elif unit.module is not None:
            if unit.module.split("/")[0] != expected:
                offenders.append(
                    f"unit {unit.name!r} (kind {unit.kind.value!r}) declares module "
                    f"{unit.module!r} but its kind belongs in '{expected}/'"
                )
            elif not (pkg.impl_dir / unit.module).exists():
                offenders.append(
                    f"unit {unit.name!r}: declared module {unit.module!r} does not exist"
                )
    return offenders


def _command_definitions(
    impl_dir: Path, symbol: str
) -> list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]:
    found: list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef] = []
    for path in sorted(impl_dir.rglob("*.py")):
        try:
            tree = _parse_py(path)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        found.extend(
            node
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == symbol
        )
    return found


def _dynamic_type_findings(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    if isinstance(node, ast.ClassDef):
        return [
            f"dynamic type on field '{child.target.id}'"
            for child in node.body
            if isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
            and _DYNAMIC_ANNOTATION.search(ast.unparse(child.annotation))
        ]
    findings: list[str] = []
    args = node.args
    params = [
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        *(x for x in (args.vararg, args.kwarg) if x is not None),
    ]
    for arg in params:
        if arg.annotation is None:
            if arg.arg in _FINANCIAL_PRIMITIVE_PARAMS:
                findings.append(f"untyped financial parameter '{arg.arg}'")
        elif _DYNAMIC_ANNOTATION.search(ast.unparse(arg.annotation)):
            findings.append(f"dynamic type on parameter '{arg.arg}'")
    returned = "Any" if node.returns is None else ast.unparse(node.returns)
    if _DYNAMIC_RETURN.match(returned) or _DYNAMIC_ANNOTATION.search(returned):
        findings.append("dynamic return type")
    return findings


def _check_command_boundaries(pkg: DiscoveredPackage) -> list[str]:
    boundaries = pkg.contract.command_boundaries
    if not boundaries:
        return []
    if pkg.impl_dir is None:
        return [
            "declares command_boundaries but implementations['be'] is missing — "
            "no definition to check"
        ]
    errors: list[str] = []
    for boundary in boundaries:
        definitions = _command_definitions(pkg.impl_dir, boundary.symbol)
        if len(definitions) != 1:
            errors.append(
                f"command boundary '{boundary.symbol}' must have exactly one "
                f"top-level definition under {pkg.impl_dir}, found {len(definitions)}"
            )
            continue
        errors.extend(
            f"command boundary '{boundary.symbol}': {finding}"
            for finding in _dynamic_type_findings(definitions[0])
        )
    return errors


def check_package(
    pkg: DiscoveredPackage,
    registered: dict[str, str],
    repo_root: Path = REPO_ROOT,
    *,
    published: dict[str, list[str]] | None = None,
    table_owner: dict[str, str] | None = None,
    model_owner: dict[str, str] | None = None,
    prefixes: dict[str, str] | None = None,
) -> list[str]:
    errors: list[str] = []
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

    for label, items in (
        ("invariant", pkg.contract.invariants),
        ("roadmap", pkg.contract.roadmap),
    ):
        for item in items:
            err = _resolve_test(item.test, repo_root)
            if err:
                errors.append(f"[{pkg.name}] {label} '{item.id}': {err}")

    subchecks = [
        *_check_no_forbidden_edge(pkg, registered, prefixes),
        *_check_unused_dependency(pkg, registered, prefixes),
        *_check_layer_purity(pkg),
        *_check_kind_placement(pkg),
        *_check_data_is_sink(pkg),
        *_check_command_boundaries(pkg),
    ]
    if published is not None:
        subchecks.extend(_check_cross_domain_deep_import(pkg, registered, published))
    if table_owner is not None:
        subchecks.extend(
            _check_cross_domain_fk(pkg, registered, table_owner, model_owner or {})
        )
    errors.extend(f"[{pkg.name}] {e}" for e in subchecks)
    return errors


def _check_duplicate_public_function_exports(
    packages: list[DiscoveredPackage],
) -> list[str]:
    owners: dict[str, set[str]] = {}
    for package in packages:
        for symbol in package.contract.interface:
            if re.fullmatch(r"[a-z][a-z0-9_]*", symbol):
                owners.setdefault(symbol, set()).add(package.name)
    return [
        f"public function '{symbol}' is exported by multiple packages: "
        f"{', '.join(sorted(package_names))}"
        for symbol, package_names in sorted(owners.items())
        if len(package_names) > 1
    ]


def _check_authored_truth_surfaces(
    packages: list[DiscoveredPackage], repo_root: Path
) -> list[str]:
    errors = [
        f"{package.name}: missing required authored surface: readme.md"
        for package in packages
        if not any(
            entry.name == "readme.md" and entry.is_file()
            for entry in package.spec_dir.iterdir()
        )
    ]
    common_root = repo_root / "common"
    if common_root.is_dir():
        for path in sorted(common_root.rglob("*")):
            if path.is_file() and path.name.casefold() == "todo.md":
                errors.append(
                    f"{path.relative_to(repo_root)}: parallel worklist is forbidden; "
                    "scheduled work belongs in GitHub issues and package roadmaps"
                )
    return errors


def _validation_context(packages: list[DiscoveredPackage], repo_root: Path):
    registered = {p.name: p.contract.klass for p in packages}
    prefixes = _registered_prefixes(packages, repo_root)
    published = {
        p.name: _package_all(p.impl_dir)
        for p in packages
        if p.impl_dir is not None and (p.impl_dir / "__init__.py").exists()
    }
    table_owner, model_owner = _collect_orm_ownership(packages)
    return registered, prefixes, published, table_owner, model_owner


def _ok_summary(pkg: DiscoveredPackage) -> str:
    return (
        f"  {pkg.name} (class {pkg.contract.klass}): "
        f"{len(pkg.contract.interface)} interface symbol(s), "
        f"{len(pkg.contract.invariants)} invariant(s), "
        f"{len(pkg.contract.roadmap)} roadmap AC(s) — OK"
    )


_RUN_CACHE: dict[Path, tuple[bool, list[str]]] = {}


def clear_run_cache(target: Path | None = None) -> None:
    clear_source_caches()
    _load_contract_cached.cache_clear()
    _python_test_names_cached.cache_clear()
    _frontend_test_names_cached.cache_clear()
    if target is not None:
        _RUN_CACHE.pop(target.resolve(), None)
    else:
        _RUN_CACHE.clear()


def check_single_package(
    package_name: str,
    repo_root: Path = REPO_ROOT,
) -> tuple[bool, list[str]]:
    packages = discover_packages(repo_root)
    pkg = next((p for p in packages if p.name == package_name), None)
    if pkg is None:
        return False, [f"package '{package_name}' not discovered"]
    registered, prefixes, published, table_owner, model_owner = _validation_context(
        packages, repo_root
    )
    all_errors = [
        *_check_authored_truth_surfaces([pkg], repo_root),
        *check_package(
            pkg,
            registered,
            repo_root,
            published=published,
            table_owner=table_owner,
            model_owner=model_owner,
            prefixes=prefixes,
        ),
    ]
    return (
        not all_errors,
        ([_ok_summary(pkg)] if not all_errors else []) + all_errors,
    )


def run(
    repo_root: Path = REPO_ROOT, *, use_cache: bool = True
) -> tuple[bool, list[str]]:
    resolved = repo_root.resolve()
    if use_cache and resolved in _RUN_CACHE:
        ok, msgs = _RUN_CACHE[resolved]
        return (ok, list(msgs))
    packages = discover_packages(repo_root)
    registered, prefixes, published, table_owner, model_owner = _validation_context(
        packages, repo_root
    )
    messages: list[str] = []
    all_errors = _check_authored_truth_surfaces(packages, repo_root)
    for pkg in packages:
        errs = check_package(
            pkg,
            registered,
            repo_root,
            published=published,
            table_owner=table_owner,
            model_owner=model_owner,
            prefixes=prefixes,
        )
        if errs:
            all_errors.extend(errs)
        else:
            messages.append(_ok_summary(pkg))
    all_errors.extend(_check_no_dependency_cycle(packages))
    all_errors.extend(_check_duplicate_public_function_exports(packages))
    if not packages:
        all_errors.append("no packages discovered (expected at least 'counter')")
    result = (not all_errors, messages + all_errors)
    if use_cache:
        _RUN_CACHE[resolved] = (result[0], list(result[1]))
    return result


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate package contracts.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args(argv)
    ok, messages = run(Path(args.repo_root))
    print(f"[PACKAGE CONTRACT] {'PASSED' if ok else 'FAILED'}")
    for line in messages:
        print(line)
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli_command(_main, argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
