'AC16.11.16 AC16.11.17 AC16.11.18 AC16.11.19 AC16.11.20 AC16.11.28 AC16.11.29'; import signal; import sys; from pathlib import Path; from types import SimpleNamespace; import pytest; sys.path.insert(0, str(Path(__file__).parent.parent)); from common.runtime.dev import cli, dev_backend, dev_frontend, toolchain
def _test_args(**kwargs): d = {'frontend': False, 'e2e': False, 'backend_e2e': False, 'perf': False, 'fast': False, 'smart': False, 'ephemeral': False}; d.update(kwargs); return SimpleNamespace(**d)
def _dev_args(**kwargs): d = {'infra': False, 'backend': False, 'frontend': False, 'migrate': False, 'check': False}; d.update(kwargs); return SimpleNamespace(**d)
def test_AC16_11_16_get_compose_cmd_prefers_podman(monkeypatch): 'AC-runtime.24.16'; monkeypatch.setattr(toolchain.shutil, 'which', lambda name: '/usr/bin/podman' if name == 'podman' else None); assert cli.get_compose_cmd() == ['podman', 'compose']
def test_AC16_11_16_get_compose_cmd_falls_back_to_docker(monkeypatch): monkeypatch.setattr(toolchain.shutil, 'which', lambda name: '/usr/bin/docker' if name == 'docker' else None); assert cli.get_compose_cmd() == ['docker', 'compose']
def test_AC16_11_16_get_compose_cmd_honors_container_runtime_override(monkeypatch): monkeypatch.setenv('CONTAINER_RUNTIME', 'docker'); monkeypatch.setattr(toolchain.shutil, 'which', lambda name: f'/usr/bin/{name}' if name in {'docker', 'podman'} else None); assert cli.get_compose_cmd() == ['docker', 'compose']
def test_AC16_11_16_get_compose_cmd_exits_when_none(monkeypatch):
    monkeypatch.setattr(toolchain.shutil, 'which', lambda name: None)
    with pytest.raises(SystemExit) as exc: cli.get_compose_cmd()
    assert exc.value.code == 1
