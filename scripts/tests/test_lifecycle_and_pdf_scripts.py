import hashlib
import json
import importlib
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import test_lifecycle as tl  # noqa: E402


def test_AC16_13_1_sanitize_namespace_normalization():
    assert tl._sanitize_namespace("Feature/ABC-123") == "feature_abc_123"
    with pytest.raises(ValueError):
        tl._sanitize_namespace("___")


def test_AC16_13_2_get_namespace_from_branch_and_workspace(monkeypatch):
    monkeypatch.setenv("BRANCH_NAME", "feature/reporting")
    monkeypatch.setenv("WORKSPACE_ID", "alice")
    assert tl.get_namespace() == "feature_reporting_alice"


def test_AC16_13_3_get_namespace_from_git_and_path_hash(monkeypatch):
    monkeypatch.delenv("BRANCH_NAME", raising=False)
    monkeypatch.delenv("WORKSPACE_ID", raising=False)
    monkeypatch.setattr(
        tl.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="feature/xyz\n"),
    )
    monkeypatch.setattr(tl.Path, "cwd", lambda: Path("/tmp/repo-a"))
    expected_hash = hashlib.sha256(
        str(Path("/tmp/repo-a").absolute()).encode()
    ).hexdigest()[:8]
    assert tl.get_namespace() == f"feature_xyz_{expected_hash}"


def test_AC16_13_4_name_helpers():
    assert tl.get_test_db_name("abc") == "finance_report_test_abc"
    assert tl.get_s3_bucket("feature_a") == "statements-feature-a"


def test_AC16_13_5_load_active_namespaces_missing_and_corrupt(monkeypatch, tmp_path):
    tracker = tmp_path / "active_namespaces.json"
    monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", tracker)
    monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
    assert tl.load_active_namespaces() == []
    tracker.write_text("{not-json")
    assert tl.load_active_namespaces() == []


def test_AC16_13_6_register_unregister_namespace(monkeypatch, tmp_path):
    tracker = tmp_path / "active_namespaces.json"
    monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", tracker)
    monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)

    tl.register_namespace("n1")
    assert json.loads(tracker.read_text()) == ["n1"]

    tl.unregister_namespace("n1")
    assert json.loads(tracker.read_text()) == []


def test_AC16_13_7_get_container_runtime(monkeypatch):
    def podman_first(cmd, capture_output=True):
        if cmd == ["which", "podman"]:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(tl.subprocess, "run", podman_first)
    assert tl.get_container_runtime() == "podman"

    def none_found(cmd, capture_output=True):
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(tl.subprocess, "run", none_found)
    assert tl.get_container_runtime() is None


def test_AC16_13_8_is_db_ready_handles_failure(monkeypatch):
    def raise_called(*args, **kwargs):
        raise tl.subprocess.CalledProcessError(1, "pg_isready")

    monkeypatch.setattr(tl.subprocess, "run", raise_called)
    assert tl.is_db_ready("docker", "db") is False


def test_AC16_13_9_cleanup_worker_databases_skips_invalid_namespace(monkeypatch):
    called = {"run": False}
    monkeypatch.setattr(
        tl.subprocess, "run", lambda *args, **kwargs: called.__setitem__("run", True)
    )
    tl.cleanup_worker_databases("docker", "db", "bad namespace!")
    assert called["run"] is False


def test_AC16_13_10_cleanup_worker_databases_drops_valid_and_skips_invalid(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output=True, check=False, text=False):
        calls.append(cmd)
        if cmd[:3] == ["docker", "ps", "-q"]:
            return SimpleNamespace(stdout="container\n")
        if "SELECT datname" in " ".join(cmd):
            return SimpleNamespace(stdout="finance_report_test_x_gw1\ninvalid-name\n")
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(tl.subprocess, "run", fake_run)
    tl.cleanup_worker_databases("docker", "finance-report-db", "x")
    joined = [" ".join(cmd) for cmd in calls]
    assert any(
        "DROP DATABASE IF EXISTS finance_report_test_x_gw1;" in text for text in joined
    )
    assert all(
        "invalid-name" not in text or "DROP DATABASE" not in text for text in joined
    )


