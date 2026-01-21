import pytest
from sqlalchemy import inspect
from sqlalchemy.types import Enum
from pathlib import Path

# Import all models to inspect them
from src import models


def get_all_models():
    """Dynamically get all SQLAlchemy models from src.models."""
    model_classes = set()  # Use set to avoid duplicates from aliases
    for name in dir(models):
        obj = getattr(models, name)
        # Check if it looks like a model (has __tablename__)
        if hasattr(obj, "__tablename__"):
            model_classes.add(obj)
    return list(model_classes)


def test_enums_have_explicit_names():
    """
    Guardrail: All sa.Enum columns MUST have a 'name' parameter.
    Failure to do so causes postgres migration issues (implicit naming conflicts).

    See: docs/ssot/schema.md
    """
    models_to_check = get_all_models()
    violations = []

    for model in models_to_check:
        mapper = inspect(model)
        for column in mapper.columns:
            if isinstance(column.type, Enum):
                # Check if name is explicitly set
                if column.type.name is None:
                    violations.append(f"{model.__name__}.{column.name}")

    assert not violations, (
        f"The following Enum columns lack an explicit 'name=' parameter:\n"
        f"{violations}\n"
        f"Please add name='enum_name' to the Enum definition."
    )


def test_migration_filenames_length():
    """
    Guardrail: Alembic migration filenames should not be excessively long.
    Long filenames cause issues on some file systems and Docker volume mounts.
    """
    # Locate migrations directory relative to this test file
    # apps/backend/tests/test_schema_guardrails.py -> apps/backend/migrations/versions
    backend_root = Path(__file__).parent.parent
    migrations_dir = backend_root / "migrations" / "versions"

    if not migrations_dir.exists():
        # If no migrations yet, pass
        return

    violations = []
    for file in migrations_dir.glob("*.py"):
        if len(file.name) > 120:  # 120 chars limit (conservative)
            violations.append(file.name)

    assert not violations, (
        f"The following migration filenames are too long (>120 chars):\n"
        f"{violations}\n"
        f"Please rename them to be shorter."
    )
