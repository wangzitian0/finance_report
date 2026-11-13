'EPIC-008'; from __future__ import annotations; import copy; import os; import re; from html import escape; from pathlib import Path; from types import SimpleNamespace; from typing import Any; import pytest; from common.audit.base import TraceRecord, TraceResult, TraceTargetClass, VersionedTraceRef; from common.testing import matrix; from common.testing.ac_proof import PROOF_ATTR, AcProof; from common.testing.check_pr_ci_evidence import _module_for, collect_executed; from common.testing.executed_proof import record_executed_proof, register_executed_proof_consumer; ROOT = Path(__file__).resolve().parents[2]; WORKFLOWS = ROOT / '.github' / 'workflows'; _BASE_CRITICAL_PROOF_MATRIX: dict[str, Any] | None = None
from tests.tooling.hook_text import hook_steps
def _get_base_matrix() -> dict[str, Any]:
    global _BASE_CRITICAL_PROOF_MATRIX
    if _BASE_CRITICAL_PROOF_MATRIX is None: from common.testing.ac_graph import build_proofs_only; from common.testing.generate_critical_proof_matrix import build_matrix_from_graph; _BASE_CRITICAL_PROOF_MATRIX = build_matrix_from_graph(build_proofs_only())
    return copy.deepcopy(_BASE_CRITICAL_PROOF_MATRIX)
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
@pytest.mark.parametrize('governance_strength', ['exact', 'schema', 'concurrency', 'value-oracle'])
def test_AC8_23_4_pr_ci_evidence_reconciliation_gate(tmp_path: Path, monkeypatch, governance_strength: str) -> None:
    'AC-testing.conformance.4 AC8.23.4'; from common.testing.check_pr_ci_evidence import run_check; matrix_payload = _get_base_matrix(); scenario_proof = next((proof for proof in matrix_payload['proofs'] if proof.get('scenario_id') and proof.get('scope') == 'behavioral' and (proof.get('ci_tier') == 'pr_ci') and (matrix.classify_stage(proof.get('file', '')) in matrix.PR_EVIDENCE_STAGES)), None); assert scenario_proof is not None, 'expected a scoped pr_ci scenario proof for semantic-strength coverage'; scenario_proof['governance_strength'] = governance_strength; monkeypatch.setattr('common.testing.ac_graph.build_proofs_only', lambda *args, **kwargs: None); monkeypatch.setattr('common.testing.generate_critical_proof_matrix.build_matrix_from_graph', lambda _graph: matrix_payload); proofs = [p for p in matrix_payload.get('proofs', []) if p.get('scope') == 'behavioral' and p.get('ci_tier') == 'pr_ci' and (matrix.classify_stage(p.get('file', '')) in matrix.PR_EVIDENCE_STAGES)]; assert proofs, 'expected at least one scoped pr_ci proof in the repo'; monkeypatch.setenv('GITHUB_ACTIONS', 'true'); monkeypatch.setenv('GITHUB_REPOSITORY', 'wangzitian0/finance_report'); monkeypatch.setenv('GITHUB_SHA', 'a' * 40); monkeypatch.setenv('GITHUB_RUN_ID', '123'); monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    def junit_for(subset: list[dict]) -> Path:
        cases = []
        for proof in subset:
            properties = ''
            if proof.get('scenario_id'):
                test = lambda: None; setattr(test, PROOF_ATTR, AcProof(proof_id=proof['id'], ac_ids=tuple(proof['ac_ids']), stage=proof['stage'], task_category=proof['task_category'], scope=proof['scope'], ci_tier=proof['ci_tier'], trust_mode=proof.get('trust_mode', ''), source_classes=tuple(proof.get('source_classes', ())), issue=proof.get('issue', ''), scenario_id=proof['scenario_id'], oracle_kind=proof['oracle_kind'], governance_strength=proof.get('governance_strength', 'exact'), required_observation_kind=proof.get('required_observation_kind', ''))); item = SimpleNamespace(obj=test, nodeid=f"{proof['file']}::{proof['test']}", user_properties=[]); required_kind = proof.get('required_observation_kind', '')
                if required_kind: required_observation = lambda record, kind=required_kind: TraceRecord.observation(scope=record.scope, target=record.target, target_class=TraceTargetClass.GENERAL, assertion=VersionedTraceRef(kind, record.assertion.id, record.assertion.version), authority=record.authority, result=TraceResult.PASS, execution_id=record.execution_id, evidence_manifest_digest=record.evidence_manifest_digest, occurred_at=record.occurred_at, score=None, reason_code='required_observation_passed'); register_executed_proof_consumer(item, required_observation)
                record_executed_proof(item, SimpleNamespace(when='call', passed=True, user_properties=[]), environ=os.environ); properties = '<properties>' + ''.join((f'<property name="{escape(name)}" value="{escape(value)}"/>' for name, value in item.user_properties)) + '</properties>'
            cases.append(f'''<testcase classname="{_module_for(proof['file'])}" name="{proof['test']}" time="0.1">{properties}</testcase>''')
        path = tmp_path / f'junit-{len(subset)}.xml'; path.write_text(f'''<testsuite name="s" tests="{len(subset)}">{''.join(cases)}</testsuite>''', encoding='utf-8'); return path
    assert run_check([junit_for(proofs)]) == 0; assert run_check([junit_for(proofs[1:])]) == 1; skipped = tmp_path / 'skipped.xml'; scenario = next((proof for proof in proofs if proof.get('scenario_id'))); without_scenario = [proof for proof in proofs if proof is not scenario]; skipped.write_text(f'''<testsuite name="s" tests="1"><testcase classname="{_module_for(scenario['file'])}" name="{scenario['test']}"><skipped/></testcase></testsuite>''', encoding='utf-8'); import common.testing.check_pr_ci_evidence as evidence_gate; orig_has_exact = evidence_gate._has_exact_executed_proof
    def reject_match_for_nonexecuted_proof(proof_arg, *args, **kwargs):
        if proof_arg.get('id') == scenario.get('id'): raise AssertionError('a skipped proof must not enter TraceRecord validation')
        return orig_has_exact(proof_arg, *args, **kwargs)
    with monkeypatch.context() as skipped_gate: skipped_gate.setattr(evidence_gate, '_has_exact_executed_proof', reject_match_for_nonexecuted_proof); assert run_check([junit_for(without_scenario), skipped]) == 1
    assert run_check([junit_for(proofs), skipped]) == 0
def test_AC8_23_4_junit_parsing_handles_params_and_classes(tmp_path: Path) -> None: 'AC8.23.4'; junit = tmp_path / 'j.xml'; junit.write_text('<testsuite name="s" tests="2"><testcase classname="tests.x.test_mod.TestK" name="test_a[case-1]"/><testcase classname="tests.x.test_mod" name="test_b"/></testsuite>', encoding='utf-8'); executed = collect_executed([junit]); assert ('tests.x.test_mod.TestK', 'test_a') in executed; assert ('tests.x.test_mod', 'test_b') in executed