def test_AC16_13_11_get_changed_files_maps_backend_modules(monkeypatch):
    outputs = iter(
        [
            "M apps/backend/src/config.py\nD apps/backend/src/old.py\n",
            "",
            "M apps/backend/src/services/accounting.py\n",
        ]
    )

    def fake_run(cmd, capture_output=True, text=True, check=True):
        return SimpleNamespace(stdout=next(outputs))

    monkeypatch.setattr(tl.subprocess, "run", fake_run)
    modules = tl._get_changed_files()
    assert "src.config" in modules
    assert "src.services.accounting" in modules


def test_AC16_13_12_generate_statement_builds_pdf_rows(monkeypatch, tmp_path):
    fake_colors = ModuleType("reportlab.lib.colors")
    setattr(fake_colors, "grey", object())
    setattr(fake_colors, "whitesmoke", object())
    setattr(fake_colors, "beige", object())
    setattr(fake_colors, "black", object())

    fake_pagesizes = ModuleType("reportlab.lib.pagesizes")
    setattr(fake_pagesizes, "A4", object())

    fake_styles = ModuleType("reportlab.lib.styles")
    setattr(
        fake_styles,
        "getSampleStyleSheet",
        lambda: {"Heading1": object(), "Normal": object()},
    )

    fake_platypus = ModuleType("reportlab.platypus")
    setattr(fake_platypus, "SimpleDocTemplate", object)
    setattr(fake_platypus, "Table", object)
    setattr(fake_platypus, "TableStyle", lambda *args, **kwargs: object())
    setattr(fake_platypus, "Paragraph", lambda *args, **kwargs: object())
    setattr(fake_platypus, "Spacer", lambda *args, **kwargs: object())

    reportlab_pkg = ModuleType("reportlab")
    reportlab_lib_pkg = ModuleType("reportlab.lib")
    setattr(reportlab_pkg, "lib", reportlab_lib_pkg)
    setattr(reportlab_lib_pkg, "colors", fake_colors)
    setattr(reportlab_lib_pkg, "pagesizes", fake_pagesizes)
    setattr(reportlab_lib_pkg, "styles", fake_styles)

    monkeypatch.setitem(sys.modules, "reportlab", reportlab_pkg)
    monkeypatch.setitem(sys.modules, "reportlab.lib", reportlab_lib_pkg)
    monkeypatch.setitem(sys.modules, "reportlab.lib.colors", fake_colors)
    monkeypatch.setitem(sys.modules, "reportlab.lib.pagesizes", fake_pagesizes)
    monkeypatch.setitem(sys.modules, "reportlab.lib.styles", fake_styles)
    monkeypatch.setitem(sys.modules, "reportlab.platypus", fake_platypus)

    gtp = importlib.import_module("generate_test_pdfs")
    monkeypatch.setattr(gtp, "OUTPUT_DIR", tmp_path)

    captured = {"data": None, "built": False}

    class FakeDoc:
        def __init__(self, *args, **kwargs):
            pass

        def build(self, elements):
            captured["built"] = True

    class FakeTable:
        def __init__(self, data):
            captured["data"] = data

        def setStyle(self, style):
            return None

    monkeypatch.setattr(gtp, "SimpleDocTemplate", FakeDoc)
    monkeypatch.setattr(gtp, "Table", FakeTable)
    monkeypatch.setattr(gtp, "Paragraph", lambda *args, **kwargs: object())
    monkeypatch.setattr(gtp, "Spacer", lambda *args, **kwargs: object())
    monkeypatch.setattr(gtp, "TableStyle", lambda *args, **kwargs: object())

    gtp.generate_statement(
        "sample.pdf",
        "Bank",
        "123",
        date(2025, 1, 1),
        date(2025, 1, 31),
        [
            {
                "date": date(2025, 1, 2),
                "description": "Salary",
                "amount": Decimal("100.00"),
            },
            {
                "date": date(2025, 1, 3),
                "description": "Food",
                "amount": Decimal("-20.00"),
            },
        ],
        Decimal("50.00"),
    )

    assert captured["built"] is True
    assert captured["data"][0] == ["Date", "Description", "Debit", "Credit", "Balance"]
    assert captured["data"][1][3] == "100.00"
    assert captured["data"][2][2] == "20.00"


