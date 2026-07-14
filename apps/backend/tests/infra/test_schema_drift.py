from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_missing_migrations_check():
    """AC-meta.phase0.6:
    Guardrail: PR CI owns Alembic migration drift proof against real Postgres.

    Backend unit tests use isolated schemas for speed. The hard schema contract
    is the CI schema-migrations job, which runs 'alembic upgrade head' and then
    'alembic check' against an ephemeral Postgres service.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    schema_block = workflow.split("  schema-migrations:", 1)[1].split("  backend:", 1)[0]

    assert "schema-migrations" in workflow
    assert "postgres:" in schema_block
    assert "uv run alembic upgrade head" in schema_block
    assert "uv run alembic check" in schema_block
