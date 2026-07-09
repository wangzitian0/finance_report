from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import yaml

from common.meta.extension import migration_risk


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: Path, content: str) -> None:
    path.write_text(dedent(content).lstrip(), encoding="utf-8")


def write_manifest(path: Path, migrations: dict[str, object]) -> None:
    path.write_text(
        yaml.safe_dump({"version": 1, "migrations": migrations}),
        encoding="utf-8",
    )


def test_AC7_11_1_migration_risk_manifest_covers_backend_migrations() -> None:
    """AC-meta.migration-risk.1: AC7.11.1: Backend Alembic migrations are covered by the risk manifest."""

    result = migration_risk.validate_repository(ROOT)

    assert result.ok
    assert result.errors == []
    assert len(result.migrations) >= 40
    assert result.manifest_path == ROOT / "docs/ssot/migration-risk.yaml"
    assert all(
        record.risk in migration_risk.RISK_LEVELS
        for record in result.migrations.values()
    )


def test_AC7_11_2_high_and_critical_migrations_require_release_proof(
    tmp_path: Path,
) -> None:
    """AC-meta.migration-risk.2: AC7.11.2: High and critical migrations carry right-sized release proof notes."""

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_high.py").write_text(
        dedent(
            """
from alembic import op

revision = "0001_high"
down_revision = None

def upgrade():
    op.execute("UPDATE accounts SET name = name")
"""
        ).lstrip(),
        encoding="utf-8",
    )
    manifest = tmp_path / "migration-risk.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "migrations": {
                    "0001_high": {
                        "file": "0001_high.py",
                        "risk": "high",
                        "proof": "Data rewrite requires more than clean-schema proof.",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = migration_risk.validate(
        manifest_path=manifest, migrations_dir=migrations_dir
    )

    assert any(
        "0001_high" in error and "staging_validation" in error
        for error in result.errors
    )
    assert any(
        "0001_high" in error and "production_preflight" in error
        for error in result.errors
    )
    assert any(
        "0001_high" in error and "rollback_strategy" in error for error in result.errors
    )


def test_AC7_11_3_destructive_migrations_must_be_classified_critical(
    tmp_path: Path,
) -> None:
    """AC-meta.migration-risk.3: AC7.11.3: Destructive upgrade operations cannot be under-classified."""

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0002_drop_legacy.py").write_text(
        dedent(
            """
from alembic import op

revision = "0002_drop_legacy"
down_revision = None

def upgrade():
    op.drop_table("legacy_rows")
"""
        ).lstrip(),
        encoding="utf-8",
    )
    manifest = tmp_path / "migration-risk.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "migrations": {
                    "0002_drop_legacy": {
                        "file": "0002_drop_legacy.py",
                        "risk": "high",
                        "proof": "This intentionally under-classifies a destructive migration.",
                        "issue": "#815",
                        "staging_validation": "Staging drop rehearsal.",
                        "production_preflight": "Production table dependency check.",
                        "rollback_strategy": "Backup before destructive change.",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = migration_risk.validate(
        manifest_path=manifest, migrations_dir=migrations_dir
    )

    assert any(
        "0002_drop_legacy" in error and "critical" in error for error in result.errors
    )


def test_AC7_11_3_migration_parser_and_manifest_shape_errors_are_reported(
    tmp_path: Path,
) -> None:
    """AC7.11.3: Parser and manifest-shape failures are surfaced as contract errors."""

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    missing_manifest = migration_risk.validate(
        manifest_path=tmp_path / "missing.yaml",
        migrations_dir=migrations_dir,
    )
    assert not missing_manifest.ok
    assert any("does not exist" in error for error in missing_manifest.errors)

    invalid_yaml = tmp_path / "invalid.yaml"
    invalid_yaml.write_text("migrations: [", encoding="utf-8")
    invalid_yaml_result = migration_risk.validate(
        manifest_path=invalid_yaml,
        migrations_dir=migrations_dir,
    )
    assert any("invalid YAML" in error for error in invalid_yaml_result.errors)

    scalar_manifest = tmp_path / "scalar.yaml"
    scalar_manifest.write_text("[]", encoding="utf-8")
    scalar_result = migration_risk.validate(
        manifest_path=scalar_manifest,
        migrations_dir=migrations_dir,
    )
    assert any("must be a YAML mapping" in error for error in scalar_result.errors)

    missing_migrations_manifest = tmp_path / "missing-migrations.yaml"
    missing_migrations_manifest.write_text("version: 1\n", encoding="utf-8")
    missing_migrations_result = migration_risk.validate(
        manifest_path=missing_migrations_manifest,
        migrations_dir=migrations_dir,
    )
    assert any(
        "missing 'migrations' mapping" in error
        for error in missing_migrations_result.errors
    )


def test_AC7_11_3_migration_file_parse_errors_are_reported(
    tmp_path: Path,
) -> None:
    """AC7.11.3: Alembic revision parsing handles syntax, missing, typed, and duplicate cases."""

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    write(migrations_dir / "bad_syntax.py", "def upgrade(:\n    pass\n")
    write(
        migrations_dir / "missing_revision.py",
        """
        down_revision = None

        def upgrade():
            pass
        """,
    )
    write(
        migrations_dir / "dynamic_revision.py",
        """
        revision = make_revision()
        down_revision = None

        def upgrade():
            pass
        """,
    )
    write(
        migrations_dir / "typed_revision.py",
        """
        revision: str = "typed_revision"
        down_revision = None

        def upgrade():
            pass
        """,
    )
    write(
        migrations_dir / "no_upgrade.py",
        """
        revision = "no_upgrade"
        down_revision = None
        """,
    )
    write(
        migrations_dir / "duplicate_a.py",
        """
        revision = "duplicate_revision"
        down_revision = None

        def upgrade():
            pass
        """,
    )
    write(
        migrations_dir / "duplicate_b.py",
        """
        revision = "duplicate_revision"
        down_revision = None

        def upgrade():
            pass
        """,
    )
    write(
        migrations_dir / "missing_manifest.py",
        """
        from alembic import op

        revision = "missing_manifest"
        down_revision = None

        def upgrade():
            op.drop_table("legacy_rows")
        """,
    )

    manifest = tmp_path / "migration-risk.yaml"
    write_manifest(
        manifest,
        {
            "typed_revision": {
                "file": "typed_revision.py",
                "risk": "low",
                "proof": "Typed revision assignment is accepted.",
            },
            "no_upgrade": {
                "file": "no_upgrade.py",
                "risk": "low",
                "proof": "No upgrade function is accepted for merge-only style revisions.",
            },
            "duplicate_revision": {
                "file": "duplicate_a.py",
                "risk": "low",
                "proof": "Only the first duplicate can be validated.",
            },
            "extra_revision": {
                "file": "extra_revision.py",
                "risk": "low",
                "proof": "Extra manifest entries must be rejected.",
            },
        },
    )

    result = migration_risk.validate(
        manifest_path=manifest, migrations_dir=migrations_dir
    )

    assert any("bad_syntax.py: cannot parse" in error for error in result.errors)
    assert any(
        "missing_revision.py: missing string Alembic revision" in error
        for error in result.errors
    )
    assert any(
        "dynamic_revision.py: missing string Alembic revision" in error
        for error in result.errors
    )
    assert any("duplicate Alembic revision" in error for error in result.errors)
    assert any(
        "missing_manifest: auto-classified critical migration requires a manifest entry"
        in error
        for error in result.errors
    )
    assert any(
        "extra_revision: manifest entry has no matching migration file" in error
        for error in result.errors
    )
    assert result.migrations["typed_revision"].file_name == "typed_revision.py"
    assert result.migrations["no_upgrade"].proof.startswith("No upgrade")


def test_AC7_11_3_manifest_entry_errors_are_reported(tmp_path: Path) -> None:
    """AC7.11.3: Invalid manifest entries and under-classified data mutations fail."""

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    write(
        migrations_dir / "not_mapping.py",
        """
        revision = "not_mapping"
        down_revision = None

        def upgrade():
            pass
        """,
    )
    write(
        migrations_dir / "bad_fields.py",
        """
        revision = "bad_fields"
        down_revision = None

        def upgrade():
            pass
        """,
    )
    write(
        migrations_dir / "bad_issue.py",
        """
        revision = "bad_issue"
        down_revision = None

        def upgrade():
            pass
        """,
    )
    write(
        migrations_dir / "low_update.py",
        """
        from alembic import op

        revision = "low_update"
        down_revision = None

        def upgrade():
            op.execute("UPDATE accounts SET name = name")
        """,
    )
    write(
        migrations_dir / "critical_drop.py",
        """
        from alembic import op

        revision = "critical_drop"
        down_revision = None

        def upgrade():
            op.drop_column("legacy_rows", "legacy_value")
        """,
    )

    manifest = tmp_path / "migration-risk.yaml"
    write_manifest(
        manifest,
        {
            "not_mapping": "bad",
            "bad_fields": {
                "file": "wrong.py",
                "risk": "extreme",
                "proof": " ",
            },
            "bad_issue": {
                "file": "bad_issue.py",
                "risk": "high",
                "proof": "High risk proof.",
                "issue": "815",
                "staging_validation": "Staging proof.",
                "production_preflight": "Production preflight.",
                "rollback_strategy": "Rollback proof.",
            },
            "low_update": {
                "file": "low_update.py",
                "risk": "low",
                "proof": "This intentionally under-classifies a data rewrite.",
            },
            "critical_drop": {
                "file": "critical_drop.py",
                "risk": "critical",
                "proof": "Critical destructive migration proof.",
                "issue": "https://github.com/wangzitian0/finance_report/issues/815",
                "staging_validation": "Staging destructive proof.",
                "production_preflight": "Production dependency check.",
                "rollback_strategy": "Backup and restore strategy.",
                "destructive_confirmation": "Destructive operation explicitly confirmed.",
            },
        },
    )

    result = migration_risk.validate(
        manifest_path=manifest, migrations_dir=migrations_dir
    )

    assert any(
        "not_mapping: manifest entry must be a mapping" in error
        for error in result.errors
    )
    assert any("bad_fields: manifest file must be" in error for error in result.errors)
    assert any("bad_fields: risk must be one of" in error for error in result.errors)
    assert any("bad_fields: proof is required" in error for error in result.errors)
    assert any(
        "bad_issue: issue must be a GitHub issue reference" in error
        for error in result.errors
    )
    assert any(
        "low_update: data-mutating upgrade operation must be classified as high or critical"
        in error
        for error in result.errors
    )
    assert result.migrations["critical_drop"].destructive_confirmation is not None


def test_AC7_11_4_summary_and_cli_paths_are_reported(tmp_path: Path, capsys) -> None:
    """AC7.11.4: CLI summary paths report pass/fail status and write release context."""

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    write(
        migrations_dir / "0001_low.py",
        """
        revision = "0001_low"
        down_revision = None

        def upgrade():
            pass
        """,
    )
    manifest = tmp_path / "migration-risk.yaml"
    write_manifest(
        manifest,
        {
            "0001_low": {
                "file": "0001_low.py",
                "risk": "low",
                "proof": "CLI success path proof.",
            }
        },
    )
    summary_path = tmp_path / "ci-context" / "migration-risk.md"

    rc = migration_risk.main(
        [
            "--repo-root",
            str(tmp_path),
            "--manifest",
            str(manifest),
            "--migrations-dir",
            str(migrations_dir),
            "--summary",
            str(summary_path),
        ]
    )
    stdout = capsys.readouterr().out

    assert rc == 0
    assert "Status: pass" in stdout
    assert "Status: pass" in summary_path.read_text(encoding="utf-8")

    failed = migration_risk.main(
        [
            "--repo-root",
            str(tmp_path),
            "--manifest",
            str(tmp_path / "missing.yaml"),
            "--migrations-dir",
            str(migrations_dir),
        ]
    )
    captured = capsys.readouterr()

    assert failed == 1
    assert "Status: fail" in captured.err

    summary = migration_risk.render_summary(
        migration_risk.ValidationResult(
            manifest_path=Path("manifest.yaml"),
            migrations_dir=Path("migrations"),
            migrations={
                "critical_manual": migration_risk.MigrationRecord(
                    revision="critical_manual",
                    file_name="critical_manual.py",
                    risk="critical",
                    proof="Manual summary proof without issue.",
                )
            },
            errors=["synthetic error"],
        )
    )
    assert (
        "`critical_manual`: critical - Manual summary proof without issue." in summary
    )
    assert "- synthetic error" in summary


def test_AC7_11_4_ci_and_release_dry_run_execute_migration_risk_contract() -> None:
    """AC-meta.migration-risk.4: AC7.11.4: CI and production dry-run surface migration risk classification."""

    ci = read(".github/workflows/ci.yml")
    release = read(".github/workflows/release.yml")

    assert "Migration Risk Contract Check" in ci
    assert "python tools/check_migration_risk.py" in ci
    assert "Validate Migration Risk Contract" in release
    assert "production-migration-risk-context.md" in release


def test_AC7_11_5_low_and_medium_migrations_are_auto_classified(tmp_path: Path) -> None:
    """AC-meta.migration-risk.5: AC7.11.5: Risk is auto-classified from upgrade(); low/medium need no manifest entry while high/critical still require explicit release proof."""

    assert migration_risk.classify_risk('op.create_table("t")') == "low"
    assert migration_risk.classify_risk("op.add_column('t', c)") == "low"
    assert migration_risk.classify_risk('op.alter_column("t", "c")') == "medium"
    assert (
        migration_risk.classify_risk('op.execute("ALTER TYPE e ADD VALUE x")')
        == "medium"
    )
    assert migration_risk.classify_risk('op.execute("UPDATE t SET c = 1")') == "high"
    assert migration_risk.classify_risk('op.drop_table("t")') == "critical"

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    write(
        migrations_dir / "additive.py",
        """
        from alembic import op

        revision = "additive"
        down_revision = None

        def upgrade():
            op.create_table("widgets")
        """,
    )
    write(
        migrations_dir / "altered.py",
        """
        from alembic import op

        revision = "altered"
        down_revision = "additive"

        def upgrade():
            op.alter_column("widgets", "name")
        """,
    )
    write(
        migrations_dir / "mutated.py",
        """
        from alembic import op

        revision = "mutated"
        down_revision = "altered"

        def upgrade():
            op.execute("UPDATE widgets SET name = name")
        """,
    )
    manifest = tmp_path / "migration-risk.yaml"
    write_manifest(manifest, {})

    result = migration_risk.validate(
        manifest_path=manifest, migrations_dir=migrations_dir
    )

    # Additive and compatibility-sensitive migrations are auto-classified, no entry needed.
    assert result.migrations["additive"].risk == "low"
    assert result.migrations["altered"].risk == "medium"
    assert all("additive" not in error for error in result.errors)
    assert all("altered" not in error for error in result.errors)

    # A data-mutating migration without an entry is rejected until proof is declared.
    assert "mutated" not in result.migrations
    assert any(
        "mutated: auto-classified high migration requires a manifest entry" in error
        for error in result.errors
    )
