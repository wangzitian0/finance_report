from __future__ import annotations; import hashlib; import json; import os; import re; import subprocess; from pathlib import Path; import pytest; ROOT = Path(__file__).resolve().parents[2]; MANIFEST_PATH = ROOT / '.ws-publish' / 'manifest.json'; CANONICAL_SKILLS = ROOT / '.agents' / 'skills'; MIRROR_SKILL_DIRS = {'claude': ROOT / '.claude' / 'skills', 'agents': ROOT / '.agents' / 'skills'}; BANNED_OPENCODE_PLUGINS = ('opencode-antigravity-auth', 'opencode-openai-codex-auth'); BANNED_MODEL_PROVIDER_PREFIXES = ('openai/', 'google/'); MCP_BASELINE = {'context7', 'github', 'basic-memory', 'sequential-thinking'}
def _all_opencode_model_refs() -> dict[str, str]:
    refs: dict[str, str] = {}; root_config = json.loads((ROOT / 'opencode.json').read_text(encoding='utf-8'))
    if 'model' in root_config: refs['opencode.json:model'] = root_config['model']
    agent_config = json.loads((ROOT / '.opencode' / 'oh-my-openagent.json').read_text(encoding='utf-8'))
    for section in ('agents', 'categories'):
        for (name, body) in agent_config.get(section, {}).items():
            if isinstance(body, dict) and 'model' in body: refs[f'{section}.{name}'] = body['model']
    return refs
def _manifest_skill_files(root: Path=ROOT) -> dict[str, str]: manifest = json.loads((root / '.ws-publish' / 'manifest.json').read_text(encoding='utf-8')); files = manifest.get('skills', {}).get('files', {}); assert isinstance(files, dict) and files, 'expected non-empty skills.files in .ws-publish/manifest.json'; return {str(k): str(v) for k, v in files.items()}
def _canonical_leaf_skill_dirs(root: Path=ROOT) -> dict[str, Path]:
    leaves: dict[str, Path] = {}; skills_root = root / '.agents' / 'skills'
    for skill_file in sorted(skills_root.rglob('SKILL.md')): leaf = skill_file.parent; assert leaf.name not in leaves, f'Rendered skills {leaves.get(leaf.name)} and {leaf} share the name {leaf.name!r}; the flat runtime directories can hold only one of them'; leaves[leaf.name] = leaf
    return leaves