# ---------------------------------------------------------------------------
# Additional coverage tests for test_lifecycle.py
# Covers missing lines: 56-57, 71-76, 82, 126-127, 154-228, 236, 248,
#   267-273, 295-296, 323-324, 333-515, 519-610, 641-642
# ---------------------------------------------------------------------------


class TestGetNamespaceEdgeCases:
    def test_branch_with_invalid_workspace_falls_back(self, monkeypatch):
        """Line 56-57: invalid workspace ValueError caught, branch-only returned."""
        monkeypatch.setenv("BRANCH_NAME", "feature/auth")
        monkeypatch.setenv("WORKSPACE_ID", "___")
        # _sanitize_namespace("___") raises ValueError, so workspace is ignored
        assert tl.get_namespace() == "feature_auth"

    def test_git_fallback_when_no_branch_env(self, monkeypatch):
        """Lines 60-76: git auto-detection with path hash."""
        monkeypatch.delenv("BRANCH_NAME", raising=False)
        monkeypatch.delenv("WORKSPACE_ID", raising=False)

        # Simulate git returning empty branch (detached HEAD)
        def fake_run(*args, **kwargs):
            return SimpleNamespace(stdout="\n")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl.Path, "cwd", lambda: Path("/tmp/test-repo"))

        expected_hash = hashlib.sha256(
            str(Path("/tmp/test-repo").absolute()).encode()
        ).hexdigest()[:8]
        assert tl.get_namespace() == f"default_{expected_hash}"

    def test_git_exception_falls_to_default(self, monkeypatch):
        """Lines 71-76: git command fails entirely."""
        monkeypatch.delenv("BRANCH_NAME", raising=False)
        monkeypatch.delenv("WORKSPACE_ID", raising=False)

        def fake_run(*args, **kwargs):
            raise OSError("git not found")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl.Path, "cwd", lambda: Path("/tmp/fallback"))

        expected_hash = hashlib.sha256(
            str(Path("/tmp/fallback").absolute()).encode()
        ).hexdigest()[:8]
        assert tl.get_namespace() == f"default_{expected_hash}"


