import shutil
import subprocess
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

    compose_path = Path(__file__).parent.parent.parent.parent.parent / "docker-compose.yml"
    workflow_path = Path(__file__).parent.parent.parent.parent.parent / ".github" / "workflows" / "pr-test.yml"

    with open(compose_path) as f:
        config = yaml.safe_load(f)

    backend_env = config["services"]["backend"]["environment"]
    assert backend_env["S3_ENDPOINT"] == "${S3_ENDPOINT:-http://minio:9000}"

    minio_entrypoint = config["services"]["minio-init"]["entrypoint"]
    assert "$$(seq 1 10)" in minio_entrypoint
    assert "\\$(seq 1 10)" not in minio_entrypoint

    workflow = workflow_path.read_text()
    assert 'echo "S3_ENDPOINT=http://finance-report-minio-pr-$PR_NUMBER:9000"' in workflow
    assert 'echo "MINIO_ROOT_PASSWORD=minio_local_secret"' in workflow
    assert 'echo "S3_SECRET_KEY=minio_local_secret"' in workflow


@pytest.mark.integration
def test_moon_project_graph():
    """AC7.8.3: Moon project graph loads without errors."""
    result = subprocess.run(["moon", "project", "backend", "--json"], capture_output=True, text=True)
    assert result.returncode == 0, f"Moon project graph check failed: {result.stderr}"
    assert "id" in result.stdout
