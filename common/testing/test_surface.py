"""Shared test-surface definitions for AC traceability tooling."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_AC_TEST_DIRS = (
    "apps/backend/tests",
    "apps/frontend/src",
    "apps/frontend/playwright",
    "tests/tooling",
    "tests/e2e",
)


def default_ac_test_dirs(repo_root: Path = REPO_ROOT) -> tuple[Path, ...]:
    """Return the default AC traceability test directories under repo_root."""
    return tuple(repo_root / path for path in DEFAULT_AC_TEST_DIRS)
