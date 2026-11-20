from __future__ import annotations

import ast
import inspect
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, status
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import AsyncClient

from src.deps import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from src.main import _resolve_app_version, app
from src.reporting import DEFAULT_INCLUDE_RESTRICTED, PACKAGE_INCLUDE_RESTRICTED

_BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"
_ROUTER_DIR = _BACKEND_SRC / "routers"
_UNTAGGED_UTILITY_PATHS = frozenset(
    {"/", "/livez", "/readyz", "/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
)
_api_routes = lambda: [c.route for c in iter_route_contexts(app.routes) if isinstance(c.route, APIRoute)]


def test_AC12_29_4_no_route_or_tag_collisions() -> None:
    routes, seen, collisions, untagged, multi_tagged = _api_routes(), {}, [], [], []
    for route in routes:
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            collisions.append(f"{method} {route.path}") if (method, route.path) in seen else None
            seen[(method, route.path)] = route.name
        if route.path not in _UNTAGGED_UTILITY_PATHS:
            tags = list(route.tags or [])
            untagged.append(route.path) if not tags else multi_tagged.append(route.path) if len(tags) > 1 else None
    tags_under = lambda p: {t for r in routes if r.path.startswith(p) for t in (r.tags or [])}
    assert not collisions and not untagged and not multi_tagged, (collisions, untagged, multi_tagged)
    assert (tags_under("/statements"), tags_under("/ai"), tags_under("/reconciliation"), tags_under("/pricing")) == (
        {"statements"},
        set(),
        {"reconciliation"},
        {"pricing"},
    )


def test_AC12_29_1_status_codes_use_constants_and_async_uses_202(openapi_schema: dict[str, Any]) -> None:
    raw_re = re.compile(r"status_code\s*=\s*\d")
    offenders = [
        f"{py.name}:{ln}"
        for py in sorted(_ROUTER_DIR.glob("*.py"))
        for ln, line in enumerate(py.read_text().splitlines(), 1)
        if raw_re.search(line)
    ]
    assert not offenders and "202" in openapi_schema["paths"]["/statements"]["post"]["responses"]


def test_AC12_29_6_verb_in_path_urls_renamed_to_resources(openapi_schema: dict[str, Any]) -> None:
    paths = set(openapi_schema["paths"])
    renamed = {
        "/reconciliation/run": "/reconciliation/runs",
        "/market-data/sync/fx": "/pricing/fx/syncs",
        "/market-data/sync/stocks": "/pricing/stocks/syncs",
        "/journal-entries/{entry_id}/post": "/journal-entries/{entry_id}/postings",
        "/journal-entries/{entry_id}/void": "/journal-entries/{entry_id}/voidings",
        "/statements/upload": "/statements",
        "/statements/{statement_id}/review/approve": "/statements/{statement_id}/approvals",
        "/statements/{statement_id}/review/reject": "/statements/{statement_id}/rejections",
        "/statements/{statement_id}/review/envelope": "/statements/{statement_id}/review-envelopes",
        "/statements/{statement_id}/brokerage/import": "/portfolio/brokerage-imports",
        "/portfolio/brokerage/import": "/portfolio/brokerage-imports",
        "/portfolio/prices/update": "/pricing/price-overrides",
        "/reports/package/generate": "/reports/package/snapshots",
        "/reports/export": "/reports/exports",
        "/reports/package/snapshots/{snapshot_id}/export": "/reports/package/snapshots/{snapshot_id}/exports",
        "/reconciliation/matches/{match_id}/accept": "/reconciliation/matches/{match_id}",
        "/reconciliation/matches/{match_id}/reject": "/reconciliation/matches/{match_id}",
        "/reconciliation/unmatched/{txn_id}/reviewed-disposition": "/reconciliation/unmatched/{txn_id}/reviewed-dispositions",
        "/reconciliation/adjustment": "/reconciliation/adjustments",
        "/chat/session/{session_id}": "/chat/sessions/{session_id}",
        "/statements/{statement_id}/conflicts/resolve": "/statements/{statement_id}/conflict-resolutions",
        "/statements/{statement_id}/stage2/run-checks": "/reconciliation/consistency-checks/runs",
        "/statements/consistency-checks/{check_id}/resolve": "/reconciliation/consistency-checks/{check_id}/resolutions",
    }
    assert "/reports/package/annual-archive" not in paths and all(
        old not in paths and new in paths for old, new in renamed.items()
    )


FINITE_COLLECTION_GET_PATHS = frozenset(
    {
        "/reports/currencies",
        "/pricing/market-data/status",
        "/pricing/valuation-components",
        "/statements/coverage",
        "/reports/account-lineage",
    }
)


def test_AC12_29_2_and_AC_platform_29_7_bounded_limits(openapi_schema: dict[str, Any]) -> None:
    paths = openapi_schema["paths"]
    schemas = openapi_schema.get("components", {}).get("schemas", {})
    for path in ("/reconciliation/transactions/{txn_id}/anomalies", "/reports/package/snapshots"):
        params = {p["name"]: p for p in paths[path]["get"].get("parameters", [])}
        assert (
            params["limit"]["schema"].get("maximum"),
            params["limit"]["schema"].get("minimum"),
            params["offset"]["schema"].get("minimum"),
        ) == (MAX_PAGE_LIMIT, 1, 0)

    unbounded: list[str] = []
    for path, item in sorted(paths.items()):
        get_op = item.get("get")
        if not get_op:
            continue
        params = {p["name"]: p for p in get_op.get("parameters", []) if p.get("in") == "query"}
        if "limit" in params:
            limit_schema = params["limit"].get("schema", {})
            if not isinstance(limit_schema.get("maximum"), int | float) or (limit_schema.get("minimum") or 0) < 1:
                unbounded.append(f"{path}: invalid limit bounds")
        resp_schema = (
            get_op.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})
        )
        ref_name = resp_schema.get("$ref", "").rsplit("/", 1)[-1] if "$ref" in resp_schema else ""
        props = set(schemas.get(ref_name, {}).get("properties", {}).keys()) if ref_name in schemas else set()
        is_collection = resp_schema.get("type") == "array" or bool(props & {"items", "sessions"})
        if is_collection and path not in FINITE_COLLECTION_GET_PATHS:
            if "limit" not in params or "offset" not in params:
                unbounded.append(f"{path}: missing limit/offset ({sorted(params)})")
            elif (params["offset"].get("schema", {}).get("minimum") is None) or (
                params["offset"]["schema"]["minimum"] < 0
            ):
                unbounded.append(f"{path}: missing offset minimum >= 0")

    assert unbounded == [], f"Unbounded or unpaginated collection GET endpoints: {unbounded}"

    slice_offenders: list[str] = []
    for py in sorted(_ROUTER_DIR.glob("*.py")):
        src_text = py.read_text(encoding="utf-8")
        tree = ast.parse(src_text, filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
                "_page_fields",
                "_paged_allocation",
            }:
                slice_offenders.append(f"{py.name}:{node.lineno} defines {node.name}")
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
                slice_src = ast.unparse(node.slice)
                if "offset" in slice_src or "limit" in slice_src:
                    slice_offenders.append(f"{py.name}:{node.lineno} slices by {slice_src}")
    assert slice_offenders == [], f"In-memory pagination helpers/slices forbidden in routers: {slice_offenders}"


