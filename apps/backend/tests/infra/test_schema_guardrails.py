from pathlib import Path

from sqlalchemy.types import Enum

import src.models._registry  # noqa: F401 — registers every mapped class on Base
from src.database import Base


def get_all_models():
    """Every mapped class, from the registry (the src.models hub is empty, #1461)."""
    return [mapper.class_ for mapper in Base.registry.mappers]


def test_enums_have_explicit_names():
    """
    Guardrail: All sa.Enum columns MUST have a 'name' parameter.
    Failure to do so causes postgres migration issues (implicit naming conflicts).

    See: docs/ssot/schema.md
    """
    models_to_check = get_all_models()
    # Anti-vacuity: the guardrail went silently green once when the models
    # facade was emptied (#1461) and this collected zero classes. A known
    # mapped class must be in the collection or the registry wasn't populated.
    assert any(model.__name__ == "User" for model in models_to_check), (
        "known mapped classes missing — the enum guardrail is scanning nothing"
    )
    violations = []

    for model in models_to_check:
        for column in model.__mapper__.columns:
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
    # apps/backend/tests/infra/test_schema_guardrails.py -> apps/backend
    backend_root = Path(__file__).resolve().parents[2]
    migrations_dir = backend_root / "migrations" / "versions"

    if not migrations_dir.exists():
        # If no migrations yet, pass
        return

    violations = []
    for file in migrations_dir.glob("*.py"):
        if len(file.name) > 120:  # 120 chars limit (conservative)
            violations.append(file.name)

    assert not violations, (
        f"The following migration filenames are too long (>120 chars):\n{violations}\nPlease rename them to be shorter."
    )
