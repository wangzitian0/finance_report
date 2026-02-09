import pytest
import os
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys
import subprocess

# Add scripts directory to path so we can import test_lifecycle
sys.path.append(str(Path(__file__).parent.parent.parent.parent.parent / "scripts"))
import test_lifecycle

@pytest.fixture(autouse=True)
def patch_cache_file(tmp_path):
    """AC8.3.1: Ensure tests use a temporary cache file for hermeticity."""
    mock_cache = tmp_path / "test_active_namespaces.json"
    with patch("test_lifecycle.ACTIVE_NAMESPACES_FILE", mock_cache):
        yield mock_cache

def test_sanitize_namespace():
    """AC8.1.1: Verify namespace sanitization replaces invalid characters."""
    assert test_lifecycle._sanitize_namespace("feat/cleanup") == "feat_cleanup"
    assert test_lifecycle._sanitize_namespace("WS-123") == "ws_123"
    assert test_lifecycle._sanitize_namespace("space name") == "spacename"
    
    with pytest.raises(ValueError):
        test_lifecycle._sanitize_namespace("")

@patch("test_lifecycle.subprocess.run")
def test_is_db_ready(mock_run):
    """AC8.2.1: Verify is_db_ready correctly checks container status."""
    mock_run.return_value = MagicMock(returncode=0)
    assert test_lifecycle.is_db_ready("podman", "db-container") is True
    
    # Simulate CalledProcessError for failure case
    mock_run.side_effect = subprocess.CalledProcessError(1, cmd=["pg_isready"])
    assert test_lifecycle.is_db_ready("podman", "db-container") is False
    
    # Reset side_effect for other tests
    mock_run.side_effect = None

@patch("test_lifecycle.subprocess.run")
@patch("test_lifecycle.get_container_runtime")
@patch("test_lifecycle.get_namespace")
@patch("test_lifecycle.register_namespace")
@patch("test_lifecycle.unregister_namespace")
@patch("test_lifecycle.cleanup_orphan_databases")
@patch("test_lifecycle.cleanup_worker_databases")
def test_test_database_persistence(mock_worker, mock_orphan, mock_unregister, mock_register, mock_get_namespace, mock_get_runtime, mock_run):
    """AC8.2.1: Verify infrastructure remains up in persistent mode."""
    mock_get_namespace.return_value = "dev"
    mock_get_runtime.return_value = "podman"
    
    # Mock sequence: up, ps, ready_check (is_db_ready), check_exists, create, port, migrations, drop_test_db
    mock_run.side_effect = [
        MagicMock(returncode=0), # up
        MagicMock(stdout="db_container\n"), # ps
        MagicMock(returncode=0), # is_db_ready check
        MagicMock(stdout="0"), # check db exists
        MagicMock(returncode=0), # create db
        MagicMock(stdout="5432"), # port check
        MagicMock(returncode=0), # migrations
        MagicMock(returncode=0), # drop test db
    ]
    
    with test_lifecycle.test_database(ephemeral=False) as (url, ns):
        assert ns == "dev"
        assert "localhost:5432" in url
    
    mock_register.assert_called_once()
    # Ensure down -v NOT called
    down_calls = [c for c in mock_run.call_args_list if "down" in str(c)]
    assert len(down_calls) == 0

@patch("test_lifecycle.subprocess.run")
@patch("test_lifecycle.get_container_runtime")
@patch("test_lifecycle.get_namespace")
@patch("test_lifecycle.register_namespace")
@patch("test_lifecycle.unregister_namespace")
@patch("test_lifecycle.cleanup_orphan_databases")
@patch("test_lifecycle.cleanup_worker_databases")
def test_test_database_ephemeral(mock_worker, mock_orphan, mock_unregister, mock_register, mock_get_namespace, mock_get_runtime, mock_run):
    """AC8.2.2: Verify infrastructure teardown in ephemeral mode."""
    mock_get_namespace.return_value = "ephemeral_run"
    mock_get_runtime.return_value = "podman"
    
    # Sequence: up, ps, ready_check, check_exists, create, port, migrations, drop_test_db, down -v, pod rm
    mock_run.side_effect = [
        MagicMock(returncode=0), # up
        MagicMock(stdout="db_container\n"), # ps
        MagicMock(returncode=0), # ready check
        MagicMock(stdout="0"), # check db exists
        MagicMock(returncode=0), # create db
        MagicMock(stdout="5432"), # port check
        MagicMock(returncode=0), # migrations
        MagicMock(returncode=0), # drop test db
        MagicMock(returncode=0), # down -v
        MagicMock(returncode=0), # pod rm
    ]
    
    with test_lifecycle.test_database(ephemeral=True) as (url, ns):
        assert ns == "ephemeral_run"
    
    # Verify resources released
    down_calls = [c for c in mock_run.call_args_list if "down" in str(c) and "-v" in str(c)]
    assert len(down_calls) == 1
    mock_unregister.assert_called_once()

def test_load_active_namespaces_corrupted(tmp_path):
    """AC8.3.1: Verify load_active_namespaces handles corrupted JSON."""
    corrupted_file = tmp_path / "corrupted.json"
    corrupted_file.write_text("invalid json")
    with patch("test_lifecycle.ACTIVE_NAMESPACES_FILE", corrupted_file):
        namespaces = test_lifecycle.load_active_namespaces()
        assert namespaces == []
