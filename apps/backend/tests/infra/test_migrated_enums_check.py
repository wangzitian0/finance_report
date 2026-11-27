"""Migrated-enum check of the schema-migrations CI job (infra2#1658)."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location(
    "check_migrated_enums", ROOT / "apps/backend/scripts/check_migrated_enums.py"
)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)
KIND = frozenset({"extract", "classify"})


@pytest.mark.parametrize(
    ("database", "expected"),
    [
        ({}, "k_enum: type missing in the database"),
        ({"k_enum": frozenset({"extract"})}, "labels missing in the database ['classify']"),
        ({"k_enum": KIND | {"gone"}}, "labels only in the database ['gone']"),
        ({"k_enum": KIND, "old_enum": frozenset({"a"})}, "old_enum: type only in the database"),
        (
            {"k_enum": frozenset({"extract", "other"})},
            "labels missing in the database ['classify'], labels only in the database ['other']",
        ),
        (
            {"k_enum": frozenset({"EXTRACT", "CLASSIFY"})},
            "labels missing in the database ['classify', 'extract'], labels only in the database ['CLASSIFY', 'EXTRACT']",
        ),
    ],
)
def test_AC_meta_phase0_20_enum_differences_name_each_kind_of_drift(database, expected):
    lines = check.enum_differences({"k_enum": KIND}, database)
    assert len(lines) == 1 and expected in lines[0]


def test_AC_meta_phase0_21_to_25_orm_enums_ci_and_main(monkeypatch, capsys):
    import src.orm_registry  # noqa: F401
    from src.database import Base

    assert check.enum_differences({"k_enum": KIND}, {"k_enum": KIND}) == []
    orm = check.code_enums(Base.metadata)
    assert orm["statement_run_kind_enum"] == KIND

    col = lambda labels, native=True: SimpleNamespace(
        type=SimpleNamespace(name="k_enum", enums=labels, native_enum=native)
    )
    with pytest.raises(ValueError, match="conflicting enum definitions"):
        check.code_enums(
            SimpleNamespace(
                tables={"a": SimpleNamespace(columns=[col(["x"])]), "b": SimpleNamespace(columns=[col(["y"])])}
            )
        )
    assert check.code_enums(
        SimpleNamespace(tables={"t": SimpleNamespace(columns=[col(["a"], True), col(["b"], False)])})
    ) == {"k_enum": frozenset({"a"})}

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://db/app")
    monkeypatch.setattr(check, "migrated_enums", lambda _url: dict(orm))
    assert check.main() == 0
    monkeypatch.setattr(check, "migrated_enums", lambda _url: {**orm, "statement_run_kind_enum": KIND | {"zz_drift"}})
    assert check.main() == 1 and "statement_run_kind_enum" in capsys.readouterr().err

    lines = [
        line.strip()
        for line in (ROOT / ".github/workflows/ci.yml")
        .read_text(encoding="utf-8")
        .split("  schema-migrations:", 1)[1]
        .split("  backend:", 1)[0]
        .splitlines()
    ]
    cmd = "uv run --frozen python scripts/check_migrated_enums.py"
    assert lines.count(cmd) == 1
    assert (
        lines.index("uv run --frozen alembic upgrade head")
        < lines.index("uv run --frozen alembic check")
        < lines.index(cmd)
        < lines.index("} 2>&1 | tee test-results/schema-migration.log")
    )


def test_AC_meta_phase0_26_the_database_side_groups_labels_and_drops_async_suffix(monkeypatch):
    from contextlib import nullcontext

    seen, queries = [], []
    cursor = nullcontext(
        SimpleNamespace(
            execute=queries.append, fetchall=lambda: [("k_enum", "extract"), ("k_enum", "classify"), ("s_enum", "x")]
        )
    )
    conn = nullcontext(SimpleNamespace(cursor=lambda: cursor))
    monkeypatch.setattr(check.psycopg, "connect", lambda url: seen.append(url) or conn)
    assert check.migrated_enums("postgresql+asyncpg://db/app") == {"k_enum": KIND, "s_enum": frozenset({"x"})}
    assert seen == ["postgresql://db/app"] and len(queries) == 1 and "pg_type_is_visible(t.oid)" in queries[0]
