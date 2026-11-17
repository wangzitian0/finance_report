"""Structural contract ratchet for FastAPI routers under apps/backend/src/routers/."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROUTER_DIR = Path(__file__).resolve().parents[2] / "src" / "routers"
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
_RW_SESSIONS = frozenset({"DbSession", "Ctx"})
_DISALLOWED_HTTP_STATUS_TOKENS = (
    "400",
    "404",
    "409",
    "HTTP_400_BAD_REQUEST",
    "HTTP_404_NOT_FOUND",
    "HTTP_409_CONFLICT",
)
_ALLOWED_TX_ROUTER_FUNCTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("statements.py", "_queue_statement_reparse"),
        ("statements.py", "_queue_classify_run"),
        ("statements.py", "upload_statement"),
    }
)

# Shrink-only allowlist of remaining legacy router violations.
# Each cleanup PR deletes fixed entries until this mapping is empty.
LEGACY_ROUTER_ALLOWLIST: dict[str, set[str]] = {}


def _route_methods(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    methods: set[str] = set()
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in _HTTP_METHODS:
            methods.add(dec.func.attr)
    return methods


def _scan_router_violations(path: Path) -> set[str]:
    name = path.name
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods = _route_methods(node)
            if "get" in methods:
                for arg in [*node.args.args, *node.args.kwonlyargs]:
                    if arg.annotation is not None and ast.unparse(arg.annotation) in _RW_SESSIONS:
                        violations.add("get_dbsession")
            if methods:
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.ExceptHandler)
                        and sub.type is not None
                        and "ValueError" in ast.unparse(sub.type)
                    ):
                        violations.add("except_value_error")
            if (name, node.name) not in _ALLOWED_TX_ROUTER_FUNCTIONS:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        if (
                            sub.func.attr in {"commit", "rollback"}
                            and isinstance(sub.func.value, ast.Name)
                            and sub.func.value.id == "db"
                        ):
                            violations.add("manual_tx")
        if isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == "HTTPException")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "HTTPException")
        ):
            call_src = ast.unparse(node)
            if any(tok in call_src for tok in _DISALLOWED_HTTP_STATUS_TOKENS):
                violations.add("http_exception")
    return violations


def _all_router_violations() -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for path in sorted(ROUTER_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        found = _scan_router_violations(path)
        if found:
            result[path.name] = found
    return result


@pytest.mark.no_db
def test_routers_have_no_unallowlisted_legacy_patterns() -> None:
    """AC-platform.router-contract.1: reject unallowlisted router violations."""
    actual = _all_router_violations()
    unexpected = {
        name: sorted(rules - LEGACY_ROUTER_ALLOWLIST.get(name, set()))
        for name, rules in actual.items()
        if rules - LEGACY_ROUTER_ALLOWLIST.get(name, set())
    }
    assert unexpected == {}, f"Unexpected legacy router violations: {unexpected}"


@pytest.mark.no_db
def test_legacy_router_allowlist_has_no_stale_entries() -> None:
    """AC-platform.router-contract.2: require allowlist entries to shrink as violations are fixed."""
    actual = _all_router_violations()
    stale = {
        name: sorted(rules - actual.get(name, set()))
        for name, rules in LEGACY_ROUTER_ALLOWLIST.items()
        if rules - actual.get(name, set())
    }
    assert stale == {}, f"Stale entries in LEGACY_ROUTER_ALLOWLIST (remove fixed items): {stale}"
