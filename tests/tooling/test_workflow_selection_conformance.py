from __future__ import annotations; import re; from pathlib import Path; import pytest; from common.testing import matrix; ROOT = Path(__file__).resolve().parents[2]; WORKFLOWS = ROOT / '.github' / 'workflows'
from tests.tooling.hook_text import hook_steps
def _joined_lines(text: str) -> list[str]:
    lines: list[str] = []; buffer = ''
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith('\\'): buffer += line[:-1] + ' '; continue
        lines.append(buffer + line); buffer = ''
    lines.append(buffer) if buffer else None; return lines
_RUN_LINE = re.compile('common\\.testing\\.test_selection .* --run$')
def _pytest_invocations() -> dict[str, list[str]]:
    from infra2_sdk.manifests import load_hooks_manifest; found: dict[str, list[str]] = {}
    for wf in sorted(WORKFLOWS.glob('*.yml')):
        rel = wf.relative_to(ROOT).as_posix()
        for line in _joined_lines(wf.read_text(encoding='utf-8')):
            stripped = line.strip()
            if stripped.startswith('#'): continue
            found.setdefault(rel, []).append(stripped) if re.search('\\bpytest\\b', stripped) and '--junit-xml=' in stripped else None
    hooks_manifest = ROOT / 'runtime-hooks.manifest.json'
    if hooks_manifest.exists():
        manifest_data = load_hooks_manifest(hooks_manifest)
        for (slot_name, spec) in manifest_data.slots.items():
            seen_in_slot: set[str] = set()
            for part in hook_steps(spec):
                stripped = part.strip()
                if re.search('\\bpytest\\b', stripped) or _RUN_LINE.search(stripped):
                    key = f'{slot_name}:{stripped}'
                    if key not in seen_in_slot: seen_in_slot.add(key); found.setdefault('runtime-hooks.manifest.json', []).append(key)
    return found
def test_AC8_23_1_every_workflow_pytest_invocation_is_registered() -> None:
    'AC-testing.conformance.1 AC8.23.1'; invocations = _pytest_invocations(); anchors = [(c, c.anchor) for c in matrix.WORKFLOW_PYTEST_CONTRACTS]; matched_lines: set[str] = set()
    for (contract, anchor) in anchors: lines = [line for line in invocations.get(contract.workflow, []) if anchor in line]; assert len(lines) == 1, f'contract {contract.stage!r}: expected exactly one invocation with anchor {anchor!r} in {contract.workflow}, found {len(lines)}'; matched_lines.add(lines[0])
    for (workflow, lines) in invocations.items():
        for line in lines: assert line in matched_lines, f'UNREGISTERED pytest invocation in {workflow}: {line!r}. Register it in matrix.WORKFLOW_PYTEST_CONTRACTS (the selection SSOT) before adding it to a workflow.'
def _run_line_marker(line: str) -> str:
    stage = re.search('--stage (\\S+)', line); corpus = re.search('--corpus (\\S+)', line)
    if stage is None: return matrix.touched_e2e_selection([])[1]
    return matrix.stage_selection(stage.group(1), corpus=corpus.group(1) if corpus else 'all')[1]
def _selection_tokens(line: str) -> set[str]:
    if _RUN_LINE.search(line): return set(re.findall('--(?:stage|corpus) \\S+|--touched-files', line))
    tokens = set(); [tokens.add(token) if token.startswith('tests/') else tokens.add(token) if token.startswith('"${') and 'TESTS' in token else None for token in line.split()]; return tokens
def test_AC8_23_2_registered_invocations_match_matrix_selection() -> None:
    'AC-testing.conformance.2 AC8.23.2'; invocations = _pytest_invocations()
    for contract in matrix.WORKFLOW_PYTEST_CONTRACTS:
        line = next((line for line in invocations[contract.workflow] if contract.anchor in line))
        if _RUN_LINE.search(line): assert contract.marker == _run_line_marker(line), f'{contract.stage}: marker drifted from the stage marker the selection tool applies: {contract.marker!r}'; assert not re.search(' -m (?!common\\.testing)', line), f'{contract.stage}: a --run line must not pass its own -m: {line}'
        elif contract.marker is not None: assert f'-m "{contract.marker}"' in line, f'{contract.stage}: marker drifted from matrix constant.\n  expected: -m "{contract.marker}"\n  line: {line}'
        assert _selection_tokens(line) == set(contract.paths), f'{contract.stage}: selection tokens drifted from the matrix contract.\n  expected: {sorted(contract.paths)}\n  found: {sorted(_selection_tokens(line))}\n  line: {line}'
def test_AC8_23_3_staging_ai_ocr_corpus_aligns_with_matrix_llm_rows() -> None: 'AC-testing.conformance.3 AC8.23.3'; from common.testing.staging_ai_ocr_gate_contract import gate_files; corpus = set(gate_files()); llm_rows = {row.file for row in matrix.E2E_ROWS if matrix.NEEDS_LLM_PROVIDER in row.needs}; connectivity = {'tests/e2e/test_ai_provider_connectivity.py'}; assert corpus <= llm_rows, f'corpus files missing llm rows: {corpus - llm_rows}'; assert llm_rows - corpus == connectivity, f'llm-marked matrix rows not covered by the staging corpus (and not the connectivity probe): {llm_rows - corpus - connectivity}'