def test_AC16_11_17_cmd_test_frontend_route(monkeypatch): 'AC-runtime.24.17'; calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd))); cli.cmd_test(_test_args(frontend=True), ['--runInBand']); assert calls[0][0] == ['npm', 'run', 'test', '--runInBand']
def test_AC16_11_17_cmd_test_e2e_route(monkeypatch): 'AC8.13.79'; calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd))); cli.cmd_test(_test_args(e2e=True), ['-q']); assert calls[0][0][:7] == ['uv', 'run', '--python', '3.12.12', 'python', '-m', 'pytest']; assert '-m' in calls[0][0]; assert 'tests/e2e/' in calls[0][0]; assert calls[0][1] == cli.REPO_ROOT
def test_AC8_13_79_cmd_test_backend_e2e_route(monkeypatch): 'AC-testing.toolchain.9 AC8.13.79'; calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd))); cli.cmd_test(_test_args(backend_e2e=True), ['--maxfail=1']); assert 'tests/tooling/test_benchmark_scenario_suite.py' in calls[0][0]; assert calls[0][1] == cli.REPO_ROOT
def test_AC16_11_17_cmd_test_perf_route(monkeypatch): calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd))); cli.cmd_test(_test_args(perf=True), []); assert calls[0][0][:7] == ['uv', 'run', '--python', '3.12.12', 'python', '-m', 'locust']
def test_AC16_11_17_cmd_test_backend_path_route(monkeypatch): calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd))); cli.cmd_test(_test_args(), ['tests/review/test_x.py']); assert calls[0][0][:7] == ['uv', 'run', '--python', '3.12.12', 'python', '-m', 'pytest']; assert calls[0][0][7:] == ['--no-cov', 'tests/review/test_x.py']
def test_AC16_11_17_cmd_test_backend_path_route_honors_explicit_cov(monkeypatch): 'AC16.11.17'; calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd))); cli.cmd_test(_test_args(), ['tests/review/test_x.py', '--cov=src']); cmd = calls[0][0]; assert '--no-cov' not in cmd; assert '--cov=src' in cmd
def test_AC16_11_17_cmd_test_backend_path_route_honors_fast_mode(monkeypatch): 'AC16.11.17'; calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd))); cli.cmd_test(_test_args(fast=True), ['tests/infra/test_boot.py']); cmd = calls[0][0]; assert cmd[:2] == [sys.executable, str(cli.REPO_ROOT / 'tools' / 'test_lifecycle.py')]; assert '--fast' in cmd; assert 'tests/infra/test_boot.py' in cmd; assert calls[0][1] == cli.BACKEND_DIR
def test_AC16_11_17_cmd_test_lifecycle_route(monkeypatch): calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append((cmd, cwd))); cli.cmd_test(_test_args(fast=True, ephemeral=True), ['-k', 'foo']); cmd = calls[0][0]; assert cmd[0:2] == [sys.executable, str(cli.REPO_ROOT / 'tools' / 'test_lifecycle.py')]; assert '--fast' in cmd; assert '--ephemeral' in cmd; assert '-k' in cmd
def test_AC16_11_18_cmd_clean_routes(monkeypatch): 'AC-runtime.24.18'; calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append(cmd)); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.cmd_clean(SimpleNamespace(db=True, containers=False, force=False, all=False)); cli.cmd_clean(SimpleNamespace(db=False, containers=True, force=False, all=False)); cli.cmd_clean(SimpleNamespace(db=False, containers=False, force=True, all=False)); assert calls[0] == [sys.executable, str(cli.REPO_ROOT / 'tools' / 'cleanup_orphaned_dbs.py')]; assert calls[1] == ['docker', 'compose', '--profile', 'infra', 'down']; assert calls[2] == ['bash', str(cli.REPO_ROOT / 'tools' / 'cleanup_dev_resources.sh'), '--force']
def test_AC16_11_19_check_database_ready_failure(monkeypatch):
    'AC-runtime.24.19'
    def raise_called(*args, **kwargs): raise dev_backend.subprocess.CalledProcessError(1, 'uv')
    monkeypatch.setattr(dev_backend.subprocess, 'run', raise_called); assert dev_backend.check_database_ready() is False
def test_AC16_11_28_check_database_ready_success(monkeypatch): 'AC-runtime.24.28'; monkeypatch.setattr(dev_backend.subprocess, 'run', lambda *args, **kwargs: None); assert dev_backend.check_database_ready() is True
def test_AC16_11_29_dev_backend_cleanup_is_process_pure(monkeypatch):
    'AC-runtime.24.29'; proc = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda timeout=5: None); dev_backend._started_resources['uvicorn_proc'] = proc; assert dev_backend.cleanup() is None
    with pytest.raises(KeyboardInterrupt): dev_backend._request_shutdown(signal.SIGTERM, None)
def test_AC16_11_20_dev_frontend_cleanup_is_process_pure(monkeypatch):
    'AC-runtime.24.20'; proc = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda timeout=5: None); dev_frontend._started_resources['next_proc'] = proc; assert dev_frontend.cleanup() is None
    with pytest.raises(KeyboardInterrupt): dev_frontend._request_shutdown(signal.SIGTERM, None)
def _mock_run(monkeypatch): calls = []; monkeypatch.setattr(cli, 'run', lambda cmd, cwd=cli.REPO_ROOT, env=None, check=True: calls.append({'cmd': cmd, 'cwd': cwd, 'env': env, 'check': check})); return calls
class TestRun:
    def test_run_prints_command(self, monkeypatch, capsys): monkeypatch.setattr(cli.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0)); cli.run(['echo', 'hello']); captured = capsys.readouterr(); assert '▶ echo hello' in captured.out
    def test_run_exits_on_nonzero_returncode(self, monkeypatch):
        monkeypatch.setattr(cli.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=42))
        with pytest.raises(SystemExit) as exc: cli.run(['false'])
        assert exc.value.code == 42
    def test_run_no_exit_when_check_false(self, monkeypatch): monkeypatch.setattr(cli.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=1)); result = cli.run(['false'], check=False); assert result.returncode == 1
    def test_run_merges_env(self, monkeypatch):
        captured_env = {}
        def fake_run(cmd, cwd, env): captured_env.update(env); return SimpleNamespace(returncode=0)
        monkeypatch.setattr(cli.subprocess, 'run', fake_run); cli.run(['echo'], env={'MY_VAR': 'test'}); assert captured_env['MY_VAR'] == 'test'
