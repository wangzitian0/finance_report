"""CLI wrapper for the #893 snapshot anonymizer (AC-runtime.snapshot-anonymizer.1).

The transform itself is proven in apps/backend/tests/infra/test_snapshot_anonymizer.py;
these tests pin the wrapper's own guarantees: --check-only validates the full
classification with no database, a run without the scratch-copy acknowledgement
is refused (RL-DATA-2), and the backend's canonical async URL is accepted.
"""

from __future__ import annotations

import pytest


def test_check_only_validates_full_classification(capsys) -> None:
    """AC-runtime.snapshot-anonymizer.1: --check-only classifies every live
    model column and exits 0 without touching any database (a zero exit IS the
    guarantee — classify_columns raises on any unclassified column)."""
    from tools.anonymize_snapshot import main

    assert main(["--check-only"]) == 0
    capsys.readouterr()


def test_transform_requires_database_url() -> None:
    from tools.anonymize_snapshot import main

    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_transform_refuses_without_scratch_acknowledgement() -> None:
    """RL-DATA-2: the tool must never be pointed at prod or live staging; the
    explicit scratch-copy acknowledgement is a hard requirement."""
    from tools.anonymize_snapshot import main

    with pytest.raises(SystemExit) as excinfo:
        main(["--database-url", "postgresql+psycopg2://x:y@localhost/scratch"])
    assert excinfo.value.code == 2


def test_async_database_url_is_normalized_to_sync_driver() -> None:
    """The backend's canonical postgresql+asyncpg:// URL is accepted and run
    through a sync driver (same normalization as migrations/env.py)."""
    from tools.anonymize_snapshot import _normalize_url

    assert (
        _normalize_url("postgresql+asyncpg://u:p@host:5432/db")
        == "postgresql+psycopg2://u:p@host:5432/db"
    )
    assert (
        _normalize_url("postgresql+psycopg2://u:p@host:5432/db")
        == "postgresql+psycopg2://u:p@host:5432/db"
    )


class _FakeConn:
    pass


class _FakeEngine:
    def __init__(self):
        self.conn = _FakeConn()

    def begin(self):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield self.conn

        return _cm()


def test_transform_success_path_reports_counts(monkeypatch, capsys) -> None:
    """The wrapper drives anonymize + residual scan in one transaction and
    reports counts only (never values)."""
    import sqlalchemy
    import tools.anonymize_snapshot as cli

    from src.runtime.extension.snapshot_anonymizer import AnonymizationReport

    report = AnonymizationReport(
        scale_factor=5, tables_updated=3, values_pseudonymized=7
    )
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda url: _FakeEngine())
    monkeypatch.setattr(
        cli, "anonymize", lambda conn, md, *, secret, scale_factor: report
    )
    monkeypatch.setattr(cli, "scan_for_residuals", lambda conn, md, originals: [])

    assert (
        cli.main(
            [
                "--database-url",
                "postgresql+asyncpg://u:p@localhost/scratch",
                "--i-am-on-a-scratch-copy",
            ]
        )
        == 0
    )
    capsys.readouterr()


def test_transform_residuals_fail_closed(monkeypatch) -> None:
    """AC-runtime.snapshot-anonymizer.3: a surviving original aborts the
    transaction — the wrapper raises instead of committing."""
    import sqlalchemy
    import tools.anonymize_snapshot as cli

    from src.runtime.extension.snapshot_anonymizer import (
        AnonymizationReport,
        ResidualError,
    )

    report = AnonymizationReport(scale_factor=5)
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda url: _FakeEngine())
    monkeypatch.setattr(
        cli, "anonymize", lambda conn, md, *, secret, scale_factor: report
    )
    monkeypatch.setattr(
        cli,
        "scan_for_residuals",
        lambda conn, md, originals: ["atomic_transactions.description"],
    )

    with pytest.raises(ResidualError):
        cli.main(
            [
                "--database-url",
                "postgresql+psycopg2://u:p@localhost/scratch",
                "--i-am-on-a-scratch-copy",
            ]
        )
