"""Layer-zero, stdlib-only helpers that two or more policy gates share."""

from __future__ import annotations

import ast
from functools import lru_cache
import re
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


def markdown_table_cells(line: str) -> list[str]:
    """Split a pipe-delimited Markdown table row into stripped cell strings."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def pytest_decorator_markers(node: ast.AST) -> set[str]:
    """Return bare ``@pytest.mark.<name>`` marker names attached to an AST node."""
    markers: set[str] = set()
    for decorator in getattr(node, "decorator_list", []):
        text = ast.unparse(decorator)
        if text.startswith("pytest.mark."):
            markers.add(text[12:].split("(", 1)[0].split(".", 1)[0])
    return markers


def required_arg(value: str, name: str) -> str:
    """Return ``value`` stripped; raise ``ValueError`` when it is blank."""
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


_TEST_PATH_ALIASES: tuple[tuple[str, str], ...] = (
    ("$be/", "apps/backend/tests/"),
    ("$fe/", "apps/frontend/src/"),
    ("$t/", "tests/tooling/"),
    ("$e2e/", "tests/e2e/"),
)


_TEST_PREFIX_RE = re.compile(
    r"^(?:test_)?(?:AC[-_][A-Za-z0-9_.-]+?\s+|AC\d+(?:[._]\d+)+(?:/AC\d+(?:[._]\d+)+)*\s+|"
    r"AC_[a-z0-9]+_[a-z0-9_]+_\d+_|AC\d+_\d+_\d+_)+",
    re.IGNORECASE,
)


def _humanize_test_ref(full_test: str) -> str:
    label = full_test.split("::", 1)[-1]
    label = _TEST_PREFIX_RE.sub("", label)
    if label.startswith("test_"):
        label = label[5:]
    words = label.replace("_", " ").strip()
    if not words:
        words = (
            full_test.rsplit("/", 1)[-1].replace("_", " ").removesuffix(".py")
            or "Verified by contract test"
        )
    return words[0].upper() + words[1:].rstrip(".") + "."


def expand_test_path(path: str) -> str:
    """Expand compact test-root prefixes used in declarative contract tables."""
    for alias, target in _TEST_PATH_ALIASES:
        if path.startswith(alias):
            return target + path[len(alias) :]
    return path


def parse_acs_table(
    pkg: str, table: str, package_tier: str | None = None
) -> list[dict[str, str | None]]:
    """Parse a declarative pipe-delimited AC table into raw roadmap dicts."""
    prefix = f"AC-{pkg}." if pkg else ""
    cur_file = ""
    cur_prio = "P0"
    cur_status = "done"
    cur_pk: str | None = None
    prev_test = ""
    records: list[dict[str, str | None]] = []
    for raw_line in table.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            parts = [p.strip() for p in line[1:].split("|")]
            raw_f = parts[0] if len(parts) > 0 and parts[0] != "-" else ""
            cur_file = expand_test_path(raw_f)
            cur_prio = parts[1] if len(parts) > 1 and parts[1] else "P0"
            cur_status = parts[2] if len(parts) > 2 and parts[2] else "done"
            cur_pk = (
                parts[3] if len(parts) > 3 and parts[3] and parts[3] != "-" else None
            )
            prev_test = ""
            continue
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 3:
            raise ValueError(f"malformed AC table row in {pkg!r}: {raw_line!r}")
        raw_id, stmt, raw_tref = cols[0], cols[1], cols[2]
        test_ref = expand_test_path(raw_tref)
        prio, status, pk = cur_prio, cur_status, cur_pk
        if len(cols) > 3 and cols[3] and cols[3] != "-":
            meta = cols[3].split(":")
            if len(meta) > 0 and meta[0]:
                prio = meta[0]
            if len(meta) > 1 and meta[1]:
                pk = None if meta[1] == "-" else meta[1]
            if len(meta) > 2 and meta[2]:
                status = meta[2]
        va = cols[4] if len(cols) > 4 and cols[4] and cols[4] != "-" else None
        full_id = (
            raw_id if raw_id.startswith("AC") or not prefix else f"{prefix}{raw_id}"
        )
        full_test = (
            prev_test
            if raw_tref == "^" and prev_test
            else (
                f"{cur_file}::{test_ref}"
                if cur_file and "::" not in test_ref
                else test_ref
            )
        )
        prev_test = full_test
        records.append(
            {
                "id": full_id,
                "statement": stmt or _humanize_test_ref(full_test),
                "test": full_test,
                "priority": prio,
                "status": status,
                "tier": package_tier,
                "proof_kind": pk,
                "vision_anchor": va,
            }
        )
    return records
