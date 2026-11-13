"""Compare the enum types of a migrated database with the ORM's native enums.

Run after `alembic upgrade head` on a fresh database (CI job `schema-migrations`).
`alembic check` does not compare enum labels, and the unit tests build their schema from the
ORM with `create_all`, so a migration that creates an enum type with other labels than the ORM
declares passes both. The infra2 pre-deploy schema gate tolerates an enum type that only new
tables use, because this check proved the migrated labels at merge time (infra2#1658).

Exit code 0: every native enum type of the ORM exists in the database with exactly the same
labels, and the database holds no other enum type. Exit code 1: any difference, printed one
per line. The same comparison runs in the gate, against the live database, before a deploy.
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
    "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')"
)


def code_enums(metadata: Any) -> dict[str, frozenset[str]]:
    """``{enum type name: labels}`` for every native enum column on ``metadata``."""
    enums: dict[str, frozenset[str]] = {}
    for table in metadata.tables.values():
        for column in table.columns:
            for candidate in (
                column.type,
                getattr(column.type, "item_type", None),
                getattr(column.type, "impl_instance", None),
            ):
                labels = getattr(candidate, "enums", None)
                name = getattr(candidate, "name", None)
                if isinstance(labels, list | tuple) and name and getattr(candidate, "native_enum", True):
                    known = enums.setdefault(name, frozenset(labels))
                    if known != frozenset(labels):
                        raise ValueError(f"enum type {name!r} is declared with different labels on two columns")
                    break
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
    import src.orm_registry  # noqa: F401  (registers every mapped class)
    from src.database import Base

    differences = enum_differences(code_enums(Base.metadata), migrated_enums(os.environ["DATABASE_URL"]))
    for line in differences:
        print(line, file=sys.stderr)
    print(f"migrated enum check: {len(differences)} difference(s)")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
