import shutil
import subprocess
from pathlib import Path

import pytest


def test_github_actions_lint():
    """Run actionlint on all workflows to catch syntax and logic errors."""
    workflow_dir = (
        Path(__file__).parent.parent.parent.parent / ".github" / "workflows"
    )
    if not workflow_dir.exists():
        pytest.skip(f"Workflow directory not found at {workflow_dir}")

    # Check if actionlint is available in PATH
    actionlint_path = shutil.which("actionlint")
    if not actionlint_path:
        pytest.skip("actionlint not installed in this environment")

    result = subprocess.run(
        [actionlint_path, "-color"],
        cwd=workflow_dir.parent.parent,  # Run from project root
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(f"GitHub Actions Lint Failed:\n{result.stdout}\n{result.stderr}")


def test_docker_compose_integrity():
    """Verify project integrity by checking docker-compose contexts."""
    import yaml

    compose_path = (
        Path(__file__).parent.parent.parent.parent / "docker-compose.yml"
    )

    with open(compose_path, "r") as f:
        config = yaml.safe_load(f)

    services = config.get("services") or {}
    for service_name, service in services.items():
        if "build" in service:
            context = service["build"].get("context")
            if context:
                # Resolve relative path from project root
                full_path = compose_path.parent / context
                assert (
                    full_path.exists()
                ), f"Service '{service_name}' has non-existent build context: {context}"
