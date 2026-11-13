"""Compare the enum types of a migrated database with the ORM's native enums.

Run after `alembic upgrade head` on a fresh database (CI job `schema-migrations`).
`alembic check` does not compare enum labels, and the unit tests build their schema from the
ORM with `create_all`, so a migration that creates an enum type with other labels than the ORM
declares passes both. The infra2 pre-deploy schema gate (infra2#1671, once merged) tolerates an
enum type that only new tables use and does not compare its labels; this check is the proof,
at merge time and by execution.

Exit code 0: every native enum type of the ORM exists in the database with the same set of
labels (label order is not compared), and the database holds no other enum type that is visible
on the search path. Exit code 1: any difference, printed one per line.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Any

import psycopg2

_DB_ENUMS_SQL = (
    "SELECT t.typname, e.enumlabel FROM pg_type t "
    "JOIN pg_enum e ON e.enumtypid = t.oid "
    "JOIN pg_namespace n ON n.oid = t.typnamespace "
    "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
    "AND pg_catalog.pg_type_is_visible(t.oid)"
)


def code_enums(metadata: Any) -> dict[str, frozenset[str]]:
    """``{enum type name: labels}`` for every native enum column on ``metadata``.

    Every enum column of the ORM is a plain ``Enum`` today. An enum behind an ARRAY or a
    TypeDecorator is not unwrapped: it would show up as "type only in the database", which
    fails loudly, and the person who adds such a column extends this function.
    """
    enums: dict[str, frozenset[str]] = {}
    for table in metadata.tables.values():
        for column in table.columns:
            labels = getattr(column.type, "enums", None)
            name = getattr(column.type, "name", None)
            if isinstance(labels, list | tuple) and name and getattr(column.type, "native_enum", True):
                known = enums.setdefault(name, frozenset(labels))
                if known != frozenset(labels):
                    raise ValueError(f"enum type {name!r} is declared with different labels on two columns")
    return enums


def migrated_enums(database_url: str) -> dict[str, frozenset[str]]:
    """``{enum type name: labels}`` that the database holds."""
    enums: dict[str, set[str]] = {}
    with psycopg2.connect(database_url.replace("+asyncpg", "")) as connection, connection.cursor() as cursor:
        cursor.execute(_DB_ENUMS_SQL)
        for name, label in cursor.fetchall():
            enums.setdefault(name, set()).add(label)
    return {name: frozenset(labels) for name, labels in enums.items()}


def enum_differences(code: Mapping[str, frozenset[str]], database: Mapping[str, frozenset[str]]) -> list[str]:
    """One line for every difference between the ORM's enum types and the database's."""
    lines: list[str] = []
    for name in sorted(code):
        if name not in database:
            lines.append(f"{name}: type missing in the database (ORM labels {sorted(code[name])})")
            continue
        missing, extra = sorted(code[name] - database[name]), sorted(database[name] - code[name])
        if missing or extra:
            lines.append(f"{name}: labels missing in the database {missing}, labels only in the database {extra}")
    lines.extend(
        f"{name}: type only in the database (labels {sorted(database[name])})"
        for name in sorted(set(database) - set(code))
    )
    return lines


def main() -> int:
    import src.counter.extension.sql  # noqa: F401  (same registrations as migrations/env.py)
    import src.identity.extension.sql  # noqa: F401
    import src.orm_registry  # noqa: F401
    import src.platform.extension.sql  # noqa: F401
    from src.database import Base

    orm = code_enums(Base.metadata)
    differences = enum_differences(orm, migrated_enums(os.environ["DATABASE_URL"]))
    for line in differences:
        print(line, file=sys.stderr)
    print(f"migrated enum check: {len(orm)} enum types compared, {len(differences)} difference(s)")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