class TestCmdSetup:
    def test_setup_backend_only(self, monkeypatch): 'AC8.13.44'; calls = _mock_run(monkeypatch); cli.cmd_setup(SimpleNamespace(backend=True, frontend=False)); assert len(calls) == 1; assert calls[0]['cmd'] == ['uv', 'sync', '--python', '3.12.12']
    def test_setup_frontend_only(self, monkeypatch): 'AC8.13.44'; calls = _mock_run(monkeypatch); cli.cmd_setup(SimpleNamespace(backend=False, frontend=True)); assert len(calls) == 1; assert calls[0]['cmd'] == ['npm', 'ci']
    def test_setup_both(self, monkeypatch): 'AC8.13.44'; calls = _mock_run(monkeypatch); cli.cmd_setup(SimpleNamespace(backend=False, frontend=False)); assert len(calls) == 2; assert calls[0]['cmd'] == ['uv', 'sync', '--python', '3.12.12']; assert calls[1]['cmd'] == ['npm', 'ci']
class TestCmdDev:
    def test_dev_infra_only(self, monkeypatch): calls = _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.cmd_dev(_dev_args(infra=True)); assert len(calls) == 1; assert '--profile' in calls[0]['cmd']; assert 'infra' in calls[0]['cmd']
    def test_dev_backend(self, monkeypatch): calls = _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.cmd_dev(_dev_args(backend=True)); assert any(('dev_backend.py' in str(c['cmd']) for c in calls))
    def test_dev_frontend(self, monkeypatch): calls = _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.cmd_dev(_dev_args(frontend=True)); assert any(('dev_frontend.py' in str(c['cmd']) for c in calls))
    def test_dev_migrate(self, monkeypatch): calls = _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.cmd_dev(_dev_args(migrate=True)); assert any(('alembic' in str(c['cmd']) for c in calls)); assert any(('head' in str(c['cmd']) for c in calls))
    def test_dev_check(self, monkeypatch): calls = _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.cmd_dev(_dev_args(check=True)); assert any(('src.boot' in str(c['cmd']) for c in calls))
    def test_dev_no_flags_prints_instructions(self, monkeypatch, capsys): _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.cmd_dev(_dev_args()); captured = capsys.readouterr(); assert '--backend' in captured.out; assert '--frontend' in captured.out
class TestCmdLint:
    def test_lint_backend_check(self, monkeypatch): calls = _mock_run(monkeypatch); cli.cmd_lint(SimpleNamespace(backend=True, frontend=False, fix=False)); assert any(('ruff' in str(c['cmd']) and 'check' in str(c['cmd']) for c in calls)); assert any(('src' in c['cmd'] and 'tests' in c['cmd'] for c in calls))
    def test_AC8_13_45_lint_backend_format_check_is_required(self, monkeypatch): 'AC-testing.toolchain.3 AC8.13.45'; calls = _mock_run(monkeypatch); cli.cmd_lint(SimpleNamespace(backend=True, frontend=False, fix=False)); format_calls = [call for call in calls if call['cmd'][:7] == ['uv', 'run', '--python', '3.12.12', 'python', '-m', 'ruff'] and 'format' in call['cmd']]; assert format_calls; assert format_calls[0]['check'] is True; assert 'src' in format_calls[0]['cmd']; assert 'tests' in format_calls[0]['cmd']
    def test_lint_backend_fix(self, monkeypatch): calls = _mock_run(monkeypatch); cli.cmd_lint(SimpleNamespace(backend=True, frontend=False, fix=True)); assert len(calls) == 2; assert 'format' in calls[0]['cmd']; assert '--fix' in calls[1]['cmd']
    def test_lint_frontend_check(self, monkeypatch): calls = _mock_run(monkeypatch); cli.cmd_lint(SimpleNamespace(backend=False, frontend=True, fix=False)); assert calls[0]['cmd'] == ['npm', 'run', 'lint']
    def test_lint_frontend_fix(self, monkeypatch): calls = _mock_run(monkeypatch); cli.cmd_lint(SimpleNamespace(backend=False, frontend=True, fix=True)); assert '--fix' in calls[0]['cmd']
    def test_lint_both(self, monkeypatch): calls = _mock_run(monkeypatch); cli.cmd_lint(SimpleNamespace(backend=False, frontend=False, fix=False)); cmds_str = str([c['cmd'] for c in calls]); assert 'ruff' in cmds_str; assert 'npm' in cmds_str
