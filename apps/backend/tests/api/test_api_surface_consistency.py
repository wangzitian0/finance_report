'AC-platform.29.4 AC-platform.29.5 EPIC-012'; from __future__ import annotations; import ast; import inspect; import re; import shutil; import subprocess; from pathlib import Path; from typing import Any; from uuid import uuid4; from fastapi import APIRouter, status
from fastapi.routing import APIRoute, iter_route_contexts; from httpx import AsyncClient; import src.routers as _routers_pkg; from src.deps import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT; from src.main import _resolve_app_version, app; from src.reporting import DEFAULT_INCLUDE_RESTRICTED, PACKAGE_INCLUDE_RESTRICTED; _ROUTER_DIR = Path(_routers_pkg.__file__).resolve().parent; _RAW_STATUS_CODE = re.compile('status_code\\s*=\\s*\\d'); _BACKEND_SRC = _ROUTER_DIR.parent; _DISHONEST_DEPENDENCY_DEFAULT = re.compile('(?:DbSession|CurrentUserId)\\s*=\\s*None'); _PREVIOUSLY_UNBOUNDED_LIST_PATHS = ('/reconciliation/transactions/{txn_id}/anomalies', '/reports/package/snapshots'); _UNTAGGED_UTILITY_PATHS = frozenset({'/', '/health', '/openapi.json', '/docs', '/docs/oauth2-redirect', '/redoc'}); _api_routes = lambda: [context.route for context in iter_route_contexts(app.routes) if isinstance(context.route, APIRoute)]  # AC-reporting.net-worth-scope.12 EPIC-023
def test_AC12_29_4_no_route_or_tag_collisions() -> None:
    'AC-platform.29.4'; routes = _api_routes(); seen: dict[tuple[str, str], str] = {}; collisions: list[str] = []
    for route in routes:
        for method in sorted(route.methods - {'HEAD', 'OPTIONS'}):
            key = (method, route.path)
            if key in seen: collisions.append(f'{method} {route.path} (defined by {seen[key]} and {route.name})')
            else: seen[key] = route.name
    assert not collisions, f'duplicate (method, path) routes: {collisions}'; untagged: list[str] = []; multi_tagged: list[str] = []
    for route in routes:
        if route.path in _UNTAGGED_UTILITY_PATHS: continue
        tags = list(route.tags or []); untagged.append(f'{sorted(route.methods)} {route.path}') if len(tags) == 0 else multi_tagged.append(f'{sorted(route.methods)} {route.path} -> {tags}') if len(tags) > 1 else None
    assert not untagged, f'operations with no OpenAPI tag (would be ungrouped in the FE client): {untagged}'; assert not multi_tagged, f'operations spanning multiple tags (would duplicate across FE modules): {multi_tagged}'
    def _tags_under_prefix(prefix: str) -> set[str]: out: set[str] = set(); [out.update(route.tags or []) if route.path.startswith(prefix) else None for route in routes]; return out
    assert {'statements', 'review'} <= _tags_under_prefix('/statements'); assert {'ai-feedback'} <= _tags_under_prefix('/ai')
def test_AC12_29_1_status_codes_use_constants_and_async_uses_202(openapi_schema: dict[str, Any]) -> None: 'AC-platform.29.1'; offenders: list[str] = []; [[offenders.append(f'{py.name}:{lineno}: {line.strip()}') if _RAW_STATUS_CODE.search(line) else None for lineno, line in enumerate(py.read_text().splitlines(), start=1)] for py in sorted(_ROUTER_DIR.glob('*.py'))]; assert not offenders, f'raw-integer status_code literals (use status.HTTP_*): {offenders}'; upload = openapi_schema['paths']['/statements/upload']['post']; assert '202' in upload['responses']
def test_AC12_29_6_verb_in_path_urls_renamed_to_resources(openapi_schema: dict[str, Any]) -> None:
    'AC-platform.29.6'; paths = set(openapi_schema['paths']); renamed = {'/reconciliation/run': '/reconciliation/runs', '/market-data/sync/fx': '/market-data/fx/syncs', '/market-data/sync/stocks': '/market-data/stocks/syncs', '/journal-entries/{entry_id}/post': '/journal-entries/{entry_id}/postings', '/journal-entries/{entry_id}/void': '/journal-entries/{entry_id}/voidings'}
    for (old, new) in renamed.items(): assert old not in paths, f'{old} should have been renamed to {new}'; assert new in paths, f'{new} missing from OpenAPI'
