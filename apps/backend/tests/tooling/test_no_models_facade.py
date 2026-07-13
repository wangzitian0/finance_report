"""Lint: forbid reintroducing ``src.models`` (issue #1461, dissolved #1675 D6).

``src/models/`` was the legacy models package: first emptied to a non-hub
marker so no module imported it as a re-export facade (#1461), then fully
dissolved in the final models-decentralization slice (#1675 D6) — its base
mixins moved to ``src/platform/orm/base.py``, its eager mapper-registration
side effect to ``src/orm_registry.py``, and its last ORM entities
(``StatementSummary``/``statement_enums``) to ``src/extraction/orm/``. This
test is the regression lock for that dissolution: the directory must not
exist, and no module under ``apps/backend/src`` may import ``src.models`` in
any form (bare hub, submodule, or ``as`` alias).

Covers AC-meta.facade.1 (no module imports models via the hub) and
AC-meta.facade.2 (a new hub import fails the lint) — the invariant those ACs
guard now extends to "the package doesn't exist at all".
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = BACKEND_ROOT / "src"
HUB = "src.models"


def _models_import_violations(path: Path) -> list[str]:
    """Return human-readable violation messages for any ``src.models`` import in ``path``."""
    tree = ast.parse(path.read_text(), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        # `from src.models import X` or `from src.models.<sub> import X`.
        if (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and (node.module == HUB or node.module.startswith(f"{HUB}."))
        ):
            names = ", ".join(a.name for a in node.names)
            violations.append(
                f"{path}:{node.lineno}: `from {node.module} import {names}` — "
                "src.models was dissolved (#1675 D6); import from the owning "
                "package instead (platform.orm.base / orm_registry / extraction.orm.*)."
            )
        # `import src.models` / `import src.models.<sub>`, with or without `as`.
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == HUB or alias.name.startswith(f"{HUB}."):
                    violations.append(
                        f"{path}:{node.lineno}: `import {alias.name}` — "
                        "src.models was dissolved (#1675 D6); import from the "
                        "owning package instead."
                    )
    return violations


def test_models_package_is_not_reintroduced() -> None:
    """AC-meta.facade.1/.2: src/models/ stays deleted and unimported (#1675 D6)."""
    assert not (SRC_ROOT / "models").exists(), (
        "src/models/ was reintroduced — it was fully dissolved in #1675 D6 "
        "(mixins -> platform.orm.base, registry -> src.orm_registry, "
        "statement_summary/statement_enums -> extraction.orm)."
    )

    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        violations.extend(_models_import_violations(path))

    assert not violations, "Forbidden src.models imports found:\n" + "\n".join(violations)
