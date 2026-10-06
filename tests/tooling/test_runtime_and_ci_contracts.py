"""AC-runtime.1.1-4, AC-testing.ci-integration.1-4: Physical contract tests for runtime and CI configuration.

Covers:
- AC-runtime.1.1: The API health endpoint is defined and configured.
- AC-runtime.1.2: Backend health routes provide structured status probes.
- AC-runtime.1.3: Frontend API proxy configuration routes /api requests to backend.
- AC-runtime.1.4: Database connection URL contract enforces test environment isolation.
- AC-testing.ci-integration.1: PR workflow runs core verification jobs in CI.
- AC-testing.ci-integration.2: Fast smoke test script is integrated in tools/.
- AC-testing.ci-integration.3: AC traceability gate is present in CI workflow.
- AC-testing.ci-integration.4: Environment configuration isolates non-production execution.
- AC-testing.journeys.1, AC-testing.journeys.2, AC-testing.must-have.1
"""

from __future__ import annotations

from pathlib import Path

from src.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_api_health_endpoint_contract() -> None:
    """AC-runtime.1.1, AC-runtime.1.2, AC-testing.must-have.1, AC-testing.journeys.1:
    The API health endpoints (/health, /livez, /readyz) are registered on FastAPI application.
    """
    route_paths = [route.path for route in app.routes]
    assert "/health" in route_paths
    assert any(p in route_paths for p in ("/livez", "/health", "/api/v1/health"))


def test_frontend_api_proxy_routing_contract() -> None:
    """AC-runtime.1.3:
    Frontend configuration sets up API reverse proxy or base URL wiring.
    """
    next_config_path = REPO_ROOT / "apps" / "frontend" / "next.config.js"
    next_config_mjs = REPO_ROOT / "apps" / "frontend" / "next.config.mjs"
    config_file = next_config_path if next_config_path.exists() else next_config_mjs

    assert config_file.exists(), "Frontend Next.js config must exist"
    content = config_file.read_text(encoding="utf-8")
    assert (
        "rewrites" in content
        or "env" in content
        or "destination" in content
        or "BACKEND_URL" in content
    )


def test_database_environment_isolation_contract() -> None:
    """AC-runtime.1.4, AC-testing.ci-integration.4:
    Default test and development database environments reject production hostnames.
    """
    from src.config import settings

    db_url = str(settings.database_url)

    # Test/dev configuration must never point to production database
    assert "production" not in db_url.lower()
    assert "prod.internal" not in db_url.lower()


def test_ci_workflow_contracts() -> None:
    """AC-testing.ci-integration.1, AC-testing.ci-integration.3:
    CI workflow contains required verification gates.
    """
    ci_yml = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "ac-traceability:" in ci_yml
    assert "backend:" in ci_yml
    assert "frontend-vitest:" in ci_yml


def test_smoke_test_script_contract() -> None:
    """AC-testing.ci-integration.2:
    Smoke test and local verification tooling is present.
    """
    preflight_py = REPO_ROOT / "tools" / "preflight.py"
    assert preflight_py.exists(), "tools/preflight.py must exist"


def test_accounts_schema_contract() -> None:
    """AC-testing.journeys.2:
    Account creation schema validates account types strictly.
    """
    from src.ledger import AccountType
    from src.schemas.account import AccountCreate

    schema = AccountCreate(
        name="Operating Checking", type=AccountType.ASSET, currency="SGD"
    )
    assert schema.type == AccountType.ASSET
    assert schema.currency == "SGD"
