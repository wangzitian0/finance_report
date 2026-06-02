import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_moon_cli_available():
    """AC7.8.1: Moon CLI is available in the environment."""
    moon_path = shutil.which("moon")
    assert moon_path is not None, "Moon CLI not found in PATH"


@pytest.mark.integration
def test_github_actions_lint():
    """AC7.8.2: GitHub Actions workflows pass actionlint validation."""
    workflow_dir = Path(__file__).parent.parent.parent.parent.parent / ".github" / "workflows"
    if not workflow_dir.exists():
        pytest.skip(".github/workflows not found")

    actionlint_path = shutil.which("actionlint")
    if not actionlint_path:
        pytest.skip("actionlint is not installed")

    result = subprocess.run(
        [actionlint_path, "-color"],
        cwd=workflow_dir.parent.parent,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"GitHub Actions Lint Failed:\n{result.stdout}\n{result.stderr}")


def test_docker_compose_integrity():
    """AC7.8.2: Docker compose build contexts exist."""
    import yaml

    compose_path = Path(__file__).parent.parent.parent.parent.parent / "docker-compose.yml"

    with open(compose_path) as f:
        config = yaml.safe_load(f)

    services = config.get("services") or {}
    for service_name, service in services.items():
        if "build" in service:
            context = service["build"].get("context")
            if context:
                full_path = compose_path.parent / context
                assert full_path.exists(), f"Service '{service_name}' has non-existent build context: {context}"


def test_docker_compose_pr_s3_endpoint_is_explicit():
    """AC7.8.2: PR compose S3 endpoint avoids unsupported nested expansion."""
    import yaml

    root = Path(__file__).parent.parent.parent.parent.parent
    sys.path.insert(0, str(root))
    lifecycle = importlib.import_module("tools._lib.dev.pr_preview_lifecycle")
    compose_path = root / "docker-compose.yml"

    with open(compose_path) as f:
        config = yaml.safe_load(f)

    backend_env = config["services"]["backend"]["environment"]
    assert backend_env["S3_ENDPOINT"] == "${S3_ENDPOINT:-http://minio:9000}"

    minio_entrypoint = config["services"]["minio-init"]["entrypoint"]
    assert "$$(seq 1 10)" in minio_entrypoint
    assert "\\$(seq 1 10)" not in minio_entrypoint

    preview_env = lifecycle.build_preview_env(
        pr_number=489,
        commit_sha="abc123",
        registry="ghcr.io",
        image_prefix="wangzitian0/finance_report",
        internal_domain="zitian.party",
    )
    assert preview_env["S3_ENDPOINT"] == "http://finance-report-minio-pr-489:9000"
    assert preview_env["MINIO_ROOT_PASSWORD"] == "minio_local_secret"
    assert preview_env["S3_SECRET_KEY"] == "minio_local_secret"


@pytest.mark.integration
def test_moon_project_graph():
    """AC7.8.3: Moon project graph loads without errors."""
    result = subprocess.run(["moon", "project", "backend", "--json"], capture_output=True, text=True)
    assert result.returncode == 0, f"Moon project graph check failed: {result.stderr}"
    assert "id" in result.stdout
