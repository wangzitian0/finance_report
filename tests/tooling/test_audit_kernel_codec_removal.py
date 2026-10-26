"""Audit kernel guards for the wire-codec removal (#2698, part of #2680).

Python has no wire or DB codecs for the value types: no production code called them.
Two guards hold that state:

1. A deleted function, method or alias must not return to either kernel tree.
2. Every mirrored file edited by the removal must stay AST-equal across both trees.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
COMMON_ROOT = REPO / "common/audit"
BACKEND_ROOT = REPO / "apps/backend/src/audit"

WIRE_FUNCTIONS = (
    "money_to_wire",
    "money_from_wire",
    "money_to_db_fields",
    "money_from_db_fields",
    "exchange_rate_to_wire",
    "exchange_rate_from_wire",
    "exchange_rate_to_db_fields",
    "exchange_rate_from_db_fields",
    "quantity_to_wire",
    "quantity_from_wire",
    "quantity_to_db_fields",
    "quantity_from_db_fields",
    "ratio_to_wire",
    "ratio_from_wire",
    "ratio_to_db_value",
    "ratio_from_db_value",
    "unit_price_to_wire",
    "unit_price_from_wire",
    "unit_price_to_db_fields",
    "unit_price_from_db_fields",
)
WIRE_TYPE_ALIASES = (
    "MoneyWire",
    "ExchangeRateWire",
    "MoneyDbFields",
    "ExchangeRateDbFields",
    "QuantityWire",
    "QuantityDbFields",
    "UnitPriceWire",
    "UnitPriceDbFields",
)
OTHER_DELETED_NAMES = (
    "WireCodec",
    "decimal_to_wire",
    "restate",
    "restate_unrounded",
    "is_multi_currency",
    "to_jsonb",
    "parent_manifest_digest",
    "read_all",
    "_RateInput",
)
DELETED_NAMES = frozenset(WIRE_FUNCTIONS + WIRE_TYPE_ALIASES + OTHER_DELETED_NAMES)
WIRE_PACKAGES = ("money", "quantity", "ratio", "unit_price")

# Mirrored files edited by the removal. `money/currency.py` is absent on purpose:
# `normalize_currency_code` exists only in the backend tree.
EDITED_MIRRORS = (
    "decimal_scalar.py",
    "base/trace.py",
    "extension/trace_adapters.py",
    "money/__init__.py",
    "money/balances.py",
    "money/exchange_rate.py",
    "quantity/__init__.py",
    "ratio/__init__.py",
    "unit_price/__init__.py",
    "unit_price/unit_price.py",
)


def _tree_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _bound_names(path: Path) -> set[str]:
    """Names a module defines or exports: def, class, assignment, import alias, `__all__` entry."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                    if target.id == "__all__" and isinstance(
                        node.value, (ast.List, ast.Tuple)
                    ):
                        names.update(
                            el.value
                            for el in node.value.elts
                            if isinstance(el, ast.Constant)
                        )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


@ac_proof(
    proof_id="test_audit_kernel_has_no_python_wire_codecs",
    ac_ids=["AC-audit.31.4"],
    ci_tier="pr_ci",
    issue="#2698",
)
@pytest.mark.parametrize("root", (COMMON_ROOT, BACKEND_ROOT), ids=("common", "backend"))
def test_AC_audit_31_4_deleted_wire_codecs_do_not_return(root: Path):
    """AC-audit.31.4: no wire module, wire function or test-only helper returns to a kernel tree."""
    assert root.is_dir(), f"{root} must exist"

    wire_modules = [root / pkg / "wire.py" for pkg in WIRE_PACKAGES]
    assert [str(p.relative_to(REPO)) for p in wire_modules if p.exists()] == []

    found = {
        str(path.relative_to(REPO)): sorted(_bound_names(path) & DELETED_NAMES)
        for path in _tree_files(root)
    }
    assert {rel: names for rel, names in found.items() if names} == {}


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
) -> tuple[list[tuple[str, str, str | None]], str]:
    """Return the sorted top-level imports and the AST dump of the rest, as `src.audit` code.

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
    tree.body = body
    _strip_docstrings(tree)
    return sorted(imports, key=str), ast.dump(tree)


@ac_proof(
    proof_id="test_audit_kernel_edited_mirrors_are_ast_equal",
    ac_ids=["AC-audit.36.2"],
    ci_tier="pr_ci",
    issue="#2698",
)
@pytest.mark.parametrize("relative", EDITED_MIRRORS)
def test_AC_audit_36_2_edited_kernel_mirrors_are_ast_equal(relative: str):
    """AC-audit.36.2: a file edited by the codec removal has the same code in both trees."""
    common = COMMON_ROOT / relative
    backend = BACKEND_ROOT / relative

    assert _normalized(common, COMMON_ROOT) == _normalized(backend, BACKEND_ROOT)
