"""Migrated-enum check of the schema-migrations CI job (infra2#1658).

Evidence: the infra2 pre-deploy schema gate blocked finance_report v0.2.65 because migration 0074
adds four enum types with a new table. A fix lets the gate tolerate such a type, and a third review
of that fix showed that nothing compared the labels that the migrations create with the labels of
the ORM: `alembic check` ignores enum labels, and the unit tests build their schema from the ORM.
`scripts/check_migrated_enums.py` compares them after `alembic upgrade head` in CI.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "apps" / "backend" / "scripts" / "check_migrated_enums.py"
_spec = importlib.util.spec_from_file_location("check_migrated_enums", SCRIPT)
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
    """AC-meta.phase0.20: A missing type, a missing label, an extra label and an extra type are each reported."""
    lines = check.enum_differences({"k_enum": KIND}, database)
    assert len(lines) == 1
    assert expected in lines[0]


def test_AC_meta_phase0_21_equal_enums_have_no_difference():
    """AC-meta.phase0.21: A database with the same types and labels as the ORM gives no difference."""
    assert check.enum_differences({"k_enum": KIND}, {"k_enum": KIND}) == []


def test_AC_meta_phase0_22_orm_enums_are_read_from_the_real_metadata():
    """AC-meta.phase0.22: The ORM side holds the statement run types, and two columns with different labels are an error."""
    import src.orm_registry  # noqa: F401
    from src.database import Base

    enums = check.code_enums(Base.metadata)
    assert enums["statement_run_kind_enum"] == KIND

    def column(labels):
        return SimpleNamespace(type=SimpleNamespace(name="k_enum", enums=labels, native_enum=True))

    clash = SimpleNamespace(
        tables={"a": SimpleNamespace(columns=[column(["x"])]), "b": SimpleNamespace(columns=[column(["y"])])}
    )
    with pytest.raises(ValueError, match="different labels"):
        check.code_enums(clash)


def test_AC_meta_phase0_23_main_exits_one_on_a_difference_and_zero_otherwise(monkeypatch, capsys):
    """AC-meta.phase0.23: The check fails the CI job when the migrated labels differ from the ORM labels."""
    import src.orm_registry  # noqa: F401
    from src.database import Base

    orm = check.code_enums(Base.metadata)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://db/app")
    monkeypatch.setattr(check, "migrated_enums", lambda _url: dict(orm))
    assert check.main() == 0
    drifted = dict(orm)
    drifted["statement_run_kind_enum"] = KIND | {"zz_drift"}
    monkeypatch.setattr(check, "migrated_enums", lambda _url: drifted)
    assert check.main() == 1
    assert "statement_run_kind_enum" in capsys.readouterr().err


def test_AC_meta_phase0_24_the_schema_migrations_job_runs_the_check_after_alembic_check():
    """AC-meta.phase0.24: The merge-authority job migrates a fresh database and then runs the enum check, unguarded."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lines = [
        line.strip() for line in workflow.split("  schema-migrations:", 1)[1].split("  backend:", 1)[0].splitlines()
    ]
    command = "uv run --frozen python scripts/check_migrated_enums.py"
    assert lines.count(command) == 1, "the command must be its own line, with no `|| true` or other suffix"
    index = lines.index(command)
    assert lines.index("uv run --frozen alembic upgrade head") < lines.index("uv run --frozen alembic check") < index
    assert index < lines.index("} 2>&1 | tee test-results/schema-migration.log")


def test_AC_meta_phase0_25_a_column_that_is_not_a_native_enum_is_not_an_enum_type():
    """AC-meta.phase0.25: A VARCHAR-backed enum column creates no Postgres type, so the ORM side skips it."""
    native = SimpleNamespace(type=SimpleNamespace(name="n_enum", enums=["a"], native_enum=True))
    plain = SimpleNamespace(type=SimpleNamespace(name="p_enum", enums=["a"], native_enum=False))
    metadata = SimpleNamespace(tables={"t": SimpleNamespace(columns=[native, plain])})
    assert check.code_enums(metadata) == {"n_enum": frozenset({"a"})}


def test_AC_meta_phase0_26_the_database_side_groups_labels_and_drops_the_async_driver_suffix(monkeypatch):
    """AC-meta.phase0.26: The labels of one type are grouped, psycopg2 gets a URL without `+asyncpg`, and only visible types count."""
    seen: list[str] = []
    queries: list[str] = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def cursor(self):
            return self

        def execute(self, sql):
            queries.append(sql)

        def fetchall(self):
            return [("k_enum", "extract"), ("k_enum", "classify"), ("s_enum", "x")]

    monkeypatch.setattr(check.psycopg2, "connect", lambda url: seen.append(url) or Connection())
    assert check.migrated_enums("postgresql+asyncpg://db/app") == {"k_enum": KIND, "s_enum": frozenset({"x"})}
    assert seen == ["postgresql://db/app"]
    assert len(queries) == 1 and "pg_type_is_visible(t.oid)" in queries[0]
