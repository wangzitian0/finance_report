import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import cli  # noqa: E402
import dev_backend  # noqa: E402
import dev_frontend  # noqa: E402


def test_AC16_11_16_get_compose_cmd_prefers_podman(monkeypatch):
    monkeypatch.setattr(
        cli.shutil,
        "which",
        lambda name: "/usr/bin/podman" if name == "podman" else None,
    )
    assert cli.get_compose_cmd() == ["podman", "compose"]


def test_AC16_11_16_get_compose_cmd_falls_back_to_docker(monkeypatch):
    monkeypatch.setattr(
        cli.shutil,
        "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None,
    )
    assert cli.get_compose_cmd() == ["docker", "compose"]


def test_AC16_11_16_get_compose_cmd_exits_when_none(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit) as exc:
        cli.get_compose_cmd()
    assert exc.value.code == 1


def test_AC16_11_17_cmd_test_frontend_route(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "run",
        lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd)),
    )
    cli.cmd_test(
        SimpleNamespace(
            frontend=True,
            e2e=False,
            perf=False,
            fast=False,
            smart=False,
            ephemeral=False,
        ),
        ["--runInBand"],
    )
    assert calls[0][0] == ["npm", "run", "test", "--runInBand"]


def test_AC16_11_17_cmd_test_e2e_route(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "run",
        lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd)),
    )
    cli.cmd_test(
        SimpleNamespace(
            frontend=False,
            e2e=True,
            perf=False,
            fast=False,
            smart=False,
            ephemeral=False,
        ),
        ["-q"],
    )
    assert calls[0][0][:4] == ["uv", "run", "pytest", "-m"]


def test_AC16_11_17_cmd_test_perf_route(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "run",
        lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd)),
    )
    cli.cmd_test(
        SimpleNamespace(
            frontend=False,
            e2e=False,
            perf=True,
            fast=False,
            smart=False,
            ephemeral=False,
        ),
        [],
    )
    assert calls[0][0][:3] == ["uv", "run", "locust"]


def test_AC16_11_17_cmd_test_backend_path_route(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "run",
        lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd)),
    )
    cli.cmd_test(
        SimpleNamespace(
            frontend=False,
            e2e=False,
            perf=False,
            fast=False,
            smart=False,
            ephemeral=False,
        ),
        ["tests/review/test_x.py"],
    )
    assert calls[0][0][:3] == ["uv", "run", "pytest"]


def test_AC16_11_17_cmd_test_lifecycle_route(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "run",
        lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd)),
    )
    cli.cmd_test(
        SimpleNamespace(
            frontend=False,
            e2e=False,
            perf=False,
            fast=True,
            smart=False,
            ephemeral=True,
        ),
        ["-k", "foo"],
    )
    cmd = calls[0][0]
    assert cmd[0:2] == ["python", "../../scripts/test_lifecycle.py"]
    assert "--fast" in cmd
    assert "--ephemeral" in cmd
    assert "-k" in cmd


def test_AC16_11_18_cmd_clean_routes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli,
        "run",
        lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append(cmd),
    )
    monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])

    cli.cmd_clean(SimpleNamespace(db=True, containers=False, force=False, all=False))
    cli.cmd_clean(SimpleNamespace(db=False, containers=True, force=False, all=False))
    cli.cmd_clean(SimpleNamespace(db=False, containers=False, force=True, all=False))

    assert calls[0] == ["python", "scripts/cleanup_orphaned_dbs.py"]
    assert calls[1] == ["docker", "compose", "--profile", "infra", "down"]
    assert calls[2] == ["bash", "scripts/cleanup_dev_resources.sh", "--force"]


def test_AC16_11_19_check_database_ready_failure(monkeypatch):
    def raise_called(*args, **kwargs):
        raise dev_backend.subprocess.CalledProcessError(1, "uv")

    monkeypatch.setattr(dev_backend.subprocess, "run", raise_called)
    assert dev_backend.check_database_ready() is False


def test_check_database_ready_success(monkeypatch):
    monkeypatch.setattr(dev_backend.subprocess, "run", lambda *args, **kwargs: None)
    assert dev_backend.check_database_ready() is True


def test_dev_backend_cleanup_terminates_and_exits(monkeypatch):
    proc = SimpleNamespace(
        poll=lambda: None, terminate=lambda: None, wait=lambda timeout=5: None
    )
    dev_backend._started_resources["uvicorn_proc"] = proc
    with pytest.raises(SystemExit) as exc:
        dev_backend.cleanup()
    assert exc.value.code == 0


def test_AC16_11_20_dev_frontend_cleanup_terminates_and_exits(monkeypatch):
    proc = SimpleNamespace(
        poll=lambda: None, terminate=lambda: None, wait=lambda timeout=5: None
    )
    dev_frontend._started_resources["next_proc"] = proc
    with pytest.raises(SystemExit) as exc:
        dev_frontend.cleanup()
    assert exc.value.code == 0