def test_AC12_29_2_named_unbounded_endpoints_are_bounded(openapi_schema: dict[str, Any]) -> None:
    'AC-platform.29.2'; paths = openapi_schema['paths']
    for path in _PREVIOUSLY_UNBOUNDED_LIST_PATHS: assert path in paths, f'{path} missing from OpenAPI'; params = {p['name']: p for p in paths[path]['get'].get('parameters', [])}; assert 'limit' in params, f'{path} GET has no `limit` query param'; assert 'offset' in params, f'{path} GET has no `offset` query param'; limit_schema = params['limit']['schema']; assert limit_schema.get('maximum') == MAX_PAGE_LIMIT, f'{path} `limit` is not capped at MAX_PAGE_LIMIT ({MAX_PAGE_LIMIT}): {limit_schema}'; assert limit_schema.get('minimum') == 1; assert params['offset']['schema'].get('minimum') == 0
def test_AC_platform_29_7_every_get_limit_has_an_upper_bound(openapi_schema: dict[str, Any]) -> None:
    'AC-platform.29.7'; offenders: list[str] = []
    for (path, path_item) in openapi_schema['paths'].items():
        operation = path_item.get('get')
        if operation is None: continue
        for parameter in operation.get('parameters', []):
            if parameter.get('in') != 'query' or parameter.get('name') != 'limit': continue
            maximum = parameter.get('schema', {}).get('maximum'); offenders.append(path) if not isinstance(maximum, int | float) else None
    assert not offenders, f'GET limit parameters without an explicit upper bound: {offenders}'
def _top_level_model_names(path: Path) -> set[str]: tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path)); return {node.name for node in tree.body if isinstance(node, ast.ClassDef) and any((isinstance(base, ast.Name) and base.id == 'BaseModel' or (isinstance(base, ast.Attribute) and base.attr == 'BaseModel') for base in node.bases))}
def test_AC_platform_29_8_delivery_helpers_have_one_honest_home() -> None:
    'AC-platform.29.8'; router_models: dict[str, list[str]] = {}; schema_models: dict[str, list[str]] = {}; dishonest_defaults: list[str] = []; normalize_currency_defs: list[str] = []; request_id_defs: list[str] = []
    for path in sorted(_BACKEND_SRC.rglob('*.py')):
        relative = path.relative_to(_BACKEND_SRC).as_posix(); source = path.read_text(encoding='utf-8'); [dishonest_defaults.append(f'{relative}:{source.count(chr(10), 0, match.start()) + 1}') for match in _DISHONEST_DEPENDENCY_DEFAULT.finditer(source)]
        if 'normalize_currency' not in source and 'request_id' not in source: continue
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef): continue
            normalize_currency_defs.append(f'{relative}:{node.lineno}') if node.name == 'normalize_currency' and relative != 'schemas/base.py' else None; request_id_defs.append(f'{relative}:{node.name}') if 'request_id' in node.name and node.name in {'_current_request_id', 'current_request_id', 'ensure_request_id'} else None
    [[router_models.setdefault(name, []).append(path.name) for name in _top_level_model_names(path)] for path in sorted(_ROUTER_DIR.glob('*.py'))]; [[schema_models.setdefault(name, []).append(path.name) for name in _top_level_model_names(path)] for path in sorted((_BACKEND_SRC / 'schemas').glob('*.py'))]; collisions = sorted(router_models.keys() & schema_models.keys()); assert not collisions, f'router/schema DTO name collisions: {collisions}'; assert not dishonest_defaults, f'dependency aliases defaulted to None: {dishonest_defaults}'; assert not normalize_currency_defs, f'ad-hoc schema currency normalizers: {normalize_currency_defs}'; assert request_id_defs == ['observability/audit.py:current_request_id', 'observability/audit.py:ensure_request_id']; utility_owners = {route.path: route.endpoint.__module__ for route in _api_routes() if route.path in {'/health'}}; assert utility_owners == {'/health': 'src.runtime.extension.api.health', }
