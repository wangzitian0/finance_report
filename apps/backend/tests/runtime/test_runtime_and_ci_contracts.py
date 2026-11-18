from __future__ import annotations
from pathlib import Path
from fastapi.routing import iter_route_contexts
from src.main import app
REPO_ROOT = Path(__file__).resolve().parents[4]
def test_api_health_endpoint_contract() -> None:
    route_paths = [getattr(context.route, "path", None) for context in iter_route_contexts(app.routes)]
    assert "/health" in route_paths
def test_frontend_api_proxy_routing_contract() -> None: next_config_path = REPO_ROOT / 'apps' / 'frontend' / 'next.config.js'; next_config_mjs = REPO_ROOT / 'apps' / 'frontend' / 'next.config.mjs'; config_file = next_config_path if next_config_path.exists() else next_config_mjs; assert config_file.exists(), 'Frontend Next.js config must exist'; content = config_file.read_text(encoding='utf-8'); assert 'rewrites' in content or 'env' in content or 'destination' in content or ('BACKEND_URL' in content)
def test_database_environment_isolation_contract() -> None: from src.config import settings; db_url = str(settings.database_url); assert 'production' not in db_url.lower(); assert 'prod.internal' not in db_url.lower()
def test_ci_workflow_contracts() -> None: ci_yml = (REPO_ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8'); assert 'backend:' in ci_yml; assert 'frontend-vitest:' in ci_yml; assert 'ac-traceability:' not in ci_yml
def test_smoke_test_script_contract() -> None: preflight_py = REPO_ROOT / 'tools' / 'preflight.py'; assert preflight_py.exists(), 'tools/preflight.py must exist'
def test_accounts_schema_contract() -> None: from src.ledger import AccountType; from src.schemas.account import AccountCreate; schema = AccountCreate(name='Operating Checking', type=AccountType.ASSET, currency='SGD'); assert schema.type == AccountType.ASSET; assert schema.currency == 'SGD'
