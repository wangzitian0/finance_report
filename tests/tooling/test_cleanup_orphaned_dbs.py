"AC16.11.8 AC16.11.9 AC16.11.10 AC16.11.11 AC16.11.12 AC16.11.13 AC16.11.14 AC16.11.15 AC16.11.30 AC16.11.31"

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))
from common.runtime.dev import cleanup_orphaned_dbs as cod


def test_AC16_11_8_extract_namespace_variants():
    "AC-runtime.24.8"
    assert cod.extract_namespace("finance_report_test_feature_x") == "feature_x"
    assert cod.extract_namespace("finance_report_test_feature_x_gw2") == "feature_x"
    assert cod.extract_namespace("random_db") is None


def test_AC16_11_9_load_active_namespaces_missing(monkeypatch, tmp_path):
    "AC-runtime.24.9"
    monkeypatch.setattr(cod, "ACTIVE_NAMESPACES_FILE", tmp_path / "missing.json")
    assert cod.load_active_namespaces() == []


def test_AC16_11_9_load_active_namespaces_corrupt(monkeypatch, tmp_path):
    f = tmp_path / "active.json"
    f.write_text("not-json")
    monkeypatch.setattr(cod, "ACTIVE_NAMESPACES_FILE", f)
    assert cod.load_active_namespaces() == []


def test_AC16_11_10_get_container_runtime_prefers_podman(monkeypatch):
    "AC-runtime.24.10"

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
    "AC-runtime.24.11"
    fake_run = lambda cmd, capture_output=True, text=True, check=True: SimpleNamespace(
        stdout=" finance_report_test_a\n finance_report_test_b\n"
    )
    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.list_test_databases("docker") == ["finance_report_test_a", "finance_report_test_b"]


def test_AC16_11_11_list_test_databases_handles_error(monkeypatch):
    def fake_run(*args, **kwargs):
        raise cod.subprocess.CalledProcessError(1, "psql")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.list_test_databases("docker") == []


def test_AC16_11_12_cleanup_orphaned_runtime_missing(monkeypatch):
    "AC-runtime.24.12"
    monkeypatch.setattr(cod, "get_container_runtime", lambda: None)
    monkeypatch.setattr(cod, "host_postgres_ready", lambda: False)
    assert cod.cleanup_orphaned() == 1


