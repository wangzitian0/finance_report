'AC7.17.1 EPIC-007'; from __future__ import annotations; import re; from pathlib import Path; REPO_ROOT = Path(__file__).resolve().parents[2]; SMOKE = REPO_ROOT / 'common' / 'runtime' / 'shell' / 'smoke_test.sh'; APP_DIR = REPO_ROOT / 'apps' / 'frontend' / 'src' / 'app'
def _frontend_page_routes() -> set[str]:
    routes: set[str] = set()
    for page in APP_DIR.rglob('page.tsx'):
        rel = page.relative_to(APP_DIR).parent; segments: list[str] = []; skip = False
        for part in rel.parts:
            if part.startswith('(') and part.endswith(')'): continue
            if part.startswith('[') and part.endswith(']'): skip = True; break
            segments.append(part)
        if skip: continue
        routes.add('/' + '/'.join(segments) if segments else '/')
    return routes
def _smoke_asserted_page_routes() -> list[str]:
    text = SMOKE.read_text(encoding='utf-8'); routes: list[str] = []; pattern = re.compile('check_endpoint\\s+"[^"]*"\\s+"\\$\\{?BASE_URL\\}?(/[^"\\s]*)"')
    for match in pattern.finditer(text):
        path = match.group(1)
        if path.startswith('/api/'): continue
        routes.append(path.rstrip('/') or '/')
    return routes
def test_AC7_17_1_smoke_asserts_only_existing_public_frontend_routes() -> None: 'AC-testing.deploy-gates.43 AC7.17.1'; real_routes = {r.rstrip('/') or '/' for r in _frontend_page_routes()}; asserted = _smoke_asserted_page_routes(); assert asserted, 'smoke_test.sh should still assert at least one frontend page route'; missing = [r for r in asserted if (r.rstrip('/') or '/') not in real_routes]; assert not missing, f'smoke_test.sh asserts page routes that do not exist under apps/frontend/src/app: {missing}. Existing routes: {sorted(real_routes)}'; _m1_asserted = {_m1_r.rstrip('/') or '/' for _m1_r in _smoke_asserted_page_routes()}; assert '/dashboard' not in _m1_asserted, 'smoke_test.sh must not assert /dashboard — there is no apps/frontend/src/app/.../dashboard/page.tsx, so it 404s'
