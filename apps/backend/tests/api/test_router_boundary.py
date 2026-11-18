from __future__ import annotations

import ast
from pathlib import Path

ROUTERS_DIR = Path(__file__).resolve().parents[2] / "src" / "routers"


def test_AC25_5_1_no_router_imports_another_router() -> None:
    offenders = [
        f"{path.name}:{node.lineno} -> from {node.module} import ..."
        for path in sorted(p for p in ROUTERS_DIR.glob("*.py") if p.name != "__init__.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        if isinstance(node, ast.ImportFrom)
        and node.module
        and (node.module == "src.routers" or node.module.startswith("src.routers."))
    ]
    assert not offenders, "router-to-router imports must not exist:\n" + "\n".join(offenders)
