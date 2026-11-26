"""Verify the backend environment ships the PostgreSQL driver required by infra2_sdk.storage check-schema."""

from __future__ import annotations

import importlib

from infra2_sdk import storage


def test_storage_check_schema_has_psycopg_driver_and_reaches_db_url_check(capsys) -> None:
    """Backend image must install psycopg via infra2-sdk[postgres] instead of failing with RuntimeError."""
    psycopg = importlib.import_module("psycopg")
    assert hasattr(psycopg, "connect")

    exit_code = storage.main(
        [
            "check-schema",
            "--metadata",
            "src.database:Base.metadata",
            "--db-url",
            "",
            "--label",
            "finance_report/app",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == storage.EXIT_NOT_EVALUATED
    assert "DATABASE_URL is required" in captured.err