async def test_collection_get_endpoints_push_limit_offset_to_sql(client: AsyncClient, db_engine) -> None:
    from sqlalchemy import event

    recorded: list[str] = []

    def _capture(_conn, _cursor, statement: str, *_args) -> None:
        recorded.append(statement)

    endpoints = (
        "/accounts?limit=2&offset=1",
        "/journal-entries?limit=2&offset=1",
        "/statements?limit=2&offset=1",
        "/statements/pending-review?limit=2&offset=1",
        "/reconciliation/matches?limit=2&offset=1",
        "/reconciliation/unmatched?limit=2&offset=1",
        "/reconciliation/consistency-checks?limit=2&offset=1",
        "/reports/package/snapshots?limit=2&offset=1",
        "/pricing/manual-valuations?limit=2&offset=1",
        "/chat/history?limit=2&offset=1",
    )
    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        missing_sql_pagination: list[str] = []
        for url in endpoints:
            recorded.clear()
            resp = await client.get(url)
            assert resp.status_code == 200, (url, resp.text)
            has_limit = any(re.search(r"\bLIMIT\b", sql, re.IGNORECASE) for sql in recorded)
            has_offset = any(re.search(r"\bOFFSET\b", sql, re.IGNORECASE) for sql in recorded)
            if not (has_limit and has_offset):
                missing_sql_pagination.append(f"{url}: limit={has_limit}, offset={has_offset}")
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    assert missing_sql_pagination == [], f"Collection endpoints missing SQL LIMIT/OFFSET: {missing_sql_pagination}"


