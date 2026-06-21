"""EPIC-007 AC7.17.1: the deploy-smoke gate asserts only real public routes.

`tools/_lib/shell/smoke_test.sh` runs in the staging / PR-preview health gate.
Every page route it asserts via ``check_endpoint "...Page" "$BASE_URL/<route>"``
must map to a real, public Next.js route under ``apps/frontend/src/app``. A check
for a non-existent path (e.g. the legacy ``/dashboard``, which 404s) makes the
gate flap or pass for the wrong reason.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE = REPO_ROOT / "tools" / "_lib" / "shell" / "smoke_test.sh"
APP_DIR = REPO_ROOT / "apps" / "frontend" / "src" / "app"


def _frontend_page_routes() -> set[str]:
    """Real URL paths that have a Next.js ``page.tsx``.

    Route-group folders ``(group)`` contribute no URL segment; dynamic segments
    ``[param]`` are skipped (not directly smoke-checkable without an id).
    """
    routes: set[str] = set()
    for page in APP_DIR.rglob("page.tsx"):
        rel = page.relative_to(APP_DIR).parent
        segments: list[str] = []
        skip = False
        for part in rel.parts:
            if part.startswith("(") and part.endswith(")"):
                continue  # route group: no URL segment
            if part.startswith("[") and part.endswith("]"):
                skip = True  # dynamic route: not a fixed smoke target
                break
            segments.append(part)
        if skip:
            continue
        routes.add("/" + "/".join(segments) if segments else "/")
    return routes


def _smoke_asserted_page_routes() -> list[str]:
    """Frontend page paths asserted by ``check_endpoint "<name>" "$BASE_URL/<path>"``.

    Captures every ``check_endpoint`` whose URL is a page path on ``$BASE_URL``
    (i.e. not an ``/api/...`` endpoint), regardless of the human label, so a
    mislabeled broken route (e.g. ``"Dashboard"`` -> ``/dashboard``) is caught.
    """
    text = SMOKE.read_text(encoding="utf-8")
    routes: list[str] = []
    pattern = re.compile(r'check_endpoint\s+"[^"]*"\s+"\$\{?BASE_URL\}?(/[^"\s]*)"')
    for match in pattern.finditer(text):
        path = match.group(1)
        if path.startswith("/api/"):
            continue
        routes.append(path.rstrip("/") or "/")
    return routes


def test_AC7_17_1_smoke_asserts_only_existing_public_frontend_routes() -> None:
    real_routes = {r.rstrip("/") or "/" for r in _frontend_page_routes()}
    asserted = _smoke_asserted_page_routes()
    assert asserted, (
        "smoke_test.sh should still assert at least one frontend page route"
    )
    missing = [r for r in asserted if (r.rstrip("/") or "/") not in real_routes]
    assert not missing, (
        "smoke_test.sh asserts page routes that do not exist under "
        f"apps/frontend/src/app: {missing}. Existing routes: {sorted(real_routes)}"
    )


def test_AC7_17_1_smoke_does_not_assert_nonexistent_dashboard_route() -> None:
    asserted = {r.rstrip("/") or "/" for r in _smoke_asserted_page_routes()}
    assert "/dashboard" not in asserted, (
        "smoke_test.sh must not assert /dashboard — there is no "
        "apps/frontend/src/app/.../dashboard/page.tsx, so it 404s"
    )
