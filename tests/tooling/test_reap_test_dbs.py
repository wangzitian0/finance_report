from __future__ import annotations

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
    assert sqls == ['DROP DATABASE IF EXISTS "finance_report_test_preflight_999" WITH (FORCE);']


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
        'DROP DATABASE IF EXISTS "finance_report_test_preflight_42_gw0" WITH (FORCE);' in q
        for q in queries
    )
