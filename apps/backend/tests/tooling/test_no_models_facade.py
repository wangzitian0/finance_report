"""Lint: forbid importing the ``src.models`` re-export hub (issue #1461).

``apps/backend/src/models/__init__.py`` is intentionally empty — it is NOT a
re-export facade. A shared facade is an ownership-hiding, collision-prone seam:
two unrelated cutovers editing the same ``__init__.py`` break the orthogonality
that later migration stages rely on. Every model must be imported from its
owning module instead, e.g. ``from src.models.layer2 import AtomicTransaction``.

This test statically scans ``apps/backend/src`` and fails if any module imports
the hub root:

* ``from src.models import X``      → forbidden (use ``from src.models.<sub> import X``)
* ``import src.models`` / ``... as m`` → forbidden (use ``import src.models.<sub>``)

Submodule imports (``from src.models.layer2 import ...``,
``import src.models._registry``) are allowed.

Covers AC-meta.facade.1 (no module imports models via the hub) and
AC-meta.facade.2 (a new hub import fails the lint).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
HUB = "src.models"


def _hub_import_violations(path: Path) -> list[str]:
    """Return human-readable violation messages for hub imports in ``path``."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        # `from src.models import X` — the re-export hub (level 0 = absolute).
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == HUB:
            names = ", ".join(a.name for a in node.names)
            violations.append(
                f"{path}:{node.lineno}: `from {HUB} import {names}` — import from the "
                f"owning module instead, e.g. `from {HUB}.<sub> import ...`"
            )
        # `import src.models` (bare hub), with or without `as`; allow `import src.models.<sub>`.
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == HUB:
                    violations.append(
                        f"{path}:{node.lineno}: `import {HUB}` (bare hub) — import a "
                        f"submodule instead, e.g. `import {HUB}._registry`"
                    )
    return violations


def test_models_hub_is_not_imported() -> None:
    """AC-meta.facade.1/.2: no module under src/ imports the src.models hub root."""
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        violations.extend(_hub_import_violations(path))

    assert not violations, "Forbidden src.models hub imports found:\n" + "\n".join(violations)
