from __future__ import annotations; import json; from pathlib import Path; from xml.etree import ElementTree; from common.runtime import tier2_http_e2e; ROOT = Path(__file__).resolve().parents[2]
def test_AC8_18_1_tier2_http_command_fails_closed_without_deployed_inputs(capsys) -> None: 'AC-testing.tier2.1 AC8.18.1'; status = tier2_http_e2e.run([], environ={}); assert status == 2; assert 'base_url' in capsys.readouterr().err
def test_AC8_18_2_tier2_http_report_is_proof_tiered_and_skip_ineligible(tmp_path: Path) -> None: 'AC-testing.tier2.2 AC8.18.2'; report_path = tmp_path / 'tier2.json'; junit_path = tmp_path / 'tier2.xml'; status = tier2_http_e2e.run(['--advisory-if-missing', '--json-report', str(report_path), '--junit-xml', str(junit_path)], environ={}); assert status == 0; report = json.loads(report_path.read_text(encoding='utf-8')); assert report['proof_tier'] == 'tier2_http'; assert report['status'] == 'not_run'; assert report['proof_eligible'] is False; assert report['env_gated'] is True; suite = ElementTree.parse(junit_path).getroot(); properties_node = suite.find('properties'); assert properties_node is not None; properties = {prop.attrib['name']: prop.attrib['value'] for prop in properties_node}; assert properties['proof_tier'] == 'tier2_http'; assert properties['proof_eligible'] == 'False'; assert suite.attrib['skipped'] == '1'
def test_AC8_18_2_tier2_http_success_report_requires_real_http_checks() -> None:
    'AC8.18.2'
    def requester(url: str, _timeout_seconds: float) -> tier2_http_e2e.HttpResponse:
        if url.endswith('/api/health'): return tier2_http_e2e.HttpResponse(200, '{"status":"healthy","git_sha":"abc123"}')
        if url.endswith('/api/ping'): return tier2_http_e2e.HttpResponse(200, '{"ok":true}')
        if url.endswith('/api/statements'): return tier2_http_e2e.HttpResponse(401, '{"detail":"Not authenticated"}')
        return tier2_http_e2e.HttpResponse(200, '<html></html>')
    report = tier2_http_e2e.run_tier2_http_e2e(tier2_http_e2e.Tier2Config(base_url='https://report-staging.example.com', expected_sha='abc123'), requester=requester); assert report['proof_tier'] == 'tier2_http'; assert report['status'] == 'passed'; assert report['proof_eligible'] is True; assert [check['name'] for check in report['checks']] == ['api_health_http_200', 'deployed_version_matches_expected', 'api_ping_http_200', 'frontend_http_success', 'protected_api_requires_auth']
def test_AC8_18_2_tier2_http_handles_non_object_health_json() -> None:
    'AC8.18.2'
    def requester(url: str, _timeout_seconds: float) -> tier2_http_e2e.HttpResponse:
        if url.endswith('/api/health'): return tier2_http_e2e.HttpResponse(200, '[]')
        if url.endswith('/api/ping'): return tier2_http_e2e.HttpResponse(200, '{"ok":true}')
        if url.endswith('/api/statements'): return tier2_http_e2e.HttpResponse(401, '{"detail":"Not authenticated"}')
        return tier2_http_e2e.HttpResponse(200, '<html></html>')
    report = tier2_http_e2e.run_tier2_http_e2e(tier2_http_e2e.Tier2Config(base_url='https://report-staging.example.com', expected_sha='abc123'), requester=requester); version_check = next((check for check in report['checks'] if check['name'] == 'deployed_version_matches_expected')); assert report['status'] == 'failed'; assert version_check['passed'] is False
def test_AC8_18_2_tier2_http_accepts_short_and_full_sha_match() -> None:
    'AC8.18.2'
    def requester(url: str, _timeout_seconds: float) -> tier2_http_e2e.HttpResponse:
        if url.endswith('/api/health'): return tier2_http_e2e.HttpResponse(200, '{"status":"healthy","git_sha":"abc123456789"}')
        if url.endswith('/api/ping'): return tier2_http_e2e.HttpResponse(200, '{"ok":true}')
        if url.endswith('/api/statements'): return tier2_http_e2e.HttpResponse(401, '{"detail":"Not authenticated"}')
        return tier2_http_e2e.HttpResponse(200, '<html></html>')
    report = tier2_http_e2e.run_tier2_http_e2e(tier2_http_e2e.Tier2Config(base_url='https://report-staging.example.com', expected_sha='abc123'), requester=requester); assert report['status'] == 'passed'
def test_AC8_18_3_staging_workflow_runs_tier2_http_before_tier3_browser_e2e() -> None: 'AC-testing.tier2.3 AC8.18.3'; from infra2_sdk.manifests import load_hooks_manifest; manifest = load_hooks_manifest(ROOT / 'runtime-hooks.manifest.json'); e2e_step = manifest.slots['staging_gate'].run; smoke_index = e2e_step.index('tools/smoke_test.sh'); tier3_index = e2e_step.index('pytest "${STAGING_CORE_E2E_TESTS[@]}"'); assert smoke_index < tier3_index; assert 'bash tools/smoke_test.sh "$INFRA2_HOOK_APP_URL"' in e2e_step; 'AC8.18.3'; 'AC8.18.3'; _m1_matrix = (ROOT / 'common/testing/data/test-execution-matrix.yaml').read_text(encoding='utf-8'); assert 'path: tools/tier2_http_e2e.py' in _m1_matrix; assert 'stage: deployment_tier2_http_e2e' in _m1_matrix
