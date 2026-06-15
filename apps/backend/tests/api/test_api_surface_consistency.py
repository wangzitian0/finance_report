"""API-surface consistency sweep (#1099, EPIC-012 AC12.29).

A follow-up to the typed-contract sweep (#1074 → AC12.27/AC12.28): the public API
surface must stay internally consistent so the generated frontend client (#1004)
is built on clean, unambiguous foundations.

PR1 of the sweep (this file's AC12.29.4/.5):
- AC12.29.4 — no route collisions; every operation maps to exactly one OpenAPI tag,
  so each operation lands in exactly one generated FE client module. The
  ``/statements`` and ``/ai`` URL prefixes are deliberately shared by two routers
  each, but those routers carry *distinct* tags (``statements`` vs ``review``,
  ``ai`` vs ``ai-feedback``) — that is the documented disambiguation.
- AC12.29.5 — the long-deprecated ``POST /statements/{id}/approve`` and ``/reject``
  are gone; the ``/statements/{id}/review/*`` variants are the supported path.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import status
from fastapi.routing import APIRoute
from httpx import AsyncClient

from src.deps import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from src.main import app

# The list endpoints #1099 named as unbounded; each must now accept bounded
# limit/offset (AC12.29.2).
_PREVIOUSLY_UNBOUNDED_LIST_PATHS = (
    "/assets/restricted",
    "/reconciliation/transactions/{txn_id}/anomalies",
    "/reports/package/snapshots",
)

# Utility/infra routes that are intentionally untagged (excluded from the
# one-tag-per-operation contract because they are not part of any FE module).
_UNTAGGED_UTILITY_PATHS = frozenset(
    {
        "/",
        "/health",
        "/ping",
        "/ping/toggle",
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
)


def _api_routes() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def test_AC12_29_4_no_route_or_tag_collisions() -> None:
    """AC12.29.4: no two operations share a (method, path), and every business
    operation maps to exactly one OpenAPI tag.

    The single-tag invariant is what keeps the generated FE client modular: a tool
    like openapi-typescript-codegen groups operations into one service module per
    tag, so an operation with zero or multiple tags lands in zero or multiple
    modules. The deliberately shared ``/statements`` and ``/ai`` prefixes must
    therefore still resolve to one coherent tag per operation.
    """
    routes = _api_routes()

    # (1) No real route shadowing: each (HTTP method, path) pair is unique.
    seen: dict[tuple[str, str], str] = {}
    collisions: list[str] = []
    for route in routes:
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            key = (method, route.path)
            if key in seen:
                collisions.append(f"{method} {route.path} (defined by {seen[key]} and {route.name})")
            else:
                seen[key] = route.name
    assert not collisions, f"duplicate (method, path) routes: {collisions}"

    # (2) Every business operation carries exactly one tag.
    untagged: list[str] = []
    multi_tagged: list[str] = []
    for route in routes:
        if route.path in _UNTAGGED_UTILITY_PATHS:
            continue
        tags = list(route.tags or [])
        if len(tags) == 0:
            untagged.append(f"{sorted(route.methods)} {route.path}")
        elif len(tags) > 1:
            multi_tagged.append(f"{sorted(route.methods)} {route.path} -> {tags}")
    assert not untagged, f"operations with no OpenAPI tag (would be ungrouped in the FE client): {untagged}"
    assert not multi_tagged, f"operations spanning multiple tags (would duplicate across FE modules): {multi_tagged}"

    # (3) The intentionally shared URL prefixes resolve to distinct tags so the
    #     generated client keeps them in separate, coherent modules.
    def _tags_under_prefix(prefix: str) -> set[str]:
        out: set[str] = set()
        for route in routes:
            if route.path.startswith(prefix):
                out.update(route.tags or [])
        return out

    assert {"statements", "review"} <= _tags_under_prefix("/statements")
    assert {"ai", "ai-feedback"} <= _tags_under_prefix("/ai")


def test_AC12_29_2_named_unbounded_endpoints_are_bounded() -> None:
    """AC12.29.2: the three named unbounded list endpoints now accept bounded
    ``limit``/``offset`` query params, with ``limit`` capped at ``MAX_PAGE_LIMIT``."""
    paths = app.openapi()["paths"]

    for path in _PREVIOUSLY_UNBOUNDED_LIST_PATHS:
        assert path in paths, f"{path} missing from OpenAPI"
        params = {p["name"]: p for p in paths[path]["get"].get("parameters", [])}

        assert "limit" in params, f"{path} GET has no `limit` query param"
        assert "offset" in params, f"{path} GET has no `offset` query param"

        limit_schema = params["limit"]["schema"]
        assert limit_schema.get("maximum") == MAX_PAGE_LIMIT, (
            f"{path} `limit` is not capped at MAX_PAGE_LIMIT ({MAX_PAGE_LIMIT}): {limit_schema}"
        )
        assert limit_schema.get("minimum") == 1
        assert params["offset"]["schema"].get("minimum") == 0


async def test_AC12_29_3_pagination_convention_is_enforced(client: AsyncClient) -> None:
    """AC12.29.3: a single documented pagination convention exists and the shared
    dependency rejects an over-max ``limit`` with 422."""
    assert isinstance(DEFAULT_PAGE_LIMIT, int)
    assert isinstance(MAX_PAGE_LIMIT, int)
    assert 1 <= DEFAULT_PAGE_LIMIT <= MAX_PAGE_LIMIT

    # A valid bounded request is accepted...
    ok = await client.get("/reports/package/snapshots", params={"limit": 5, "offset": 0})
    assert ok.status_code == status.HTTP_200_OK

    # ...and a request above the documented hard maximum is rejected by the
    # shared PaginationParams bound, not silently clamped.
    too_big = await client.get("/reports/package/snapshots", params={"limit": MAX_PAGE_LIMIT + 1})
    assert too_big.status_code == 422


async def test_AC12_29_5_deprecated_statement_decision_endpoints_removed(client: AsyncClient) -> None:
    """AC12.29.5: the deprecated Stage-0 ``/approve`` and ``/reject`` statement
    decision endpoints are removed; the ``/review/*`` variants remain.

    Asserts both the routing layer (the endpoints no longer respond, returning
    404/405 rather than a real status) and the OpenAPI schema (the Stage-1
    replacements are still declared), so a route that exists but is hidden from the
    schema cannot pass silently.
    """
    sid = uuid4()

    # Routing layer: the removed endpoints no longer resolve. POSTing returns 404
    # (no such path) or 405 (method not allowed) — never an authenticated 2xx/4xx
    # from the handler that used to live here.
    for removed in (f"/statements/{sid}/approve", f"/statements/{sid}/reject"):
        response = await client.post(removed, json={"notes": ""})
        assert response.status_code in (404, 405), f"{removed} still resolves: {response.status_code}"

    # OpenAPI schema: removed paths gone, Stage-1 replacements still declared.
    paths = set(app.openapi()["paths"])
    assert "/statements/{statement_id}/approve" not in paths
    assert "/statements/{statement_id}/reject" not in paths
    assert "/statements/{statement_id}/review/approve" in paths
    assert "/statements/{statement_id}/review/reject" in paths
