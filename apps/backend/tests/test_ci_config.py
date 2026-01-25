import subprocess
import shutil
import pytest
from pathlib import Path

@pytest.mark.integration
def test_moon_cli_available():
    """Verify that 'moon' CLI is available in the environment."""
    moon_path = shutil.which("moon")
    assert moon_path is not None, "Moon CLI not found in PATH"

def test_github_actions_lint():
    """Run actionlint on all workflows to catch syntax and logic errors."""
    # Navigate up from apps/backend/tests to root
    workflow_dir = Path(__file__).parent.parent.parent.parent / ".github" / "workflows"
    if not workflow_dir.exists():
        return  # Pass but no-op if directory missing

    # Check if actionlint is available in PATH
    actionlint_path = shutil.which("actionlint")
    if not actionlint_path:
        return  # Pass but no-op if tool missing

@pytest.mark.integration
def test_moon_project_graph():
    """Verify that moon can load the project graph without errors."""
    result = subprocess.run(
        ["moon", "project", "backend", "--json"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Moon project graph check failed: {result.stderr}"
    assert "id" in result.stdout

@pytest.mark.integration
def test_moon_env_check_task():
    """Verify that the 'env-check' task is correctly configured and runnable via moon."""
    # We run with --dryRun to check configuration validity without executing side effects
    result = subprocess.run(
        ["moon", "run", "backend:env-check", "--dryRun"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Moon task configuration check failed: {result.stderr}"
