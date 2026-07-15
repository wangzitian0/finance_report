"""Repository-location helper shared by backend-owned runtime tooling."""

from pathlib import Path


def get_project_root() -> Path:
    """Return the root five levels above runtime/extension modules."""
    return Path(__file__).resolve().parents[5]