def test_AC_platform_29_9_report_wire_shape_and_policy_are_single(openapi_schema: dict[str, Any]) -> None: 'AC-platform.29.9'; assert DEFAULT_INCLUDE_RESTRICTED is True; assert PACKAGE_INCLUDE_RESTRICTED is False; paths = openapi_schema['paths']; generation = paths['/reports/package/generate']['post']; assert generation.get('parameters', []) == []; assert generation['requestBody']['required'] is True; body_ref = generation['requestBody']['content']['application/json']['schema']['$ref'].rsplit('/', 1)[-1]; body = openapi_schema['components']['schemas'][body_ref]; assert body['properties']['include_restricted'].get('default') is None; defaults = {path: {item['name']: item for item in paths[path]['get']['parameters']}['include_restricted']['schema']['default'] for path in ('/reports/balance-sheet', '/reports/balance-sheet/diagnostics', '/reports/export', '/reports/net-worth/allocation', '/reports/net-worth/timeseries', '/reports/package')}; assert defaults == {'/reports/balance-sheet': DEFAULT_INCLUDE_RESTRICTED, '/reports/balance-sheet/diagnostics': DEFAULT_INCLUDE_RESTRICTED, '/reports/export': DEFAULT_INCLUDE_RESTRICTED, '/reports/net-worth/allocation': DEFAULT_INCLUDE_RESTRICTED, '/reports/net-worth/timeseries': DEFAULT_INCLUDE_RESTRICTED, '/reports/package': PACKAGE_INCLUDE_RESTRICTED}
async def test_AC12_29_3_pagination_convention_is_enforced(client: AsyncClient) -> None: 'AC-platform.29.3'; assert isinstance(DEFAULT_PAGE_LIMIT, int); assert isinstance(MAX_PAGE_LIMIT, int); assert 1 <= DEFAULT_PAGE_LIMIT <= MAX_PAGE_LIMIT; ok = await client.get('/reports/package/snapshots', params={'limit': 5, 'offset': 0}); assert ok.status_code == status.HTTP_200_OK; too_big = await client.get('/reports/package/snapshots', params={'limit': MAX_PAGE_LIMIT + 1}); assert too_big.status_code == 422
def test_issue3010_mock_only_routes_removed(openapi_schema: dict[str, Any]) -> None: '#3010 #3009 slice 1: no route exists that only a Playwright mock calls'; paths = set(openapi_schema['paths']); removed = ('/reports/trend', '/income/annualized', '/assets/restricted', '/portfolio/performance', '/reports/{report_type}/snapshots', '/statements/{statement_id}/review/edit'); leftovers = [p for p in removed if p in paths]; assert not leftovers, f'mock-only routes still live (delete the route and its mocks, #3010): {leftovers}'
async def test_AC12_29_5_deprecated_statement_decision_endpoints_removed(client: AsyncClient, openapi_schema: dict[str, Any]) -> None:
    'AC-platform.29.5'; sid = uuid4()
    for removed in (f'/statements/{sid}/approve', f'/statements/{sid}/reject'): response = await client.post(removed, json={'notes': ''}); assert response.status_code in (404, 405), f'{removed} still resolves: {response.status_code}'
    paths = set(openapi_schema['paths']); assert '/statements/{statement_id}/approve' not in paths; assert '/statements/{statement_id}/reject' not in paths; assert '/statements/{statement_id}/review/approve' in paths; assert '/statements/{statement_id}/review/reject' in paths


async def test_issue3012_uncalled_routes_removed(client: AsyncClient, openapi_schema: dict[str, Any]) -> None:
    """#3012 #3009 slice 3: uncalled routes deleted and return 404/405."""
    paths = openapi_schema['paths']
    retired_ops = (
        ('get', '/users'),
        ('get', '/users/{user_id}'),
        ('put', '/users/{user_id}'),
        ('delete', '/users/{user_id}'),
        ('get', '/assets/positions'),
        ('get', '/assets/positions/{position_id}'),
        ('post', '/assets/reconcile'),
        ('get', '/accounts/{account_id}'),
        ('get', '/corrections/stats'),
        ('get', '/notifications'),
    )
    still_in_openapi = [f'{m.upper()} {p}' for m, p in retired_ops if m in paths.get(p, {})]
    assert not still_in_openapi, f'uncalled #3012 routes still in OpenAPI: {still_in_openapi}'

    uid = uuid4()
    probes = (
        ('GET', '/users', (404,)),
        ('GET', f'/users/{uid}', (404,)),
        ('PUT', f'/users/{uid}', (404,)),
        ('DELETE', f'/users/{uid}', (404,)),
        ('GET', '/assets/positions', (404,)),
        ('GET', f'/assets/positions/{uid}', (404,)),
        ('POST', '/assets/reconcile', (404,)),
        ('GET', f'/accounts/{uid}', (404, 405)),
        ('GET', '/corrections/stats', (404,)),
        ('GET', '/notifications', (404,)),
    )
    for method, url, allowed in probes:
        kwargs = {'json': {}} if method == 'PUT' else {}
        resp = await client.request(method, url, **kwargs)
        assert resp.status_code in allowed, f'{method} {url} returned {resp.status_code}, expected {allowed}'


