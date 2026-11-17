"""Structural contract ratchet for FastAPI API route modules."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
ROUTER_DIR = _SRC_DIR / "routers"
API_ROUTER_DIRS = (
    ROUTER_DIR,
    _SRC_DIR / "identity" / "extension" / "api",
)
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
_RW_SESSIONS = frozenset({"DbSession", "Ctx"})
_FORBIDDEN_HELPER_CALLS = frozenset(
    {
        "get_owned_or_404",
        "raise_bad_request",
        "raise_conflict",
        "raise_gateway_timeout",
        "raise_internal_error",
        "raise_not_found",
        "raise_service_unavailable",
        "raise_too_large",
        "raise_too_many_requests",
        "raise_unauthorized",
    }
)
_TRANSLATED_DOMAIN_EXCEPTIONS = frozenset(
    {
        "AccountingError",
        "AccountNotFoundError",
        "AccountServiceError",
        "AIAdvisorError",
        "DecisionAnchorError",
        "HintsNotApplicable",
        "InvestmentAccountingError",
        "InvestmentAccountingValidationError",
        "LLMConfigError",
        "PackageDocumentVersionError",
        "PortfolioError",
        "PositionServiceError",
        "PricingError",
        "ReconciliationError",
        "ReportError",
        "ReviewedDispositionError",
        "StatementStatusChanged",
        "SuggestionCorrectionError",
        "ValuationServiceError",
    }
)
_ALLOWED_TX_ROUTER_FUNCTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("auth.py", "register"),
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


def _handler_re_raises_only(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(stmt, ast.Raise) and stmt.exc is None for stmt in ast.walk(handler))


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
                    if isinstance(sub, ast.ExceptHandler) and sub.type is not None:
                        exc_src = ast.unparse(sub.type)
                        if "ValueError" in exc_src:
                            violations.add("except_value_error")
                        if any(tok in exc_src for tok in _TRANSLATED_DOMAIN_EXCEPTIONS) and not _handler_re_raises_only(
                            sub
                        ):
                            for inner in ast.walk(sub):
                                if isinstance(inner, ast.Raise) and inner.exc is not None:
                                    violations.add("except_domain_translation")
            if (name, node.name) not in _ALLOWED_TX_ROUTER_FUNCTIONS:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        if (
                            sub.func.attr in {"commit", "rollback"}
                            and isinstance(sub.func.value, ast.Name)
                            and sub.func.value.id == "db"
                        ):
                            violations.add("manual_tx")
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Name) and node.func.id == "HTTPException") or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "HTTPException"
            ):
                violations.add("http_exception")
            func_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
            )
            if func_name in _FORBIDDEN_HELPER_CALLS:
                violations.add("legacy_http_helper")
    return violations


def _all_router_violations() -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for directory in API_ROUTER_DIRS:
        for path in sorted(directory.glob("*.py")):
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
