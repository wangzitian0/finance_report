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