def test_instruction_md_symlinks_to_agents_md() -> None:
    agents_md = ROOT / 'AGENTS.md'; assert agents_md.is_file() and (not agents_md.is_symlink()); assert not os.path.lexists(ROOT / 'CLAUDE.md'), 'CLAUDE.md must not exist'; tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True).stdout.split(b'\x00'); tracked_claude_md = [p.decode() for p in tracked if p and Path(p.decode()).name == 'CLAUDE.md']; assert tracked_claude_md == [], f'tracked CLAUDE.md files stop AGENTS.md loading: {tracked_claude_md}'
    for entry in ('GEMINI.md',): link = ROOT / entry; assert link.is_symlink(), f'{entry} must be a symlink, not a copy'; assert os.readlink(link) == 'AGENTS.md'; assert link.resolve() == agents_md.resolve()
    from common.meta.extension import check_ssot_ownership; assert ROOT / 'GEMINI.md' in check_ssot_ownership.CHECK4_EXEMPT_PATHS; assert ROOT / 'CLAUDE.md' not in check_ssot_ownership.CHECK4_EXEMPT_PATHS; _verify_rendered_skills_match_manifest(ROOT); assert not (ROOT / '.codex' / 'skills').exists(), '.codex/skills must not exist: Codex reads .agents/skills natively and would list every repository skill twice (dev_env#673).'; _verify_no_unmanifested_or_orphan_skill_files(ROOT); _m5_config = json.loads((ROOT / 'opencode.json').read_text(encoding='utf-8')); _m5_plugins = _m5_config.get('plugin', []); assert isinstance(_m5_plugins, list), 'opencode.json plugin field must be a list'
    for _m5_plugin in _m5_plugins:
        for _m5_banned in BANNED_OPENCODE_PLUGINS: assert _m5_banned not in _m5_plugin, f'ban-risk auth plugin {_m5_banned!r} must not be re-added to opencode.json (found {_m5_plugin!r})'
    _m6_refs = _all_opencode_model_refs(); assert _m6_refs, 'expected to find model references to validate'
    for (_m6_location, _m6_model) in sorted(_m6_refs.items()):
        for _m6_prefix in BANNED_MODEL_PROVIDER_PREFIXES: assert not _m6_model.startswith(_m6_prefix), f'{_m6_location} routes to ban-risk provider {_m6_model!r}; OpenCode can only reach {_m6_prefix}* via borrowed subscription OAuth. Re-point it at github-copilot or an api-key provider.'
    _m7_cfg = json.loads((ROOT / '.mcp.json').read_text(encoding='utf-8')); _m7_servers = set(_m7_cfg.get('mcpServers', {})); _m7_missing = MCP_BASELINE - _m7_servers; assert not _m7_missing, f'.mcp.json missing baseline MCP servers: {sorted(_m7_missing)}'; _m8_cfg = json.loads((ROOT / 'opencode.json').read_text(encoding='utf-8')); _m8_servers = set(_m8_cfg.get('mcp', {})); _m8_missing = MCP_BASELINE - _m8_servers; assert not _m8_missing, f'opencode.json missing baseline MCP servers: {sorted(_m8_missing)}'; _m9_cfg = json.loads((ROOT / '.gemini' / 'settings.json').read_text(encoding='utf-8')); _m9_servers = set(_m9_cfg.get('mcpServers', {})); _m9_missing = MCP_BASELINE - _m9_servers; assert not _m9_missing, f'.gemini/settings.json missing baseline MCP servers: {sorted(_m9_missing)}'; _m10_proc = subprocess.run(['git', 'ls-files', '-s', '.claude/settings.json'], cwd=ROOT, capture_output=True, text=True, check=True); _assert_claude_settings_untracked(_m10_proc.stdout.strip()); _m11_fake_output = '120000 4b825dc642cb6eb9a060e54bf8d69288fbee4904 0\t.claude/settings.json'
    with pytest.raises(AssertionError, match='tracked in git index'): _assert_claude_settings_untracked(_m11_fake_output)
    _m12_repo_basenames = _repo_py_basenames(); _m12_skill_mds = sorted(CANONICAL_SKILLS.rglob('SKILL.md')); assert _m12_skill_mds, f'expected canonical SKILL.md files under {CANONICAL_SKILLS}'; _m12_missing: list[str] = []
    for _m12_skill_md in _m12_skill_mds:
        if _m12_skill_md.parent.name in _COMMON_ENGINEERING_SKILLS: continue
        _m12_text = _m12_skill_md.read_text(encoding='utf-8'); _m12_rel = _m12_skill_md.relative_to(ROOT); [_m12_missing.append(f'{_m12_rel} -> {_m12_ref}') if not (ROOT / _m12_ref).is_file() else None for _m12_ref in _TOOL_PATH_REF.findall(_m12_text)]; [_m12_missing.append(f'{_m12_rel} -> {_m12_name} (no such file in repo)') if _m12_name not in _m12_repo_basenames else None for _m12_name in _BARE_PY_REF.findall(_m12_text)]
    assert not _m12_missing, f'SKILL.md files reference non-existent tools: {sorted(set(_m12_missing))}'; assert _is_ignored('.agents/runs/issue1/probe.log'), '.agents/runs/ is not ignored: run artifacts make the working tree dirty'; assert not _is_ignored('.agents/skills/example/SKILL.md'), '.agents/skills must stay tracked: do not ignore all of .agents/'; _m13_tracked = subprocess.check_output(['git', 'ls-files', '.agents/skills'], cwd=ROOT, text=True); assert _m13_tracked.strip(), 'no tracked file under .agents/skills'
def _verify_rendered_skills_match_manifest(root: Path=ROOT) -> None:
    manifest_files = _manifest_skill_files(root); leaves = _canonical_leaf_skill_dirs(root); assert leaves, 'expected to discover .agents/skills/**/SKILL.md leaves'; mirror_dirs = {'claude': root / '.claude' / 'skills', 'agents': root / '.agents' / 'skills'}
    for (rel_str, expected_sha) in sorted(manifest_files.items()): path = root / rel_str; assert path.is_file() and (not path.is_symlink()), f'manifest skill file {rel_str} must exist as a physical file, not a symlink'; actual_sha = hashlib.sha256(path.read_bytes()).hexdigest(); assert actual_sha == expected_sha, f'rendered skill file {rel_str} sha256 {actual_sha} != manifest sha256 {expected_sha} (.ws-publish/manifest.json)'
    for (runtime, skills_dir) in mirror_dirs.items():
        for (name, leaf) in sorted(leaves.items()):
            mirror_dir = skills_dir / name; assert mirror_dir.is_dir() and (not mirror_dir.is_symlink()), f'{runtime}: {mirror_dir} must be a physical directory, not a symlink'; skill_md = mirror_dir / 'SKILL.md'; assert skill_md.is_file() and (not skill_md.is_symlink()), f'{runtime}: {mirror_dir} does not expose a physical SKILL.md'
            for canonical_file in sorted((p for p in leaf.rglob('*') if p.is_file())): rel = canonical_file.relative_to(leaf); mirror_file = mirror_dir / rel; assert mirror_file.is_file() and (not mirror_file.is_symlink()), f'{runtime}: missing rendered file {mirror_file}'; mirror_rel = mirror_file.relative_to(root).as_posix(); assert mirror_rel in manifest_files, f'{runtime}: {mirror_rel} is not recorded in .ws-publish/manifest.json'; assert mirror_file.read_bytes() == canonical_file.read_bytes(), f'{runtime}: {mirror_file} content drifts from {canonical_file}'
