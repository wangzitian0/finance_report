import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

workspace_root = Path(__file__).resolve().parents[4]
isolation_utils_path = workspace_root / "scripts" / "isolation_utils.py"

spec = importlib.util.spec_from_file_location("isolation_utils", isolation_utils_path)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load isolation_utils from {isolation_utils_path}")

isolation_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(isolation_utils)

get_namespace = isolation_utils.get_namespace
get_test_db_name = isolation_utils.get_test_db_name
get_env_suffix = isolation_utils.get_env_suffix
get_s3_bucket = isolation_utils.get_s3_bucket
sanitize_namespace = isolation_utils.sanitize_namespace


class TestNamespaceGeneration:
    """Test namespace generation logic for multi-repo isolation."""

    def test_explicit_branch_name(self):
        with patch.dict(os.environ, {"BRANCH_NAME": "feature-auth"}, clear=True):
            namespace = get_namespace()
            assert namespace == "feature_auth"

    def test_explicit_branch_name_with_workspace_id(self):
        with patch.dict(
            os.environ,
            {"BRANCH_NAME": "feature-auth", "WORKSPACE_ID": "abc123"},
            clear=True,
        ):
            namespace = get_namespace()
            assert namespace == "feature_auth_abc123"

    def test_sanitize_removes_special_chars(self):
        assert sanitize_namespace("feature/auth-system") == "feature_auth_system"
        assert sanitize_namespace("bug-fix#123") == "bug_fix123"
        assert sanitize_namespace("FEATURE_Auth") == "feature_auth"

    def test_git_branch_with_path_hash(self, tmp_path):
        test_repo = tmp_path / "test_repo"
        test_repo.mkdir()
        (test_repo / ".git").mkdir()

        with patch.dict(os.environ, {}, clear=True):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.stdout = "feature-payments\n"
                mock_run.return_value.returncode = 0

                with patch("pathlib.Path.cwd", return_value=test_repo):
                    namespace = get_namespace()

                    path_hash = hashlib.sha256(str(test_repo).encode()).hexdigest()[:8]
                    expected = f"feature_payments_{path_hash}"
                    assert namespace == expected

    def test_fallback_default_with_warning(self, capsys):
        with patch.dict(os.environ, {}, clear=True):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = Exception("Not a git repo")

                namespace = get_namespace()
                assert namespace == "default"

                captured = capsys.readouterr()
                assert "WARNING" in captured.out
                assert "may conflict" in captured.out.lower()

    def test_main_branch_auto_detect_adds_path_hash(self, tmp_path):
        """Auto-detected main/master branch should add path hash for multi-repo isolation."""
        test_repo = tmp_path / "test_repo"
        test_repo.mkdir()
        (test_repo / ".git").mkdir()

        with patch.dict(os.environ, {}, clear=True):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.stdout = "main\n"
                mock_run.return_value.returncode = 0

                with patch("pathlib.Path.cwd", return_value=test_repo):
                    namespace = get_namespace()

                    # Should include path hash even for main branch
                    path_hash = hashlib.sha256(str(test_repo).encode()).hexdigest()[:8]
                    expected = f"main_{path_hash}"
                    assert namespace == expected

    def test_subprocess_timeout_fallback(self, tmp_path, capsys):
        """Git command timeout should fall back to default namespace with warning."""
        test_repo = tmp_path / "test_repo"
        test_repo.mkdir()
        (test_repo / ".git").mkdir()

        with patch.dict(os.environ, {}, clear=True):
            with patch("subprocess.run") as mock_run:
                import subprocess

                mock_run.side_effect = subprocess.TimeoutExpired("git", 5)

                with patch("pathlib.Path.cwd", return_value=test_repo):
                    namespace = get_namespace()

                    # Should fall back to default with path hash
                    path_hash = hashlib.sha256(str(test_repo).encode()).hexdigest()[:8]
                    expected = f"default_{path_hash}"
                    assert namespace == expected

                    captured = capsys.readouterr()
                    assert "WARNING" in captured.out

    def test_sanitize_empty_input_raises_error(self):
        """Empty namespace input should raise ValueError."""
        with pytest.raises(ValueError, match="results in empty identifier"):
            sanitize_namespace("")

        with pytest.raises(ValueError, match="results in empty identifier"):
            sanitize_namespace("   ")

        with pytest.raises(ValueError, match="results in empty identifier"):
            sanitize_namespace("///")

        with pytest.raises(ValueError, match="results in empty identifier"):
            sanitize_namespace("---")

    def test_sanitize_comprehensive_special_chars(self):
        """All special characters should be properly sanitized."""
        # Slashes become underscores
        assert sanitize_namespace("feature/auth/system") == "feature_auth_system"

        # Hyphens become underscores
        assert sanitize_namespace("bug-fix-123") == "bug_fix_123"

        # Mixed special chars are removed or converted
        assert sanitize_namespace("test@#$%branch") == "test_branch"

        # Dots are removed
        assert sanitize_namespace("v1.2.3") == "v123"

        # Multiple consecutive special chars collapse to single underscore
        assert sanitize_namespace("test///branch") == "test_branch"
        assert sanitize_namespace("test---branch") == "test_branch"

        # Leading/trailing special chars are stripped
        assert sanitize_namespace("/feature/") == "feature"
        assert sanitize_namespace("-branch-") == "branch"

        # Uppercase is lowercased
        assert sanitize_namespace("Feature-AUTH") == "feature_auth"

        # Parentheses and brackets removed
        assert sanitize_namespace("fix(auth)") == "fixauth"
        assert sanitize_namespace("test[123]") == "test123"


