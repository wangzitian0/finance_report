"""Mirror lock for the audit value kernel (#2752, part of #2680).

`apps/backend/src/audit` is the one editable source. `common/audit` is a mirror that
bare-Python tooling imports: those CI jobs install neither the backend nor SQLAlchemy.
Every Python module under `common/audit` must hold the same code as its twin under
`apps/backend/src/audit`, except the modules and names that this file lists with a reason.
The comparison removes docstrings, import order and import style, which the two trees
format differently (ruff line length 120 and 88).
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

# Modules in `apps/backend/src/audit` with no twin. Each one needs SQLAlchemy, the ledger
# source types or the promotion policy, so the stdlib-only mirror cannot hold it.
BACKEND_ONLY = {
    "base/promotion.py": "promotion policy types",
    "base/terminal_audit.py": "terminal audit spec",
    "data/__init__.py": "confidence projection package",
    "data/trace_confidence.py": "confidence projection",
    "extension/promotion.py": "promotion evaluation",
    "extension/terminal_audit.py": "terminal audit verifier",
    "extension/trace_decision_projection.py": "SQLAlchemy decision projection",
    "extension/trace_emitter.py": "emitter on the SQL repository",
    "extension/trace_repository.py": "SQLAlchemy repository",
    "money/adopt.py": "backend money adoption helpers",
    "orm/__init__.py": "ORM package",
    "orm/trace_record.py": "ORM rows and triggers",
    "promotion/__init__.py": "promotion package",
    "source_type_priority.py": "ledger source type priority",
}

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


def _normalized(
    path: Path, root: Path
) -> tuple[list[tuple[str, str, str | None]], list[ast.stmt]]:
    """Return the sorted top-level imports and the other top-level statements, as `src.audit` code.

    The two trees differ only by import prefix (`common.audit` or `src.audit`), relative
    imports, import ordering and docstring wording. The comparison removes those four.
    """
    tree = ast.parse(
        path.read_text(encoding="utf-8").replace("common.audit", "src.audit")
    )
    package = ".".join(("src.audit", *path.relative_to(root).parent.parts))
    imports: list[tuple[str, str, str | None]] = []
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend((alias.name, "", alias.asname) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            parts = package.split(".")
            base = parts[: len(parts) - (node.level - 1)] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            imports.extend((module, alias.name, alias.asname) for alias in node.names)
        else:
            body.append(node)
    module_tree = ast.Module(body=body, type_ignores=[])
    _strip_docstrings(module_tree)
    return sorted(imports, key=str), module_tree.body


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
