"""Audit kernel guards for the dead-code removal (#2698 and #2752, part of #2680).

Python has no wire or DB codecs for the value types, and no kernel helper without a
production caller: no production code called them. One guard holds that state: a deleted
function, method, class or alias must not return to either kernel tree. The mirror lock
that keeps the two trees equal is `test_audit_mirror_lock.py`.
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
    # #2752: no production caller outside the kernel trees and their tests.
    "InvalidMoneyPayloadError",
    "InvalidQuantityPayloadError",
    "InvalidRatioPayloadError",
    "InvalidUnitPricePayloadError",
    "MoneyTolerance",
    "fraction_or_none",
    "JsonlTraceRecordStore",
    "_decode_jsonl",
)
DELETED_NAMES = frozenset(WIRE_FUNCTIONS + WIRE_TYPE_ALIASES + OTHER_DELETED_NAMES)
WIRE_PACKAGES = ("money", "quantity", "ratio", "unit_price")
DELETED_MODULES = ("money/tolerance.py",)


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
    """AC-audit.31.4: no wire module, wire function or caller-less helper returns to a kernel tree."""
    assert root.is_dir(), f"{root} must exist"

    deleted_modules = [root / pkg / "wire.py" for pkg in WIRE_PACKAGES]
    deleted_modules += [root / relative for relative in DELETED_MODULES]
    assert [str(p.relative_to(REPO)) for p in deleted_modules if p.exists()] == []

    found = {
        str(path.relative_to(REPO)): sorted(_bound_names(path) & DELETED_NAMES)
        for path in _tree_files(root)
    }
    assert {rel: names for rel, names in found.items() if names} == {}
