"""AC16.13.1 AC16.13.2 AC16.13.3 AC16.13.4 AC16.13.5 AC16.13.6 AC16.13.7 AC16.13.8 AC16.13.9 AC16.13.10 AC16.13.11 AC16.13.12"""

import hashlib
import importlib
import json
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from common.runtime.dev import test_lifecycle as tl
from common.runtime.dev import toolchain

GENERATE_TEST_PDFS_MODULE = "common.testing.fixtures.generate_test_pdfs"


@pytest.fixture
def fake_reportlab(monkeypatch):
    fake_colors = ModuleType("reportlab.lib.colors")
    for color in ("grey", "whitesmoke", "beige", "black"):
        setattr(fake_colors, color, object())
    fake_pagesizes = ModuleType("reportlab.lib.pagesizes")
    fake_pagesizes.A4 = (595.27, 841.89)
    fake_styles = ModuleType("reportlab.lib.styles")
    fake_styles.getSampleStyleSheet = lambda: {"Heading1": object(), "Normal": object()}
    fake_platypus = ModuleType("reportlab.platypus")
    for cls_name in ("SimpleDocTemplate", "Table"):
        setattr(fake_platypus, cls_name, object)
    for fn_name in ("TableStyle", "Paragraph", "Spacer"):
        setattr(fake_platypus, fn_name, lambda *a, **k: object())
    fake_pdfmetrics = ModuleType("reportlab.pdfbase.pdfmetrics")
    fake_pdfmetrics.registerFont = lambda font: None
    fake_cidfonts = ModuleType("reportlab.pdfbase.cidfonts")
    fake_cidfonts.UnicodeCIDFont = lambda name: object()
    fake_pdfbase = ModuleType("reportlab.pdfbase")
    fake_pdfbase.pdfmetrics = fake_pdfmetrics
    fake_pdfbase.cidfonts = fake_cidfonts
    captured = {"strings": [], "saved": False}

    class FakeCanvas:
        def __init__(self, *args, **kwargs):
            pass

        def setTitle(self, *a):
            pass

        def setAuthor(self, *a):
            pass

        def setCreator(self, *a):
            pass

        def setSubject(self, *a):
            pass

        def setFont(self, *a):
            pass

        def drawString(self, x, y, text):
            captured["strings"].append(text)

        def drawRightString(self, x, y, text):
            captured["strings"].append(text)

        def line(self, *a):
            pass

        def showPage(self):
            pass

        def save(self):
            captured["saved"] = True

    fake_canvas_mod = ModuleType("reportlab.pdfgen.canvas")
    fake_canvas_mod.Canvas = FakeCanvas
    fake_pdfgen = ModuleType("reportlab.pdfgen")
    fake_pdfgen.canvas = fake_canvas_mod
    reportlab_pkg = ModuleType("reportlab")
    reportlab_lib_pkg = ModuleType("reportlab.lib")
    reportlab_pkg.lib = reportlab_lib_pkg
    reportlab_pkg.pdfbase = fake_pdfbase
    reportlab_pkg.pdfgen = fake_pdfgen
    reportlab_lib_pkg.colors = fake_colors
    reportlab_lib_pkg.pagesizes = fake_pagesizes
    reportlab_lib_pkg.styles = fake_styles

    for mod_name, mod_obj in (
        ("reportlab", reportlab_pkg),
        ("reportlab.lib", reportlab_lib_pkg),
        ("reportlab.lib.colors", fake_colors),
        ("reportlab.lib.pagesizes", fake_pagesizes),
        ("reportlab.lib.styles", fake_styles),
        ("reportlab.platypus", fake_platypus),
        ("reportlab.pdfbase", fake_pdfbase),
        ("reportlab.pdfbase.pdfmetrics", fake_pdfmetrics),
        ("reportlab.pdfbase.cidfonts", fake_cidfonts),
        ("reportlab.pdfgen", fake_pdfgen),
        ("reportlab.pdfgen.canvas", fake_canvas_mod),
    ):
        monkeypatch.setitem(sys.modules, mod_name, mod_obj)
    yield captured


