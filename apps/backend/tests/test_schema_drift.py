import pytest
import os
import subprocess


def test_missing_migrations_check():
    """
    Guardrail: Runs 'alembic check' to detect Model-DB drift.

    This ensures that every change to a SQLAlchemy model has a corresponding
    Alembic migration file.
    """
    # Only run in CI or if explicitly requested
    if not os.environ.get("CI"):
        pytest.skip("Skipping drift check in non-CI environment")

    try:
        # Run alembic check in the backend directory
        result = subprocess.run(
            ["alembic", "check"], cwd="apps/backend", capture_output=True, text=True
        )

        if result.returncode != 0:
            if "Target database is not up to date" in result.stderr:
                pytest.skip("Database not migrated, skipping drift check")

            assert result.returncode == 0, (
                f"Schema Drift Detected! Models do not match Migrations.\n"
                f"Did you modify a model but forget to run 'alembic revision --autogenerate'?\n"
                f"Output:\n{result.stdout}\n{result.stderr}"
            )

    except FileNotFoundError:
        pytest.skip("Alembic executable not found")
