'AC7.18.1 EPIC-007'; from __future__ import annotations; from pathlib import Path; import yaml; REPO_ROOT = Path(__file__).resolve().parents[2]; CI_WORKFLOW = REPO_ROOT / '.github' / 'workflows' / 'ci.yml'
def _container_images_job() -> dict: workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding='utf-8')); jobs = workflow['jobs']; assert 'container-images' in jobs, 'ci.yml must define the container-images job'; return jobs['container-images']
_step_names = lambda job: [str(step.get('name', '')) for step in job.get('steps', [])]
def _step_effective_run(step: dict) -> str:
    run = str(step.get('run', '')); uses = str(step.get('uses', ''))
    if uses.startswith('./.github/actions/'):
        action_file = REPO_ROOT / uses.removeprefix('./') / 'action.yml'
        if action_file.exists(): action_data = yaml.safe_load(action_file.read_text(encoding='utf-8')); runs = [str(st.get('run', '')) for st in action_data.get('runs', {}).get('steps', [])]; with_inputs = ' '.join((f'{k}: {v}' for k, v in step.get('with', {}).items())); return run + ' ' + ' '.join(runs) + ' ' + with_inputs
    return run
def _secret_scan_step(job: dict) -> dict:
    for step in job.get('steps', []):
        text = (str(step.get('name', '')) + ' ' + str(step.get('run', '')) + ' ' + str(step.get('uses', ''))).lower()
        if 'gitleaks' in text and 'secret' in text: return step
    raise AssertionError('container-images job has no build-context gitleaks secret-scan step')
def test_AC7_18_1_container_images_job_has_build_context_secret_scan() -> None: 'AC-testing.secret-scan.2 AC7.18.1'; job = _container_images_job(); step = _secret_scan_step(job); run = _step_effective_run(step); assert 'gitleaks' in run, 'secret-scan step must invoke gitleaks'; assert 'apps/' in run or 'matrix.component' in run, 'secret-scan step must scan the per-component build context (apps/<component>)'; _m1_job = _container_images_job(); _m1_step = _secret_scan_step(_m1_job); _m1_run = _step_effective_run(_m1_step); assert '--exit-code 1' in _m1_run or '--exit-code=1' in _m1_run, 'build-context gitleaks scan must fail closed (--exit-code 1)'; assert '--no-git' in _m1_run, 'build-context scan must use --no-git (scan the context tree)'; assert _m1_step.get('continue-on-error', False) is not True, 'secret-scan step must not be continue-on-error (would not fail the build)'; assert '|| true' not in _m1_run, 'secret-scan step must not swallow failures with `|| true`'; assert '--redact' in _m1_run, 'secret-scan must keep findings visible via --redact'; _m1_names = _step_names(_m1_job); _m1_scan_idx = _m1_names.index(str(_m1_step.get('name', ''))); _m1_build_idx = next((_m1_i for _m1_i, _m1_n in enumerate(_m1_names) if 'build' in _m1_n.lower() and 'image' in _m1_n.lower()), None); assert _m1_build_idx is not None, 'container-images job must have an image build step'; assert _m1_scan_idx < _m1_build_idx, 'secret-scan must run BEFORE the image build (fail before a secret is baked in)'
