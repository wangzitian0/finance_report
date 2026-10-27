"""Layer-zero, stdlib-only helpers that two or more policy gates share."""

from __future__ import annotations

import ast
from pathlib import PurePath


def display_path(path: PurePath, root: PurePath) -> str:
    """Return ``path`` as POSIX text relative to ``root``, or absolute when outside."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def call_name(func: ast.expr) -> str | None:
    """Return the bare callee name of a call target (``ForeignKey``, ``sa.ForeignKey``)."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def required_arg(value: str, name: str) -> str:
    """Return ``value`` stripped; raise ``ValueError`` when it is blank."""
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value
