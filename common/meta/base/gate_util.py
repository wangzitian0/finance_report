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


_TEST_PATH_ALIASES: tuple[tuple[str, str], ...] = (
    ("$be/", "apps/backend/tests/"),
    ("$fe/", "apps/frontend/src/"),
    ("$t/", "tests/tooling/"),
    ("$e2e/", "tests/e2e/"),
)


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
            continue
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 3:
            raise ValueError(f"malformed AC table row in {pkg!r}: {raw_line!r}")
        raw_id, stmt, test_ref = cols[0], cols[1], expand_test_path(cols[2])
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
            f"{cur_file}::{test_ref}" if cur_file and "::" not in test_ref else test_ref
        )
        records.append(
            {
                "id": full_id,
                "statement": stmt,
                "test": full_test,
                "priority": prio,
                "status": status,
                "tier": package_tier,
                "proof_kind": pk,
                "vision_anchor": va,
            }
        )
    return records