_top_models = lambda path: {
    n.name
    for n in ast.parse(path.read_text(encoding="utf-8")).body
    if isinstance(n, ast.ClassDef)
    and any(
        (isinstance(b, ast.Name) and b.id == "BaseModel") or (isinstance(b, ast.Attribute) and b.attr == "BaseModel")
        for b in n.bases
    )
}


def test_AC_platform_29_8_delivery_helpers_have_one_honest_home() -> None:
    dishonest_re = re.compile(r"(?:DbSession|CurrentUserId)\s*=\s*None")
    dishonest, norm_defs, req_defs = [], [], []
    for path in sorted(_BACKEND_SRC.rglob("*.py")):
        rel, src = path.relative_to(_BACKEND_SRC).as_posix(), path.read_text(encoding="utf-8")
        dishonest.extend(f"{rel}:{src.count(chr(10), 0, m.start()) + 1}" for m in dishonest_re.finditer(src))
        for node in (
            ast.walk(ast.parse(src, filename=str(path))) if ("normalize_currency" in src or "request_id" in src) else ()
        ):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                norm_defs.append(
                    f"{rel}:{node.lineno}"
                ) if node.name == "normalize_currency" and rel != "schemas/base.py" else None
                req_defs.append(f"{rel}:{node.name}") if node.name in {
                    "_current_request_id",
                    "current_request_id",
                    "ensure_request_id",
                } else None
    assert (
        not (
            {n for p in sorted(_ROUTER_DIR.glob("*.py")) for n in _top_models(p)}
            & {n for p in sorted((_BACKEND_SRC / "schemas").glob("*.py")) for n in _top_models(p)}
        )
        and not dishonest
        and not norm_defs
    )
    assert req_defs == ["observability/audit.py:current_request_id", "observability/audit.py:ensure_request_id"]
    assert {
        r.path: r.endpoint.__module__ for r in _api_routes() if r.path in {"/livez", "/readyz", "/health"}
    } == dict.fromkeys(("/livez", "/readyz", "/health"), "infra2_sdk.fastapi")


def test_AC_platform_29_9_report_wire_shape_and_policy_are_single(openapi_schema: dict[str, Any]) -> None:
    paths = openapi_schema["paths"]
    gen = paths["/reports/package/snapshots"]["post"]
    body_ref = gen["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    assert (
        DEFAULT_INCLUDE_RESTRICTED is True
        and PACKAGE_INCLUDE_RESTRICTED is False
        and gen.get("parameters", []) == []
        and gen["requestBody"]["required"] is True
        and openapi_schema["components"]["schemas"][body_ref]["properties"]["include_restricted"].get("default") is None
    )
    for path, expected in [
        ("/pricing/valuation-components", True),
        ("/reports/balance-sheet", True),
        ("/reports/balance-sheet/diagnostics", True),
        ("/reports/exports", True),
        ("/reports/net-worth/allocation", True),
        ("/reports/net-worth/timeseries", True),
        ("/reports/package", False),
    ]:
        assert {i["name"]: i for i in paths[path]["get"]["parameters"]}["include_restricted"]["schema"][
            "default"
        ] is expected


async def test_AC12_29_3_pagination_convention_is_enforced(client: AsyncClient) -> None:
    assert (
        1 <= DEFAULT_PAGE_LIMIT <= MAX_PAGE_LIMIT
        and (await client.get("/reports/package/snapshots", params={"limit": 5, "offset": 0})).status_code
        == status.HTTP_200_OK
        and (await client.get("/reports/package/snapshots", params={"limit": MAX_PAGE_LIMIT + 1})).status_code == 422
    )