def import_gtp_with_mocks(monkeypatch, tmp_path, captured):
    sys.modules.pop(GENERATE_TEST_PDFS_MODULE, None)
    gtp = importlib.import_module(GENERATE_TEST_PDFS_MODULE)
    monkeypatch.setattr(gtp, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(gtp, "ROOT_DIR", tmp_path.parent)
    return gtp


def _setup_ns_files(monkeypatch, tmp_path, *, active=None, branch=None):
    ns_file = tmp_path / "ns.json"
    if active is not None:
        ns_file.write_text(json.dumps(active))
    monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tl, "ACTIVE_NAMESPACES_FILE", ns_file)
    if branch is not None:
        monkeypatch.setenv("BRANCH_NAME", branch)
    return ns_file


def _setup_main_mocks(monkeypatch, tmp_path, argv, *, returncode=0, changed=None):
    monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)

    @contextmanager
    def fake_test_db(ephemeral=False):
        yield ("postgresql+asyncpg://localhost/test", "test_ns")

    monkeypatch.setattr(tl, "test_database", fake_test_db)
    monkeypatch.setattr(tl, "get_s3_bucket", lambda ns: "test-bucket")
    if changed is not None:
        monkeypatch.setattr(
            tl, "_get_changed_files", lambda base_branch="main": changed
        )
    captured_cmd = {}

    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and "pytest" in cmd:
            captured_cmd["cmd"] = cmd
        return SimpleNamespace(returncode=returncode, stdout="")

    monkeypatch.setattr(tl.subprocess, "run", fake_run)
    monkeypatch.setattr(tl.signal, "signal", lambda *a: None)
    monkeypatch.setattr(tl.sys, "argv", argv)
    return captured_cmd


def test_AC8_13_15_pdf_fixture_modules_are_importable_for_script_coverage():
    """AC8.13.15"""
    modules = [
        "common.testing.fixtures.pdf.analyzers.analyze_pdf",
        "common.testing.fixtures.pdf.analyzers.pdf_analyzer",
        "common.testing.fixtures.pdf.generate_pdf_fixtures",
        "common.testing.fixtures.pdf.generators.moomoo_generator",
        "common.testing.fixtures.pdf.generators.pingan_generator",
    ]
    assert all(importlib.import_module(m) for m in modules)


def test_AC16_13_1_sanitize_namespace_normalization():
    """AC-testing.lifecycle.2 AC16.13.1"""
    assert tl._sanitize_namespace("Feature/ABC-123") == "feature_abc_123"
    with pytest.raises(ValueError):
        tl._sanitize_namespace("___")


def test_AC16_13_2_get_namespace_from_branch_and_workspace(monkeypatch):
    """AC-testing.lifecycle.3"""
    monkeypatch.setenv("BRANCH_NAME", "feature/reporting")
    monkeypatch.setenv("WORKSPACE_ID", "alice")
    assert tl.get_namespace() == "feature_reporting_alice"


def test_AC16_13_3_get_namespace_from_git_and_path_hash(monkeypatch):
    """AC-testing.lifecycle.4"""
    monkeypatch.delenv("BRANCH_NAME", raising=False)
    monkeypatch.delenv("WORKSPACE_ID", raising=False)
    monkeypatch.setattr(
        tl.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="feature/xyz\n")
    )
    monkeypatch.setattr(tl.Path, "cwd", lambda: Path("/tmp/repo-a"))
    expected = hashlib.sha256(str(Path("/tmp/repo-a").absolute()).encode()).hexdigest()[
        :8
    ]
    assert tl.get_namespace() == f"feature_xyz_{expected}"


def test_AC16_13_4_name_helpers():
    """AC-testing.lifecycle.5 AC8.13.69"""
    assert tl.get_test_db_name("abc") == "finance_report_test_abc"
    assert tl.get_s3_bucket("feature_a") == "statements-feature-a"
    long_ns = "codex_issue_490_testing_strategy_ac_coverage_0bb5607e"
    db_name, bucket = tl.get_test_db_name(long_ns), tl.get_s3_bucket(long_ns)
    assert len(db_name) <= 63 and db_name.startswith("finance_report_test_")
    assert len(bucket) <= 63 and bucket.startswith("statements-") and "_" not in bucket
    assert tl._extract_host_port("\n  \nnot-a-port\n0.0.0.0:65432\n") == "65432"
    assert (
        tl._extract_host_port("5432/tcp -> 127.0.0.1:65433\nignored:invalid\n")
        == "65433"
    )
    assert tl._extract_host_port("\ninvalid\n") is None


