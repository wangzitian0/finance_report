"""Verify the backend environment ships the PostgreSQL driver required by infra2_sdk.storage check-schema."""

from __future__ import annotations

import importlib
import subprocess
import sys
from typing import Any


def _iter_enum_types(col_type: Any):
    item = getattr(col_type, "item_type", None)
    if item is not None:
        yield from _iter_enum_types(item)
    if (
        getattr(col_type, "native_enum", True)
        and getattr(col_type, "name", None)
        and getattr(col_type, "enums", None) is not None
    ):
        yield col_type


def code_enum_tuples(metadata: Any) -> dict[str, tuple[str, ...]]:
    """``{enum type name: ordered labels}`` for every native enum column on ``metadata``."""
    out: dict[str, tuple[str, ...]] = {}
    for table in metadata.tables.values():
        for col in table.columns:
            for enum_t in _iter_enum_types(col.type):
                labels = tuple(str(v) for v in enum_t.enums)
                if enum_t.name in out and out[enum_t.name] != labels:
                    raise ValueError(
                        f"conflicting enum definitions for {enum_t.name!r}: {out[enum_t.name]!r} != {labels!r}"
                    )
                out[enum_t.name] = labels
    return out


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