class TestCmdBuild:
    def test_build_runs_npm_build(self, monkeypatch): calls = _mock_run(monkeypatch); cli.cmd_build(SimpleNamespace(frontend=True)); assert calls[0]['cmd'] == ['npm', 'run', 'build']
class TestCmdCleanAll:
    def test_clean_all_flag(self, monkeypatch): calls = _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.cmd_clean(SimpleNamespace(db=False, containers=False, force=False, all=True)); assert calls[0]['cmd'] == ['bash', str(cli.REPO_ROOT / 'tools' / 'cleanup_dev_resources.sh'), '--all']
    def test_clean_default(self, monkeypatch): calls = _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.cmd_clean(SimpleNamespace(db=False, containers=False, force=False, all=False)); assert calls[0]['cmd'] == ['bash', str(cli.REPO_ROOT / 'tools' / 'cleanup_dev_resources.sh')]
class TestCmdTestSmart:
    def test_smart_flag(self, monkeypatch): calls = _mock_run(monkeypatch); cli.cmd_test(_test_args(smart=True), []); cmd = calls[0]['cmd']; assert '--smart' in cmd
class TestMainDispatch:
    def test_main_setup_dispatch(self, monkeypatch): monkeypatch.setattr('sys.argv', ['cli.py', 'setup']); calls = _mock_run(monkeypatch); cli.main(); assert any(('uv' in str(c['cmd']) for c in calls))
    def test_main_dev_dispatch(self, monkeypatch): monkeypatch.setattr('sys.argv', ['cli.py', 'dev', '--backend']); calls = _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.main(); assert any(('dev_backend' in str(c['cmd']) for c in calls))
    def test_main_lint_dispatch(self, monkeypatch): monkeypatch.setattr('sys.argv', ['cli.py', 'lint', '--backend']); calls = _mock_run(monkeypatch); cli.main(); assert any(('ruff' in str(c['cmd']) for c in calls))
    def test_main_build_dispatch(self, monkeypatch): monkeypatch.setattr('sys.argv', ['cli.py', 'build']); calls = _mock_run(monkeypatch); cli.main(); assert calls[0]['cmd'] == ['npm', 'run', 'build']
    def test_main_clean_dispatch(self, monkeypatch): monkeypatch.setattr('sys.argv', ['cli.py', 'clean', '--db']); calls = _mock_run(monkeypatch); monkeypatch.setattr(cli, 'get_compose_cmd', lambda: ['docker', 'compose']); cli.main(); assert calls[0]['cmd'] == [sys.executable, str(cli.REPO_ROOT / 'tools' / 'cleanup_orphaned_dbs.py')]
    def test_main_test_with_extra_args(self, monkeypatch): monkeypatch.setattr('sys.argv', ['cli.py', 'test', '-k', 'mytest']); calls = _mock_run(monkeypatch); cli.main(); cmd = calls[0]['cmd']; assert '-k' in cmd; assert 'mytest' in cmd