def test_AC16_13_5_load_active_namespaces_missing_and_corrupt(monkeypatch, tmp_path):
    """AC-testing.lifecycle.6"""
    tracker = _setup_ns_files(monkeypatch, tmp_path)
    assert tl.load_active_namespaces() == []
    tracker.write_text("{not-json")
    assert tl.load_active_namespaces() == []


def test_AC16_13_6_register_unregister_namespace(monkeypatch, tmp_path):
    """AC-testing.lifecycle.7"""
    tracker = _setup_ns_files(monkeypatch, tmp_path)
    tl.register_namespace("n1")
    assert json.loads(tracker.read_text()) == ["n1"]
    tl.unregister_namespace("n1")
    assert json.loads(tracker.read_text()) == []


def test_AC16_13_7_get_container_runtime(monkeypatch):
    """AC-testing.lifecycle.8"""
    monkeypatch.setattr(
        toolchain.shutil,
        "which",
        lambda n: "/usr/bin/podman" if n == "podman" else None,
    )
    assert tl.get_container_runtime() == "podman"
    monkeypatch.setattr(toolchain.shutil, "which", lambda n: None)
    assert tl.get_container_runtime() is None


def test_AC16_13_7_get_container_runtime_honors_container_runtime_override(monkeypatch):
    monkeypatch.setenv("CONTAINER_RUNTIME", "docker")
    monkeypatch.setattr(
        toolchain.shutil,
        "which",
        lambda n: f"/usr/bin/{n}" if n in {"docker", "podman"} else None,
    )
    assert tl.get_container_runtime() == "docker"


def test_AC8_13_69_resolve_postgres_host_port_uses_runtime_fallback(monkeypatch):
    """AC8.13.69"""
    calls = []

    def fake_run(cmd, capture_output=True, text=False, env=None):
        calls.append((cmd, env))
        if cmd == ["podman-compose", "port", "postgres", "5432"]:
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="5432/tcp -> 127.0.0.1:65432\n")

    monkeypatch.setattr(tl.subprocess, "run", fake_run)
    assert (
        tl.resolve_postgres_host_port(
            "podman", ["podman-compose"], {"TEST_ENV": "1"}, "db-container"
        )
        == "65432"
    )
    assert calls == [
        (["podman-compose", "port", "postgres", "5432"], {"TEST_ENV": "1"}),
        (["podman", "port", "db-container", "5432/tcp"], None),
    ]


def test_AC16_13_8_is_db_ready_handles_failure(monkeypatch):
    """AC-testing.lifecycle.9"""

    def raise_called(*a, **k):
        raise tl.subprocess.CalledProcessError(1, "pg_isready")

    monkeypatch.setattr(tl.subprocess, "run", raise_called)
    assert tl.is_db_ready("docker", "db") is False


def test_AC16_13_9_cleanup_worker_databases_skips_invalid_namespace(monkeypatch):
    """AC-testing.lifecycle.10"""
    called = {"run": False}
    monkeypatch.setattr(
        tl.subprocess, "run", lambda *a, **k: called.__setitem__("run", True)
    )
    tl.cleanup_worker_databases("docker", "db", "bad namespace!")
    assert called["run"] is False


def test_AC16_13_10_cleanup_worker_databases_drops_valid_and_skips_invalid(monkeypatch):
    """AC-testing.lifecycle.11"""
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
        "DROP DATABASE IF EXISTS finance_report_test_x_gw1;" in t for t in joined
    )
    assert all("invalid-name" not in t or "DROP DATABASE" not in t for t in joined)


def test_AC16_13_11_get_changed_files_maps_backend_modules(monkeypatch):
    """AC-testing.lifecycle.12"""
    outputs = iter(
        [
            "M apps/backend/src/config.py\nD apps/backend/src/old.py\n",
            "",
            "M apps/backend/src/ledger/extension/accounting.py\n",
        ]
    )
    monkeypatch.setattr(
        tl.subprocess,
        "run",
        lambda cmd, capture_output=True, text=True, check=True: SimpleNamespace(
            stdout=next(outputs)
        ),
    )
    modules = tl._get_changed_files()
    assert "src.config" in modules and "src.ledger.extension.accounting" in modules


