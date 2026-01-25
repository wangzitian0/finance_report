import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.integration
def test_moon_cli_available():
    """Verify that 'moon' CLI is available in the environment."""
    moon_path = shutil.which("moon")
    assert moon_path is not None, "Moon CLI not found in PATH"


def test_github_actions_lint():
    """Run actionlint on all workflows to catch syntax and logic errors."""
    workflow_dir = Path(__file__).parent.parent.parent.parent.parent / ".github" / "workflows"
    if not workflow_dir.exists():
        return

    actionlint_path = shutil.which("actionlint")
    if not actionlint_path:
        return

    result = subprocess.run(
        [actionlint_path, "-color"],
        cwd=workflow_dir.parent.parent,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"GitHub Actions Lint Failed:\n{result.stdout}\n{result.stderr}")


def test_docker_compose_integrity():
    """Verify project integrity by checking docker-compose contexts."""
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


@pytest.mark.integration
def test_moon_project_graph():
    """Verify that moon can load the project graph without errors."""
    result = subprocess.run(["moon", "project", "backend", "--json"], capture_output=True, text=True)
    assert result.returncode == 0, f"Moon project graph check failed: {result.stderr}"
    assert "id" in result.stdout


@pytest.mark.integration
def test_moon_env_check_task():
    """Verify that the 'env-check' task is correctly configured in moon."""
    result = subprocess.run(["moon", "project", "backend", "--json"], capture_output=True, text=True)
    assert result.returncode == 0, f"Moon project query failed: {result.stderr}"
    project_data = json.loads(result.stdout)
    tasks = project_data.get("tasks", {})
    assert "env-check" in tasks, f"Task 'env-check' not found in backend project tasks: {list(tasks.keys())}"
