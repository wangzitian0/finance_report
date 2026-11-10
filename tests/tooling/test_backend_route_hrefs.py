from __future__ import annotations; import ast; import json; import re; from pathlib import Path; REPO_ROOT = Path(__file__).resolve().parents[2]; ROUTE_MAP_PATH = REPO_ROOT / 'apps' / 'frontend' / 'src' / 'lib' / 'route-map.json'; FRONTEND_PATTERNS_PATH = REPO_ROOT / 'apps' / 'frontend' / 'frontend-patterns.md'; BACKEND_PACKAGES = (REPO_ROOT / 'apps' / 'backend' / 'src' / 'workflow', REPO_ROOT / 'apps' / 'backend' / 'src' / 'reporting', REPO_ROOT / 'apps' / 'backend' / 'src' / 'advisor'); DYNAMIC_SEGMENT_RE = re.compile('\\[[^/\\]]+\\]'); DOC_FILE_REF_RE = re.compile('`([^`\\n]+\\.(?:tsx?|py|json|mjs|css))`')
def load_redirect_route_patterns(route_map_path: Path=ROUTE_MAP_PATH) -> dict[str, re.Pattern[str]]:
    payload = json.loads(route_map_path.read_text(encoding='utf-8')); patterns: dict[str, re.Pattern[str]] = {}
    for entry in payload.get('routes', []):
        if entry.get('state') != 'redirect': continue
        route_path = str(entry['path']); escaped = DYNAMIC_SEGMENT_RE.sub('__DYNAMIC__', route_path); escaped = re.escape(escaped).replace('__DYNAMIC__', '[^/?#]+'); patterns[route_path] = re.compile(f'^{escaped}(?:[?#].*)?$')
    return patterns
def _joined_str_template(node: ast.JoinedStr) -> str: parts: list[str] = []; [parts.append(value.value) if isinstance(value, ast.Constant) and isinstance(value.value, str) else parts.append('{expr}') for value in node.values]; return ''.join(parts)
def scan_source_for_redirect_hrefs(source: str, *, filename: str='<memory>', redirect_patterns: dict[str, re.Pattern[str]] | None=None) -> list[str]:
    patterns = redirect_patterns if redirect_patterns is not None else load_redirect_route_patterns(); tree = ast.parse(source, filename=filename); joined_children: set[int] = set(); [[joined_children.add(id(child)) for child in node.values] if isinstance(node, ast.JoinedStr) else None for node in ast.walk(tree)]; violations: list[str] = []
    for node in ast.walk(tree):
        candidate: str | None = None
        if isinstance(node, ast.JoinedStr): candidate = _joined_str_template(node)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and (id(node) not in joined_children): candidate = node.value
        if not candidate or not candidate.startswith('/'): continue
        for (route_path, pattern) in patterns.items():
            if pattern.match(candidate): lineno = getattr(node, 'lineno', 0); violations.append(f'{filename}:{lineno}: {candidate!r} matches redirect route {route_path!r}'); break
    return violations
def test_AC_platform_36_1_backend_packages_emit_no_redirect_route_hrefs() -> None:
    'AC-platform.36.1'; patterns = load_redirect_route_patterns(); assert '/reports/package' in patterns; assert '/statements/[id]/review' in patterns; assert '/review' in patterns; violations: list[str] = []
    for package_dir in BACKEND_PACKAGES:
        for path in sorted(package_dir.rglob('*.py')): rel = str(path.relative_to(REPO_ROOT)); source = path.read_text(encoding='utf-8'); violations.extend(scan_source_for_redirect_hrefs(source, filename=rel, redirect_patterns=patterns))
    assert violations == [], 'Backend emitted redirect UI routes:\n' + '\n'.join(violations); 'AC-platform.36.1'; 'AC-platform.36.1'; _m1_synthetic_source = '\ndef sample(statement):\n    a = "/reports/package"\n    b = f"/statements/{statement.id}/review"\n    c = "/review?source=events"\n    ok_a = "/reports?tab=package"\n    ok_b = f"/statements/{statement.id}"\n    ok_c = "/audit"\n    return a, b, c, ok_a, ok_b, ok_c\n'; _m1_violations = scan_source_for_redirect_hrefs(_m1_synthetic_source, filename='synthetic.py'); assert len(_m1_violations) == 3, _m1_violations; assert any(('/reports/package' in _m1_item for _m1_item in _m1_violations)); assert any(('/statements/[id]/review' in _m1_item for _m1_item in _m1_violations)); assert any(('/review' in _m1_item for _m1_item in _m1_violations)); 'AC-platform.36.1'; 'AC-platform.36.1'; _m2_markdown = FRONTEND_PATTERNS_PATH.read_text(encoding='utf-8'); _m2_missing = scan_doc_for_missing_file_refs(_m2_markdown); assert _m2_missing == [], 'apps/frontend/frontend-patterns.md cites deleted files:\n' + '\n'.join(_m2_missing); _m2_synthetic_missing = scan_doc_for_missing_file_refs('- `app/(main)/statements/page.tsx`\n- `app/(main)/upload/page.tsx`\n'); assert _m2_synthetic_missing == ['app/(main)/statements/page.tsx']
def scan_doc_for_missing_file_refs(markdown: str, *, repo_root: Path=REPO_ROOT) -> list[str]:
    search_roots = (repo_root, repo_root / 'apps' / 'frontend', repo_root / 'apps' / 'frontend' / 'src'); missing: list[str] = []
    for match in DOC_FILE_REF_RE.finditer(markdown):
        candidate = match.group(1).strip()
        if '/' not in candidate or '*' in candidate or '<' in candidate: continue
        if any(((root / candidate).is_file() for root in search_roots)): continue
        missing.append(candidate)
    return missing