def _verify_no_unmanifested_or_orphan_skill_files(root: Path=ROOT) -> None:
    manifest_files = _manifest_skill_files(root); leaves = _canonical_leaf_skill_dirs(root); mirror_dirs = {'claude': root / '.claude' / 'skills', 'agents': root / '.agents' / 'skills'}; on_disk_files: set[str] = set()
    for (runtime, skills_dir) in mirror_dirs.items():
        for entry in sorted(skills_dir.iterdir()):
            if entry.name == '.ws-agy-managed': continue
            assert entry.is_dir() and (not entry.is_symlink()), f'{runtime}: {entry} must be a physical directory, not a symlink'; assert entry.name in leaves, f'{runtime}: {entry.name} is not in .ws-publish/manifest.json. Rendered skill directories are pinned by .ws-publish/manifest.json; anything else is drift.'; leaf = leaves[entry.name]; canonical_rels = {p.relative_to(leaf) for p in leaf.rglob('*') if p.is_file()}; mirror_rels: set[Path] = set()
            for p in sorted(entry.rglob('*')):
                assert not p.is_symlink(), f'{runtime}: {p} must not be a symlink'
                if p.is_file(): mirror_rels.add(p.relative_to(entry)); rel_posix = p.relative_to(root).as_posix(); assert rel_posix in manifest_files, f'{runtime}: unmanifested file {rel_posix} not in .ws-publish/manifest.json'; on_disk_files.add(rel_posix)
            assert mirror_rels == canonical_rels, f'{runtime}: {entry.name} file set {sorted(mirror_rels)} != rendered {sorted(canonical_rels)}'
    assert on_disk_files == set(manifest_files), f'on-disk skill files {sorted(on_disk_files ^ set(manifest_files))} do not match .ws-publish/manifest.json'
def test_rendered_skill_drift_fails_closed(tmp_path: Path) -> None:
    skill_text = '# Sample skill\n'; skill_sha = hashlib.sha256(skill_text.encode('utf-8')).hexdigest(); manifest_files: dict[str, str] = {}
    for prefix in ('.agents/skills', '.claude/skills'): rel = f'{prefix}/audit/SKILL.md'; p = tmp_path / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(skill_text, encoding='utf-8'); manifest_files[rel] = skill_sha
    manifest_dir = tmp_path / '.ws-publish'; manifest_dir.mkdir(parents=True, exist_ok=True); (manifest_dir / 'manifest.json').write_text(json.dumps({'skills': {'files': manifest_files}}), encoding='utf-8'); _verify_rendered_skills_match_manifest(tmp_path); _verify_no_unmanifested_or_orphan_skill_files(tmp_path); claude_skill = tmp_path / '.claude/skills/audit/SKILL.md'; claude_skill.write_text('# Hand-edited drift\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='manifest sha256'): _verify_rendered_skills_match_manifest(tmp_path)
    claude_skill.write_text(skill_text, encoding='utf-8'); extra_file = tmp_path / '.claude/skills/audit/extra.md'; extra_file.write_text('orphan\n', encoding='utf-8')
    with pytest.raises(AssertionError, match='unmanifested file'): _verify_no_unmanifested_or_orphan_skill_files(tmp_path)
def test_claude_settings_enable_mcp_baseline() -> None:
    proc = subprocess.run(['git', 'ls-files', '.claude/settings.json'], cwd=ROOT, capture_output=True, text=True, check=True)
    if not proc.stdout.strip(): return
    cfg = json.loads((ROOT / '.claude' / 'settings.json').read_text(encoding='utf-8')); enabled = set(cfg.get('enabledMcpjsonServers', [])); missing = MCP_BASELINE - enabled; assert not missing, f'.claude/settings.json does not enable baseline MCP servers: {sorted(missing)}'
def _assert_claude_settings_untracked(tracked_output: str) -> None: assert tracked_output == '', f'.claude/settings.json is tracked in git index: {tracked_output!r}. It must be untracked (git rm --cached) and ignored to avoid leaking private paths.'
_TOOL_PATH_REF = re.compile('\\btools/[A-Za-z0-9_./-]+\\.py\\b'); _BARE_PY_REF = re.compile('`([A-Za-z0-9_-]+\\.py)`'); _PY_SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', 'worktrees'}
def _repo_py_basenames() -> set[str]:
    names: set[str] = set()
    for (dirpath, dirnames, filenames) in os.walk(ROOT): dirnames[:] = [d for d in dirnames if d not in _PY_SKIP_DIRS]; names.update((fn for fn in filenames if fn.endswith('.py')))
    return names
_COMMON_ENGINEERING_SKILLS = {'audit', 'close', 'codegraph', 'deploy-evidence', 'prr', 'recall', 'smoke', 'ssot', 'start'}
def _is_ignored(path: str) -> bool: result = subprocess.run(['git', 'check-ignore', '-q', path], cwd=ROOT, capture_output=True); assert result.returncode in (0, 1), result.stderr.decode(); return result.returncode == 0
