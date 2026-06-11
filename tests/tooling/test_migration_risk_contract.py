from __future__ import annotations

from pathlib import Path

import yaml

from common.ci import migration_risk


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_AC7_11_1_migration_risk_manifest_covers_backend_migrations() -> None:
    """AC7.11.1: Backend Alembic migrations are covered by the risk manifest."""

    result = migration_risk.validate_repository(ROOT)

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
    """AC7.11.2: High and critical migrations carry right-sized release proof notes."""

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_high.py").write_text(
        """
from alembic import op

revision = "0001_high"
down_revision = None

def upgrade():
    op.execute("UPDATE accounts SET name = name")
""",
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
    """AC7.11.3: Destructive upgrade operations cannot be under-classified."""

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0002_drop_legacy.py").write_text(
        """
from alembic import op

revision = "0002_drop_legacy"
down_revision = None

def upgrade():
    op.drop_table("legacy_rows")
""",
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


def test_AC7_11_4_ci_and_release_dry_run_execute_migration_risk_contract() -> None:
    """AC7.11.4: CI and production dry-run surface migration risk classification."""

    ci = read(".github/workflows/ci.yml")
    release = read(".github/workflows/production-release.yml")

    assert "Migration Risk Contract Check" in ci
    assert "python tools/check_migration_risk.py" in ci
    assert "Validate Migration Risk Contract" in release
    assert "production-migration-risk-context.md" in release