class TestSanitizeNamespaceEdgeCases:
    def test_empty_string_raises(self):
        """Line 82: empty name after stripping."""
        with pytest.raises(ValueError):
            tl._sanitize_namespace("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            tl._sanitize_namespace("   ")

    def test_special_chars_only_raises(self):
        """Line 88-89: all chars stripped results in empty."""
        with pytest.raises(ValueError):
            tl._sanitize_namespace("@#$%")

    def test_double_underscores_collapsed(self):
        """Line 85-86: while loop collapses double underscores."""
        assert tl._sanitize_namespace("a//b--c") == "a_b_c"


class TestSaveActiveNamespacesError:
    def test_oserror_on_write(self, monkeypatch, tmp_path):
        """Lines 126-127: OSError during file write."""
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        # Point to a file path where parent dir is a file (can't write)
        bad_file = tmp_path / "blocking_file"
        bad_file.write_text("block")
        fake_path = bad_file / "subdir" / "active_namespaces.json"
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", fake_path)
        # Should not raise, just log warning
        tl.save_active_namespaces(["test"])


class TestGetContainerRuntimeDocker:
    def test_docker_found_when_podman_missing(self, monkeypatch):
        """Line 236: docker path when podman is missing."""
        def fake_run(cmd, capture_output=True):
            if cmd == ["which", "podman"]:
                return SimpleNamespace(returncode=1)
            if cmd == ["which", "docker"]:
                return SimpleNamespace(returncode=0)
            return SimpleNamespace(returncode=1)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        assert tl.get_container_runtime() == "docker"


class TestIsDbReadySuccess:
    def test_returns_true_when_ready(self, monkeypatch):
        """Line 248: pg_isready success."""
        def fake_run(*args, **kwargs):
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        assert tl.is_db_ready("docker", "db-container") is True


class TestCleanupOrphanDatabases:
    """Lines 154-228: test cleanup_orphan_databases function."""

    def test_no_test_databases_found(self, monkeypatch, tmp_path):
        """Lines 173-175: no databases found."""
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", tmp_path / "ns.json")

        def fake_run(cmd, capture_output=True, text=True, check=True):
            # Return empty stdout
            return SimpleNamespace(stdout="\n", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        # Should not raise
        tl.cleanup_orphan_databases("docker", "db-container")

    def test_no_orphaned_databases(self, monkeypatch, tmp_path):
        """Lines 198-199: dbs found but all belong to current namespace."""
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        ns_file = tmp_path / "ns.json"
        ns_file.write_text(json.dumps([]))
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", ns_file)
        monkeypatch.setenv("BRANCH_NAME", "main")

        def fake_run(cmd, capture_output=True, text=True, check=True):
            if "SELECT datname" in " ".join(str(c) for c in cmd):
                return SimpleNamespace(stdout="finance_report_test_main\n")
            return SimpleNamespace(stdout="", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_orphan_databases("docker", "db-container")

    def test_orphaned_databases_dropped(self, monkeypatch, tmp_path):
        """Lines 186-219: orphan dbs found and dropped."""
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        ns_file = tmp_path / "ns.json"
        ns_file.write_text(json.dumps([]))
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", ns_file)
        monkeypatch.setenv("BRANCH_NAME", "main")

        dropped = []

        def fake_run(cmd, capture_output=True, text=True, check=False):
            cmd_str = " ".join(str(c) for c in cmd)
            if "SELECT datname" in cmd_str:
                return SimpleNamespace(
                    stdout="finance_report_test_main\nfinance_report_test_old_branch\nfinance_report_test\n"
                )
            if "DROP DATABASE" in cmd_str:
                dropped.append(cmd_str)
            return SimpleNamespace(stdout="", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_orphan_databases("docker", "db-container")
        # Should have dropped old_branch and legacy 'finance_report_test'
        assert len(dropped) == 2

    def test_called_process_error_handled(self, monkeypatch, tmp_path):
        """Line 227-228: CalledProcessError caught."""
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", tmp_path / "ns.json")

        def fake_run(*args, **kwargs):
            raise tl.subprocess.CalledProcessError(1, "psql")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        # Should not raise
        tl.cleanup_orphan_databases("docker", "db-container")

    def test_stale_namespaces_cleared(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        ns_file = tmp_path / "ns.json"
        ns_file.write_text(json.dumps(["stale_ns", "main"]))
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", ns_file)
        monkeypatch.setenv("BRANCH_NAME", "main")
        def fake_run(cmd, capture_output=True, check=False, text=False):
            cmd_str = " ".join(str(c) for c in cmd)
            if "SELECT datname" in cmd_str:
                return SimpleNamespace(stdout="finance_report_test_dead_ns\n")
            return SimpleNamespace(stdout="", returncode=0)
        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_orphan_databases("docker", "db-container")
        saved = json.loads(ns_file.read_text())
        assert "stale_ns" not in saved


class TestCleanupWorkerDatabasesEdgeCases:
    """Lines 267-273, 295-296, 323-324."""

    def test_container_not_running_skips(self, monkeypatch):
        """Lines 266-270: container check returns empty stdout."""
        def fake_run(cmd, capture_output=True, check=False, text=False):
            # ps -q returns empty (container not running)
            return SimpleNamespace(stdout=b"", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        # Should not raise
        tl.cleanup_worker_databases("docker", "db-container", "valid_ns")

    def test_container_check_process_error(self, monkeypatch):
        """Lines 271-273: CalledProcessError on container check."""
        def fake_run(cmd, capture_output=True, check=False, text=False):
            if "ps" in cmd:
                raise tl.subprocess.CalledProcessError(1, "docker ps")
            return SimpleNamespace(stdout="", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_worker_databases("docker", "db-container", "valid_ns")

    def test_no_worker_databases_found(self, monkeypatch):
        """Lines 294-296: empty result from SELECT."""
        call_count = {"n": 0}

        def fake_run(cmd, capture_output=True, check=False, text=False):
            call_count["n"] += 1
            if call_count["n"] == 1:  # ps -q check
                return SimpleNamespace(stdout=b"container_id\n", returncode=0)
            # SELECT datname returns empty
            return SimpleNamespace(stdout="\n", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_worker_databases("docker", "db-container", "valid_ns")

    def test_select_databases_process_error(self, monkeypatch):
        """Lines 323-324: CalledProcessError on SELECT."""
        call_count = {"n": 0}

        def fake_run(cmd, capture_output=True, check=False, text=False):
            call_count["n"] += 1
            if call_count["n"] == 1:  # ps -q check
                return SimpleNamespace(stdout=b"container_id\n", returncode=0)
            # SELECT raises error
            raise tl.subprocess.CalledProcessError(1, "psql")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_worker_databases("docker", "db-container", "valid_ns")


class TestTestDatabaseContextManager:
    """Lines 333-515: test_database context manager."""

    def test_no_runtime_exits(self, monkeypatch):
        """Lines 333-336: no container runtime found."""
        monkeypatch.setattr(tl, "get_container_runtime", lambda: None)
        with pytest.raises(SystemExit):
            with tl.test_database():
                pass  # pragma: no cover

    def test_compose_up_failure_raises(self, monkeypatch, tmp_path):
        """Lines 366-369: compose up fails."""
        monkeypatch.setattr(tl, "get_container_runtime", lambda: "docker")
        monkeypatch.setenv("BRANCH_NAME", "test")
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", tmp_path / "ns.json")

        def fake_run(*args, **kwargs):
            raise tl.subprocess.CalledProcessError(1, "compose up")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        with pytest.raises(tl.subprocess.CalledProcessError):
            with tl.test_database():
                pass  # pragma: no cover

    def test_db_not_ready_raises(self, monkeypatch, tmp_path):
        """Lines 397-400: DB never becomes ready."""
        monkeypatch.setattr(tl, "get_container_runtime", lambda: "docker")
        monkeypatch.setenv("BRANCH_NAME", "test")
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", tmp_path / "ns.json")

        call_idx = {"n": 0}

        def fake_run(*args, **kwargs):
            call_idx["n"] += 1
            if call_idx["n"] == 1:  # compose up
                return SimpleNamespace(returncode=0)
            if "ps" in str(args) and "format" in str(args):  # compose ps
                return SimpleNamespace(stdout="", returncode=0)
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl, "is_db_ready", lambda *a: False)
        monkeypatch.setattr(tl.time, "sleep", lambda s: None)

        with pytest.raises(Exception, match="Database not ready"):
            with tl.test_database():
                pass  # pragma: no cover

    def test_successful_lifecycle(self, monkeypatch, tmp_path):
        """Lines 333-515: full happy path through context manager."""
        monkeypatch.setattr(tl, "get_container_runtime", lambda: "docker")
        monkeypatch.setenv("BRANCH_NAME", "test")
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", tmp_path / "ns.json")
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

        steps = []

        def fake_run(cmd_or_args, *args, **kwargs):
            cmd = cmd_or_args if isinstance(cmd_or_args, list) else [cmd_or_args]
            cmd_str = " ".join(str(c) for c in cmd)
            steps.append(cmd_str)
            # compose ps returns a container name
            if "ps" in cmd_str and "format" in cmd_str:
                return SimpleNamespace(stdout="test-db-container\n", returncode=0)
            # port command returns a port
            if "port" in cmd_str:
                return SimpleNamespace(stdout="0.0.0.0:5433\n", returncode=0)
            return SimpleNamespace(stdout="", stderr=b"", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl, "is_db_ready", lambda *a: True)
        monkeypatch.setattr(tl, "cleanup_orphan_databases", lambda *a: None)
        monkeypatch.setattr(tl, "cleanup_worker_databases", lambda *a: None)

        with tl.test_database() as (db_url, namespace):
            assert "postgresql+asyncpg" in db_url
            assert "5433" in db_url
            assert namespace == "test"

    def test_ephemeral_mode_teardown(self, monkeypatch, tmp_path):
        """Lines 498-510: ephemeral mode tears down infrastructure."""
        monkeypatch.setattr(tl, "get_container_runtime", lambda: "docker")
        monkeypatch.setenv("BRANCH_NAME", "test")
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", tmp_path / "ns.json")
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

        teardown_calls = []

        def fake_run(cmd_or_args, *args, **kwargs):
            cmd = cmd_or_args if isinstance(cmd_or_args, list) else [cmd_or_args]
            cmd_str = " ".join(str(c) for c in cmd)
            if "down" in cmd_str:
                teardown_calls.append(cmd_str)
            if "ps" in cmd_str and "format" in cmd_str:
                return SimpleNamespace(stdout="", returncode=0)
            if "port" in cmd_str:
                return SimpleNamespace(stdout="0.0.0.0:5432\n", returncode=0)
            return SimpleNamespace(stdout="", stderr=b"", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl, "is_db_ready", lambda *a: True)
        monkeypatch.setattr(tl, "cleanup_orphan_databases", lambda *a: None)
        monkeypatch.setattr(tl, "cleanup_worker_databases", lambda *a: None)

        with tl.test_database(ephemeral=True) as (db_url, namespace):
            pass

        assert any("down" in c for c in teardown_calls)

    def test_migration_failure_raises(self, monkeypatch, tmp_path):
        """Lines 465-468: alembic migration fails."""
        monkeypatch.setattr(tl, "get_container_runtime", lambda: "docker")
        monkeypatch.setenv("BRANCH_NAME", "test")
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", tmp_path / "ns.json")
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

        call_idx = {"n": 0}

        def fake_run(cmd_or_args, *args, **kwargs):
            cmd = cmd_or_args if isinstance(cmd_or_args, list) else [cmd_or_args]
            cmd_str = " ".join(str(c) for c in cmd)
            call_idx["n"] += 1
            if "ps" in cmd_str and "format" in cmd_str:
                return SimpleNamespace(stdout="", returncode=0)
            if "port" in cmd_str:
                return SimpleNamespace(stdout="0.0.0.0:5432\n", returncode=0)
            if "alembic" in cmd_str:
                raise tl.subprocess.CalledProcessError(
                    1, "alembic", stderr=b"migration error"
                )
            return SimpleNamespace(stdout="", stderr=b"", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl, "is_db_ready", lambda *a: True)
        monkeypatch.setattr(tl, "cleanup_orphan_databases", lambda *a: None)

        with pytest.raises(tl.subprocess.CalledProcessError):
            with tl.test_database():
                pass  # pragma: no cover


class TestMainFunction:
    """Lines 519-610: main() function."""

    def test_main_default_mode(self, monkeypatch, tmp_path):
        """Lines 578-583: default mode (no --fast/--smart)."""
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

        # Patch test_database to yield immediately
        from contextlib import contextmanager

        @contextmanager
        def fake_test_db(ephemeral=False):
            yield ("postgresql+asyncpg://localhost/test", "test_ns")

        monkeypatch.setattr(tl, "test_database", fake_test_db)
        monkeypatch.setattr(tl, "get_s3_bucket", lambda ns: "test-bucket")

        # Patch subprocess to succeed for pytest command
        def fake_run(cmd, *args, **kwargs):
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl.signal, "signal", lambda *a: None)
        monkeypatch.setattr(tl.sys, "argv", ["test_lifecycle.py"])

        tl.main()

    def test_main_fast_mode(self, monkeypatch, tmp_path):
        """Lines 539-547: --fast mode adds specific pytest args."""
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

        from contextlib import contextmanager

        @contextmanager
        def fake_test_db(ephemeral=False):
            yield ("postgresql+asyncpg://localhost/test", "test_ns")

        monkeypatch.setattr(tl, "test_database", fake_test_db)
        monkeypatch.setattr(tl, "get_s3_bucket", lambda ns: "test-bucket")

        captured_cmd = {}

        def fake_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "pytest" in cmd:
                captured_cmd["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl.signal, "signal", lambda *a: None)
        monkeypatch.setattr(tl.sys, "argv", ["test_lifecycle.py", "--fast"])

        tl.main()
        assert "--no-cov" in captured_cmd["cmd"]
        assert "-n" in captured_cmd["cmd"]

    def test_main_smart_mode_with_changes(self, monkeypatch, tmp_path):
        """Lines 548-577: --smart mode with detected changes."""
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

        from contextlib import contextmanager

        @contextmanager
        def fake_test_db(ephemeral=False):
            yield ("postgresql+asyncpg://localhost/test", "test_ns")

        monkeypatch.setattr(tl, "test_database", fake_test_db)
        monkeypatch.setattr(tl, "get_s3_bucket", lambda ns: "test-bucket")
        monkeypatch.setattr(
            tl, "_get_changed_files",
            lambda base_branch="main": ["src.config", "src.models.account"]
        )

        captured_cmd = {}

        def fake_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "pytest" in cmd:
                captured_cmd["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl.signal, "signal", lambda *a: None)
        monkeypatch.setattr(tl.sys, "argv", ["test_lifecycle.py", "--smart"])

        tl.main()
        assert "--cov=src.config" in captured_cmd["cmd"]

    def test_main_smart_mode_no_changes(self, monkeypatch, tmp_path):
        """Lines 570-577: --smart mode with no changes falls back."""
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

        from contextlib import contextmanager

        @contextmanager
        def fake_test_db(ephemeral=False):
            yield ("postgresql+asyncpg://localhost/test", "test_ns")

        monkeypatch.setattr(tl, "test_database", fake_test_db)
        monkeypatch.setattr(tl, "get_s3_bucket", lambda ns: "test-bucket")
        monkeypatch.setattr(
            tl, "_get_changed_files",
            lambda base_branch="main": []
        )

        captured_cmd = {}

        def fake_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "pytest" in cmd:
                captured_cmd["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl.signal, "signal", lambda *a: None)
        monkeypatch.setattr(tl.sys, "argv", ["test_lifecycle.py", "--smart"])

        tl.main()
        assert "--cov=src" in captured_cmd["cmd"]

    def test_main_test_failure_exits_nonzero(self, monkeypatch, tmp_path):
        """Lines 602-604: test failure exits with code."""
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

        from contextlib import contextmanager

        @contextmanager
        def fake_test_db(ephemeral=False):
            yield ("postgresql+asyncpg://localhost/test", "test_ns")

        monkeypatch.setattr(tl, "test_database", fake_test_db)
        monkeypatch.setattr(tl, "get_s3_bucket", lambda ns: "test-bucket")

        def fake_run(cmd, *args, **kwargs):
            return SimpleNamespace(returncode=1, stdout="")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl.signal, "signal", lambda *a: None)
        monkeypatch.setattr(tl.sys, "argv", ["test_lifecycle.py"])

        with pytest.raises(SystemExit) as exc:
            tl.main()
        assert exc.value.code == 1

    def test_main_exception_exits(self, monkeypatch, tmp_path):
        """Lines 608-610: exception during main exits."""
        from contextlib import contextmanager

        @contextmanager
        def failing_test_db(ephemeral=False):
            raise RuntimeError("boom")
            yield  # unreachable but needed for generator

        monkeypatch.setattr(tl, "test_database", failing_test_db)
        monkeypatch.setattr(tl.signal, "signal", lambda *a: None)
        monkeypatch.setattr(tl.sys, "argv", ["test_lifecycle.py"])

        with pytest.raises(SystemExit) as exc:
            tl.main()
        assert exc.value.code == 1


class TestGetChangedFilesEdgeCases:
    """Lines 641-642: CalledProcessError returns empty list."""

    def test_git_error_returns_empty(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise tl.subprocess.CalledProcessError(1, "git diff")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        assert tl._get_changed_files() == []

    def test_smart_mode_many_changed_files_truncated_log(self, monkeypatch, tmp_path):
        """Lines 558-562: more than 5 changed modules triggers truncated log."""
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

        from contextlib import contextmanager

        @contextmanager
        def fake_test_db(ephemeral=False):
            yield ("postgresql+asyncpg://localhost/test", "test_ns")

        monkeypatch.setattr(tl, "test_database", fake_test_db)
        monkeypatch.setattr(tl, "get_s3_bucket", lambda ns: "test-bucket")
        monkeypatch.setattr(
            tl, "_get_changed_files",
            lambda base_branch="main": [f"src.mod{i}" for i in range(8)]
        )

        def fake_run(cmd, *args, **kwargs):
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl.signal, "signal", lambda *a: None)
        monkeypatch.setattr(tl.sys, "argv", ["test_lifecycle.py", "--smart"])

        # Should not raise
        tl.main()