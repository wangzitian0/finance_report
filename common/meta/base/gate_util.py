"""Layer-zero, stdlib-only helpers that two or more policy gates share."""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path, PurePath


@lru_cache(maxsize=8192)
def _read_text_stat_cached(path_str: str, mtime_ns: int, size: int) -> str:
    return Path(path_str).read_text(encoding="utf-8")


def read_text_cached(path: Path) -> str:
    """Read UTF-8 file text using a ``(resolved_path, mtime_ns, size)`` cache."""
    resolved = path.resolve()
    st = resolved.stat()
    return _read_text_stat_cached(str(resolved), st.st_mtime_ns, st.st_size)


@lru_cache(maxsize=4096)
def _parse_ast_stat_cached(path_str: str, mtime_ns: int, size: int) -> ast.Module:
    return ast.parse(
        _read_text_stat_cached(path_str, mtime_ns, size), filename=path_str
    )


def parse_ast_cached(path: Path) -> ast.Module:
    """Parse a Python source file using a ``(resolved_path, mtime_ns, size)`` cache."""
    resolved = path.resolve()
    st = resolved.stat()
    return _parse_ast_stat_cached(str(resolved), st.st_mtime_ns, st.st_size)


def clear_source_caches() -> None:
    """Clear the shared UTF-8 text and Python AST stat-keyed caches."""
    _parse_ast_stat_cached.cache_clear()
    _read_text_stat_cached.cache_clear()


def display_path(path: PurePath, root: PurePath) -> str:
    """Return ``path`` as POSIX text relative to ``root``, or absolute when outside."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


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
