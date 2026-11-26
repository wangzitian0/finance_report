"""Verify the backend environment ships the PostgreSQL driver required by infra2_sdk.storage check-schema."""

from __future__ import annotations

import importlib
import subprocess
import sys

from scripts.check_migrated_enums import code_enum_tuples


def test_storage_check_schema_has_psycopg_driver_and_reaches_db_url_check() -> None:
    """Backend image must install psycopg via infra2-sdk[postgres] instead of failing with RuntimeError."""
    psycopg = importlib.import_module("psycopg")
    assert hasattr(psycopg, "connect")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "infra2_sdk.storage",
            "check-schema",
            "--metadata",
            "src.database:Base.metadata",
            "--db-url",
            "",
            "--label",
            "finance_report/app",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 3
    assert "DATABASE_URL is required" in proc.stderr


def test_manual_valuation_component_type_enum_matches_pg_append_order() -> None:
    """ORM enum order must match PostgreSQL enumsortorder from ALTER TYPE ADD VALUE."""
    import src.orm_registry  # noqa: F401
    from src.database import Base

    by_name = code_enum_tuples(Base.metadata)
    assert by_name["manual_valuation_component_type_enum"] == (
        "property_value",
        "mortgage_balance",
        "cpf_balance",
        "long_term_savings",
        "tax_payable",
        "tax_refund",
        "insurance_cash_value",
        "esop",
        "rsu",
        "stock_options",
        "other_asset",
        "other_liability",
        "retirement_account",
        "social_security_personal_account",
        "long_term_benefit_asset",
    )