def test_AC16_13_12_generate_statement_builds_pdf_rows(
    monkeypatch, tmp_path, fake_reportlab
):
    """AC-testing.lifecycle.13"""
    captured = fake_reportlab
    gtp = import_gtp_with_mocks(monkeypatch, tmp_path, captured)
    dbs_fixture = gtp.get_fixtures()[0]
    balances = gtp.compute_balances(Decimal("12000.00"), dbs_fixture.transactions)
    assert balances[:3] == [
        Decimal("17200.00"),
        Decimal("15000.00"),
        Decimal("14913.60"),
    ]
    gtp.write_fixture_pdf_and_json(dbs_fixture)
    assert captured["saved"] is True
    assert any("DBS BANK" in s for s in captured["strings"])
    assert any("3456" in s for s in captured["strings"])
    data = json.loads((tmp_path / dbs_fixture.json_name).read_text())
    assert data["institution"] == "DBS" and data["success"] is True
    assert (
        len(data["events"]) == 7 and data["statement"]["opening_balance"] == "12000.00"
    )


class TestGetNamespaceEdgeCases:
    def test_branch_with_invalid_workspace_falls_back(self, monkeypatch):
        monkeypatch.setenv("BRANCH_NAME", "feature/auth")
        monkeypatch.setenv("WORKSPACE_ID", "___")
        assert tl.get_namespace() == "feature_auth"

    def test_git_fallback_when_no_branch_env(self, monkeypatch):
        monkeypatch.delenv("BRANCH_NAME", raising=False)
        monkeypatch.delenv("WORKSPACE_ID", raising=False)
        monkeypatch.setattr(
            tl.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="\n")
        )
        monkeypatch.setattr(tl.Path, "cwd", lambda: Path("/tmp/test-repo"))
        expected = hashlib.sha256(
            str(Path("/tmp/test-repo").absolute()).encode()
        ).hexdigest()[:8]
        assert tl.get_namespace() == f"default_{expected}"

    def test_git_exception_falls_to_default(self, monkeypatch):
        monkeypatch.delenv("BRANCH_NAME", raising=False)
        monkeypatch.delenv("WORKSPACE_ID", raising=False)

        def fake_run(*a, **k):
            raise OSError("git not found")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl.Path, "cwd", lambda: Path("/tmp/fallback"))
        expected = hashlib.sha256(
            str(Path("/tmp/fallback").absolute()).encode()
        ).hexdigest()[:8]
        assert tl.get_namespace() == f"default_{expected}"


class TestSanitizeNamespaceEdgeCases:
    def test_empty_string_raises(self):
        for bad in ("", "   ", "@#$%"):
            with pytest.raises(ValueError):
                tl._sanitize_namespace(bad)
        assert tl._sanitize_namespace("a//b--c") == "a_b_c"


class TestSaveActiveNamespacesError:
    def test_oserror_on_write(self, monkeypatch, tmp_path):
        bad_file = tmp_path / "blocking_file"
        bad_file.write_text("block")
        monkeypatch.setattr(tl, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(
            tl, "ACTIVE_NAMESPACES_FILE", bad_file / "subdir" / "active.json"
        )
        tl.save_active_namespaces(["test"])


class TestGetContainerRuntimeDocker:
    def test_docker_found_when_podman_missing(self, monkeypatch):
        monkeypatch.setattr(
            toolchain.shutil,
            "which",
            lambda n: "/usr/bin/docker" if n == "docker" else None,
        )
        assert tl.get_container_runtime() == "docker"


class TestIsDbReadySuccess:
    def test_returns_true_when_ready(self, monkeypatch):
        monkeypatch.setattr(
            tl.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0)
        )
        assert tl.is_db_ready("docker", "db-container") is True


