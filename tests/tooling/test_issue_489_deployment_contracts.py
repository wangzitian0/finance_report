"""Issue #489 deployment and environment verification contracts."""

from __future__ import annotations

import ast
import configparser
import importlib
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
IAC_ROOT = ROOT / "repo" / "finance_report" / "finance_report"


def read(path: Path | str) -> str:
    path = ROOT / path if isinstance(path, str) else path
    return path.read_text(encoding="utf-8")


def load_yaml(path: Path | str) -> dict:
    data = yaml.safe_load(read(path))
    assert isinstance(data, dict), f"{path} must parse as a YAML mapping"
    return data


def load_gitmodules() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(ROOT / ".gitmodules")
    return parser


def class_attrs(path: Path, class_name: str) -> dict[str, object]:
    module = ast.parse(read(path), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            attrs: dict[str, object] = {}
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            attrs[target.id] = ast.literal_eval(item.value)
            return attrs
    raise AssertionError(f"{class_name} not found in {path}")


def class_method_names(path: Path, class_name: str) -> set[str]:
    module = ast.parse(read(path), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name for item in node.body if isinstance(item, ast.FunctionDef)
            }
    raise AssertionError(f"{class_name} not found in {path}")


def template_keys(path: Path) -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", read(path), flags=re.MULTILINE))


def policy_paths(path: Path) -> set[str]:
    return set(re.findall(r'path "([^"]+)"', read(path)))


def shell_text(command: object) -> str:
    if isinstance(command, list):
        return "\n".join(str(part) for part in command)
    return str(command)


def test_infra2_submodule_and_finance_report_iac_tree() -> None:
    """AC7.1.1 AC7.1.2 AC7.1.3: infra2 submodule owns the Finance Report IaC tree."""
    modules = load_gitmodules()
    assert modules.has_section('submodule "repo"')
    assert modules.get('submodule "repo"', "path") == "repo"
    assert (
        modules.get('submodule "repo"', "url")
        == "https://github.com/wangzitian0/infra2"
    )

    assert (ROOT / "repo" / ".git").exists()
    assert (IAC_ROOT / "README.md").is_file()
    for component in ("01.postgres", "02.redis", "10.app"):
        component_dir = IAC_ROOT / component
        assert (component_dir / "compose.yaml").is_file()
        assert (component_dir / "vault-agent.hcl").is_file()
        assert (component_dir / "vault-policy.hcl").is_file()
        assert (component_dir / "secrets.ctmpl").is_file()
        assert (component_dir / "deploy.py").is_file()


def test_postgres_and_redis_iac_services_have_vault_gated_runtime_contracts() -> None:
    """AC7.2.1 AC7.2.2 AC7.2.3 AC7.2.4 AC7.2.5 AC7.3.1 AC7.3.2 AC7.3.3 AC7.3.4 AC7.3.5: stateful services are Vault gated."""
    cases = {
        "01.postgres": {
            "service": "postgres",
            "deployer": "PostgresDeployer",
            "image": "postgres:16-alpine",
            "secret_key": "POSTGRES_PASSWORD",
            "policy_path": "secret/data/finance_report/+/postgres",
            "health_token": "pg_isready -U postgres -d finance_report",
            "data_path": "/data/finance_report/postgres",
            "port": 5432,
        },
        "02.redis": {
            "service": "redis",
            "deployer": "RedisDeployer",
            "image": "redis:alpine",
            "secret_key": "PASSWORD",
            "policy_path": "secret/data/finance_report/+/redis",
            "health_token": 'redis-cli -a "$$PASSWORD" ping',
            "data_path": "/data/finance_report/redis",
            "port": 6379,
        },
    }

    for folder, expected in cases.items():
        component_dir = IAC_ROOT / folder
        compose = load_yaml(component_dir / "compose.yaml")
        services = compose["services"]
        runtime = services[expected["service"]]
        vault_agent = services["vault-agent"]

        assert runtime["image"] == expected["image"]
        assert (
            runtime["container_name"]
            == f"finance_report-{expected['service']}${{ENV_SUFFIX}}"
        )
        assert runtime["depends_on"] == ["vault-agent"]
        assert runtime["labels"] == ["traefik.enable=false"]
        assert "dokploy-network" in runtime["networks"]
        assert any("${DATA_PATH}" in volume for volume in runtime["volumes"])
        assert expected["health_token"] in shell_text(runtime["healthcheck"]["test"])

        startup = shell_text(runtime.get("entrypoint", runtime.get("command")))
        assert "while [ ! -f /secrets/.env ]" in startup
        assert ". /secrets/.env" in startup

        assert vault_agent["image"] == "hashicorp/vault:1.15"
        assert "VAULT_APP_TOKEN is required" in shell_text(vault_agent["entrypoint"])
        assert "exec vault agent -config=/etc/vault/vault-agent.hcl" in shell_text(
            vault_agent["entrypoint"]
        )
        assert "VAULT_ADDR" in vault_agent["environment"]
        assert "VAULT_APP_TOKEN" in vault_agent["environment"]
        assert "test -s /vault/secrets/.env" in shell_text(
            vault_agent["healthcheck"]["test"]
        )
        assert "vault token lookup" in shell_text(vault_agent["healthcheck"]["test"])

        assert template_keys(component_dir / "secrets.ctmpl") == {
            expected["secret_key"]
        }
        paths = policy_paths(component_dir / "vault-policy.hcl")
        assert expected["policy_path"] in paths
        assert "auth/token/lookup-self" in paths

        attrs = class_attrs(component_dir / "deploy.py", expected["deployer"])
        assert attrs["service"] == expected["service"]
        assert attrs["compose_path"].endswith(f"{folder}/compose.yaml")
        assert attrs["data_path"] == expected["data_path"]
        assert attrs["secret_key"] == expected["secret_key"]
        assert attrs["project"] == "finance_report"
        assert attrs["service_port"] == expected["port"]
        assert attrs["subdomain"] is None


def test_app_iac_wires_vault_secrets_health_and_traefik_routes() -> None:
    """AC7.4.1 AC7.4.2 AC7.4.3 AC7.4.4 AC7.4.5 AC7.4.6 AC7.5.1 AC7.5.2 AC7.5.3 AC7.5.4 AC7.5.5 AC7.6.2 AC7.9.6 AC7.9.7 AC7.9.8: app deployment is Vault and health gated."""
    app_dir = IAC_ROOT / "10.app"
    compose = load_yaml(app_dir / "compose.yaml")
    services = compose["services"]
    backend = services["backend"]
    frontend = services["frontend"]
    vault_agent = services["vault-agent"]

    assert backend["depends_on"]["vault-agent"]["condition"] == "service_healthy"
    assert frontend["depends_on"]["backend"]["condition"] == "service_healthy"
    assert backend["image"].startswith("ghcr.io/wangzitian0/finance_report-backend:")
    assert frontend["image"].startswith("ghcr.io/wangzitian0/finance_report-frontend:")

    backend_entrypoint = shell_text(backend["entrypoint"])
    assert "[CHECKPOINT-1] Waiting for Vault secrets" in backend_entrypoint
    assert "[CHECKPOINT-2] Starting database migrations" in backend_entrypoint
    assert "alembic upgrade head" in backend_entrypoint
    assert "[CHECKPOINT-3] Starting uvicorn" in backend_entrypoint
    assert ". /secrets/.env" in backend_entrypoint

    assert backend["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-f",
        "http://localhost:8000/health",
    ]
    assert frontend["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-f",
        "http://localhost:3000",
    ]

    labels = "\n".join(backend["labels"] + frontend["labels"])
    assert "traefik.enable=true" in labels
    assert "PathPrefix(`/api`)" in labels
    assert "stripprefix.prefixes=/api" in labels
    assert "loadbalancer.server.port=8000" in labels
    assert "loadbalancer.server.port=3000" in labels
    assert "finance-report-web${ENV_DOMAIN_SUFFIX}.priority=1" in labels

    assert "VAULT_APP_TOKEN is required" in shell_text(vault_agent["entrypoint"])
    assert "vault token lookup" in shell_text(vault_agent["healthcheck"]["test"])
    assert "IAC_CONFIG_HASH" in vault_agent["environment"]

    app_template = read(app_dir / "secrets.ctmpl")
    keys = template_keys(app_dir / "secrets.ctmpl")
    for key in (
        "DATABASE_URL",
        "REDIS_URL",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "S3_BUCKET",
        "ZAI_API_KEY",
    ):
        assert key in keys
    assert "secret/data/finance_report/%s/postgres" in app_template
    assert "secret/data/finance_report/%s/redis" in app_template
    assert "finance_report-postgres%s:5432" in app_template
    assert "finance_report-redis%s:6379/0" in app_template
    assert "printf" in app_template

    paths = policy_paths(app_dir / "vault-policy.hcl")
    assert "secret/data/finance_report/+/app" in paths
    assert "secret/data/finance_report/+/postgres" in paths
    assert "secret/data/finance_report/+/redis" in paths
    assert "auth/token/lookup-self" in paths

    attrs = class_attrs(app_dir / "deploy.py", "AppDeployer")
    assert attrs["service"] == "app"
    assert attrs["compose_path"].endswith("10.app/compose.yaml")
    assert attrs["secret_key"] == "DATABASE_URL"
    assert attrs["service_port"] == 3000
    assert {"pre_compose", "_ensure_minio_bucket"} <= class_method_names(
        app_dir / "deploy.py", "AppDeployer"
    )

    readme = read(app_dir / "README.md")
    for key in (
        "DATABASE_URL",
        "REDIS_URL",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "ZAI_API_KEY",
    ):
        assert key in readme


def test_pr_preview_deploy_gate_exercises_health_smoke_e2e_and_storage_paths() -> None:
    """AC7.9.1 AC7.9.2 AC7.9.3 AC7.9.4 AC7.9.5: PR preview deploy verifies runtime health, API, domain, and storage upload paths."""
    lifecycle = importlib.import_module("tools._lib.dev.pr_preview_lifecycle")
    workflow = read(".github/workflows/pr-test.yml")
    smoke = read("tools/_lib/shell/smoke_test.sh")
    hard_gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")

    assert "name: Deploy Test Environment" in workflow
    assert "python tools/pr_preview_lifecycle.py" in workflow
    preview_env = lifecycle.build_preview_env(
        pr_number=489,
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="wangzitian0/finance_report",
        internal_domain="zitian.party",
    )
    assert preview_env["COMPOSE_PROFILES"] == "infra,app"
    assert preview_env["DB_HOST"] == "finance-report-db-pr-489"
    assert preview_env["S3_HOST"] == "finance-report-minio-pr-489"
    assert preview_env["S3_ENDPOINT"] == "http://finance-report-minio-pr-489:9000"
    assert 'echo "S3_BUCKET=statements"' in workflow or "S3_BUCKET:-statements" in read(
        "docker-compose.yml"
    )
    assert "Wait for API readiness" in workflow
    assert 'url = os.environ["APP_URL"] + "/api/health"' in workflow
    assert "bash tools/smoke_test.sh" in workflow
    assert 'pytest tests/e2e -v -m "(smoke or e2e) and not llm"' in workflow
    assert "| API Health | [${url}/api/health](${url}/api/health) |" in workflow

    assert 'wait_for_endpoint "API Health" "$BASE_URL/api/health"' in smoke
    assert 'wait_for_endpoint "Frontend Ready" "$BASE_URL/"' in smoke
    assert 'check_endpoint "DB Connectivity" "$BASE_URL/api/health" "healthy"' in smoke
    assert 'check_endpoint "Ping API" "$BASE_URL/api/ping"' in smoke
    assert 'check_endpoint "API Docs" "$BASE_URL/api/docs"' in smoke

    assert "test_statement_upload_to_dashboard_vision_hard_gate" in hard_gate
    assert "/api/statements/upload" in hard_gate
    assert "dashboard" in hard_gate.lower()
