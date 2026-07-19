"""Discover ORM-defined symbols exported from package roots (pure AST)."""

from __future__ import annotations

import ast
from pathlib import Path


def _literal_exports(tree: ast.Module, path: Path) -> set[str]:
    value: ast.expr | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and (node.target.id == "__all__")
        ):
            value = node.value
    if value is None:
        raise ValueError(f"missing or unreadable __all__ in {path}")
    try:
        values = ast.literal_eval(value)
    except (SyntaxError, TypeError, ValueError) as exc:
        raise ValueError(f"unreadable __all__ in {path}") from exc
    if not isinstance(values, (list, tuple)) or not all(
        isinstance(value, str) for value in values
    ):
        raise ValueError(f"unreadable __all__ in {path}")
    return set(values)


def _local_module_path(backend_src: Path, package: str, module: str) -> Path | None:
    """Resolve a package-local import path without importing application code."""
    prefix = f"src.{package}."
    if not module.startswith(prefix):
        return None
    relative = Path(*module.removeprefix(prefix).split("."))
    module_file = backend_src / package / relative.with_suffix(".py")
    package_init = backend_src / package / relative / "__init__.py"
    if module_file.is_file():
        return module_file
    if package_init.is_file():
        return package_init
    return None


def _orm_class_names(path: Path) -> set[str]:
    """Return locally-defined SQLAlchemy model names from one source module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"cannot parse re-export source {path}: {exc}") from exc
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Base" for base in node.bases)
    }


def discover_public_orm_exports(backend_src: Path) -> list[str]:
    """Return canonical ``package::symbol`` records for root-exported ORM names."""
    if not backend_src.is_dir():
        raise ValueError(f"missing backend source directory {backend_src}")

    findings: list[str] = []
    for init in sorted(backend_src.glob("*/__init__.py")):
        package = init.parent.name
        try:
            tree = ast.parse(init.read_text(encoding="utf-8"), filename=str(init))
        except (OSError, SyntaxError) as exc:
            raise ValueError(f"cannot parse package root {init}: {exc}") from exc
        exports = _literal_exports(tree, init)
        orm_names: set[str] = set()
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module == f"src.{package}.orm" or node.module.startswith(
                f"src.{package}.orm."
            ):
                orm_names.update(alias.asname or alias.name for alias in node.names)
                continue
            source = _local_module_path(backend_src, package, node.module)
            if source is None:
                continue
            source_orm_names = _orm_class_names(source)
            orm_names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in source_orm_names
            )
        findings.extend(f"{package}::{name}" for name in sorted(exports & orm_names))
    return sorted(findings)
