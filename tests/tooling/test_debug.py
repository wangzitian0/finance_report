'AC16.11.1 AC16.11.2 AC16.11.3 AC16.11.4 AC16.11.5 AC16.11.6 AC16.11.7 AC16.11.21 AC16.11.22 AC16.11.23 AC16.11.24 AC16.11.25 AC16.11.26 AC16.11.27'; import sys; from pathlib import Path; from types import SimpleNamespace; import pytest; sys.path.insert(0, str(Path(__file__).parent.parent)); from common.runtime.dev import debug
def test_AC16_11_1_detect_environment_ci(monkeypatch): 'AC-runtime.24.1 AC16.11.1'; monkeypatch.setenv('GITHUB_ACTIONS', 'true'); assert debug.detect_environment() == debug.Environment.CI
def test_AC16_11_2_detect_environment_local_when_docker_ok(monkeypatch): 'AC-runtime.24.2'; monkeypatch.delenv('GITHUB_ACTIONS', raising=False); monkeypatch.setattr(debug.subprocess, 'run', lambda *args, **kwargs: None); assert debug.detect_environment() == debug.Environment.LOCAL
def test_AC16_11_3_detect_environment_fallback_production(monkeypatch):
    'AC-runtime.24.3'; monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    def raise_error(*args, **kwargs): raise FileNotFoundError()
    monkeypatch.setattr(debug.subprocess, 'run', raise_error); assert debug.detect_environment() == debug.Environment.PRODUCTION
def test_AC16_11_4_validate_hostname_cases(): 'AC-runtime.24.4'; assert debug.validate_hostname('example.com') is True; assert debug.validate_hostname('1.2.3.4') is True; assert debug.validate_hostname('') is False; assert debug.validate_hostname('-bad-host') is False
def test_AC16_11_5_validate_username_cases(): 'AC-runtime.24.5'; assert debug.validate_username('root') is True; assert debug.validate_username('user_1') is True; assert debug.validate_username('User') is False; assert debug.validate_username('9user') is False
def test_AC16_11_6_get_container_name_mapping(): 'AC-runtime.24.6'; assert debug.get_container_name(debug.Service.BACKEND, debug.Environment.STAGING) == 'finance_report-backend-staging'; assert debug.get_container_name(debug.Service.FRONTEND, debug.Environment.PRODUCTION) == 'finance_report-frontend'; assert debug.validate_username('') is False
def test_AC16_11_7_list_containers_prints_all(capsys): 'AC-runtime.24.7'; debug.list_containers(debug.Environment.LOCAL); output = capsys.readouterr().out; assert 'backend' in output; assert 'frontend' in output; assert 'postgres' in output; capsys.readouterr(); debug.view_remote_logs_observability(debug.Service.BACKEND, debug.Environment.STAGING); _m2_captured = capsys.readouterr(); assert 'observability backend' in _m2_captured.out; assert 'signoz' not in _m2_captured.out.lower(); assert 'service.name = "finance-report-backend"' in _m2_captured.out; assert 'staging' in _m2_captured.out; capsys.readouterr(); debug.view_remote_logs_observability(debug.Service.BACKEND, debug.Environment.PRODUCTION); _m3_captured = capsys.readouterr(); assert 'observability backend' in _m3_captured.out; assert 'deployment.environment = "production"' not in _m3_captured.out
def test_AC16_11_21_view_remote_logs_docker_exits_when_vps_host_missing(monkeypatch):
    'AC-runtime.24.21'; monkeypatch.delenv('VPS_HOST', raising=False)
    with pytest.raises(SystemExit) as exc: debug.view_remote_logs_docker(debug.Service.BACKEND, debug.Environment.PRODUCTION)
    assert exc.value.code == 1
def test_AC16_11_22_view_remote_logs_docker_exits_on_invalid_host(monkeypatch):
    'AC-runtime.24.22'; monkeypatch.setenv('VPS_HOST', '-bad')
    with pytest.raises(SystemExit) as exc: debug.view_remote_logs_docker(debug.Service.BACKEND, debug.Environment.PRODUCTION)
    assert exc.value.code == 1
def test_AC16_11_23_view_remote_logs_docker_exits_on_invalid_user(monkeypatch):
    'AC-runtime.24.23'; monkeypatch.setenv('VPS_HOST', 'example.com'); monkeypatch.setenv('VPS_USER', 'BadUser')
    with pytest.raises(SystemExit) as exc: debug.view_remote_logs_docker(debug.Service.BACKEND, debug.Environment.PRODUCTION)
    assert exc.value.code == 1
def test_AC16_11_24_view_local_logs_builds_docker_command(monkeypatch):
    'AC-runtime.24.24'; calls = []
    def fake_run(cmd, check=True): calls.append(cmd); return SimpleNamespace(returncode=0)
    monkeypatch.setattr(debug.subprocess, 'run', fake_run); debug.view_local_logs(debug.Service.BACKEND, tail=33, follow=True); assert calls[0] == ['docker', 'logs', 'finance-report-backend', '--tail', '33', '-f']