class TestCleanupOrphanDatabases:
    def test_no_test_databases_found(self, monkeypatch, tmp_path):
        _setup_ns_files(monkeypatch, tmp_path)
        monkeypatch.setattr(
            tl.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(stdout="\n", returncode=0),
        )
        tl.cleanup_orphan_databases("docker", "db-container")

    def test_no_orphaned_databases(self, monkeypatch, tmp_path):
        _setup_ns_files(monkeypatch, tmp_path, active=[], branch="main")
        monkeypatch.setattr(
            tl.subprocess,
            "run",
            lambda cmd, **k: SimpleNamespace(
                stdout="finance_report_test_main\n"
                if "SELECT datname" in " ".join(map(str, cmd))
                else "",
                returncode=0,
            ),
        )
        tl.cleanup_orphan_databases("docker", "db-container")

    def test_orphaned_databases_dropped(self, monkeypatch, tmp_path):
        _setup_ns_files(monkeypatch, tmp_path, active=[], branch="main")
        dropped = []

        def fake_run(cmd, **k):
            cmd_str = " ".join(map(str, cmd))
            if "SELECT datname" in cmd_str:
                return SimpleNamespace(
                    stdout="finance_report_test_main\nfinance_report_test_old_branch\nfinance_report_test\n"
                )
            if "DROP DATABASE" in cmd_str:
                dropped.append(cmd_str)
            return SimpleNamespace(stdout="", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_orphan_databases("docker", "db-container")
        assert len(dropped) == 2

    def test_called_process_error_handled(self, monkeypatch, tmp_path):
        _setup_ns_files(monkeypatch, tmp_path)

        def fake_run(*a, **k):
            raise tl.subprocess.CalledProcessError(1, "psql")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_orphan_databases("docker", "db-container")

    def test_stale_namespaces_cleared(self, monkeypatch, tmp_path):
        ns_file = _setup_ns_files(
            monkeypatch, tmp_path, active=["stale_ns", "main"], branch="main"
        )
        monkeypatch.setattr(
            tl.subprocess,
            "run",
            lambda cmd, **k: SimpleNamespace(
                stdout="finance_report_test_dead_ns\n"
                if "SELECT datname" in " ".join(map(str, cmd))
                else "",
                returncode=0,
            ),
        )
        tl.cleanup_orphan_databases("docker", "db-container")
        assert "stale_ns" not in json.loads(ns_file.read_text())


class TestCleanupWorkerDatabasesEdgeCases:
    def test_container_not_running_skips(self, monkeypatch):
        monkeypatch.setattr(
            tl.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(stdout=b"", returncode=0),
        )
        tl.cleanup_worker_databases("docker", "db-container", "valid_ns")

    def test_container_check_process_error(self, monkeypatch):
        def fake_run(cmd, **k):
            if "ps" in cmd:
                raise tl.subprocess.CalledProcessError(1, "docker ps")
            return SimpleNamespace(stdout="", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_worker_databases("docker", "db-container", "valid_ns")

    def test_no_worker_databases_found(self, monkeypatch):
        n = {"c": 0}

        def fake_run(cmd, **k):
            n["c"] += 1
            return SimpleNamespace(
                stdout=b"container_id\n" if n["c"] == 1 else "\n", returncode=0
            )

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_worker_databases("docker", "db-container", "valid_ns")

    def test_select_databases_process_error(self, monkeypatch):
        n = {"c": 0}

        def fake_run(cmd, **k):
            n["c"] += 1
            if n["c"] == 1:
                return SimpleNamespace(stdout=b"container_id\n", returncode=0)
            raise tl.subprocess.CalledProcessError(1, "psql")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        tl.cleanup_worker_databases("docker", "db-container", "valid_ns")


class TestTestDatabaseContextManager:
    def _mock_ctx(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tl, "get_container_runtime", lambda: "docker")
        monkeypatch.setattr(tl, "BACKEND_DIR", tmp_path)
        _setup_ns_files(monkeypatch, tmp_path, branch="test")

    def test_no_runtime_exits(self, monkeypatch):
        monkeypatch.setattr(tl, "get_container_runtime", lambda: None)
        with pytest.raises(SystemExit), tl.test_database():
            pass

    def test_compose_up_failure_raises(self, monkeypatch, tmp_path):
        self._mock_ctx(monkeypatch, tmp_path)

        def fake_run(*a, **k):
            raise tl.subprocess.CalledProcessError(1, "compose up")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        with pytest.raises(tl.subprocess.CalledProcessError), tl.test_database():
            pass

    def test_db_not_ready_raises(self, monkeypatch, tmp_path):
        self._mock_ctx(monkeypatch, tmp_path)
        monkeypatch.setattr(
            tl.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(stdout="", returncode=0),
        )
        monkeypatch.setattr(tl, "is_db_ready", lambda *a: False)
        monkeypatch.setattr(tl.time, "sleep", lambda s: None)
        with pytest.raises(Exception, match="Database not ready"), tl.test_database():
            pass

    def test_successful_lifecycle(self, monkeypatch, tmp_path):
        self._mock_ctx(monkeypatch, tmp_path)

        def fake_run(cmd_or_args, *a, **k):
            cmd_str = " ".join(
                map(
                    str, cmd_or_args if isinstance(cmd_or_args, list) else [cmd_or_args]
                )
            )
            if "ps" in cmd_str and "format" in cmd_str:
                return SimpleNamespace(stdout="test-db-container\n", returncode=0)
            if "port" in cmd_str:
                return SimpleNamespace(stdout="0.0.0.0:5433\n", returncode=0)
            return SimpleNamespace(stdout="", stderr=b"", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl, "is_db_ready", lambda *a: True)
        monkeypatch.setattr(tl, "cleanup_orphan_databases", lambda *a: None)
        monkeypatch.setattr(tl, "cleanup_worker_databases", lambda *a: None)
        with tl.test_database() as (db_url, namespace):
            assert (
                "postgresql+asyncpg" in db_url
                and "5433" in db_url
                and namespace == "test"
            )

    def test_ephemeral_mode_teardown(self, monkeypatch, tmp_path):
        self._mock_ctx(monkeypatch, tmp_path)
        teardown_calls = []

        def fake_run(cmd_or_args, *a, **k):
            cmd_str = " ".join(
                map(
                    str, cmd_or_args if isinstance(cmd_or_args, list) else [cmd_or_args]
                )
            )
            if "down" in cmd_str:
                teardown_calls.append(cmd_str)
            if "port" in cmd_str:
                return SimpleNamespace(stdout="0.0.0.0:5432\n", returncode=0)
            return SimpleNamespace(stdout="", stderr=b"", returncode=0)

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        monkeypatch.setattr(tl, "is_db_ready", lambda *a: True)
        monkeypatch.setattr(tl, "cleanup_orphan_databases", lambda *a: None)
        monkeypatch.setattr(tl, "cleanup_worker_databases", lambda *a: None)
        with tl.test_database(ephemeral=True):
            pass
        assert any("down" in c for c in teardown_calls)

    def test_migration_failure_raises(self, monkeypatch, tmp_path):
        self._mock_ctx(monkeypatch, tmp_path)

        def fake_run(cmd_or_args, *a, **k):
            cmd_str = " ".join(
                map(
                    str, cmd_or_args if isinstance(cmd_or_args, list) else [cmd_or_args]
                )
            )
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
        with pytest.raises(tl.subprocess.CalledProcessError), tl.test_database():
            pass


class TestMainFunction:
    def test_main_default_mode(self, monkeypatch, tmp_path):
        _setup_main_mocks(monkeypatch, tmp_path, ["test_lifecycle.py"])
        assert tl.main() == 0

    def test_main_fast_mode(self, monkeypatch, tmp_path):
        captured = _setup_main_mocks(
            monkeypatch, tmp_path, ["test_lifecycle.py", "--fast"]
        )
        tl.main()
        assert "--no-cov" in captured["cmd"] and "-n" in captured["cmd"]

    def test_main_smart_mode_with_changes(self, monkeypatch, tmp_path):
        captured = _setup_main_mocks(
            monkeypatch,
            tmp_path,
            ["test_lifecycle.py", "--smart"],
            changed=["src.config", "src.ledger.orm.account"],
        )
        tl.main()
        assert "--cov=src.config" in captured["cmd"]

    def test_main_smart_mode_no_changes(self, monkeypatch, tmp_path):
        captured = _setup_main_mocks(
            monkeypatch, tmp_path, ["test_lifecycle.py", "--smart"], changed=[]
        )
        tl.main()
        assert "--cov=src" in captured["cmd"]

    def test_main_test_failure_exits_nonzero(self, monkeypatch, tmp_path):
        _setup_main_mocks(monkeypatch, tmp_path, ["test_lifecycle.py"], returncode=1)
        assert tl.main() == 1

    def test_main_exception_exits(self, monkeypatch, tmp_path):
        @contextmanager
        def failing_test_db(ephemeral=False):
            raise RuntimeError("boom")
            yield

        monkeypatch.setattr(tl, "test_database", failing_test_db)
        monkeypatch.setattr(tl.signal, "signal", lambda *a: None)
        monkeypatch.setattr(tl.sys, "argv", ["test_lifecycle.py"])
        assert tl.main() == 1


class TestGetChangedFilesEdgeCases:
    def test_git_error_returns_empty(self, monkeypatch):
        def fake_run(*a, **k):
            raise tl.subprocess.CalledProcessError(1, "git diff")

        monkeypatch.setattr(tl.subprocess, "run", fake_run)
        assert tl._get_changed_files() == []

    def test_smart_mode_many_changed_files_truncated_log(self, monkeypatch, tmp_path):
        _setup_main_mocks(
            monkeypatch,
            tmp_path,
            ["test_lifecycle.py", "--smart"],
            changed=[f"src.mod{i}" for i in range(8)],
        )
        assert tl.main() == 0


def test_money_helpers_and_dd_and_ensure_output_dir(
    tmp_path, fake_reportlab, monkeypatch
):
    gtp = import_gtp_with_mocks(monkeypatch, tmp_path, fake_reportlab)
    assert gtp.money_str(Decimal("1234.5")) == "1234.50"
    assert gtp.money_with_commas(Decimal("1234567.89")) == "1,234,567.89"
    assert gtp.dd_mmm_yyyy("2025-01-05") == "05 Jan 2025"
    gtp.ensure_output_dir()
    assert (tmp_path / ".gitkeep").exists()


def test_dbs_raw_text_and_get_fixtures_and_build_expected_json(
    tmp_path, fake_reportlab, monkeypatch
):
    gtp = import_gtp_with_mocks(monkeypatch, tmp_path, fake_reportlab)
    fixtures = gtp.get_fixtures()
    assert len(fixtures) == 14
    assert {
        "DBS",
        "CMB",
        "GXS",
        "MariBank",
        "ICBC",
        "HSBC HK",
        "Sparkasse",
        "Barclays",
        "Chase",
        "Citi SG Card",
        "Moomoo",
        "Futu",
    } <= {f.institution for f in fixtures}
    txt = gtp.dbs_raw_text(fixtures[0].transactions[0])
    assert "Jan" in txt and "CR" in txt
    for fixture in fixtures:
        balances = gtp.compute_balances(fixture.opening_balance, fixture.transactions)
        payload = gtp.build_expected_json(fixture, balances)
        assert payload["institution"] == fixture.institution
        assert payload["file"] == fixture.pdf_name
        assert len(payload["events"]) == len(fixture.transactions)


def test_write_fixture_pdf_and_json_for_all_institutions(
    tmp_path, fake_reportlab, monkeypatch
):
    captured = fake_reportlab
    gtp = import_gtp_with_mocks(monkeypatch, tmp_path, captured)
    for fixture in gtp.get_fixtures():
        gtp.write_fixture_pdf_and_json(fixture)
        assert (tmp_path / fixture.json_name).exists()
        assert captured["saved"] is True
        assert any(
            fixture.institution.split()[0] in s for s in captured["strings"]
        ) or any(fixture.account_last4 in s for s in captured["strings"])


def test_main_success_and_font_failure(tmp_path, fake_reportlab, monkeypatch):
    gtp = import_gtp_with_mocks(monkeypatch, tmp_path, fake_reportlab)
    assert gtp.main() == 0
    sys.modules.pop(GENERATE_TEST_PDFS_MODULE, None)
    fake_pdfmetrics = sys.modules["reportlab.pdfbase.pdfmetrics"]
    monkeypatch.setattr(
        fake_pdfmetrics,
        "registerFont",
        lambda f: (_ for _ in ()).throw(Exception("fail")),
    )
    assert importlib.import_module(GENERATE_TEST_PDFS_MODULE).main() == 1