class TestDatabaseNaming:
    """Test database name generation with namespace isolation."""

    def test_test_db_name_with_namespace(self):
        namespace = "feature_auth_abc123"
        db_name = get_test_db_name(namespace)
        assert db_name == "finance_report_test_feature_auth_abc123"

    def test_test_db_name_default(self):
        db_name = get_test_db_name("default")
        assert db_name == "finance_report_test_default"

    def test_env_suffix(self):
        namespace = "feature_auth"
        suffix = get_env_suffix(namespace)
        assert suffix == "-feature_auth"


class TestS3BucketNaming:
    """Test S3 bucket name generation with namespace isolation."""

    def test_s3_bucket_with_namespace(self):
        namespace = "feature_auth_abc123"
        bucket = get_s3_bucket(namespace)
        assert bucket == "statements-feature_auth_abc123"

    def test_s3_bucket_default(self):
        bucket = get_s3_bucket("default")
        assert bucket == "statements-default"


class TestIntegrationWithConftest:
    """Test that conftest.py properly integrates with isolation_utils."""

    def test_conftest_uses_test_namespace_env_var(self):
        from tests.conftest import get_test_db_url

        with patch.dict(os.environ, {"TEST_NAMESPACE": "feature_test_xyz789"}, clear=True):
            master_url = get_test_db_url("master")
            assert "finance_report_test_feature_test_xyz789" in master_url

            worker_url = get_test_db_url("gw0")
            assert "finance_report_test_feature_test_xyz789_gw0" in worker_url

    def test_conftest_falls_back_to_default(self):
        from tests.conftest import get_test_db_url

        with patch.dict(os.environ, {}, clear=True):
            master_url = get_test_db_url("master")
            assert "finance_report_test_default" in master_url


class TestWorkerDatabaseNaming:
    """Test pytest-xdist worker database naming patterns."""

    def test_master_worker_no_suffix(self):
        from tests.conftest import get_test_db_url

        with patch.dict(os.environ, {"TEST_NAMESPACE": "feature_a"}, clear=True):
            url = get_test_db_url("master")
            assert url.endswith("finance_report_test_feature_a")
            assert "_gw" not in url

    def test_parallel_workers_get_suffix(self):
        from tests.conftest import get_test_db_url

        with patch.dict(os.environ, {"TEST_NAMESPACE": "feature_b"}, clear=True):
            gw0_url = get_test_db_url("gw0")
            gw1_url = get_test_db_url("gw1")
            gw2_url = get_test_db_url("gw2")

            assert "finance_report_test_feature_b_gw0" in gw0_url
            assert "finance_report_test_feature_b_gw1" in gw1_url
            assert "finance_report_test_feature_b_gw2" in gw2_url

    def test_worker_urls_are_distinct(self):
        from tests.conftest import get_test_db_url

        with patch.dict(os.environ, {"TEST_NAMESPACE": "feature_c"}, clear=True):
            urls = [get_test_db_url(f"gw{i}") for i in range(5)]

            assert len(urls) == len(set(urls))
            for url in urls:
                assert "finance_report_test_feature_c_gw" in url