async def test_AC12_29_5_and_retired_routes_removed(client: AsyncClient, openapi_schema: dict[str, Any]) -> None:
    paths = openapi_schema["paths"]
    mock_only = (
        "/reports/trend",
        "/income/annualized",
        "/assets/restricted",
        "/portfolio/performance",
        "/reports/{report_type}/snapshots",
        "/statements/{statement_id}/review/edit",
        "/statements/{statement_id}/approve",
        "/statements/{statement_id}/reject",
        "/statements/{statement_id}/review/approve",
        "/statements/{statement_id}/review/reject",
    )
    retired_ops = (
        ("get", "/users"),
        ("get", "/users/{user_id}"),
        ("put", "/users/{user_id}"),
        ("delete", "/users/{user_id}"),
        ("get", "/assets/positions"),
        ("get", "/assets/positions/{position_id}"),
        ("post", "/assets/reconcile"),
        ("get", "/accounts/{account_id}"),
        ("get", "/corrections/stats"),
        ("get", "/notifications"),
        ("get", "/transactions/{transaction_id}/audit"),
        ("get", "/review/conflicts/{statement_id}"),
        ("post", "/review/conflicts/{statement_id}/resolve"),
        ("get", "/statements/consistency-checks/list"),
        ("post", "/reconciliation/batch-accept"),
        ("post", "/statements/batch-approve-matches"),
        ("post", "/statements/batch-reject-matches"),
    )
    required = (
        ("get", "/journal-entries/{entry_id}/audit"),
        ("get", "/statements/{statement_id}/conflicts"),
        ("post", "/statements/{statement_id}/conflict-resolutions"),
        ("get", "/reconciliation/consistency-checks"),
        ("post", "/reconciliation/matches"),
    )
    assert (
        not any(p in paths for p in mock_only)
        and not any(p.startswith("/classifications") for p in paths)
        and {"/statements/{statement_id}/approvals", "/statements/{statement_id}/rejections"} <= set(paths)
    )
    assert not [f"{m} {p}" for m, p in retired_ops if m in paths.get(p, {})] and all(
        m in paths.get(p, {}) for m, p in required
    )
    assert not [
        f"{p} ({seg})"
        for p in sorted(paths)
        for seg in p.strip("/").split("/")
        if not seg.startswith("{")
        and (
            seg in {"list", "session", "adjustment", "reviewed-disposition", "envelope"}
            or seg.startswith(("batch-", "get-", "create-", "update-", "delete-"))
        )
    ]

    uid = uuid4()
    for method, url, allowed, body in (
        ("POST", f"/statements/{uid}/approve", (404, 405), {"notes": ""}),
        ("POST", f"/statements/{uid}/reject", (404, 405), {"notes": ""}),
        ("POST", "/classifications/backfill", (404,), None),
        ("GET", "/users", (404,), None),
        ("GET", f"/users/{uid}", (404,), None),
        ("PUT", f"/users/{uid}", (404,), {}),
        ("DELETE", f"/users/{uid}", (404,), None),
        ("GET", "/assets/positions", (404,), None),
        ("GET", f"/assets/positions/{uid}", (404,), None),
        ("POST", "/assets/reconcile", (404,), None),
        ("GET", f"/accounts/{uid}", (404, 405), None),
        ("GET", "/corrections/stats", (404,), None),
        ("GET", "/notifications", (404,), None),
        ("GET", f"/transactions/{uid}/audit", (404,), None),
        ("GET", f"/review/conflicts/{uid}", (404,), None),
        ("POST", f"/review/conflicts/{uid}/resolve", (404,), None),
        ("GET", "/statements/consistency-checks/list", (404,), None),
        ("POST", "/reconciliation/batch-accept", (404,), None),
        ("POST", "/statements/batch-approve-matches", (404, 405), None),
        ("POST", "/statements/batch-reject-matches", (404, 405), None),
    ):
        assert (
            await client.request(method, url, **({"json": body} if body is not None else {}))
        ).status_code in allowed, (method, url)
    checks = await client.get("/reconciliation/consistency-checks")
    assert checks.status_code == status.HTTP_200_OK and "items" in checks.json()


_undocumented = lambda routes: [
    f"{c.route.path} ({c.route.endpoint.__name__})"
    for c in iter_route_contexts(routes)
    if isinstance(c.route, APIRoute)
    and c.route.endpoint.__module__ != "infra2_sdk.fastapi"
    and (
        not (inspect.getdoc(c.route.endpoint) or "").strip()
        or (inspect.getdoc(c.route.endpoint) or "").strip().endswith("..")
    )
]


