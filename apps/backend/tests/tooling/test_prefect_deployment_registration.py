'AC-extraction.1913.3 EPIC-019'; from __future__ import annotations; import pytest; pytestmark = pytest.mark.no_db
def test_AC_extraction_1913_3_registration_script_targets_the_deployment_api_submits_to(): from scripts import register_prefect_deployment as registration_module; from src.extraction.extension.statement_flow import parse_statement_flow; from src.extraction.extension.statement_pipeline import PARSE_DEPLOYMENT; registered_as = f'{parse_statement_flow.name}/{registration_module.DEPLOYMENT_NAME}'; assert registered_as == PARSE_DEPLOYMENT; assert registration_module.WORK_POOL_NAME == 'finance-report'; from pathlib import Path; _m1_entrypoint = Path('scripts/prefect_worker_entrypoint.sh').read_text(); _m1_register_line = _m1_entrypoint.index('register_prefect_deployment.py'); _m1_worker_start_line = _m1_entrypoint.index('prefect worker start'); assert _m1_register_line < _m1_worker_start_line; assert '--pool finance-report' in _m1_entrypoint; assert '--pool default' not in _m1_entrypoint
def test_AC_extraction_1913_3_registration_script_deploys_from_local_source(monkeypatch):
    calls: dict = {}
    class _FakeSourcedFlow:
        def deploy(self, *, name: str, work_pool_name: str): calls['name'] = name; calls['work_pool_name'] = work_pool_name
    def fake_from_source(self, *, source: str, entrypoint: str): calls['source'] = source; calls['entrypoint'] = entrypoint; return _FakeSourcedFlow()
    import src.extraction.extension.statement_flow as statement_flow_module; monkeypatch.setattr(statement_flow_module.parse_statement_flow.__class__, 'from_source', fake_from_source); from scripts import register_prefect_deployment
    async def _fake_ensure_pool(name: str) -> None: calls['ensured_pool'] = name
    monkeypatch.setattr(register_prefect_deployment, '_ensure_work_pool_exists', _fake_ensure_pool); assert register_prefect_deployment.main() == 0; assert calls['source'] == str(register_prefect_deployment.BACKEND_ROOT); assert calls['entrypoint'] == 'src/extraction/extension/statement_flow.py:parse_statement_flow'; assert calls['name'] == 'parse-statement'; assert calls['work_pool_name'] == 'finance-report'; assert calls['ensured_pool'] == 'finance-report'
def test_AC_extraction_1913_3_ensure_work_pool_exists_swallows_concurrent_create_race(monkeypatch):
    import asyncio; from contextlib import asynccontextmanager; from prefect.exceptions import ObjectAlreadyExists, ObjectNotFound; calls = {'create': 0}
    class _FakeClient:
        async def read_work_pool(self, name: str) -> None: raise ObjectNotFound(http_exc=Exception('404'))
        async def create_work_pool(self, work_pool) -> None: calls['create'] += 1; raise ObjectAlreadyExists(http_exc=Exception('409'))
    @asynccontextmanager
    async def fake_get_client(): yield _FakeClient()
    import prefect.client.orchestration as orchestration_module; monkeypatch.setattr(orchestration_module, 'get_client', fake_get_client); from scripts.register_prefect_deployment import _ensure_work_pool_exists; asyncio.run(_ensure_work_pool_exists('finance-report')); assert calls['create'] == 1
