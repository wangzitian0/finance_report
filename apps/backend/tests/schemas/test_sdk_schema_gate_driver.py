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


def test_manual_valuation_component_type_enum_matches_pg_append_order() -> None:
    """ORM enum order must match PostgreSQL enumsortorder from ALTER TYPE ADD VALUE."""
    import src.orm_registry  # noqa: F401
    from src.database import Base

    by_name = {spec.name: spec.labels for spec in storage.enums_from_metadata(Base.metadata)}
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
