from __future__ import annotations; from pathlib import Path; ROOT = Path(__file__).resolve().parents[2]; FORBIDDEN_PHRASES = ('never merge', 'user merges pr', 'not merged code', 'user-only action (merging', 'triggers no deploy'); TARGET_FILES: tuple[Path, ...] = (ROOT / 'AGENTS.md',) + tuple(sorted((ROOT / 'docs' / 'agents').glob('*.md'))) + (ROOT / 'docs' / 'contributing' / 'branch-policy.md',)
def _violations(path: Path) -> list[str]:
    text = path.read_text(encoding='utf-8'); hits: list[str] = []
    for (lineno, line) in enumerate(text.splitlines(), start=1): lowered = line.lower(); [hits.append(f'{path.relative_to(ROOT)}:{lineno}: hit {phrase!r} -> {line.strip()!r}') if phrase in lowered else None for phrase in FORBIDDEN_PHRASES]
    return hits
def test_target_docs_exist() -> None:
    assert len(TARGET_FILES) >= 3, f'expected AGENTS.md + docs/agents/*.md + branch-policy.md, got {TARGET_FILES}'
    for path in TARGET_FILES: assert path.is_file(), f'expected target doc to exist: {path}'
    _m1_violations = [_m1_hit for _m1_path in TARGET_FILES for _m1_hit in _violations(_m1_path)]; assert not _m1_violations, "found reintroduced 'agents never merge' wording (issue #2069). Merge authority lives only in docs/contributing/branch-policy.md §4 — point at it instead of restating or contradicting it:\n" + '\n'.join(_m1_violations)