def test_issue3014_routes_have_docstrings_and_app_version_reads_git_tag(
    tmp_path: Path, monkeypatch: Any, openapi_schema: dict[str, Any]
) -> None:
    probe = APIRouter()

    @probe.get("/probe-missing-docstring")
    async def no_doc_handler() -> dict[str, str]:
        return {"status": "ok"}

    assert _undocumented(app.routes) == [] and _undocumented(probe.routes) == [
        "/probe-missing-docstring (no_doc_handler)"
    ]
    main_src = (_BACKEND_SRC / "main.py").read_text(encoding="utf-8")
    assert (
        'version="0.1.0"' not in main_src
        and "version='0.1.0'" not in main_src
        and openapi_schema["info"]["version"] == app.version
    )
    git_bin = shutil.which("git")
    for args in (
        ("init",),
        ("config", "user.email", "test@example.com"),
        ("config", "user.name", "Test User"),
        ("commit", "--allow-empty", "-m", "init"),
        ("tag", "v0.2.99"),
    ):
        subprocess.run([git_bin, *args], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert _resolve_app_version(tmp_path) == "0.2.99"
    monkeypatch.setenv("APP_VERSION", "v9.8.7")
    assert _resolve_app_version() == "9.8.7"


def test_issue3123_domain_aligned_routes_and_router_boundaries(openapi_schema: dict[str, Any]) -> None:
    """#3123: fold evidence & app-config routers, unify brokerage-imports, and keep pricing router domain-pure."""
    paths = openapi_schema["paths"]

    # 1) evidence -> /statements/evidence-lineage
    assert not any(p.startswith("/evidence") for p in paths)
    assert "/statements/evidence-lineage" in paths
    assert "get" in paths["/statements/evidence-lineage"]
    assert paths["/statements/evidence-lineage"]["get"]["tags"] == ["statements"]

    # 2) app-config -> /users/me/settings/base-currency
    assert not any(p.startswith("/app-config") for p in paths)
    assert "/users/me/settings/base-currency" in paths
    assert set(paths["/users/me/settings/base-currency"].keys()) == {"get", "put"}
    assert paths["/users/me/settings/base-currency"]["get"]["tags"] == ["user-settings"]
    assert paths["/users/me/settings/base-currency"]["put"]["tags"] == ["user-settings"]

    # 3) unified brokerage-imports under /portfolio/brokerage-imports
    assert "/statements/{statement_id}/brokerage-imports" not in paths
    assert "/portfolio/brokerage-imports" in paths
    assert "post" in paths["/portfolio/brokerage-imports"]
    assert paths["/portfolio/brokerage-imports"]["post"]["tags"] == ["portfolio"]

    # 4) exact 11 domain router modules under src/routers
    router_modules = {path.stem for path in sorted(_ROUTER_DIR.glob("*.py")) if path.name != "__init__.py"}
    assert router_modules == {
        "accounts",
        "chat",
        "journal",
        "llm",
        "portfolio",
        "pricing",
        "reconciliation",
        "reports",
        "statements",
        "user_settings",
        "workflow",
    }

    # 5) routers stay decoupled from non-owning domain models & cross-domain internals
    def _find_forbidden_imports(router_name: str, forbidden_prefixes: tuple[str, ...]) -> list[str]:
        tree = ast.parse((_ROUTER_DIR / router_name).read_text(encoding="utf-8"))
        leaks: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                targets = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
                if any(
                    target == prefix or target.startswith(f"{prefix}.")
                    for target in targets
                    for prefix in forbidden_prefixes
                ):
                    leaks.append(f"line {node.lineno}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name == p or alias.name.startswith(f"{p}.") for p in forbidden_prefixes):
                        leaks.append(f"line {node.lineno}: import {alias.name}")
        return leaks

    pricing_leaks = _find_forbidden_imports("pricing.py", ("src.extraction", "src.portfolio", "src.reporting"))
    assert pricing_leaks == [], f"routers/pricing.py leaks cross-domain imports: {pricing_leaks}"

    reconciliation_leaks = _find_forbidden_imports("reconciliation.py", ("src.extraction", "src.ledger"))
    assert reconciliation_leaks == [], f"routers/reconciliation.py leaks cross-domain imports: {reconciliation_leaks}"

    reports_leaks = _find_forbidden_imports("reports.py", ("src.pricing.FxRate",))
    assert reports_leaks == [], f"routers/reports.py leaks cross-domain ORM imports: {reports_leaks}"

    statements_leaks = _find_forbidden_imports("statements.py", ("src.ledger.Account",))
    assert statements_leaks == [], f"routers/statements.py leaks cross-domain ORM imports: {statements_leaks}"
