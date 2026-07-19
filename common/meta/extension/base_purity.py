"""Pure AST discovery of forbidden dependencies in package ``base`` layers."""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_SEGMENTS = frozenset({"orm", "observability", "database", "session"})
FORBIDDEN_MODULES = frozenset({"sqlalchemy", "httpx", "requests", "aiohttp"})


def _forbidden(module: str) -> bool:
    parts = module.split(".")
    return (
        parts[0] in FORBIDDEN_MODULES
        or module == "src.config"
        or any(part in FORBIDDEN_SEGMENTS for part in parts)
    )


def discover_impurities(backend_src: Path) -> list[str]:
    """Return canonical forbidden import statements under production ``*/base``."""
    findings: list[str] = []
    for path in sorted(backend_src.glob("*/base/**/*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rel = path.relative_to(backend_src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and _forbidden(node.module)
            ):
                names = ", ".join(alias.name for alias in node.names)
                findings.append(f"{rel}::from {node.module} import {names}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _forbidden(alias.name):
                        findings.append(f"{rel}::import {alias.name}")
    return sorted(set(findings))
