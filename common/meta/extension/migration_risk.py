"""Validate Alembic migration risk classification.

The contract is intentionally static. It does not try to prove production data
safety; it checks that migration risk is declared and that higher-risk changes
carry the release proof notes needed before a human approves deployment.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


RISK_LEVELS = ("low", "medium", "high", "critical")
RISK_RANK = {risk: index for index, risk in enumerate(RISK_LEVELS)}
HIGH_RISK_FIELDS = (
    "issue",
    "staging_validation",
    "production_preflight",
    "rollback_strategy",
)
CRITICAL_RISK_FIELDS = HIGH_RISK_FIELDS + ("destructive_confirmation",)

DESTRUCTIVE_UPGRADE_PATTERNS = (
    r"\bop\.drop_table\s*\(",
    r"\bop\.drop_column\s*\(",
    r"\bDROP\s+TABLE\b",
    r"\bDROP\s+COLUMN\b",
    r"\bTRUNCATE\b",
)
DATA_MUTATION_UPGRADE_PATTERNS = (
    r"\bUPDATE\s+",
    r"\bINSERT\s+INTO\b",
    r"\bDELETE\s+FROM\b",
)
SCHEMA_SENSITIVE_UPGRADE_PATTERNS = (
    r"\bop\.alter_column\s*\(",
    r"\bop\.drop_constraint\s*\(",
    r"\bop\.drop_index\s*\(",
    r"\bALTER\s+TYPE\b",
    r"\bADD\s+VALUE\b",
)


@dataclass(frozen=True)
class ParsedMigration:
    revision: str
    file_name: str
    upgrade_source: str


@dataclass(frozen=True)
class MigrationRecord:
    revision: str
    file_name: str
    risk: str
    proof: str
    issue: str | None = None
    staging_validation: str | None = None
    production_preflight: str | None = None
    rollback_strategy: str | None = None
    destructive_confirmation: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    manifest_path: Path
    migrations_dir: Path
    migrations: dict[str, MigrationRecord]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _literal_string(node: ast.AST) -> str | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _parse_revision(tree: ast.Module) -> str | None:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "revision":
                    return _literal_string(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "revision"
        ):
            return _literal_string(node.value) if node.value is not None else None
    return None


def _parse_upgrade_source(source: str, tree: ast.Module) -> str:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            return ast.get_source_segment(source, node) or ""
    return ""


def parse_migration_file(path: Path) -> ParsedMigration | str:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return f"{path.name}: cannot parse migration Python: {exc}"

    revision = _parse_revision(tree)
    if not revision:
        return f"{path.name}: missing string Alembic revision"

    return ParsedMigration(
        revision=revision,
        file_name=path.name,
        upgrade_source=_parse_upgrade_source(source, tree),
    )


def _load_manifest(path: Path) -> tuple[dict[str, Any], list[str]]:
    if not path.exists():
        return {}, [f"{path}: migration risk manifest does not exist"]

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return {}, [f"{path}: invalid YAML: {exc}"]

    if not isinstance(payload, dict):
        return {}, [f"{path}: manifest must be a YAML mapping"]
    if not isinstance(payload.get("migrations"), dict):
        return payload, [f"{path}: missing 'migrations' mapping"]
    return payload, []


def _matches_any(source: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, source, flags=re.IGNORECASE) for pattern in patterns)


def classify_risk(upgrade_source: str) -> str:
    """Auto-classify migration risk from the ``upgrade()`` source.

    Destructive drops set a critical floor, data mutations a high floor, and
    compatibility-sensitive schema changes default to medium; anything else
    (additive tables/columns, clean-schema DDL) is low. The manifest only needs
    to carry entries that raise risk above this floor or attach release proof.
    """
    if _matches_any(upgrade_source, DESTRUCTIVE_UPGRADE_PATTERNS):
        return "critical"
    if _matches_any(upgrade_source, DATA_MUTATION_UPGRADE_PATTERNS):
        return "high"
    if _matches_any(upgrade_source, SCHEMA_SENSITIVE_UPGRADE_PATTERNS):
        return "medium"
    return "low"


def _entry_text(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    return value.strip() if isinstance(value, str) else ""


def _validate_entry(
    revision: str, parsed: ParsedMigration, entry: object
) -> tuple[MigrationRecord | None, list[str]]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        return None, [f"{revision}: manifest entry must be a mapping"]

    file_name = _entry_text(entry, "file")
    risk = _entry_text(entry, "risk")
    proof = _entry_text(entry, "proof")

    if file_name != parsed.file_name:
        errors.append(
            f"{revision}: manifest file must be {parsed.file_name!r}, got {file_name!r}"
        )
    if risk not in RISK_LEVELS:
        errors.append(f"{revision}: risk must be one of {', '.join(RISK_LEVELS)}")
    if not proof:
        errors.append(f"{revision}: proof is required")

    if risk in {"high", "critical"}:
        for field in CRITICAL_RISK_FIELDS if risk == "critical" else HIGH_RISK_FIELDS:
            if not _entry_text(entry, field):
                errors.append(
                    f"{revision}: {field} is required for {risk} migration risk"
                )

    issue = _entry_text(entry, "issue") or None
    if (
        risk in {"high", "critical"}
        and issue
        and not (issue.startswith("#") or issue.startswith("https://github.com/"))
    ):
        errors.append(
            f"{revision}: issue must be a GitHub issue reference like #815 or a GitHub URL"
        )

    if (
        _matches_any(parsed.upgrade_source, DESTRUCTIVE_UPGRADE_PATTERNS)
        and risk != "critical"
    ):
        errors.append(
            f"{revision}: destructive upgrade operation must be classified as critical"
        )

    if (
        _matches_any(parsed.upgrade_source, DATA_MUTATION_UPGRADE_PATTERNS)
        and RISK_RANK.get(risk, -1) < RISK_RANK["high"]
    ):
        errors.append(
            f"{revision}: data-mutating upgrade operation must be classified as high or critical"
        )

    if errors:
        return None, errors

    return (
        MigrationRecord(
            revision=revision,
            file_name=file_name,
            risk=risk,
            proof=proof,
            issue=issue,
            staging_validation=_entry_text(entry, "staging_validation") or None,
            production_preflight=_entry_text(entry, "production_preflight") or None,
            rollback_strategy=_entry_text(entry, "rollback_strategy") or None,
            destructive_confirmation=_entry_text(entry, "destructive_confirmation")
            or None,
        ),
        [],
    )


def validate(*, manifest_path: Path, migrations_dir: Path) -> ValidationResult:
    payload, errors = _load_manifest(manifest_path)
    manifest_entries = (
        payload.get("migrations", {})
        if isinstance(payload.get("migrations"), dict)
        else {}
    )

    parsed_by_revision: dict[str, ParsedMigration] = {}
    for path in sorted(migrations_dir.glob("*.py")):
        parsed = parse_migration_file(path)
        if isinstance(parsed, str):
            errors.append(parsed)
            continue
        if parsed.revision in parsed_by_revision:
            errors.append(f"{parsed.revision}: duplicate Alembic revision")
            continue
        parsed_by_revision[parsed.revision] = parsed

    records: dict[str, MigrationRecord] = {}
    for revision, parsed in parsed_by_revision.items():
        auto_risk = classify_risk(parsed.upgrade_source)
        if revision not in manifest_entries:
            if auto_risk in {"high", "critical"}:
                errors.append(
                    f"{revision}: auto-classified {auto_risk} migration requires a "
                    f"manifest entry with release proof in {manifest_path.name}"
                )
                continue
            records[revision] = MigrationRecord(
                revision=revision,
                file_name=parsed.file_name,
                risk=auto_risk,
                proof=(
                    f"Auto-classified {auto_risk} from upgrade operations; "
                    "covered by the PR Alembic contract."
                ),
            )
            continue
        record, entry_errors = _validate_entry(
            revision, parsed, manifest_entries[revision]
        )
        errors.extend(entry_errors)
        if record is not None:
            records[revision] = record

    for revision in sorted(set(manifest_entries) - set(parsed_by_revision)):
        errors.append(f"{revision}: manifest entry has no matching migration file")

    return ValidationResult(
        manifest_path=manifest_path,
        migrations_dir=migrations_dir,
        migrations=records,
        errors=errors,
    )


def validate_repository(repo_root: Path) -> ValidationResult:
    return validate(
        manifest_path=repo_root / "common" / "meta" / "data" / "migration-risk.yaml",
        migrations_dir=repo_root / "apps" / "backend" / "migrations" / "versions",
    )


def render_summary(result: ValidationResult) -> str:
    counts = Counter(record.risk for record in result.migrations.values())
    high_risk = [
        record
        for record in result.migrations.values()
        if record.risk in {"high", "critical"}
    ]

    lines = [
        "## Migration Risk Contract",
        "",
        f"- Manifest: `{result.manifest_path.as_posix()}`",
        f"- Migrations checked: {len(result.migrations)}",
        f"- Status: {'pass' if result.ok else 'fail'}",
        "",
        "| Risk | Count |",
        "|---|---:|",
    ]
    for risk in RISK_LEVELS:
        lines.append(f"| {risk} | {counts[risk]} |")
    if high_risk:
        lines.extend(["", "### High/Critical Migrations", ""])
        for record in sorted(high_risk, key=lambda item: item.revision):
            issue = f" ({record.issue})" if record.issue else ""
            lines.append(
                f"- `{record.revision}`: {record.risk}{issue} - {record.proof}"
            )
    if result.errors:
        lines.extend(["", "### Errors", ""])
        lines.extend(f"- {error}" for error in result.errors)
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Alembic migration risk classification."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--migrations-dir", type=Path, default=None)
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Optional Markdown summary output path.",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    result = validate(
        manifest_path=args.manifest
        or repo_root / "common" / "meta" / "data" / "migration-risk.yaml",
        migrations_dir=args.migrations_dir
        or repo_root / "apps" / "backend" / "migrations" / "versions",
    )

    summary = render_summary(result)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(summary, encoding="utf-8")

    if result.errors:
        print(summary, file=sys.stderr)
        return 1

    print(summary)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
