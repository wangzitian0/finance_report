from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_ci() -> dict:
    return yaml.safe_load(read(".github/workflows/ci.yml"))


def test_AC8_13_121_pr_ci_runs_schema_migration_contract() -> None:
    """AC-testing.schema.1: AC8.13.121: PR CI proves Alembic migrations against real Postgres."""

    workflow_text = read(".github/workflows/ci.yml")
    workflow = load_ci()
    jobs = workflow["jobs"]

    assert "schema-migrations" in jobs
    schema_job = jobs["schema-migrations"]
    assert schema_job["name"] == "Schema Migration Contract"
    assert schema_job["needs"] == ["changes"]
    assert schema_job["if"] == "needs.changes.outputs.pr_required == 'true'"
    assert "postgres" in schema_job["services"]

    schema_block = workflow_text.split("  schema-migrations:", 1)[1].split(
        "  backend:", 1
    )[0]
    assert "uv run alembic upgrade head" in schema_block
    assert "uv run alembic check" in schema_block
    assert "schema-migration-context.txt" in schema_block
    assert "schema-migration-test-context" in schema_block

    finish = jobs["finish"]
    assert "schema-migrations" in finish["needs"]
    finish_block = workflow_text.split("  finish:", 1)[1]
    assert (
        'echo "Schema Migrations: ${{ needs.schema-migrations.result }}"'
        in finish_block
    )
    assert (
        'if [[ "${{ needs.schema-migrations.result }}" != "success" ]]; then'
        in finish_block
    )
    assert "Schema migration contract failed" in finish_block


def test_AC8_13_122_schema_drift_guard_does_not_accept_outdated_targets() -> None:
    """AC-testing.schema.2: AC8.13.122: Alembic drift checks must not treat stale DB targets as success."""

    source = read("apps/backend/tests/infra/test_schema_drift.py")

    assert "Target database is not up to date" not in source
    assert "FileNotFoundError" not in source
    assert "schema-migrations" in source


def test_AC8_13_123_schema_guardrails_scan_real_migration_directory() -> None:
    """AC-testing.schema.3: AC8.13.123: Migration guardrails inspect apps/backend/migrations/versions."""

    source = read("apps/backend/tests/infra/test_schema_guardrails.py")

    assert "backend_root = Path(__file__).resolve().parents[2]" in source
    assert 'migrations_dir = backend_root / "migrations" / "versions"' in source
    assert (ROOT / "apps/backend/migrations/versions").exists()
    assert not (ROOT / "apps/backend/tests/migrations/versions").exists()


def test_retire_bank_statement_migration_normalizes_uppercase_source_type_drift() -> (
    None
):
    """Enum rebuild tolerates prod rows written with legacy uppercase labels."""

    source = read("apps/backend/migrations/versions/0040_retire_bank_stmt_source.py")

    assert "lower(source_type::text) = 'bank_statement'" in source
    assert (
        "WHEN lower(source_type::text) = 'bank_statement' THEN 'auto_parsed'" in source
    )
    assert "ELSE lower(source_type::text)" in source


def test_AC8_13_124_traceability_gate_and_audit_builder_share_test_surface() -> None:
    """AC-testing.acgates.13: AC8.13.124: AC traceability gate and uploaded audit scan the same roots."""

    from common.testing import build_ac_traceability as bat
    from common.testing.test_surface import DEFAULT_AC_TEST_DIRS

    expected = (
        "apps/backend/tests",
        "apps/frontend/src",
        "apps/frontend/playwright",
        "tests/tooling",
        "tests/e2e",
    )
    builder_defaults = tuple(
        path.relative_to(ROOT).as_posix() for path in bat.DEFAULT_TEST_DIRS
    )

    assert builder_defaults == expected
    assert DEFAULT_AC_TEST_DIRS == expected

    parser_defaults_source = read("common/testing/check_ac_traceability.py")
    assert "DEFAULT_AC_TEST_DIRS" in parser_defaults_source

    builder_source = read("common/testing/build_ac_traceability.py")
    assert "default_ac_test_dirs" in builder_source
    assert ' + ".join(DEFAULT_AC_TEST_DIRS)' in builder_source
