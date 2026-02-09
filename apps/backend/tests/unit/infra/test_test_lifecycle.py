import pytest
import os
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys

# Add scripts directory to path so we can import test_lifecycle
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent.parent / "scripts"))
import test_lifecycle

def test_sanitize_namespace():
    """AC8.1.1: Verify namespace sanitization replaces invalid characters."""
    assert test_lifecycle._sanitize_namespace("feat/cleanup") == "feat_cleanup"
    assert test_lifecycle._sanitize_namespace("WS-123") == "ws_123"
    assert test_lifecycle._sanitize_namespace("space name") == "spacename"
    assert test_lifecycle._sanitize_namespace("  Spaces and-Dashes  ") == "spacesand_dashes"
    
    with pytest.raises(ValueError):
        test_lifecycle._sanitize_namespace("")
    with pytest.raises(ValueError):
        test_lifecycle._sanitize_namespace("   ")

def test_get_namespace_env_only():
    """AC8.1.2: Verify namespace retrieval from environment variables."""
    with patch.dict(os.environ, {"BRANCH_NAME": "test-branch", "WORKSPACE_ID": "ws-1"}):
        assert test_lifecycle.get_namespace() == "test_branch_ws_1"

def test_get_test_db_name():
    """AC8.1.3: Verify test database naming convention."""
    assert test_lifecycle.get_test_db_name("my_ns") == "finance_report_test_my_ns"

def test_get_s3_bucket():
    """AC8.1.4: Verify S3 bucket naming convention."""
    assert test_lifecycle.get_s3_bucket("my_ns") == "statements-my-ns"

@patch("test_lifecycle.subprocess.run")
@patch("test_lifecycle.get_container_runtime")
@patch("test_lifecycle.get_namespace")
def test_test_database_persistence(mock_get_namespace, mock_get_runtime, mock_run):
    """AC8.2.1: Verify infrastructure remains up in persistent mode."""
    mock_get_namespace.return_value = "dev"
    mock_get_runtime.return_value = "podman"
    
    # Mock readiness check
    mock_run.side_effect = [
        MagicMock(returncode=0), # up
        MagicMock(stdout="db_container\n"), # ps
        MagicMock(returncode=0), # ready check
        MagicMock(stdout=""), # sql list dbs
        MagicMock(stdout="0"), # sql check db exists
        MagicMock(returncode=0), # sql create db
        MagicMock(stdout="5432"), # port check
        MagicMock(returncode=0), # migrations
        MagicMock(stdout=""), # worker cleanup list
        MagicMock(returncode=0), # drop db
    ]
    
    with test_lifecycle.test_database(ephemeral=False) as (url, ns):
        assert ns == "dev"
        assert "finance_report_test_dev" in url
    
    # Check that "down -v" was NOT called
    for call_args in mock_run.call_args_list:
        assert "down" not in call_args[0][0]

@patch("test_lifecycle.subprocess.run")
@patch("test_lifecycle.get_container_runtime")
@patch("test_lifecycle.get_namespace")
def test_test_database_ephemeral(mock_get_namespace, mock_get_runtime, mock_run):
    """AC8.2.2: Verify infrastructure teardown in ephemeral mode."""
    mock_get_namespace.return_value = "ephemeral_run"
    mock_get_runtime.return_value = "podman"
    
    # Mock everything to succeed
    mock_run.side_effect = [
        MagicMock(returncode=0), # up
        MagicMock(stdout="db_container\n"), # ps
        MagicMock(returncode=0), # ready check
        MagicMock(stdout=""), # sql list dbs
        MagicMock(stdout="0"), # sql check db exists
        MagicMock(returncode=0), # sql create db
        MagicMock(stdout="5432"), # port check
        MagicMock(returncode=0), # migrations
        MagicMock(stdout=""), # worker cleanup list
        MagicMock(returncode=0), # drop db
        MagicMock(returncode=0), # down -v
        MagicMock(returncode=0), # pod rm
    ]
    
    with test_lifecycle.test_database(ephemeral=True) as (url, ns):
        assert ns == "ephemeral_run"
    
    # Verify down -v was called
    down_calls = [c for c in mock_run.call_args_list if "down" in c[0][0] and "-v" in c[0][0]]
    assert len(down_calls) == 1
    
    # Verify pod removal was called
    pod_calls = [c for c in mock_run.call_args_list if "pod" in c[0][0] and "rm" in c[0][0]]
    assert len(pod_calls) == 1
    assert "pod_finance-report-ephemeral_run" in pod_calls[0][0][0]

