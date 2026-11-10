import subprocess; import sys; from pathlib import Path; from unittest.mock import MagicMock, patch; import pytest; REPO_ROOT = Path(__file__).resolve().parents[5]; sys.path.insert(0, str(REPO_ROOT)) if str(REPO_ROOT) not in sys.path else None; from common.runtime.dev import test_lifecycle; sys.modules.setdefault('test_lifecycle', test_lifecycle)
@pytest.fixture(autouse=True)
def patch_cache_file(tmp_path):
    'AC8.3.1'; mock_cache = tmp_path / 'test_active_namespaces.json'
    with patch('test_lifecycle.ACTIVE_NAMESPACES_FILE', mock_cache): yield mock_cache
def test_sanitize_namespace():
    assert test_lifecycle._sanitize_namespace('feat/cleanup') == 'feat_cleanup'; assert test_lifecycle._sanitize_namespace('WS-123') == 'ws_123'; assert test_lifecycle._sanitize_namespace('space name') == 'spacename'
    with pytest.raises(ValueError): test_lifecycle._sanitize_namespace('')
    _m1_namespace = 'codex_issue_490_testing_strategy_ac_coverage_0bb5607e'; _m1_db_name = test_lifecycle.get_test_db_name(_m1_namespace); _m1_bucket = test_lifecycle.get_s3_bucket(_m1_namespace); assert len(_m1_db_name) <= 63; assert len(_m1_bucket) <= 63; assert '_' not in _m1_bucket; 'AC8.13.69'; 'AC8.13.69'; assert test_lifecycle._extract_host_port('\n  \nnot-a-port\n0.0.0.0:65432\n') == '65432'; assert test_lifecycle._extract_host_port('5432/tcp -> 127.0.0.1:65433\nignored:invalid\n') == '65433'; assert test_lifecycle._extract_host_port('\ninvalid\n') is None
@patch('test_lifecycle.subprocess.run')
def test_is_db_ready(mock_run): 'AC8.2.1'; mock_run.return_value = MagicMock(returncode=0); assert test_lifecycle.is_db_ready('podman', 'db-container') is True; mock_run.side_effect = subprocess.CalledProcessError(1, cmd=['pg_isready']); assert test_lifecycle.is_db_ready('podman', 'db-container') is False; mock_run.side_effect = None
@patch('test_lifecycle.subprocess.run')
@patch('test_lifecycle.get_container_runtime')
@patch('test_lifecycle.get_namespace')
@patch('test_lifecycle.register_namespace')
@patch('test_lifecycle.unregister_namespace')
@patch('test_lifecycle.cleanup_orphan_databases')
@patch('test_lifecycle.cleanup_worker_databases')
def test_test_database_persistence(mock_worker, mock_orphan, mock_unregister, mock_register, mock_get_namespace, mock_get_runtime, mock_run):
    'AC8.2.1'; mock_get_namespace.return_value = 'dev'; mock_get_runtime.return_value = 'podman'; mock_run.side_effect = [MagicMock(returncode=0), MagicMock(stdout='db_container\n'), MagicMock(returncode=0), MagicMock(stdout='0'), MagicMock(returncode=0), MagicMock(stdout='5432'), MagicMock(returncode=0), MagicMock(returncode=0)]
    with test_lifecycle.test_database(ephemeral=False) as (url, ns): assert ns == 'dev'; assert 'localhost:5432' in url
    mock_register.assert_called_once(); down_calls = [c for c in mock_run.call_args_list if c.args and isinstance(c.args[0], list | tuple) and ('down' in c.args[0])]; assert len(down_calls) == 0
@patch('test_lifecycle.subprocess.run')
@patch('test_lifecycle.get_container_runtime')
@patch('test_lifecycle.get_namespace')
@patch('test_lifecycle.register_namespace')
@patch('test_lifecycle.unregister_namespace')
@patch('test_lifecycle.cleanup_orphan_databases')
@patch('test_lifecycle.cleanup_worker_databases')
def test_namespaced_infra_uses_ephemeral_host_ports(mock_worker, mock_orphan, mock_unregister, mock_register, mock_get_namespace, mock_get_runtime, mock_run):
    'AC-testing.lifecycle.1 AC8.13.69'; mock_get_namespace.return_value = 'feature_branch'; mock_get_runtime.return_value = 'podman'; mock_run.side_effect = [MagicMock(returncode=0), MagicMock(stdout='db_container\n'), MagicMock(returncode=0), MagicMock(stdout='0'), MagicMock(returncode=0), MagicMock(stdout=''), MagicMock(stdout='5432/tcp -> 127.0.0.1:65432'), MagicMock(returncode=0), MagicMock(returncode=0)]
    with test_lifecycle.test_database(ephemeral=False) as (url, ns): assert ns == 'feature_branch'; assert 'localhost:65432' in url
    up_call = mock_run.call_args_list[0]; env = up_call.kwargs['env']; assert env['DB_PORTS'] == '127.0.0.1::5432'; assert env['MINIO_API_PORTS'] == '127.0.0.1::9000'; assert env['MINIO_CONSOLE_PORTS'] == '127.0.0.1::9001'
@patch('test_lifecycle.subprocess.run')
@patch('test_lifecycle.get_container_runtime')
@patch('test_lifecycle.get_namespace')
@patch('test_lifecycle.register_namespace')
@patch('test_lifecycle.unregister_namespace')
@patch('test_lifecycle.cleanup_orphan_databases')
@patch('test_lifecycle.cleanup_worker_databases')
def test_test_database_ephemeral(mock_worker, mock_orphan, mock_unregister, mock_register, mock_get_namespace, mock_get_runtime, mock_run):
    'AC8.2.2'; mock_get_namespace.return_value = 'ephemeral_run'; mock_get_runtime.return_value = 'podman'; mock_run.side_effect = [MagicMock(returncode=0), MagicMock(stdout='db_container\n'), MagicMock(returncode=0), MagicMock(stdout='0'), MagicMock(returncode=0), MagicMock(stdout='5432'), MagicMock(returncode=0), MagicMock(returncode=0), MagicMock(returncode=0), MagicMock(returncode=0)]
    with test_lifecycle.test_database(ephemeral=True) as (url, ns): assert ns == 'ephemeral_run'
    down_calls = [c for c in mock_run.call_args_list if c.args and isinstance(c.args[0], list | tuple) and ('down' in c.args[0]) and ('-v' in c.args[0])]; assert len(down_calls) == 1; mock_unregister.assert_called_once()
def test_load_active_namespaces_corrupted(tmp_path):
    'AC8.3.1'; corrupted_file = tmp_path / 'corrupted.json'; corrupted_file.write_text('invalid json')
    with patch('test_lifecycle.ACTIVE_NAMESPACES_FILE', corrupted_file): namespaces = test_lifecycle.load_active_namespaces(); assert namespaces == []
