from __future__ import annotations

import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_AC8_13_44_bootstrap_script_installs_local_toolchain_and_project_deps() -> None:
    """AC8.13.44: The local bootstrap command owns runtime and dependency setup."""
    script = ROOT / "tools" / "bootstrap.sh"

    assert script.exists()
    assert script.stat().st_mode & stat.S_IXUSR

    content = script.read_text(encoding="utf-8")
    for expected in (
        "uv python install",
        "nvm install",
        "@moonrepo/cli",
        "moon run :setup",
        "uvx pre-commit install",
    ):
        assert expected in content


def test_AC8_13_44_bootstrap_reports_container_runtime_prerequisite() -> None:
    """AC8.13.44: Bootstrap diagnoses the host container runtime instead of hiding it."""
    content = (ROOT / "tools" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "docker" in content
    assert "podman" in content
    assert "container runtime" in content.lower()


def test_AC8_13_44_readme_documents_one_command_and_host_prerequisite() -> None:
    """AC8.13.44: README exposes one setup command and the host-level prerequisite."""
    content = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "bash tools/bootstrap.sh" in content
    assert "Docker Desktop" in content
    assert "Podman" in content


def test_AC8_13_44_submodule_hook_accepts_standard_gitfile_checkout() -> None:
    """AC8.13.44: The pre-commit submodule hook supports normal gitfile submodules."""
    content = (ROOT / "tools" / "check_repo_submodule.sh").read_text(encoding="utf-8")

    assert '[ ! -e "repo/.git" ]' in content
    assert 'if [ "$CURRENT_SHA" != "$LATEST_SHA" ]; then' in content


def test_AC8_13_44_root_moon_tasks_use_python3_entrypoint() -> None:
    """AC8.13.44: Moon tasks avoid relying on a nonstandard `python` command."""
    content = (ROOT / "moon.yml").read_text(encoding="utf-8")

    assert "python3 tools/cli.py setup" in content
    assert "python tools/cli.py" not in content
