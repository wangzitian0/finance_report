"""EPIC-025 AC25.5.1: no backend router imports a symbol from another router.

A router importing another router's handler couples two HTTP boundaries and
hides the real owner of the logic (the service layer). This contract scans every
module under ``apps/backend/src/routers`` and fails if any of them contains a
``from src.routers.<x> import ...`` statement. The package aggregator
(``src/routers/__init__.py``) imports the router *modules* themselves, which is
the legitimate package wiring and is therefore exempt.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROUTERS_DIR = Path(__file__).resolve().parents[2] / "src" / "routers"


def _router_module_files() -> list[Path]:
    # The package __init__ legitimately imports the router modules; exclude it.
    return sorted(p for p in ROUTERS_DIR.glob("*.py") if p.name != "__init__.py")


def test_AC25_5_1_no_router_imports_another_router() -> None:
    """AC-meta.router.1."""
    offenders: list[str] = []
    for path in _router_module_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Match `from src.routers.<x> import ...` (a sibling router),
                # but not `from src.routers import ...` (the package itself).
                if node.module == "src.routers" or node.module.startswith("src.routers."):
                    if node.module != "src.routers":
                        offenders.append(f"{path.name}:{node.lineno} -> from {node.module} import ...")
    assert not offenders, "router-to-router imports must not exist:\n" + "\n".join(offenders)
