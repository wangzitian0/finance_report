"""Mirror lock for the audit value kernel (#2752, part of #2680).

`apps/backend/src/audit` is the one editable source. `common/audit` is a mirror that
bare-Python tooling imports: those CI jobs install neither the backend nor SQLAlchemy.
Every Python module under `common/audit` must hold the same code as its twin under
`apps/backend/src/audit`, except the modules and names that this file lists with a reason.
The comparison removes docstrings, import order and import style, which the two trees
format differently (ruff line length 120 and 88). It rewrites the module names of import
statements only: a string constant that names `common.audit` or `src.audit` is code. The
four TraceRecord files keep a stricter comparison that also keeps docstrings and import order.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
COMMON_ROOT = REPO / "common/audit"
BACKEND_ROOT = REPO / "apps/backend/src/audit"

# Modules in `common/audit` with no twin. Each one serves bare-Python tooling only.
COMMON_ONLY = {
    "contract.py": "package contract (roadmap, units); the backend image does not ship it",
    "extension/cascade_ownership.py": "FK cascade inventory gate; tests/tooling runs it",
    "money/guard.py": "float scan over both trees; tests/tooling runs it",
    "money/conformance/__init__.py": "money vector loader for tests/tooling and backend tests",
    "quantity/conformance/__init__.py": "quantity vector loader for tests/tooling and backend tests",
    "ratio/conformance/__init__.py": "ratio vector loader for tests/tooling and backend tests",
    "unit_price/conformance/__init__.py": "unit price vector loader for tests/tooling and backend tests",
}

# Modules in `apps/backend/src/audit` with no twin, with the kind and the reason.
# SQLALCHEMY: the module imports SQLAlchemy or `src.database`, directly or through another
# listed module, so the stdlib-only mirror cannot hold it.
# NO_BARE_CONSUMER: the module imports only the standard library and `src.audit`, but no
# bare-Python job and no tooling consumer under `common/` or `tools/` uses it. Every
# `src.audit.*` import runs `src/audit/__init__.py`, which imports SQLAlchemy. The consumer
# test below fails when a file under `common/` or `tools/` starts to import one.
SQLALCHEMY = "SQLALCHEMY"
NO_BARE_CONSUMER = "NO_BARE_CONSUMER"
BACKEND_ONLY = {
    "base/promotion.py": (NO_BARE_CONSUMER, "promotion policy types"),
    "base/terminal_audit.py": (NO_BARE_CONSUMER, "terminal audit spec"),
    "data/__init__.py": (NO_BARE_CONSUMER, "confidence projection package"),
    "data/trace_confidence.py": (NO_BARE_CONSUMER, "confidence projection"),
    "digest.py": (
        NO_BARE_CONSUMER,
        "canonical JSON and text SHA-256 digests of backend packages (#2768)",
    ),
    "extension/promotion.py": (NO_BARE_CONSUMER, "promotion evaluation"),
    "extension/terminal_audit.py": (NO_BARE_CONSUMER, "terminal audit verifier"),
    "extension/trace_decision_projection.py": (
        SQLALCHEMY,
        "decision projection queries",
    ),
    "extension/trace_emitter.py": (NO_BARE_CONSUMER, "emitter on the repository port"),
    "extension/trace_repository.py": (SQLALCHEMY, "SQL repository"),
    "money/adopt.py": (NO_BARE_CONSUMER, "backend money adoption helpers"),
    "orm/__init__.py": (SQLALCHEMY, "ORM package"),
    "orm/trace_record.py": (SQLALCHEMY, "ORM rows and triggers"),
    "promotion/__init__.py": (NO_BARE_CONSUMER, "promotion package"),
    "source_type_priority.py": (
        NO_BARE_CONSUMER,
        "source type priority of journal entries",
    ),
}
# Files under `common/` or `tools/` that run in the backend virtualenv and import a
# backend-only module. Empty today; a new entry needs a reason.
BACKEND_RUN_CONSUMERS: dict[str, str] = {}
# The four TraceRecord files keep the full comparison of the former lock: docstrings and
# import order count.
STRICT_FILES = (
    "base/trace.py",
    "base/trace_repository.py",
    "extension/trace_codec.py",
    "extension/trace_adapters.py",
)

# Twin modules whose text differs by design. The package surface of the root, `base` and
# `extension` differs: the backend publishes the ORM, repository and promotion names, and
# the mirror publishes `CONTRACT` and the cascade gate. The surface test checks the rest.
SURFACE_MODULES = ("__init__.py", "base/__init__.py", "extension/__init__.py")
# Names that one side publishes and the other side does not, with the reason above.
COMMON_ONLY_EXPORTS = {
    "base/__init__.py": set(),
    "extension/__init__.py": {
        "CascadeInventoryError",
        "CascadeOwnership",
        "CascadeSite",
        "DEBT_BASELINE_PATH",
        "INVENTORY_PATH",
        "discover_cascades",
        "load_debt_baseline",
        "load_inventory",
        "validate_debt_ratchet",
        "validate_inventory",
    },
}
BACKEND_ONLY_EXPORTS = {
    "base/__init__.py": {"TerminalAuditSpec"},
    "extension/__init__.py": {
        "TERMINAL_AUDIT_POLICY_VERSION",
        "SqlTraceRecordRepository",
        "TerminalAuditVerifier",
        "TraceEmitter",
        "TraceRecordPersistenceError",
        "current_authoritative_trace_decision_projection",
        "current_authoritative_trace_decisions",
        "shared_current_authority",
        "trace_decision_projection",
    },
}

# Twin modules that hold the same code except for one backend-only definition.
BACKEND_ONLY_DEFS = {"money/currency.py": {"normalize_currency_code"}}
BACKEND_ONLY_IMPORTS = {
    "money/currency.py": {("typing", "Any", None), ("typing", "overload", None)},
}


def _py_files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*.py")}


def _strip_docstrings(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = node.body[1:] or [ast.Pass()]


def _as_backend_module(name: str) -> str:
    """Return a module name with the `common.audit` prefix written as `src.audit`."""
    if name == "common.audit" or name.startswith("common.audit."):
        return "src.audit" + name[len("common.audit") :]
    return name


def _normalized(
    path: Path, root: Path
) -> tuple[list[tuple[str, str, str | None]], list[ast.stmt]]:
    """Return the sorted top-level imports and the other top-level statements, as `src.audit` code.

    The two trees differ only by import prefix (`common.audit` or `src.audit`), relative
    imports, import ordering and docstring wording. The comparison removes those four.
    Only the module names of `import` statements are rewritten, never string constants.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = ".".join(("src.audit", *path.relative_to(root).parent.parts))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                alias.name = _as_backend_module(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = parts[: len(parts) - (node.level - 1)]
                node.module = ".".join([*base, *([node.module] if node.module else [])])
                node.level = 0
            if node.module:
                node.module = _as_backend_module(node.module)
    imports: list[tuple[str, str, str | None]] = []
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend((alias.name, "", alias.asname) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(
                (node.module or "", alias.name, alias.asname) for alias in node.names
            )
        else:
            body.append(node)
    module_tree = ast.Module(body=body, type_ignores=[])
    _strip_docstrings(module_tree)
    return sorted(imports, key=str), module_tree.body


def _strict_dump(path: Path) -> str:
    """Return the full AST dump, with docstrings and import order, as the former lock did.

    Only the module names of import statements change: `common.audit` and `src.audit`
    both become `audit`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in ("common.audit", "src.audit"):
                    if alias.name == prefix or alias.name.startswith(prefix + "."):
                        alias.name = "audit" + alias.name[len(prefix) :]
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("common.audit"):
                node.module = node.module.replace("common.audit", "audit", 1)
            elif node.module and node.module.startswith("src.audit"):
                node.module = node.module.replace("src.audit", "audit", 1)
            elif node.level == 2 and node.module == "ratio":
                node.module = "audit.ratio"
                node.level = 0
    return ast.dump(tree, include_attributes=False)


def _dump(body: list[ast.stmt]) -> str:
    return ast.dump(ast.Module(body=body, type_ignores=[]))


def _exports(path: Path) -> set[str]:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return {el.value for el in node.value.elts if isinstance(el, ast.Constant)}
    raise AssertionError(f"{path} has no __all__ list")


_COMMON = _py_files(COMMON_ROOT)
_BACKEND = _py_files(BACKEND_ROOT)
MIRRORED = sorted((_COMMON & _BACKEND) - set(SURFACE_MODULES) - set(BACKEND_ONLY_DEFS))


@ac_proof(
    proof_id="test_audit_mirror_inventory_is_complete",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
def test_AC_audit_43_1_every_module_is_mirrored_or_listed_with_a_reason():
    """AC-audit.43.1: a module that exists in one tree only appears in an explicit list."""
    assert MIRRORED, "no mirrored module found: the lock would compare nothing"
    common_unlisted = _COMMON - _BACKEND - set(COMMON_ONLY)
    backend_unlisted = _BACKEND - _COMMON - set(BACKEND_ONLY)
    stale_common_only = set(COMMON_ONLY) & _BACKEND
    stale_backend_only = set(BACKEND_ONLY) & _COMMON
    missing_common_only = set(COMMON_ONLY) - _COMMON
    missing_backend_only = set(BACKEND_ONLY) - _BACKEND

    assert sorted(common_unlisted) == [], (
        "mirror it in src/audit or list it in COMMON_ONLY"
    )
    assert sorted(backend_unlisted) == [], (
        "mirror it in common/audit or list it in BACKEND_ONLY"
    )
    assert sorted(stale_common_only | stale_backend_only) == [], (
        "listed module has a twin"
    )
    assert sorted(missing_common_only | missing_backend_only) == [], (
        "listed module is gone"
    )
    assert set(SURFACE_MODULES) <= _COMMON & _BACKEND
    assert set(BACKEND_ONLY_DEFS) <= _COMMON & _BACKEND


@ac_proof(
    proof_id="test_audit_mirrored_modules_are_ast_equal",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
@pytest.mark.parametrize("relative", MIRRORED)
def test_AC_audit_43_1_mirrored_modules_are_ast_equal(relative: str):
    """AC-audit.43.1: a mirrored module holds the same code in both trees."""
    common_imports, common_body = _normalized(COMMON_ROOT / relative, COMMON_ROOT)
    backend_imports, backend_body = _normalized(BACKEND_ROOT / relative, BACKEND_ROOT)

    assert common_imports == backend_imports
    assert _dump(common_body) == _dump(backend_body)


@ac_proof(
    proof_id="test_audit_mirror_differs_only_by_backend_only_definitions",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
@pytest.mark.parametrize("relative", sorted(BACKEND_ONLY_DEFS))
def test_AC_audit_43_1_backend_only_definition_is_the_only_difference(relative: str):
    """AC-audit.43.1: the listed backend-only definition is the whole difference of a twin."""
    common_imports, common_body = _normalized(COMMON_ROOT / relative, COMMON_ROOT)
    backend_imports, backend_body = _normalized(BACKEND_ROOT / relative, BACKEND_ROOT)
    allowed = BACKEND_ONLY_DEFS[relative]
    kept = [node for node in backend_body if getattr(node, "name", None) not in allowed]

    assert len(kept) < len(backend_body), (
        f"{allowed} is no longer defined in the backend"
    )
    assert _dump(common_body) == _dump(kept)
    assert set(backend_imports) - set(common_imports) == BACKEND_ONLY_IMPORTS[relative]
    assert set(common_imports) <= set(backend_imports)


@ac_proof(
    proof_id="test_audit_mirror_package_surfaces_agree",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
@pytest.mark.parametrize("relative", ("base/__init__.py", "extension/__init__.py"))
def test_AC_audit_43_1_package_surfaces_agree_except_listed_names(relative: str):
    """AC-audit.43.1: both trees publish the same names from the same modules, except the listed ones."""
    common_exports = _exports(COMMON_ROOT / relative)
    backend_exports = _exports(BACKEND_ROOT / relative)
    shared = common_exports - COMMON_ONLY_EXPORTS[relative]

    assert common_exports >= COMMON_ONLY_EXPORTS[relative]
    assert backend_exports >= BACKEND_ONLY_EXPORTS[relative]
    assert shared == backend_exports - BACKEND_ONLY_EXPORTS[relative]

    common_imports, _ = _normalized(COMMON_ROOT / relative, COMMON_ROOT)
    backend_imports, _ = _normalized(BACKEND_ROOT / relative, BACKEND_ROOT)
    assert [row for row in common_imports if row[1] in shared] == [
        row for row in backend_imports if row[1] in shared
    ]


@ac_proof(
    proof_id="test_audit_mirror_root_exposes_only_the_contract",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
def test_AC_audit_43_1_mirror_root_exposes_only_the_contract():
    """AC-audit.43.1: the mirror root publishes `CONTRACT` and no value type, so no import path forks."""
    assert _exports(COMMON_ROOT / "__init__.py") == {"CONTRACT"}


@ac_proof(
    proof_id="test_audit_mirror_normalizer_rewrites_imports_only",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
def test_AC_audit_43_1_normalizer_rewrites_import_names_and_not_string_constants(
    tmp_path: Path,
):
    """AC-audit.43.1: `X = "common.audit.money"` and `X = "src.audit.money"` are different code."""
    common_root = tmp_path / "common_audit"
    backend_root = tmp_path / "backend_audit"
    for root in (common_root, backend_root):
        root.mkdir()
    (common_root / "m.py").write_text(
        "from common.audit.money import Money\nX = 'common.audit.money'\n",
        encoding="utf-8",
    )
    (backend_root / "m.py").write_text(
        "from src.audit.money import Money\nX = 'src.audit.money'\n",
        encoding="utf-8",
    )
    (backend_root / "same.py").write_text(
        "from src.audit.money import Money\nX = 'common.audit.money'\n",
        encoding="utf-8",
    )

    common_imports, common_body = _normalized(common_root / "m.py", common_root)
    backend_imports, backend_body = _normalized(backend_root / "m.py", backend_root)
    same_imports, same_body = _normalized(backend_root / "same.py", backend_root)

    assert common_imports == backend_imports
    assert _dump(common_body) != _dump(backend_body)
    assert _dump(common_body) == _dump(same_body)


@ac_proof(
    proof_id="test_audit_mirror_trace_record_files_keep_docstrings_and_import_order",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
@pytest.mark.parametrize("relative", STRICT_FILES)
def test_AC_audit_43_1_trace_record_files_are_equal_with_docstrings_and_import_order(
    relative: str,
):
    """AC-audit.43.1: the four TraceRecord files stay identical down to docstrings and import order."""
    assert relative in MIRRORED

    assert _strict_dump(COMMON_ROOT / relative) == _strict_dump(BACKEND_ROOT / relative)


def _imported_modules(path: Path) -> set[str]:
    """Return every absolute module name that a file imports, with each `from` name joined."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _dotted(relative: str) -> str:
    parts = relative.removesuffix(".py").split("/")
    return ".".join(part for part in parts if part != "__init__")


def _closure_imports_sqlalchemy(relative: str, seen: set[str] | None = None) -> bool:
    """Tell whether a backend audit module reaches SQLAlchemy or `src.database` by its imports.

    The walk skips `src/audit/__init__.py`, which every `src.audit.*` import runs first.
    """
    seen = set() if seen is None else seen
    if relative in seen:
        return False
    seen.add(relative)
    for module in _imported_modules(BACKEND_ROOT / relative):
        if module.split(".")[0] == "sqlalchemy" or module.startswith("src.database"):
            return True
        if module.startswith("src.audit."):
            inner = module[len("src.audit.") :].replace(".", "/")
            for candidate in (f"{inner}.py", f"{inner}/__init__.py"):
                if (BACKEND_ROOT / candidate).is_file() and _closure_imports_sqlalchemy(
                    candidate, seen
                ):
                    return True
    return False


@ac_proof(
    proof_id="test_audit_mirror_backend_only_reasons_are_true",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
@pytest.mark.parametrize("relative", sorted(BACKEND_ONLY))
def test_AC_audit_43_1_backend_only_reason_matches_the_imports(relative: str):
    """AC-audit.43.1: a SQLALCHEMY module reaches SQLAlchemy; a NO_BARE_CONSUMER module does not need to."""
    kind, reason = BACKEND_ONLY[relative]

    assert kind in (SQLALCHEMY, NO_BARE_CONSUMER), reason
    if kind == SQLALCHEMY:
        assert _closure_imports_sqlalchemy(relative), (
            f"{relative} imports neither SQLAlchemy nor src.database: mirror it or relabel it"
        )
    else:
        assert not _closure_imports_sqlalchemy(relative), (
            f"{relative} reaches SQLAlchemy: label it SQLALCHEMY"
        )


@ac_proof(
    proof_id="test_audit_mirror_no_bare_consumer_imports_a_backend_only_module",
    ac_ids=["AC-audit.43.1"],
    ci_tier="pr_ci",
    issue="#2752",
)
def test_AC_audit_43_1_no_common_or_tools_file_imports_a_backend_only_module():
    """AC-audit.43.1: tooling under `common/` and `tools/` imports no backend-only audit module."""
    forbidden = {"src.audit"}
    forbidden.update(f"common.audit.{_dotted(relative)}" for relative in BACKEND_ONLY)

    hits_by_file: dict[str, list[str]] = {}
    for root in (REPO / "common", REPO / "tools"):
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(REPO)
            if relative.parts[:2] == ("common", "audit"):
                continue
            if path.name.startswith("test_") or "tests" in relative.parts:
                continue
            hits = sorted(
                module
                for module in _imported_modules(path)
                if any(
                    module == name or module.startswith(f"{name}.")
                    for name in forbidden
                )
            )
            if hits:
                hits_by_file[str(relative)] = hits

    unlisted = {
        rel: hits
        for rel, hits in hits_by_file.items()
        if rel not in BACKEND_RUN_CONSUMERS
    }
    assert unlisted == {}, (
        "a bare-Python consumer cannot import src.audit: mirror the module"
    )
    assert sorted(set(BACKEND_RUN_CONSUMERS) - set(hits_by_file)) == [], (
        "BACKEND_RUN_CONSUMERS lists a file that imports no backend-only module"
    )