def test_AC16_11_13_cleanup_orphaned_no_databases(monkeypatch):
    "AC-runtime.24.13"
    monkeypatch.setattr(cod, "get_container_runtime", lambda: "docker")
    monkeypatch.setattr(cod, "list_test_databases", lambda runtime: [])

    def fake_run(cmd, capture_output=True):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return SimpleNamespace(stdout="container-id\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.cleanup_orphaned() == 0


def test_AC16_11_13_cleanup_orphaned_returns_error_when_container_is_missing(monkeypatch):
    monkeypatch.setattr(cod, "get_container_runtime", lambda: "docker")

    def fake_run(cmd, capture_output=True):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.cleanup_orphaned() == 1


def test_AC16_11_14_cleanup_orphaned_skips_active(monkeypatch):
    "AC-runtime.24.14"
    monkeypatch.setattr(cod, "get_container_runtime", lambda: "docker")
    monkeypatch.setattr(
        cod, "list_test_databases", lambda runtime: ["finance_report_test_active_ns", "finance_report_test_orphan_ns"]
    )
    monkeypatch.setattr(cod, "load_active_namespaces", lambda: ["active_ns"])
    dropped = []
    monkeypatch.setattr(cod, "drop_database", lambda runtime, db_name, dry_run=False: dropped.append(db_name) or True)

    def fake_run(cmd, capture_output=True):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return SimpleNamespace(stdout="container-id\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.cleanup_orphaned() == 0
    assert dropped == ["finance_report_test_orphan_ns"]


def test_AC16_11_15_cleanup_orphaned_clean_all(monkeypatch):
    "AC-runtime.24.15"
    monkeypatch.setattr(cod, "get_container_runtime", lambda: "docker")
    monkeypatch.setattr(cod, "list_test_databases", lambda runtime: ["finance_report_test_a", "finance_report_test_b"])
    dropped = []
    monkeypatch.setattr(cod, "drop_database", lambda runtime, db_name, dry_run=False: dropped.append(db_name) or True)

    def fake_run(cmd, capture_output=True):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return SimpleNamespace(stdout="container-id\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.cleanup_orphaned(clean_all=True) == 0
    assert dropped == ["finance_report_test_a", "finance_report_test_b"]


def test_AC16_11_30_drop_database_dry_run_returns_true():
    "AC-runtime.24.30"
    assert cod.drop_database("docker", "finance_report_test_x", dry_run=True) is True


def test_AC16_11_30_drop_database_returns_false_on_subprocess_error(monkeypatch):
    def fake_run(*args, **kwargs):
        raise cod.subprocess.CalledProcessError(1, "psql")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.drop_database("docker", "finance_report_test_x") is False


def test_AC16_11_14_cleanup_orphaned_attempts_all_drops_when_one_fails(monkeypatch):
    monkeypatch.setattr(cod, "get_container_runtime", lambda: "docker")
    monkeypatch.setattr(cod, "list_test_databases", lambda runtime: ["finance_report_test_a", "finance_report_test_b"])
    monkeypatch.setattr(cod, "load_active_namespaces", lambda: [])
    attempted = []

    def fake_drop(runtime, db_name, dry_run=False):
        attempted.append(db_name)
        return db_name.endswith("_a")

    def fake_run(cmd, capture_output=True):
        if cmd[:3] == ["docker", "ps", "-q"]:
            return SimpleNamespace(stdout="container-id\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(cod, "drop_database", fake_drop)
    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.cleanup_orphaned() == 0
    assert attempted == ["finance_report_test_a", "finance_report_test_b"]


def test_AC16_11_31_main_calls_cleanup_orphaned(monkeypatch):
    "AC-runtime.24.31"
    monkeypatch.setattr(
        cod.argparse.ArgumentParser, "parse_args", lambda self: SimpleNamespace(dry_run=True, all=False)
    )
    monkeypatch.setattr(cod, "cleanup_orphaned", lambda dry_run=False, clean_all=False: 7)
    assert cod.main() == 7


def test_AC16_11_32_cleanup_orphaned_falls_back_to_host_postgres(monkeypatch):
    "AC-runtime.24.32"
    monkeypatch.setattr(cod, "get_container_runtime", lambda: "podman")
    monkeypatch.setattr(cod, "load_active_namespaces", lambda: [])
    monkeypatch.setattr(cod.shutil, "which", lambda name: "/opt/homebrew/bin/psql" if name == "psql" else None)
    commands: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=False, check=False, env=None):
        commands.append(list(cmd))
        if cmd[:3] == ["podman", "ps", "-q"]:
            return SimpleNamespace(returncode=0, stdout="")
        sql = cmd[-1]
        if "SELECT 1" in sql:
            return SimpleNamespace(returncode=0, stdout="1\n")
        if "pg_database" in sql:
            return SimpleNamespace(returncode=0, stdout=" finance_report_test_orphan\n")
        if "pg_stat_database" in sql:
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=0, stdout="DROP DATABASE\n")

    monkeypatch.setattr(cod.subprocess, "run", fake_run)
    assert cod.cleanup_orphaned() == 0
    assert any(
        cmd[0] == "psql" and 'DROP DATABASE IF EXISTS "finance_report_test_orphan";' in cmd[-1] for cmd in commands
    )


def test_AC16_11_33_cleanup_orphaned_skips_active_backends(monkeypatch):
    "AC-runtime.24.33"
    monkeypatch.setattr(cod, "get_container_runtime", lambda: None)
    monkeypatch.setattr(cod, "host_postgres_ready", lambda: True)
    monkeypatch.setattr(cod, "load_active_namespaces", lambda: [])
    monkeypatch.setattr(
        cod, "list_test_databases", lambda target: ["finance_report_test_busy", "finance_report_test_idle"]
    )
    monkeypatch.setattr(cod, "list_active_databases", lambda target: {"finance_report_test_busy"})
    dropped: list[str] = []
    monkeypatch.setattr(cod, "drop_database", lambda target, db_name, dry_run=False: dropped.append(db_name) or True)
    assert cod.cleanup_orphaned() == 0
    assert dropped == ["finance_report_test_idle"]
