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


def test_AC16_11_28_check_database_ready_success(monkeypatch):
    monkeypatch.setattr(dev_backend.subprocess, "run", lambda *args, **kwargs: None)
    assert dev_backend.check_database_ready() is True


def test_AC16_11_29_dev_backend_cleanup_terminates_and_exits(monkeypatch):
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


from unittest.mock import MagicMock, patch


def _mock_run(monkeypatch):
    """Given monkeypatch, replace cli.run with a call recorder."""
    calls = []
    monkeypatch.setattr(
        cli,
        "run",
        lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append(
            {"cmd": cmd, "cwd": cwd, "env": env, "check": check}
        ),
    )
    return calls


class TestRun:
    """Tests for the run() subprocess wrapper."""

    def test_run_prints_command(self, monkeypatch, capsys):
        """Given a command, should print it with ▶ prefix."""
        monkeypatch.setattr(
            cli.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=0),
        )
        cli.run(["echo", "hello"])
        captured = capsys.readouterr()
        assert "▶ echo hello" in captured.out

    def test_run_exits_on_nonzero_returncode(self, monkeypatch):
        """Given a command that fails with check=True, should sys.exit with that code."""
        monkeypatch.setattr(
            cli.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=42),
        )
        with pytest.raises(SystemExit) as exc:
            cli.run(["false"])
        assert exc.value.code == 42

    def test_run_no_exit_when_check_false(self, monkeypatch):
        """Given check=False and nonzero returncode, should not exit."""
        monkeypatch.setattr(
            cli.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=1),
        )
        result = cli.run(["false"], check=False)
        assert result.returncode == 1

    def test_run_merges_env(self, monkeypatch):
        """Given extra env vars, should merge them with os.environ."""
        captured_env = {}

        def fake_run(cmd, cwd, env):
            captured_env.update(env)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(cli.subprocess, "run", fake_run)
        cli.run(["echo"], env={"MY_VAR": "test"})
        assert captured_env["MY_VAR"] == "test"


class TestCmdSetup:
    """Tests for cmd_setup dependency installation."""

    def test_setup_backend_only(self, monkeypatch):
        """Given --backend flag, should only run uv sync."""
        calls = _mock_run(monkeypatch)
        cli.cmd_setup(SimpleNamespace(backend=True, frontend=False))
        assert len(calls) == 1
        assert calls[0]["cmd"] == ["uv", "sync"]

    def test_setup_frontend_only(self, monkeypatch):
        """Given --frontend flag, should only run npm install."""
        calls = _mock_run(monkeypatch)
        cli.cmd_setup(SimpleNamespace(backend=False, frontend=True))
        assert len(calls) == 1
        assert calls[0]["cmd"] == ["npm", "install"]

    def test_setup_both(self, monkeypatch):
        """Given no flags, should run both uv sync and npm install."""
        calls = _mock_run(monkeypatch)
        cli.cmd_setup(SimpleNamespace(backend=False, frontend=False))
        assert len(calls) == 2
        assert calls[0]["cmd"] == ["uv", "sync"]
        assert calls[1]["cmd"] == ["npm", "install"]


class TestCmdDev:
    """Tests for cmd_dev development server management."""

    def test_dev_infra_only(self, monkeypatch):
        """Given --infra flag, should start infrastructure."""
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.cmd_dev(SimpleNamespace(
            infra=True, backend=False, frontend=False, migrate=False, check=False
        ))
        assert len(calls) == 1
        assert "--profile" in calls[0]["cmd"]
        assert "infra" in calls[0]["cmd"]

    def test_dev_backend(self, monkeypatch):
        """Given --backend flag, should run dev_backend.py."""
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.cmd_dev(SimpleNamespace(
            infra=False, backend=True, frontend=False, migrate=False, check=False
        ))
        assert any("dev_backend.py" in str(c["cmd"]) for c in calls)

    def test_dev_frontend(self, monkeypatch):
        """Given --frontend flag, should run dev_frontend.py."""
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.cmd_dev(SimpleNamespace(
            infra=False, backend=False, frontend=True, migrate=False, check=False
        ))
        assert any("dev_frontend.py" in str(c["cmd"]) for c in calls)

    def test_dev_migrate(self, monkeypatch):
        """Given --migrate flag, should run alembic upgrade head."""
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.cmd_dev(SimpleNamespace(
            infra=False, backend=False, frontend=False, migrate=True, check=False
        ))
        assert any("alembic" in str(c["cmd"]) for c in calls)
        assert any("head" in str(c["cmd"]) for c in calls)

    def test_dev_check(self, monkeypatch):
        """Given --check flag, should run boot module."""
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.cmd_dev(SimpleNamespace(
            infra=False, backend=False, frontend=False, migrate=False, check=True
        ))
        assert any("src.boot" in str(c["cmd"]) for c in calls)

    def test_dev_no_flags_prints_instructions(self, monkeypatch, capsys):
        """Given no flags, should start infra and print instructions."""
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.cmd_dev(SimpleNamespace(
            infra=False, backend=False, frontend=False, migrate=False, check=False
        ))
        captured = capsys.readouterr()
        assert "--backend" in captured.out
        assert "--frontend" in captured.out