@patch("test_lifecycle.subprocess.run")
def test_get_namespace_git(mock_run):
    """AC8.1.5: Verify namespace retrieval from git branch name."""
    # Mock git success
    mock_run.return_value = MagicMock(stdout="feature-X\n", returncode=0)
    with patch.dict(os.environ, {}, clear=True):
        ns = test_lifecycle.get_namespace()
        assert "feature_x_" in ns

@patch("test_lifecycle.subprocess.run")
@patch("test_lifecycle.load_active_namespaces")
def test_cleanup_orphan_databases(mock_load, mock_run):
    """AC8.3.1: Verify orphaned databases are correctly identified and dropped."""
    mock_load.return_value = ["active-ns"]
    # Mock psql list dbs
    mock_run.side_effect = [
        MagicMock(stdout="finance_report_test_orphaned\nfinance_report_test_active-ns\n"), # list
        MagicMock(returncode=0), # drop
    ]
    
    with patch("test_lifecycle.get_namespace", return_value="current-ns"):
        test_lifecycle.cleanup_orphan_databases("podman", "db-container")
    
    # Verify drop was called for 'orphaned' but NOT for 'active-ns'
    drop_calls = [c for c in mock_run.call_args_list if "DROP DATABASE" in str(c)]
    assert len(drop_calls) == 1
    assert "orphaned" in str(drop_calls[0])
    assert "active-ns" not in str(drop_calls[0])

@patch("test_lifecycle.subprocess.run")
def test_cleanup_worker_databases(mock_run):
    """AC8.3.2: Verify worker databases (xdist) are cleaned up."""
    # Mock container running
    mock_run.side_effect = [
        MagicMock(stdout="running", returncode=0), # ps check
        MagicMock(stdout="finance_report_test_ns_gw0\nfinance_report_test_ns_gw1\n"), # list
        MagicMock(returncode=0), # drop 0
        MagicMock(returncode=0), # drop 1
    ]
    
    test_lifecycle.cleanup_worker_databases("podman", "db-container", "ns")
    
    # Verify both workers were dropped
    drop_calls = [c for c in mock_run.call_args_list if "DROP DATABASE" in str(c)]
    assert len(drop_calls) == 2

def test_load_active_namespaces_corrupted(tmp_path):
    corrupted_file = tmp_path / "corrupted.json"
    corrupted_file.write_text("invalid json")
    
    with patch("test_lifecycle.ACTIVE_NAMESPACES_FILE", corrupted_file):
        assert test_lifecycle.load_active_namespaces() == []

@patch("test_lifecycle.subprocess.run")
def test_is_db_ready(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert test_lifecycle.is_db_ready("podman", "db-container") is True
    
    from subprocess import CalledProcessError
    mock_run.side_effect = CalledProcessError(1, "cmd")
    assert test_lifecycle.is_db_ready("podman", "db-container") is False

@patch("test_lifecycle.test_database")
@patch("test_lifecycle.subprocess.run")
def test_main_fast_mode(mock_run, mock_test_db):
    # Mock context manager
    mock_test_db.return_value.__enter__.return_value = ("db_url", "ns")
    
    # Mock pytest run
    mock_run.return_value = MagicMock(returncode=0)
    
    with patch.object(sys, "argv", ["test_lifecycle.py", "--fast"]):
        test_lifecycle.main()
    
    # Verify the pytest args
    pytest_call = [c for c in mock_run.call_args_list if "pytest" in str(c)]
    assert "-n" in str(pytest_call[0])
    assert "--no-cov" in str(pytest_call[0])

@patch("test_lifecycle.test_database")
@patch("test_lifecycle.subprocess.run")
def test_main_failure(mock_run, mock_test_db):
    # Mock context manager
    mock_test_db.return_value.__enter__.return_value = ("db_url", "ns")
    
    # Mock pytest failure
    mock_run.return_value = MagicMock(returncode=1)
    
    with patch.object(sys, "argv", ["test_lifecycle.py"]):
        with pytest.raises(SystemExit) as excinfo:
            test_lifecycle.main()
        assert excinfo.value.code == 1

@patch("test_lifecycle.test_database")
@patch("test_lifecycle.subprocess.run")
@patch("test_lifecycle._get_changed_files")
def test_main_smart_mode(mock_changed, mock_run, mock_test_db):
    mock_test_db.return_value.__enter__.return_value = ("db_url", "ns")
    mock_run.return_value = MagicMock(returncode=0)
    mock_changed.return_value = ["src.models", "src.utils"]
    
    with patch.object(sys, "argv", ["test_lifecycle.py", "--smart"]):
        test_lifecycle.main()
    
    pytest_call = [c for c in mock_run.call_args_list if "pytest" in str(c)]
    assert "--cov=src.models" in str(pytest_call[0])
    assert "--cov=src.utils" in str(pytest_call[0])