def test_AC16_11_25_main_logs_observability_path(monkeypatch): 'AC-runtime.24.25'; monkeypatch.setattr(debug.argparse.ArgumentParser, 'parse_args', lambda self: SimpleNamespace(command='logs', service='backend', tail=10, follow=False, env='production', method='observability')); called = {'observability': False}; monkeypatch.setattr(debug, 'view_remote_logs_observability', lambda service, env: called.__setitem__('observability', True)); debug.main(); assert called['observability'] is True
def test_AC16_11_26_main_status_local_path(monkeypatch): 'AC-runtime.24.26'; monkeypatch.setattr(debug.argparse.ArgumentParser, 'parse_args', lambda self: SimpleNamespace(command='status', service='backend', env='local')); calls = []; monkeypatch.setattr(debug, 'view_local_logs', lambda service, tail=50, follow=False: calls.append((service, tail, follow))); debug.main(); assert calls == [(debug.Service.BACKEND, 20, False)]
def test_AC16_11_27_main_containers_path(monkeypatch): 'AC-runtime.24.27'; monkeypatch.setattr(debug.argparse.ArgumentParser, 'parse_args', lambda self: SimpleNamespace(command='containers', env='staging')); called = {'env': None}; monkeypatch.setattr(debug, 'list_containers', lambda env: called.__setitem__('env', env)); debug.main(); assert called['env'] == debug.Environment.STAGING
def test_view_local_logs_called_process_error(monkeypatch):
    def raise_cpe(cmd, check=True): raise debug.subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(debug.subprocess, 'run', raise_cpe)
    with pytest.raises(SystemExit) as exc: debug.view_local_logs(debug.Service.BACKEND)
    assert exc.value.code == 1
def test_view_local_logs_file_not_found(monkeypatch):
    def raise_fnf(cmd, check=True): raise FileNotFoundError('docker not found')
    monkeypatch.setattr(debug.subprocess, 'run', raise_fnf)
    with pytest.raises(SystemExit) as exc: debug.view_local_logs(debug.Service.BACKEND)
    assert exc.value.code == 1
def test_view_remote_logs_docker_success(monkeypatch):
    calls = []
    def fake_run(cmd, check=True): calls.append(cmd); return SimpleNamespace(returncode=0)
    monkeypatch.setenv('VPS_HOST', 'example.com'); monkeypatch.setenv('VPS_USER', 'root'); monkeypatch.setattr(debug.subprocess, 'run', fake_run); debug.view_remote_logs_docker(debug.Service.BACKEND, debug.Environment.PRODUCTION, tail=25, follow=True); assert len(calls) == 1; assert 'ssh' in calls[0][0]; assert 'root@example.com' in calls[0][1]; assert '--tail 25' in calls[0][2]; assert '-f' in calls[0][2]
def test_view_remote_logs_docker_called_process_error(monkeypatch):
    def raise_cpe(cmd, check=True): raise debug.subprocess.CalledProcessError(1, cmd)
    monkeypatch.setenv('VPS_HOST', 'example.com'); monkeypatch.setenv('VPS_USER', 'root'); monkeypatch.setattr(debug.subprocess, 'run', raise_cpe)
    with pytest.raises(SystemExit) as exc: debug.view_remote_logs_docker(debug.Service.BACKEND, debug.Environment.PRODUCTION)
    assert exc.value.code == 1
def test_main_logs_docker_local_path(monkeypatch): monkeypatch.setattr(debug.argparse.ArgumentParser, 'parse_args', lambda self: SimpleNamespace(command='logs', service='backend', tail=10, follow=False, env='local', method='docker')); calls = []; monkeypatch.setattr(debug, 'view_local_logs', lambda service, tail=50, follow=False: calls.append((service, tail, follow))); debug.main(); assert calls == [(debug.Service.BACKEND, 10, False)]
def test_main_logs_docker_remote_path(monkeypatch): monkeypatch.setattr(debug.argparse.ArgumentParser, 'parse_args', lambda self: SimpleNamespace(command='logs', service='backend', tail=10, follow=False, env='production', method='docker')); calls = []; monkeypatch.setattr(debug, 'view_remote_logs_docker', lambda service, env, tail=50, follow=False: calls.append((service, env, tail, follow))); debug.main(); assert calls == [(debug.Service.BACKEND, debug.Environment.PRODUCTION, 10, False)]
def test_main_status_remote_path(monkeypatch): monkeypatch.setattr(debug.argparse.ArgumentParser, 'parse_args', lambda self: SimpleNamespace(command='status', service='backend', env='production')); calls = []; monkeypatch.setattr(debug, 'view_remote_logs_docker', lambda service, env, tail=50, follow=False: calls.append((service, env, tail, follow))); debug.main(); assert calls == [(debug.Service.BACKEND, debug.Environment.PRODUCTION, 20, False)]
def test_main_logs_auto_detect_env(monkeypatch): monkeypatch.setattr(debug.argparse.ArgumentParser, 'parse_args', lambda self: SimpleNamespace(command='logs', service='backend', tail=10, follow=False, env=None, method='docker')); monkeypatch.setattr(debug, 'detect_environment', lambda: debug.Environment.LOCAL); calls = []; monkeypatch.setattr(debug, 'view_local_logs', lambda service, tail=50, follow=False: calls.append((service, tail, follow))); debug.main(); assert calls == [(debug.Service.BACKEND, 10, False)]
