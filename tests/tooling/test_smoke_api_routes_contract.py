"""AC-runtime.smoke-routes.1: the deployed-URL probes call only routes of the app (#3062).

Neighbour of ``test_smoke_routes_contract.py``, which guards the page routes.
The route list is ``apps/frontend/openapi.json``. The gate
``tools/generate_openapi_spec.py --check`` keeps that file equal to the app.
The app serves its routes under ``/api``. The Swagger page ``/api/docs`` is not an
OpenAPI path, so it is the only extra route.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "common" / "runtime" / "shell" / "smoke_test.sh"
TIER2 = ROOT / "common" / "runtime" / "tier2_http_e2e.py"
OPENAPI = ROOT / "apps" / "frontend" / "openapi.json"

API_PREFIX = "/api"
EXTRA_ROUTES = {"/api/docs"}
SHELL_URL = re.compile(r"\$\{?BASE_URL\}?(/api(?:/[^\"\s?]*)?)")
PYTHON_URL = re.compile(r"^/?(api(?:/[^\s?]*)?)$")


def _app_routes() -> set[str]:
    paths = json.loads(OPENAPI.read_text(encoding="utf-8"))["paths"]
    return {API_PREFIX + path for path in paths} | EXTRA_ROUTES


def _shell_api_urls(text: str) -> list[str]:
    return SHELL_URL.findall(text)


def _python_api_urls(text: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            match = PYTHON_URL.match(node.value)
            if match:
                found.append("/" + match.group(1))
    return found


def _unknown(urls: list[str], routes: set[str]) -> list[str]:
    patterns = [
        re.compile("^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(route)) + "/?$")
        for route in routes
    ]
    return sorted({url for url in urls if not any(p.match(url) for p in patterns)})


def test_AC_runtime_smoke_routes_1_every_api_url_in_the_deployed_probes_is_an_app_route() -> (
    None
):
    "AC-runtime.smoke-routes.1"
    routes = _app_routes()
    probes = {
        SMOKE: _shell_api_urls(SMOKE.read_text(encoding="utf-8")),
        TIER2: _python_api_urls(TIER2.read_text(encoding="utf-8")),
    }
    unknown = {
        str(path.relative_to(ROOT)): _unknown(urls, routes)
        for path, urls in probes.items()
        if _unknown(urls, routes)
    }
    assert not unknown, (
        f"these probes call routes that the app does not serve: {unknown}"
    )


def test_AC_runtime_smoke_routes_1_the_guard_reads_both_probes_and_flags_an_unknown_route() -> (
    None
):
    "AC-runtime.smoke-routes.1"
    routes = _app_routes()
    assert "/api/health" in routes
    smoke_urls = _shell_api_urls(SMOKE.read_text(encoding="utf-8"))
    tier2_urls = _python_api_urls(TIER2.read_text(encoding="utf-8"))
    assert {"/api/health", "/api/docs", "/api/statements"} <= set(smoke_urls)
    assert {"/api/health", "/api/statements"} <= set(tier2_urls)
    unknown_shell = 'check_endpoint "X" "$BASE_URL/api/no-such-route?q=1"'
    unknown_python = 'urljoin(base, "api/no-such-route")'
    assert _unknown(_shell_api_urls(unknown_shell), routes) == ["/api/no-such-route"]
    assert _unknown(_python_api_urls(unknown_python), routes) == ["/api/no-such-route"]
