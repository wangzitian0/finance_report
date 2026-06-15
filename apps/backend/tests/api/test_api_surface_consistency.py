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

from fastapi.routing import APIRoute

from src.main import app

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


def test_AC12_29_5_deprecated_statement_decision_endpoints_removed() -> None:
    """AC12.29.5: the deprecated Stage-0 ``/approve`` and ``/reject`` statement
    decision endpoints are removed; the ``/review/*`` variants remain."""
    paths = set(app.openapi()["paths"])

    assert "/statements/{statement_id}/approve" not in paths
    assert "/statements/{statement_id}/reject" not in paths

    # The supported Stage-1 review variants must still exist.
    assert "/statements/{statement_id}/review/approve" in paths
    assert "/statements/{statement_id}/review/reject" in paths