class TestDevBackendMain:
    def test_main_success_path(self, monkeypatch): monkeypatch.setattr(dev_backend, 'check_database_ready', lambda: True); import signal as _signal; monkeypatch.setattr(_signal, 'signal', lambda *args: None); fake_proc = SimpleNamespace(poll=lambda: 0, wait=lambda **kw: 0, terminate=lambda: None); monkeypatch.setattr(dev_backend.subprocess, 'Popen', lambda *args, **kwargs: fake_proc); dev_backend.main(); assert dev_backend._started_resources['uvicorn_proc'] is fake_proc
    def test_main_exits_when_db_not_ready(self, monkeypatch): monkeypatch.setattr(dev_backend, 'check_database_ready', lambda: False); import signal as _signal; monkeypatch.setattr(_signal, 'signal', lambda *args: None); assert dev_backend.main() == 1
    def test_AC16_11_29_main_keyboard_interrupt_returns_130(self, monkeypatch):
        'AC-runtime.24.29'; monkeypatch.setattr(dev_backend, 'check_database_ready', lambda: True); import signal as _signal; monkeypatch.setattr(_signal, 'signal', lambda *args: None); wait_calls = [0]
        def smart_wait(**kwargs):
            wait_calls[0] += 1
            if wait_calls[0] == 1: raise KeyboardInterrupt
        fake_proc = SimpleNamespace(poll=lambda: None, wait=smart_wait, terminate=lambda: None); monkeypatch.setattr(dev_backend.subprocess, 'Popen', lambda *args, **kwargs: fake_proc); assert dev_backend.main() == 130
    def test_get_compose_cmd_returns_podman(self, monkeypatch): monkeypatch.setattr(toolchain.shutil, 'which', lambda name: '/usr/bin/podman' if name == 'podman' else None); result = dev_backend.get_compose_cmd(); assert result == ['podman', 'compose']
    def test_get_compose_cmd_returns_empty_when_none(self, monkeypatch):
        monkeypatch.setattr(toolchain.shutil, 'which', lambda name: None)
        with pytest.raises(SystemExit) as exc: dev_backend.get_compose_cmd()
        assert exc.value.code == 1
    def test_AC16_11_29_cleanup_timeout_kills_process(self, monkeypatch):
        'AC-runtime.24.29'; killed = []
        def raise_timeout(timeout=5): raise dev_backend.subprocess.TimeoutExpired('proc', timeout)
        fake_proc = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=raise_timeout, kill=lambda: killed.append(True)); dev_backend._started_resources['uvicorn_proc'] = fake_proc; dev_backend.cleanup(); assert killed, 'kill() should have been called on timeout'
class TestDevFrontendMain:
    def test_main_success_path(self, monkeypatch): import signal as _signal; monkeypatch.setattr(_signal, 'signal', lambda *args: None); fake_proc = SimpleNamespace(poll=lambda: 0, wait=lambda **kw: 0, terminate=lambda: None); monkeypatch.setattr(dev_frontend.subprocess, 'Popen', lambda *args, **kwargs: fake_proc); dev_frontend.main(); assert dev_frontend._started_resources['next_proc'] is fake_proc
    def test_AC16_11_20_main_keyboard_interrupt_returns_130(self, monkeypatch):
        'AC-runtime.24.20'; import signal as _signal; monkeypatch.setattr(_signal, 'signal', lambda *args: None); wait_calls = [0]
        def smart_wait(**kwargs):
            wait_calls[0] += 1
            if wait_calls[0] == 1: raise KeyboardInterrupt
        fake_proc = SimpleNamespace(poll=lambda: None, wait=smart_wait, terminate=lambda: None); monkeypatch.setattr(dev_frontend.subprocess, 'Popen', lambda *args, **kwargs: fake_proc); assert dev_frontend.main() == 130
    def test_AC16_11_20_cleanup_timeout_kills_process(self, monkeypatch):
        'AC-runtime.24.20'; killed = []
        def raise_timeout(timeout=5): raise dev_frontend.subprocess.TimeoutExpired('proc', timeout)
        fake_proc = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=raise_timeout, kill=lambda: killed.append(True)); dev_frontend._started_resources['next_proc'] = fake_proc; dev_frontend.cleanup(); assert killed, 'kill() should have been called on timeout'
    def test_main_custom_app_url(self, monkeypatch, capsys): import signal as _signal; monkeypatch.setattr(_signal, 'signal', lambda *args: None); monkeypatch.setenv('NEXT_PUBLIC_APP_URL', 'http://localhost:9000'); fake_proc = SimpleNamespace(poll=lambda: 0, wait=lambda **kw: 0, terminate=lambda: None); monkeypatch.setattr(dev_frontend.subprocess, 'Popen', lambda *args, **kwargs: fake_proc); dev_frontend.main(); captured = capsys.readouterr(); assert 'http://localhost:9000' in captured.out
