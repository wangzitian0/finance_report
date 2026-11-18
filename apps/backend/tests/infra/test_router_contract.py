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
_UNAUTHENTICATED_DB_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("auth.py", "register"),
        ("auth.py", "login"),
        ("reports.py", "get_available_currencies"),
    }
)
_STATELESS_AUTH_ROUTES: frozenset[tuple[str, str]] = frozenset({("llm.py", "get_config_status")})
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
                annos = {
                    ast.unparse(arg.annotation)
                    for arg in [*node.args.args, *node.args.kwonlyargs]
                    if arg.annotation is not None
                }
                if (name, node.name) not in _UNAUTHENTICATED_DB_ROUTES and (
                    ("DbSession" in annos or "ReadDbSession" in annos)
                    or (
                        "CurrentUserId" in annos
                        and "Ctx" not in annos
                        and "ReadCtx" not in annos
                        and (name, node.name) not in _STATELESS_AUTH_ROUTES
                    )
                ):
                    violations.add("legacy_db_route_param")
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


_NON_DOMAIN_PACKAGE_DIRS = frozenset({"routers", "__pycache__"})


@pytest.mark.no_db
def test_domain_packages_do_not_import_config_app() -> None:
    """AC-platform.router-contract.3: keep domain packages free of src.config_app imports."""
    violators: list[str] = []
    discovered_dirs = tuple(
        sorted(
            p.name
            for p in _SRC_DIR.iterdir()
            if p.is_dir() and p.name not in _NON_DOMAIN_PACKAGE_DIRS and not p.name.startswith(".")
        )
    )
    for pkg in discovered_dirs:
        pkg_dir = _SRC_DIR / pkg
        for path in sorted(pkg_dir.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    imports_config_app = (
                        mod.startswith("src.config_app")
                        or (mod == "src" and any(a.name == "config_app" for a in node.names))
                        or (node.level > 0 and (mod == "config_app" or mod.startswith("config_app.") or any(a.name == "config_app" for a in node.names)))
                    )
                    if imports_config_app:
                        violators.append(f"{path.relative_to(_SRC_DIR)}:{node.lineno}")
                elif isinstance(node, ast.Import) and any(
                    alias.name == "src.config_app" or alias.name.startswith("src.config_app.")
                    for alias in node.names
                ):
                    violators.append(f"{path.relative_to(_SRC_DIR)}:{node.lineno}")
    assert violators == [], f"Unexpected src.config_app imports in domain packages: {violators}"