async def test_issue3013_naming_overlaps_resolved_and_action_url_rule(
    client: AsyncClient, openapi_schema: dict[str, Any]
) -> None:
    """#3013 #3009 slice 4: resolve 5 URL naming overlaps and forbid verb/list action path segments."""
    paths = openapi_schema['paths']
    retired = (
        ('get', '/transactions/{transaction_id}/audit'),
        ('get', '/review/conflicts/{statement_id}'),
        ('post', '/review/conflicts/{statement_id}/resolve'),
        ('get', '/statements/consistency-checks/list'),
        ('post', '/reconciliation/batch-accept'),
        ('post', '/statements/batch-approve-matches'),
        ('post', '/statements/batch-reject-matches'),
    )
    still_present = [f'{m.upper()} {p}' for m, p in retired if m in paths.get(p, {})]
    assert not still_present, f'legacy overlapping #3013 routes still in OpenAPI: {still_present}'

    required = (
        ('get', '/journal-entries/{entry_id}/audit'),
        ('get', '/statements/{statement_id}/conflicts'),
        ('post', '/statements/{statement_id}/conflicts/resolve'),
        ('get', '/statements/consistency-checks'),
        ('post', '/reconciliation/matches'),
    )
    missing = [f'{m.upper()} {p}' for m, p in required if m not in paths.get(p, {})]
    assert not missing, f'canonical #3013 routes missing from OpenAPI: {missing}'

    bad_segments = []
    forbidden_prefixes = ('batch-', 'get-', 'create-', 'update-', 'delete-')
    for path in sorted(paths):
        for seg in path.strip('/').split('/'):
            if seg.startswith('{'):
                continue
            if seg == 'list' or seg.startswith(forbidden_prefixes):
                bad_segments.append(f'{path} ({seg})')
    assert not bad_segments, f'action/verb URL segments violate REST resource rule (#3013): {bad_segments}'

    uid = uuid4()
    for method, url, allowed in (
        ('GET', f'/transactions/{uid}/audit', (404,)),
        ('GET', f'/review/conflicts/{uid}', (404,)),
        ('POST', f'/review/conflicts/{uid}/resolve', (404,)),
        ('GET', '/statements/consistency-checks/list', (404,)),
        ('POST', '/reconciliation/batch-accept', (404,)),
        ('POST', '/statements/batch-approve-matches', (404, 405)),
        ('POST', '/statements/batch-reject-matches', (404, 405)),
    ):
        resp = await client.request(method, url)
        assert resp.status_code in allowed, f'{method} {url} -> {resp.status_code}, expected {allowed}'

    checks_resp = await client.get('/statements/consistency-checks')
    assert checks_resp.status_code == status.HTTP_200_OK, checks_resp.text
    assert 'items' in checks_resp.json()


def _find_undocumented_api_routes(routes: Any) -> list[str]:
    missing: list[str] = []
    for context in iter_route_contexts(routes):
        route = context.route
        if not isinstance(route, APIRoute):
            continue
        doc = inspect.getdoc(route.endpoint) or ''
        if not doc.strip() or doc.strip().endswith('..'):
            missing.append(f'{route.path} ({route.endpoint.__name__})')
    return missing


def test_issue3014_routes_have_docstrings_and_missing_docstring_fails() -> None:
    """#3014 #3009 slice 5: every route handler has a clean docstring and missing docstrings fail."""
    assert _find_undocumented_api_routes(app.routes) == []

    probe_router = APIRouter()

    @probe_router.get('/probe-missing-docstring')
    async def no_doc_handler() -> dict[str, str]:
        return {'status': 'ok'}

    assert _find_undocumented_api_routes(probe_router.routes) == ['/probe-missing-docstring (no_doc_handler)']


def test_issue3014_app_version_reads_from_git_tag(
    tmp_path: Path, monkeypatch: Any, openapi_schema: dict[str, Any]
) -> None:
    """#3014 #3009 slice 5: app version resolves from git tag/APP_VERSION and is not hardcoded 0.1.0."""
    main_source = (_BACKEND_SRC / 'main.py').read_text(encoding='utf-8')
    assert 'version="0.1.0"' not in main_source
    assert "version='0.1.0'" not in main_source
    assert openapi_schema['info']['version'] == app.version

    git_bin = shutil.which('git')
    assert git_bin is not None
    subprocess.run([git_bin, 'init'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git_bin, 'config', 'user.email', 'test@example.com'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git_bin, 'config', 'user.name', 'Test User'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git_bin, 'commit', '--allow-empty', '-m', 'init'], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git_bin, 'tag', 'v0.2.99'], cwd=tmp_path, check=True, capture_output=True)

    monkeypatch.delenv('APP_VERSION', raising=False)
    assert _resolve_app_version(tmp_path) == '0.2.99'

    monkeypatch.setenv('APP_VERSION', 'v9.8.7')
    assert _resolve_app_version() == '9.8.7'
