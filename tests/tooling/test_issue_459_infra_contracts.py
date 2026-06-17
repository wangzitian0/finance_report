"""Behavioral replacements for legacy AC traceability stubs.

These tests exercise repository configuration, deployment templates, and PDF fixture
tooling that used to be represented only by apps/backend/tests/_ac_stubs.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_FIXTURES = REPO_ROOT / "tools" / "_lib" / "pdf_fixtures"
FINANCE_REPORT_IAC = REPO_ROOT / "repo" / "finance_report" / "finance_report"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(_read(path))
    assert isinstance(data, dict), f"{path} must parse as a YAML mapping"
    return data


def _assert_python_defines_class(path: Path, class_name: str) -> None:
    module = ast.parse(_read(path), filename=str(path))
    classes = {node.name for node in module.body if isinstance(node, ast.ClassDef)}
    assert class_name in classes


def _assert_python_defines_function(path: Path, function_name: str) -> None:
    module = ast.parse(_read(path), filename=str(path))
    functions = {
        node.name
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert function_name in functions


def test_epic_007_finance_report_iac_components() -> None:
    """Finance Report IaC components exist.

    AC7.1.2 AC7.1.3 AC7.2.1 AC7.2.2 AC7.2.3 AC7.2.4 AC7.2.5
    AC7.3.1 AC7.3.2 AC7.3.3 AC7.3.4 AC7.3.5
    AC7.4.1 AC7.4.2 AC7.4.3 AC7.4.4 AC7.4.5 AC7.4.6
    """
    assert (REPO_ROOT / "README.md").exists()
    assert (REPO_ROOT / "apps" / "backend" / "src").is_dir()
    assert (REPO_ROOT / "apps" / "frontend" / "src").is_dir()
    assert (FINANCE_REPORT_IAC / "README.md").exists()

    components = {
        "01.postgres": ("postgres", "PostgresDeployer"),
        "02.redis": ("redis", "RedisDeployer"),
        "10.app": ("app", "AppDeployer"),
    }
    for folder, (service_hint, deployer_class) in components.items():
        component_dir = FINANCE_REPORT_IAC / folder
        compose = _load_yaml(component_dir / "compose.yaml")
        services = compose.get("services", {})
        assert service_hint in yaml.safe_dump(services).lower()
        assert (component_dir / "vault-agent.hcl").exists()
        assert "path" in _read(component_dir / "vault-policy.hcl")
        assert "{{" in _read(component_dir / "secrets.ctmpl")
        _assert_python_defines_class(component_dir / "deploy.py", deployer_class)

    app_compose = _load_yaml(FINANCE_REPORT_IAC / "10.app" / "compose.yaml")
    labels = "\n".join(
        str(label)
        for service in app_compose["services"].values()
        for label in service.get("labels", [])
    )
    assert "traefik" in labels.lower()


def test_epic_007_secret_and_health_contracts_are_documented() -> None:
    """Secrets and health contracts are documented.

    AC7.5.1 AC7.5.2 AC7.5.3 AC7.5.4 AC7.5.5 AC7.6.2
    AC7.9.1 AC7.9.2 AC7.9.3 AC7.9.4 AC7.9.5 AC7.9.6 AC7.9.7 AC7.9.8
    """
    app_template = _read(FINANCE_REPORT_IAC / "10.app" / "secrets.ctmpl")
    postgres_template = _read(FINANCE_REPORT_IAC / "01.postgres" / "secrets.ctmpl")
    redis_template = _read(FINANCE_REPORT_IAC / "02.redis" / "secrets.ctmpl")
    deployment_ssot = _read(REPO_ROOT / "docs" / "ssot" / "deployment.md")
    root_env = _read(REPO_ROOT / ".env.example")

    assert "DATABASE_URL" in app_template
    assert "REDIS_URL" in app_template
    assert "S3_" in app_template
    assert "ZAI_API_KEY" in app_template or "AI_API_KEY" in app_template
    assert "POSTGRES" in postgres_template
    assert "PASSWORD" in redis_template
    assert "vault" in deployment_ssot.lower()
    assert "health" in deployment_ssot.lower()
    assert "INTERNAL_DOMAIN" in _read(FINANCE_REPORT_IAC / "10.app" / "compose.yaml")
    assert "DATABASE_URL" in root_env and "REDIS_URL" in root_env


def test_epic_009_pdf_fixture_tooling_contracts() -> None:
    """PDF fixture tooling modules, templates, and docs exist."""
    _assert_python_defines_class(
        PDF_FIXTURES / "generators" / "base_generator.py", "BasePDFGenerator"
    )
    _assert_python_defines_class(
        PDF_FIXTURES / "generators" / "dbs_generator.py", "DBSGenerator"
    )
    _assert_python_defines_class(
        PDF_FIXTURES / "generators" / "cmb_generator.py", "CMBGenerator"
    )
    _assert_python_defines_class(
        PDF_FIXTURES / "generators" / "mari_generator.py", "MariGenerator"
    )
    _assert_python_defines_function(
        PDF_FIXTURES / "generators" / "font_utils.py", "register_chinese_fonts"
    )
    _assert_python_defines_function(
        PDF_FIXTURES / "data" / "fake_data.py", "generate_dbs_transactions"
    )
    _assert_python_defines_class(
        PDF_FIXTURES / "analyzers" / "template_extractor.py", "TemplateExtractor"
    )
    _assert_python_defines_class(
        PDF_FIXTURES / "validators" / "pdf_validator.py", "PDFValidator"
    )

    for template in ("dbs_template.yaml", "cmb_template.yaml", "mari_template.yaml"):
        data = _load_yaml(PDF_FIXTURES / "templates" / template)
        assert "source" in json.dumps(data).lower()

    assert (PDF_FIXTURES / "generate_pdf_fixtures.py").exists()
    assert (PDF_FIXTURES / "README.md").exists()
    assert (PDF_FIXTURES / "FONT_HANDLING.md").exists()
    assert "*.pdf" in _read(PDF_FIXTURES / ".gitignore")


def test_epic_009_generator_templates_and_cli_options() -> None:
    """PDF generators load templates and expose CLI options."""
    generator_text = _read(PDF_FIXTURES / "generate_pdf_fixtures.py")
    analyzer_text = _read(PDF_FIXTURES / "analyzers" / "analyze_pdf.py")
    cmb_text = _read(PDF_FIXTURES / "generators" / "cmb_generator.py")
    mari_template_text = _read(PDF_FIXTURES / "templates" / "mari_template.yaml")
    fake_data_text = _read(PDF_FIXTURES / "data" / "fake_data.py")

    for source in ("DBS", "CMB", "MariGenerator"):
        assert source in generator_text
    assert "Decimal" in generator_text
    assert "%y%m" in generator_text or "strftime" in generator_text
    assert "generate_" in fake_data_text and "transactions" in fake_data_text
    assert "{source}_template.yaml" in generator_text
    assert "register_chinese_fonts" in cmb_text
    assert "{source}_template.yaml" in generator_text
    assert "interest_details" in mari_template_text
    assert "--source" in generator_text
    assert "--output" in generator_text
    assert "--input" in analyzer_text and "--output" in analyzer_text


def test_epic_010_observability_docs_and_templates() -> None:
    """Observability SSOT, env docs, and app templates stay aligned."""
    observability = _read(REPO_ROOT / "docs" / "ssot" / "observability.md")
    ssot_index = _read(REPO_ROOT / "docs" / "ssot" / "README.md")
    env_example = _read(REPO_ROOT / ".env.example")
    config_py = _read(REPO_ROOT / "apps" / "backend" / "src" / "config.py")
    app_template = _read(FINANCE_REPORT_IAC / "10.app" / "secrets.ctmpl")
    app_readme = _read(FINANCE_REPORT_IAC / "10.app" / "README.md")
    app_compose = _read(FINANCE_REPORT_IAC / "10.app" / "compose.yaml")

    for key in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SERVICE_NAME"):
        assert key in observability
        assert key in env_example
        assert key.lower() in config_py.lower()
        assert key in app_template
    assert "observability" in observability.lower()
    assert "ci-cd" in ssot_index.lower()
    assert "otel" in app_readme.lower()
    assert "IAC_CONFIG_HASH" in app_compose
    assert "printf" in app_template
    # Genuine secrets must fall back to EMPTY (Vault-sourced), never a baked literal.
    # Non-secret OTEL telemetry config (Infra-014 #360/#376) legitimately carries
    # canonical defaults, so assert secret hygiene directly instead of banning the
    # substring "default" outright (which now false-positives on the telemetry block).
    for secret_key in ("SECRET_KEY", "S3_SECRET_KEY", "S3_ACCESS_KEY"):
        secret_line = next(
            line for line in app_template.splitlines() if line.startswith(f"{secret_key}=")
        )
        assert secret_line.endswith('{{ else }}""{{ end }}'), (
            f"{secret_key} must fall back to empty (Vault-sourced), not a baked default: {secret_line}"
        )
    assert "optional" in observability.lower()
    assert "redact" in observability.lower() or "sensitive" in observability.lower()
    assert "json" in observability.lower()


def test_epic_012_and_014_tooling_contracts() -> None:
    """Moon, schema, and quality tooling contracts exist."""
    assert (REPO_ROOT / "moon.yml").exists()
    assert (REPO_ROOT / ".moon" / "workspace.yml").exists()

    statements_router = _read(
        REPO_ROOT / "apps" / "backend" / "src" / "routers" / "statements.py"
    )
    review_schemas = _read(
        REPO_ROOT / "apps" / "backend" / "src" / "schemas" / "review.py"
    )
    statement_parsing = _read(
        REPO_ROOT / "apps" / "backend" / "src" / "services" / "statement_parsing.py"
    )
    pyproject = _read(REPO_ROOT / "apps" / "backend" / "pyproject.toml")
    precommit = _read(REPO_ROOT / ".pre-commit-config.yaml")

    assert "StatementReviewResponse" in review_schemas
    assert "StatementReviewResponse" in statements_router
    assert "parse_statement_background" in statement_parsing
    assert "cov-fail-under" in pyproject and "96" in pyproject
    assert "mypy" in precommit
    assert (REPO_ROOT / "tools" / "validate_schemas.py").exists()
    assert (REPO_ROOT / "tools" / "check_env_keys.py").exists()
    assert (REPO_ROOT / "tools" / "smoke_test.sh").exists()
    assert (REPO_ROOT / "tools" / "generate_ac_registry.py").exists()
