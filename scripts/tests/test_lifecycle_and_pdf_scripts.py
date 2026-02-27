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
