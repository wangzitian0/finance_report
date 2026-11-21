from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from common.testing import reap_test_dbs as rtd


def test_reap_orphaned_test_databases_respects_active_backends_and_live_pids(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        rtd,
        "list_test_databases",
        lambda **_kw: [
            "finance_report_test_preflight_111_gw0",
            "finance_report_test_preflight_222_gw0",
            "finance_report_test_mutation_333",
            "finance_report_test_planner_seq_abcd1234",
            "finance_report_test_busy_ns",
            "finance_report_test_active_ns",
        ],
    )
    monkeypatch.setattr(
        rtd, "list_active_databases", lambda **_kw: {"finance_report_test_busy_ns"}
    )
    monkeypatch.setattr(rtd, "load_active_namespaces", lambda: ["active_ns"])

    def fake_kill(pid: int, sig: int) -> None:
        if pid == 111:
            return None
        raise ProcessLookupError()

    monkeypatch.setattr(rtd.os, "kill", fake_kill)
    dropped: list[str] = []
    monkeypatch.setattr(
        rtd,
        "drop_database",
        lambda db_name, **_kw: dropped.append(db_name) or True,
    )

    reaped, total = rtd.reap_orphaned_test_databases()
    assert total == 6
    assert reaped == 3
    assert dropped == [
        "finance_report_test_preflight_222_gw0",
        "finance_report_test_mutation_333",
        "finance_report_test_planner_seq_abcd1234",
    ]


def test_drop_database_uses_with_force_and_validates_prefix(monkeypatch) -> None:
    sqls: list[str] = []

    def fake_run_psql(sql: str, **_kw):
        sqls.append(sql)
        return SimpleNamespace(returncode=0, stdout="DROP DATABASE\n")

    monkeypatch.setattr(rtd, "_run_psql", fake_run_psql)
    assert rtd.drop_database("postgres") is False
    assert rtd.drop_database("finance_report_test_bad;DROP") is False
    assert rtd.drop_database("finance_report_test_preflight_999") is True
    assert sqls == [
        'DROP DATABASE IF EXISTS "finance_report_test_preflight_999" WITH (FORCE);'
    ]


def test_drop_namespace_databases_targets_master_and_worker_dbs(monkeypatch) -> None:
    queries: list[str] = []

    def fake_run_psql(sql: str, **_kw):
        queries.append(sql)
        if sql.startswith("SELECT datname"):
            return SimpleNamespace(
                returncode=0,
                stdout="finance_report_test_preflight_42\nfinance_report_test_preflight_42_gw0\n",
            )
        return SimpleNamespace(returncode=0, stdout="DROP DATABASE\n")

    monkeypatch.delenv("KEEP_TEST_DB", raising=False)
    monkeypatch.setattr(rtd, "_run_psql", fake_run_psql)
    assert rtd.drop_namespace_databases("preflight_42") == 2
    assert any(
        'DROP DATABASE IF EXISTS "finance_report_test_preflight_42" WITH (FORCE);' in q
        for q in queries
    )
    assert any(
        'DROP DATABASE IF EXISTS "finance_report_test_preflight_42_gw0" WITH (FORCE);'
        in q
        for q in queries
    )


def test_register_namespace_lease_lifecycle_and_dead_pid_pruning(
    tmp_path: Path,
) -> None:
    from apps.backend.tests._support import test_isolation as ti

    lease_file = tmp_path / "active_namespaces.json"
    dead_pid = 999_999_999
    live_pid = 1 if False else __import__("os").getpid()
    ti.register_namespace("dead_ns", lease_file, tmp_path, pid=dead_pid)
    ti.register_namespace("live_ns", lease_file, tmp_path, pid=live_pid)
    assert rtd.load_active_namespaces(lease_file) == ["live_ns"]
    ti.unregister_namespace("live_ns", lease_file, tmp_path, pid=live_pid)
    assert rtd.load_active_namespaces(lease_file) == []


def test_reap_ephemeral_only_and_active_worktree_protection(
    monkeypatch, tmp_path: Path
) -> None:
    import hashlib

    wt = tmp_path / "wt_active"
    backend = wt / "apps" / "backend"
    backend.mkdir(parents=True)
    wt_hash = hashlib.sha256(str(backend.resolve()).encode()).hexdigest()[:8]
    active_wt_db = f"finance_report_test_feat_open_{wt_hash}"
    gone_wt_db = "finance_report_test_feat_merged_deadbeef"
    dead_ephem_db = "finance_report_test_preflight_999999999"

    monkeypatch.setattr(
        rtd,
        "list_test_databases",
        lambda **_kw: [active_wt_db, gone_wt_db, dead_ephem_db],
    )
    monkeypatch.setattr(rtd, "list_active_databases", lambda **_kw: set())
    monkeypatch.setattr(rtd, "load_active_namespaces", lambda: [])
    monkeypatch.setattr(rtd, "active_worktree_db_names", lambda _r=None: {active_wt_db})
    monkeypatch.setattr(rtd, "is_live_ephemeral_pid", lambda _ns: False)
    dropped: list[str] = []
    monkeypatch.setattr(
        rtd, "drop_database", lambda db, **_kw: dropped.append(db) or True
    )

    reaped_e, _ = rtd.reap_orphaned_test_databases(ephemeral_only=True)
    assert reaped_e == 1 and dropped == [dead_ephem_db]
    dropped.clear()
    reaped_all, total = rtd.reap_orphaned_test_databases()
    assert total == 3 and reaped_all == 2
    assert dropped == [gone_wt_db, dead_ephem_db]


def test_session_teardown_drops_only_a_test_database() -> None:
    """The session teardown must not drop the DATABASE_URL development database."""
    from apps.backend.tests._support import test_isolation as ti

    assert ti.is_droppable_test_db("finance_report_test")
    assert ti.is_droppable_test_db("finance_report_test_gw3")
    assert ti.is_droppable_test_db(ti.get_test_db_name("feat_x_1a2b3c4d"))
    for name in ("finance_report", "postgres", "finance_report_gw0", "", None):
        assert not ti.is_droppable_test_db(name), name

    conftest = (
        Path(__file__).resolve().parents[2] / "apps/backend/tests/conftest.py"
    ).read_text(encoding="utf-8")
    drop_calls = [
        line for line in conftest.splitlines() if "await _drop_test_database(" in line
    ]
    assert len(drop_calls) == 1
    guard_line = conftest.splitlines()[conftest.splitlines().index(drop_calls[0]) - 1]
    assert "is_droppable_test_db(db_name)" in guard_line