class TestCmdLint:
    """Tests for cmd_lint code quality checks."""

    def test_lint_backend_check(self, monkeypatch):
        """Given --backend without --fix, should run ruff check only."""
        calls = _mock_run(monkeypatch)
        cli.cmd_lint(SimpleNamespace(backend=True, frontend=False, fix=False))
        assert any("ruff" in str(c["cmd"]) and "check" in str(c["cmd"]) for c in calls)

    def test_lint_backend_fix(self, monkeypatch):
        """Given --backend --fix, should run ruff format then ruff check --fix."""
        calls = _mock_run(monkeypatch)
        cli.cmd_lint(SimpleNamespace(backend=True, frontend=False, fix=True))
        assert len(calls) == 2
        assert "format" in calls[0]["cmd"]
        assert "--fix" in calls[1]["cmd"]

    def test_lint_frontend_check(self, monkeypatch):
        """Given --frontend without --fix, should run npm run lint."""
        calls = _mock_run(monkeypatch)
        cli.cmd_lint(SimpleNamespace(backend=False, frontend=True, fix=False))
        assert calls[0]["cmd"] == ["npm", "run", "lint"]

    def test_lint_frontend_fix(self, monkeypatch):
        """Given --frontend --fix, should run npm run lint --fix."""
        calls = _mock_run(monkeypatch)
        cli.cmd_lint(SimpleNamespace(backend=False, frontend=True, fix=True))
        assert "--fix" in calls[0]["cmd"]

    def test_lint_both(self, monkeypatch):
        """Given no --backend/--frontend flags, should lint both."""
        calls = _mock_run(monkeypatch)
        cli.cmd_lint(SimpleNamespace(backend=False, frontend=False, fix=False))
        cmds_str = str([c["cmd"] for c in calls])
        assert "ruff" in cmds_str
        assert "npm" in cmds_str


class TestCmdBuild:
    """Tests for cmd_build frontend build."""

    def test_build_runs_npm_build(self, monkeypatch):
        """Given build command, should run npm run build."""
        calls = _mock_run(monkeypatch)
        cli.cmd_build(SimpleNamespace(frontend=True))
        assert calls[0]["cmd"] == ["npm", "run", "build"]


class TestCmdCleanAll:
    """Tests for cmd_clean --all and default flags."""

    def test_clean_all_flag(self, monkeypatch):
        """Given --all flag, should pass --all to cleanup script."""
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.cmd_clean(SimpleNamespace(db=False, containers=False, force=False, all=True))
        assert calls[0]["cmd"] == ["bash", "scripts/cleanup_dev_resources.sh", "--all"]

    def test_clean_default(self, monkeypatch):
        """Given no flags, should run cleanup script without flags."""
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.cmd_clean(SimpleNamespace(db=False, containers=False, force=False, all=False))
        assert calls[0]["cmd"] == ["bash", "scripts/cleanup_dev_resources.sh"]


class TestCmdTestSmart:
    """Tests for cmd_test --smart flag."""

    def test_smart_flag(self, monkeypatch):
        """Given --smart flag, should pass --smart to lifecycle script."""
        calls = _mock_run(monkeypatch)
        cli.cmd_test(
            SimpleNamespace(
                frontend=False, e2e=False, perf=False,
                fast=False, smart=True, ephemeral=False,
            ),
            [],
        )
        cmd = calls[0]["cmd"]
        assert "--smart" in cmd


class TestMainDispatch:
    """Tests for main() argparse dispatch to subcommands."""

    def test_main_setup_dispatch(self, monkeypatch):
        """Given 'setup' command, should call cmd_setup."""
        monkeypatch.setattr("sys.argv", ["cli.py", "setup"])
        calls = _mock_run(monkeypatch)
        cli.main()
        assert any("uv" in str(c["cmd"]) for c in calls)

    def test_main_dev_dispatch(self, monkeypatch):
        """Given 'dev --backend' command, should call cmd_dev."""
        monkeypatch.setattr("sys.argv", ["cli.py", "dev", "--backend"])
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.main()
        assert any("dev_backend" in str(c["cmd"]) for c in calls)

    def test_main_lint_dispatch(self, monkeypatch):
        """Given 'lint' command, should call cmd_lint."""
        monkeypatch.setattr("sys.argv", ["cli.py", "lint", "--backend"])
        calls = _mock_run(monkeypatch)
        cli.main()
        assert any("ruff" in str(c["cmd"]) for c in calls)

    def test_main_build_dispatch(self, monkeypatch):
        """Given 'build' command, should call cmd_build."""
        monkeypatch.setattr("sys.argv", ["cli.py", "build"])
        calls = _mock_run(monkeypatch)
        cli.main()
        assert calls[0]["cmd"] == ["npm", "run", "build"]

    def test_main_clean_dispatch(self, monkeypatch):
        """Given 'clean --db' command, should call cmd_clean."""
        monkeypatch.setattr("sys.argv", ["cli.py", "clean", "--db"])
        calls = _mock_run(monkeypatch)
        monkeypatch.setattr(cli, "get_compose_cmd", lambda: ["docker", "compose"])
        cli.main()
        assert calls[0]["cmd"] == ["python", "scripts/cleanup_orphaned_dbs.py"]

    def test_main_test_with_extra_args(self, monkeypatch):
        """Given 'test' with extra pytest args, should pass them through."""
        monkeypatch.setattr("sys.argv", ["cli.py", "test", "-k", "mytest"])
        calls = _mock_run(monkeypatch)
        cli.main()
        cmd = calls[0]["cmd"]
        assert "-k" in cmd
        assert "mytest" in cmd