import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import debug  # noqa: E402


def test_AC16_11_1_detect_environment_ci(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert debug.detect_environment() == debug.Environment.CI


def test_AC16_11_2_detect_environment_local_when_docker_ok(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(debug.subprocess, "run", lambda *args, **kwargs: None)
    assert debug.detect_environment() == debug.Environment.LOCAL


def test_AC16_11_3_detect_environment_fallback_production(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    def raise_error(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(debug.subprocess, "run", raise_error)
    assert debug.detect_environment() == debug.Environment.PRODUCTION


def test_AC16_11_4_validate_hostname_cases():
    assert debug.validate_hostname("example.com") is True
    assert debug.validate_hostname("1.2.3.4") is True
    assert debug.validate_hostname("") is False
    assert debug.validate_hostname("-bad-host") is False


def test_AC16_11_5_validate_username_cases():
    assert debug.validate_username("root") is True
    assert debug.validate_username("user_1") is True
    assert debug.validate_username("User") is False
    assert debug.validate_username("9user") is False


def test_AC16_11_6_get_container_name_mapping():
    assert (
        debug.get_container_name(debug.Service.BACKEND, debug.Environment.STAGING)
        == "finance_report-backend-staging"
    )
    assert (
        debug.get_container_name(debug.Service.FRONTEND, debug.Environment.PRODUCTION)
        == "finance_report-frontend"
    )


def test_AC16_11_7_list_containers_prints_all(capsys):
    debug.list_containers(debug.Environment.LOCAL)
    output = capsys.readouterr().out
    assert "backend" in output
    assert "frontend" in output
    assert "postgres" in output
    assert "redis" in output


def test_AC16_11_21_view_remote_logs_docker_exits_when_vps_host_missing(monkeypatch):
    monkeypatch.delenv("VPS_HOST", raising=False)
    with pytest.raises(SystemExit) as exc:
        debug.view_remote_logs_docker(
            debug.Service.BACKEND, debug.Environment.PRODUCTION
        )
    assert exc.value.code == 1


def test_AC16_11_22_view_remote_logs_docker_exits_on_invalid_host(monkeypatch):
    monkeypatch.setenv("VPS_HOST", "-bad")
    with pytest.raises(SystemExit) as exc:
        debug.view_remote_logs_docker(
            debug.Service.BACKEND, debug.Environment.PRODUCTION
        )
    assert exc.value.code == 1


def test_AC16_11_23_view_remote_logs_docker_exits_on_invalid_user(monkeypatch):
    monkeypatch.setenv("VPS_HOST", "example.com")
    monkeypatch.setenv("VPS_USER", "BadUser")
    with pytest.raises(SystemExit) as exc:
        debug.view_remote_logs_docker(
            debug.Service.BACKEND, debug.Environment.PRODUCTION
        )
    assert exc.value.code == 1


def test_AC16_11_24_view_local_logs_builds_docker_command(monkeypatch):
    calls = []

    def fake_run(cmd, check=True):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(debug.subprocess, "run", fake_run)
    debug.view_local_logs(debug.Service.BACKEND, tail=33, follow=True)
    assert calls[0] == [
        "docker",
        "logs",
        "finance-report-backend",
        "--tail",
        "33",
        "-f",
    ]


def test_AC16_11_25_main_logs_signoz_path(monkeypatch):
    monkeypatch.setattr(
        debug.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            command="logs",
            service="backend",
            tail=10,
            follow=False,
            env="production",
            method="signoz",
        ),
    )
    called = {"signoz": False}
    monkeypatch.setattr(
        debug,
        "view_remote_logs_signoz",
        lambda service, env: called.__setitem__("signoz", True),
    )
    debug.main()
    assert called["signoz"] is True


def test_AC16_11_26_main_status_local_path(monkeypatch):
    monkeypatch.setattr(
        debug.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(command="status", service="backend", env="local"),
    )
    calls = []
    monkeypatch.setattr(
        debug,
        "view_local_logs",
        lambda service, tail=50, follow=False: calls.append((service, tail, follow)),
    )
    debug.main()
    assert calls == [(debug.Service.BACKEND, 20, False)]


def test_AC16_11_27_main_containers_path(monkeypatch):
    monkeypatch.setattr(
        debug.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(command="containers", env="staging"),
    )
    called = {"env": None}
    monkeypatch.setattr(
        debug, "list_containers", lambda env: called.__setitem__("env", env)
    )
    debug.main()
    assert called["env"] == debug.Environment.STAGING


# ---------------------------------------------------------------------------
# Coverage gap: view_local_logs error handlers (lines 128-133)
# ---------------------------------------------------------------------------


def test_view_local_logs_called_process_error(monkeypatch):
    """view_local_logs exits on CalledProcessError (lines 128-130)."""
    def raise_cpe(cmd, check=True):
        raise debug.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(debug.subprocess, "run", raise_cpe)
    with pytest.raises(SystemExit) as exc:
        debug.view_local_logs(debug.Service.BACKEND)
    assert exc.value.code == 1


def test_view_local_logs_file_not_found(monkeypatch):
    """view_local_logs exits on FileNotFoundError (lines 131-133)."""
    def raise_fnf(cmd, check=True):
        raise FileNotFoundError("docker not found")

    monkeypatch.setattr(debug.subprocess, "run", raise_fnf)
    with pytest.raises(SystemExit) as exc:
        debug.view_local_logs(debug.Service.BACKEND)
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Coverage gap: validate_username empty string (line 149)
# ---------------------------------------------------------------------------


def test_validate_username_empty_string():
    """validate_username returns False for empty string (line 148-149)."""
    assert debug.validate_username("") is False


# ---------------------------------------------------------------------------
# Coverage gap: view_remote_logs_docker success path (lines 183-197)
# ---------------------------------------------------------------------------


def test_view_remote_logs_docker_success(monkeypatch):
    """view_remote_logs_docker runs SSH command successfully (lines 183-197)."""
    calls = []

    def fake_run(cmd, check=True):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    monkeypatch.setenv("VPS_HOST", "example.com")
    monkeypatch.setenv("VPS_USER", "root")
    monkeypatch.setattr(debug.subprocess, "run", fake_run)
    debug.view_remote_logs_docker(
        debug.Service.BACKEND, debug.Environment.PRODUCTION, tail=25, follow=True
    )
    assert len(calls) == 1
    assert "ssh" in calls[0][0]
    assert "root@example.com" in calls[0][1]
    assert "--tail 25" in calls[0][2]
    assert "-f" in calls[0][2]


def test_view_remote_logs_docker_called_process_error(monkeypatch):
    """view_remote_logs_docker exits on CalledProcessError (lines 195-197)."""
    def raise_cpe(cmd, check=True):
        raise debug.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setenv("VPS_HOST", "example.com")
    monkeypatch.setenv("VPS_USER", "root")
    monkeypatch.setattr(debug.subprocess, "run", raise_cpe)
    with pytest.raises(SystemExit) as exc:
        debug.view_remote_logs_docker(
            debug.Service.BACKEND, debug.Environment.PRODUCTION
        )
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Coverage gap: view_remote_logs_signoz (lines 202-217)
# ---------------------------------------------------------------------------


def test_view_remote_logs_signoz(capsys):
    """view_remote_logs_signoz prints SigNoz info (lines 200-217)."""
    debug.view_remote_logs_signoz(debug.Service.BACKEND, debug.Environment.STAGING)
    captured = capsys.readouterr()
    assert "SigNoz" in captured.out
    assert "finance-report-backend" in captured.out
    assert "staging" in captured.out


def test_view_remote_logs_signoz_production(capsys):
    """view_remote_logs_signoz skips deployment.environment for production (line 214)."""
    debug.view_remote_logs_signoz(debug.Service.BACKEND, debug.Environment.PRODUCTION)
    captured = capsys.readouterr()
    assert "SigNoz" in captured.out
    assert 'deployment.environment = "production"' not in captured.out


# ---------------------------------------------------------------------------
# Coverage gap: restart_service (lines 222-237)
# ---------------------------------------------------------------------------


def test_restart_service_local_exits():
    """restart_service exits for local environment (lines 222-227)."""
    with pytest.raises(SystemExit) as exc:
        debug.restart_service(debug.Service.BACKEND, debug.Environment.LOCAL)
    assert exc.value.code == 1


def test_restart_service_remote_prints_instructions(capsys):
    """restart_service prints Dokploy message for remote (lines 229-237)."""
    debug.restart_service(debug.Service.BACKEND, debug.Environment.STAGING)
    captured = capsys.readouterr()
    assert "Restarting" in captured.out
    assert "Dokploy" in captured.out
    assert "docker restart" in captured.out


# ---------------------------------------------------------------------------
# Coverage gap: main logs docker path for local (lines 338-341)
# ---------------------------------------------------------------------------


def test_main_logs_docker_local_path(monkeypatch):
    """main() logs command with docker method routes to local (lines 338-339)."""
    monkeypatch.setattr(
        debug.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            command="logs",
            service="backend",
            tail=10,
            follow=False,
            env="local",
            method="docker",
        ),
    )
    calls = []
    monkeypatch.setattr(
        debug,
        "view_local_logs",
        lambda service, tail=50, follow=False: calls.append((service, tail, follow)),
    )
    debug.main()
    assert calls == [(debug.Service.BACKEND, 10, False)]


def test_main_logs_docker_remote_path(monkeypatch):
    """main() logs command with docker method routes to remote (lines 340-341)."""
    monkeypatch.setattr(
        debug.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            command="logs",
            service="backend",
            tail=10,
            follow=False,
            env="production",
            method="docker",
        ),
    )
    calls = []
    monkeypatch.setattr(
        debug,
        "view_remote_logs_docker",
        lambda service, env, tail=50, follow=False: calls.append((service, env, tail, follow)),
    )
    debug.main()
    assert calls == [(debug.Service.BACKEND, debug.Environment.PRODUCTION, 10, False)]


# ---------------------------------------------------------------------------
# Coverage gap: main status remote path (line 351)
# ---------------------------------------------------------------------------


def test_main_status_remote_path(monkeypatch):
    """main() status command routes to remote (line 351)."""
    monkeypatch.setattr(
        debug.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            command="status",
            service="backend",
            env="production",
        ),
    )
    calls = []
    monkeypatch.setattr(
        debug,
        "view_remote_logs_docker",
        lambda service, env, tail=50, follow=False: calls.append((service, env, tail, follow)),
    )
    debug.main()
    assert calls == [(debug.Service.BACKEND, debug.Environment.PRODUCTION, 20, False)]


# ---------------------------------------------------------------------------
# Coverage gap: main auto-detect environment (line 334)
# ---------------------------------------------------------------------------


def test_main_logs_auto_detect_env(monkeypatch):
    """main() auto-detects environment when env is None."""
    monkeypatch.setattr(
        debug.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            command="logs",
            service="backend",
            tail=10,
            follow=False,
            env=None,
            method="docker",
        ),
    )
    monkeypatch.setattr(debug, "detect_environment", lambda: debug.Environment.LOCAL)
    calls = []
    monkeypatch.setattr(
        debug,
        "view_local_logs",
        lambda service, tail=50, follow=False: calls.append((service, tail, follow)),
    )
    debug.main()
    assert calls == [(debug.Service.BACKEND, 10, False)]