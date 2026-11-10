'AC-runtime.env-empty-values.1'; from __future__ import annotations; import json; import re; from pathlib import Path; import yaml; ROOT = Path(__file__).resolve().parents[2]; MANIFEST_PATH = ROOT / 'common' / 'runtime' / 'required-env.generated.json'; ENV_EXAMPLE_PATH = ROOT / '.env.example'; _EMPTY_EXPANSION_RE = re.compile('^\\$\\{[A-Za-z_][A-Za-z0-9_]*(?::?-\\s*(?:""|\'\')?)?\\}$'); _DOTENV_ASSIGNMENT_RE = re.compile('^\\s*(?:export\\s+)?([A-Za-z_][A-Za-z0-9_]*)\\s*=(.*)$')
def _alias_chain_env_names() -> set[str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8')); names: set[str] = set()
    for entry in manifest['fields']:
        aliases = entry.get('aliases') or []
        if aliases: names.add(entry['env']); names.update(aliases)
    return names
def _materializes_empty(value: object) -> bool:
    if value is None: return False
    text = str(value).strip()
    if text in ('', '""', "''"): return True
    return bool(_EMPTY_EXPANSION_RE.match(text))
def _dotenv_empty_assignments(path: Path, names: set[str]) -> list[str]:
    findings: list[str] = []
    for (number, line) in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if line.lstrip().startswith('#'): continue
        match = _DOTENV_ASSIGNMENT_RE.match(line)
        if match is None: continue
        name, raw_value = (match.group(1), match.group(2)); findings.append(f'{path.name}:{number}: {line.strip()}') if name in names and _materializes_empty(raw_value) else None
    return findings
def _compose_environment_blocks(node: object, where: str) -> list[tuple[str, object]]: blocks: list[tuple[str, object]] = []; [blocks.append((where, value)) if key == 'environment' else blocks.extend(_compose_environment_blocks(value, f'{where}.{key}')) for key, value in node.items()] if isinstance(node, dict) else [blocks.extend(_compose_environment_blocks(item, f'{where}[{index}]')) for index, item in enumerate(node)] if isinstance(node, list) else None; return blocks
def _compose_empty_assignments(path: Path, names: set[str]) -> list[str]:
    document = yaml.safe_load(path.read_text(encoding='utf-8')); findings: list[str] = []
    for (where, block) in _compose_environment_blocks(document, path.name):
        pairs: list[tuple[str, object]] = []
        if isinstance(block, dict): pairs = list(block.items())
        elif isinstance(block, list):
            for item in block:
                text = str(item)
                if '=' not in text: continue
                key, _, value = text.partition('='); pairs.append((key.strip(), value))
        [findings.append(f'{where}: {name}: {value!r}') if name in names and _materializes_empty(value) else None for name, value in pairs]
    return findings
_shipped_compose_files = lambda: sorted(ROOT.glob('docker-compose*.yml'))
def test_AC_runtime_env_empty_values_1_no_artifact_ships_an_empty_alias_chain_value() -> None: 'AC-runtime.env-empty-values.1'; names = _alias_chain_env_names(); assert 'ENVIRONMENT' in names and 'ENV' in names, 'the environment alias chain vanished from the generated manifest — this gate would be scanning for nothing'; compose_files = _shipped_compose_files(); assert compose_files, 'expected root docker-compose*.yml files to scan'; findings = _dotenv_empty_assignments(ENV_EXAMPLE_PATH, names); [findings.extend(_compose_empty_assignments(compose_file, names)) for compose_file in compose_files]; assert not findings, "a shipped artifact assigns an empty value to an env name that competes in a Settings alias chain. An empty value is NOT 'unset' today (Settings has no env_ignore_empty), so it shadows every later alias in the chain. Ship a commented example in .env.example, and the pass-through form (`KEY:` / `- KEY`) in compose:\n  " + '\n  '.join(findings)
def test_the_detectors_still_recognise_every_empty_producing_spelling(tmp_path: Path) -> None: names = {'WATCHED', 'WATCHED_ALIAS'}; dotenv = tmp_path / '.env.example'; dotenv.write_text('\n'.join(['# WATCHED=', 'WATCHED_ALIAS=real-value', 'UNWATCHED=', 'WATCHED=', 'export WATCHED_ALIAS=""']) + '\n', encoding='utf-8'); dotenv_findings = _dotenv_empty_assignments(dotenv, names); assert len(dotenv_findings) == 2, dotenv_findings; assert all(('UNWATCHED' not in finding for finding in dotenv_findings)); compose = tmp_path / 'docker-compose.probe.yml'; compose.write_text(yaml.safe_dump({'services': {'ok-map': {'environment': {'WATCHED': None}}, 'ok-list': {'environment': ['WATCHED']}, 'ok-default': {'environment': {'WATCHED': '${WATCHED:-real}'}}, 'ok-required': {'environment': {'WATCHED': '${WATCHED:?set me}'}}, 'bad-empty-default': {'environment': {'WATCHED': '${WATCHED:-}'}}, 'bad-dash-default': {'environment': {'WATCHED': '${WATCHED-}'}}, 'bad-bare-expansion': {'environment': {'WATCHED': '${WATCHED}'}}, 'bad-literal': {'environment': {'WATCHED_ALIAS': ''}}, 'bad-list': {'environment': ['WATCHED_ALIAS=${WATCHED_ALIAS:-}']}}}), encoding='utf-8'); compose_findings = _compose_empty_assignments(compose, names); assert len(compose_findings) == 5, compose_findings; assert all(('.services.bad-' in finding for finding in compose_findings)), compose_findings
