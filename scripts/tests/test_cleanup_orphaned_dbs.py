import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import cleanup_orphaned_dbs as cod  # noqa: E402


def test_AC16_11_8_extract_namespace_variants():
    assert cod.extract_namespace("finance_report_test_feature_x") == "feature_x"
    assert cod.extract_namespace("finance_report_test_feature_x_gw2") == "feature_x"
    assert cod.extract_namespace("random_db") is None


def test_AC16_11_9_load_active_namespaces_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(cod, "ACTIVE_NAMESPACES_FILE", tmp_path / "missing.json")
    assert cod.load_active_namespaces() == []


def test_AC16_11_9_load_active_namespaces_corrupt(monkeypatch, tmp_path):
    f = tmp_path / "active.json"
    f.write_text("not-json")
    monkeypatch.setattr(cod, "ACTIVE_NAMESPACES_FILE", f)
    assert cod.load_active_namespaces() == []


def test_AC16_11_10_get_container_runtime_prefers_podman(monkeypatch):
    def fake_run(cmd, capture_output=True):
        if cmd == ["which", "podman"]:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.get_container_runtime() == "podman"


def test_AC16_11_10_get_container_runtime_falls_back_docker(monkeypatch):
    def fake_run(cmd, capture_output=True):
        if cmd == ["which", "podman"]:
            return SimpleNamespace(returncode=1)
        if cmd == ["which", "docker"]:
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.get_container_runtime() == "docker"


def test_AC16_11_11_list_test_databases_parses_rows(monkeypatch):
    def fake_run(cmd, capture_output=True, text=True, check=True):
        return SimpleNamespace(
            stdout=" finance_report_test_a\n finance_report_test_b\n"
        )

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.list_test_databases("docker") == [
        "finance_report_test_a",
        "finance_report_test_b",
    ]


def test_AC16_11_11_list_test_databases_handles_error(monkeypatch):
    def fake_run(*args, **kwargs):
        raise cod.subprocess.CalledProcessError(1, "psql")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.list_test_databases("docker") == []


def test_AC16_11_12_cleanup_orphaned_runtime_missing(monkeypatch):
    monkeypatch.setattr(cod, "get_container_runtime", lambda: None)
    assert cod.cleanup_orphaned() == 1


def test_AC16_11_13_cleanup_orphaned_no_databases(monkeypatch):
    monkeypatch.setattr(cod, "get_container_runtime", lambda: "docker")
    monkeypatch.setattr(cod, "list_test_databases", lambda runtime: [])

    def fake_run(cmd, capture_output=True):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return SimpleNamespace(stdout="container-id\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.cleanup_orphaned() == 0


def test_AC16_11_14_cleanup_orphaned_skips_active(monkeypatch):
    monkeypatch.setattr(cod, "get_container_runtime", lambda: "docker")
    monkeypatch.setattr(
        cod,
        "list_test_databases",
        lambda runtime: [
            "finance_report_test_active_ns",
            "finance_report_test_orphan_ns",
        ],
    )
    monkeypatch.setattr(cod, "load_active_namespaces", lambda: ["active_ns"])

    dropped = []
    monkeypatch.setattr(
        cod,
        "drop_database",
        lambda runtime, db_name, dry_run=False: dropped.append(db_name) or True,
    )

    def fake_run(cmd, capture_output=True):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return SimpleNamespace(stdout="container-id\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.cleanup_orphaned() == 0
    assert dropped == ["finance_report_test_orphan_ns"]


def test_AC16_11_15_cleanup_orphaned_clean_all(monkeypatch):
    monkeypatch.setattr(cod, "get_container_runtime", lambda: "docker")
    monkeypatch.setattr(
        cod,
        "list_test_databases",
        lambda runtime: ["finance_report_test_a", "finance_report_test_b"],
    )
    dropped = []
    monkeypatch.setattr(
        cod,
        "drop_database",
        lambda runtime, db_name, dry_run=False: dropped.append(db_name) or True,
    )

    def fake_run(cmd, capture_output=True):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return SimpleNamespace(stdout="container-id\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.cleanup_orphaned(clean_all=True) == 0
    assert dropped == ["finance_report_test_a", "finance_report_test_b"]


def test_AC16_11_30_drop_database_dry_run_returns_true():
    assert cod.drop_database("docker", "finance_report_test_x", dry_run=True) is True


def test_AC16_11_31_main_calls_cleanup_orphaned(monkeypatch):
    monkeypatch.setattr(
        cod.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(dry_run=True, all=False),
    )
    monkeypatch.setattr(
        cod, "cleanup_orphaned", lambda dry_run=False, clean_all=False: 7
    )
    assert cod.main() == 7
