"""Report-only SSOT governance metrics.

The report is intentionally advisory. Hard failures remain owned by the
existing manifest and ownership checkers; this module measures baseline shape
so gradual gates can be introduced with explicit thresholds later.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - CLI guard
    yaml = None


REPORT_VERSION = 1
SOURCE_ISSUE = "https://github.com/wangzitian0/finance_report/issues/822"
HLS_ISSUE = "https://github.com/wangzitian0/finance_report/issues/821"

HIGH_RISK_SUBSTRINGS = (
    "migration",
    "environment",
    "deploy",
    "deployment",
    "secret",
    "secrets",
    "vault",
    "coverage",
    "evidence",
    "pipeline",
)
HIGH_RISK_TOKENS = {"ci", "env"}
MACHINE_OWNER_SUFFIXES = (".yaml", ".yml", ".json")
MACHINE_KINDS = {"machine_table", "baseline", "registry", "matrix"}
PROOF_MARKERS = (
    "tests/",
    "/tests/",
    "tools/",
    "common/",
    ".github/workflows/",
    "apps/",
    "libs/tests/",
    "platform/",
)
SSOT_FILE_SUFFIXES = {".md", ".yaml", ".yml", ".json"}
SSOT_FILE_EXCLUDES = {"README.md", "MANIFEST.yaml", "template.md"}


@dataclass(frozen=True)
class GovernanceEntry:
    key: str
    owner: str
    description: str
    cross_refs: tuple[str, ...]
    proofs: tuple[str, ...]
    family: str | None
    kind: str | None
    parent: str | None
    authority: str | None


@dataclass(frozen=True)
class ManifestSource:
    system: str
    source_root: Path
    manifest_path: Path
    entry_key: str


def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required. Run with: uv run --with pyyaml ...")


def _file_part(ref: str) -> str:
    return ref.split("#", 1)[0]


def _as_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _display_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.relative_to(workspace_root).as_posix()
    except ValueError:
        return path.as_posix()


def _source_relative_path(path: Path, source_root: Path) -> str:
    try:
        return path.relative_to(source_root).as_posix()
    except ValueError:
        return path.as_posix()


def _display_ref(source_root: Path, ref: str, workspace_root: Path) -> str:
    try:
        prefix = source_root.relative_to(workspace_root).as_posix()
    except ValueError:
        prefix = ""
    if not prefix or prefix == ".":
        return ref
    return f"{prefix}/{ref}"


def _infer_family(entry: GovernanceEntry) -> str:
    if entry.family:
        return entry.family

    owner_file = _file_part(entry.owner)
    owner_path = Path(owner_file)
    parts = owner_path.parts
    if len(parts) >= 3 and parts[0] == "docs" and parts[1] == "ssot":
        stem = owner_path.stem
        for delimiter in (".", "-", "_"):
            if delimiter in stem:
                return stem.split(delimiter, 1)[0]
        return stem
    if len(parts) >= 2 and parts[0] == "docs":
        return parts[1]
    if "." in entry.key:
        return entry.key.split(".", 1)[0]
    if "_" in entry.key:
        return entry.key.split("_", 1)[0]
    return "unknown"


def _has_proof(entry: GovernanceEntry) -> bool:
    refs = entry.proofs + entry.cross_refs
    return any(any(marker in ref for marker in PROOF_MARKERS) for ref in refs)


def _is_machine_owned(entry: GovernanceEntry) -> bool:
    owner_file = _file_part(entry.owner).lower()
    return owner_file.endswith(MACHINE_OWNER_SUFFIXES) or (
        (entry.kind or "").lower() in MACHINE_KINDS
    )


def _is_high_risk(entry: GovernanceEntry) -> bool:
    haystack = " ".join((entry.key, entry.owner, entry.description)).lower()
    tokens = set(re.findall(r"[a-z0-9]+", haystack))
    return any(term in haystack for term in HIGH_RISK_SUBSTRINGS) or bool(
        HIGH_RISK_TOKENS & tokens
    )


def _field_coverage(entries: list[GovernanceEntry], field: str) -> dict[str, object]:
    missing = sorted(entry.key for entry in entries if not getattr(entry, field))
    return {
        "present": len(entries) - len(missing),
        "missing": len(missing),
        "missing_keys": missing,
    }


def _future_candidate(code: str, count: int, sample: object) -> dict[str, object]:
    return {"code": code, "count": count, "sample": sample}


def _load_manifest_entries(
    source: ManifestSource,
) -> tuple[list[GovernanceEntry], list[str]]:
    errors: list[str] = []
    if not source.manifest_path.exists():
        manifest = _source_relative_path(source.manifest_path, source.source_root)
        return [], [f"{source.system}: manifest not found: {manifest}"]

    _require_yaml()
    try:
        data = yaml.safe_load(source.manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - exact parser errors vary
        return [], [f"{source.system}: invalid YAML: {exc}"]

    if not isinstance(data, Mapping):
        return [], [f"{source.system}: manifest must be a YAML mapping"]

    raw_entries = data.get(source.entry_key)
    if not isinstance(raw_entries, Mapping):
        return [], [f"{source.system}: missing '{source.entry_key}' mapping"]

    entries: list[GovernanceEntry] = []
    for key, raw_entry in raw_entries.items():
        key_str = str(key)
        if not isinstance(raw_entry, Mapping):
            errors.append(f"{source.system}: entry '{key_str}' must be a YAML mapping")
            continue
        entries.append(
            GovernanceEntry(
                key=key_str,
                owner=str(raw_entry.get("owner") or ""),
                description=str(raw_entry.get("description") or ""),
                cross_refs=_as_strings(raw_entry.get("cross_refs")),
                proofs=_as_strings(raw_entry.get("proofs")),
                family=(str(raw_entry["family"]) if raw_entry.get("family") else None),
                kind=str(raw_entry["kind"]) if raw_entry.get("kind") else None,
                parent=(str(raw_entry["parent"]) if raw_entry.get("parent") else None),
                authority=(
                    str(raw_entry["authority"]) if raw_entry.get("authority") else None
                ),
            )
        )
    return entries, errors


def _orphan_ssot_files(
    source: ManifestSource,
    entries: list[GovernanceEntry],
    workspace_root: Path,
) -> list[str]:
    ssot_dir = source.source_root / "docs" / "ssot"
    if not ssot_dir.exists():
        return []

    owner_files = {_file_part(entry.owner) for entry in entries if entry.owner}
    orphan_files: list[str] = []
    for path in sorted(ssot_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name in SSOT_FILE_EXCLUDES or path.suffix not in SSOT_FILE_SUFFIXES:
            continue
        relative = path.relative_to(source.source_root).as_posix()
        if relative not in owner_files:
            orphan_files.append(
                _display_ref(source.source_root, relative, workspace_root)
            )
    return orphan_files


def build_source_report(
    source: ManifestSource,
    workspace_root: Path,
) -> dict[str, object]:
    """Build advisory governance metrics for one manifest."""

    entries, errors = _load_manifest_entries(source)
    owner_to_keys: dict[str, list[str]] = {}
    for entry in entries:
        if entry.owner:
            owner_to_keys.setdefault(entry.owner, []).append(entry.key)

    duplicate_owner_groups = [
        {"owner": owner, "keys": sorted(keys)}
        for owner, keys in sorted(owner_to_keys.items())
        if len(keys) > 1
    ]
    manifest_load_failed = bool(errors) and not entries
    orphan_ssot_files = (
        []
        if manifest_load_failed
        else _orphan_ssot_files(source, entries, workspace_root)
    )

    explicit_kind_distribution = Counter(entry.kind or "unknown" for entry in entries)
    inferred_family_distribution = Counter(_infer_family(entry) for entry in entries)

    machine_entries = [entry for entry in entries if _is_machine_owned(entry)]
    machine_missing_proof = sorted(
        entry.key for entry in machine_entries if not _has_proof(entry)
    )
    high_risk_entries = [entry for entry in entries if _is_high_risk(entry)]
    high_risk_missing_proof = sorted(
        entry.key for entry in high_risk_entries if not _has_proof(entry)
    )
    clause_missing_parent = sorted(
        entry.key
        for entry in entries
        if (entry.kind or "").lower() == "clause" and not entry.parent
    )

    future_gate_candidates = [
        _future_candidate(
            "duplicate_owner_groups",
            len(duplicate_owner_groups),
            duplicate_owner_groups[:5],
        ),
        _future_candidate(
            "orphan_ssot_files",
            len(orphan_ssot_files),
            orphan_ssot_files[:10],
        ),
        _future_candidate(
            "explicit_clauses_missing_parent",
            len(clause_missing_parent),
            clause_missing_parent[:10],
        ),
        _future_candidate(
            "machine_owner_entries_missing_proof",
            len(machine_missing_proof),
            machine_missing_proof[:10],
        ),
        _future_candidate(
            "high_risk_entries_missing_proof",
            len(high_risk_missing_proof),
            high_risk_missing_proof[:10],
        ),
    ]

    return {
        "system": source.system,
        "manifest": _display_path(source.manifest_path, workspace_root),
        "entry_key": source.entry_key,
        "entry_count": len(entries),
        "owner_count": len(owner_to_keys),
        "errors": errors,
        "duplicate_owner_groups": duplicate_owner_groups,
        "orphan_ssot_files": orphan_ssot_files,
        "field_coverage": {
            "family": _field_coverage(entries, "family"),
            "kind": _field_coverage(entries, "kind"),
            "parent": _field_coverage(entries, "parent"),
            "authority": _field_coverage(entries, "authority"),
        },
        "kind_distribution": dict(sorted(explicit_kind_distribution.items())),
        "inferred_family_distribution": dict(
            sorted(inferred_family_distribution.items())
        ),
        "machine_owner_entries": {
            "total": len(machine_entries),
            "with_proof": len(machine_entries) - len(machine_missing_proof),
            "missing_proof": machine_missing_proof,
        },
        "high_risk_entries": {
            "total": len(high_risk_entries),
            "with_proof": len(high_risk_entries) - len(high_risk_missing_proof),
            "missing_proof": high_risk_missing_proof,
        },
        "future_gate_candidates": future_gate_candidates,
    }


def build_report(repo_root: Path, include_infra2: bool = True) -> dict[str, object]:
    """Build the full report for finance_report and the checked-out infra2 repo."""

    repo_root = repo_root.resolve()
    sources = [
        ManifestSource(
            system="finance_report",
            source_root=repo_root,
            manifest_path=repo_root / "docs" / "ssot" / "MANIFEST.yaml",
            entry_key="concepts",
        )
    ]
    infra_manifest = repo_root / "repo" / "docs" / "ssot" / "MANIFEST.yaml"
    if include_infra2:
        sources.append(
            ManifestSource(
                system="infra2",
                source_root=repo_root / "repo",
                manifest_path=infra_manifest,
                entry_key="entries",
            )
        )

    source_reports = [build_source_report(source, repo_root) for source in sources]
    errors = [
        error for source_report in source_reports for error in source_report["errors"]
    ]
    return {
        "version": REPORT_VERSION,
        "report_only": True,
        "source_issue": SOURCE_ISSUE,
        "hls_issue": HLS_ISSUE,
        "sources": source_reports,
        "overall": {
            "system_count": len(source_reports),
            "entry_count": sum(
                int(source_report["entry_count"]) for source_report in source_reports
            ),
            "future_gate_candidate_count": sum(
                int(candidate["count"])
                for source_report in source_reports
                for candidate in source_report["future_gate_candidates"]
            ),
            "errors": errors,
        },
    }


def _join_sample(values: object, limit: int = 5) -> str:
    if not isinstance(values, list) or not values:
        return "-"
    rendered: list[str] = []
    for item in values[:limit]:
        if isinstance(item, Mapping):
            rendered.append(str(item.get("owner") or item))
        else:
            rendered.append(str(item))
    return ", ".join(rendered)


def render_markdown(report: Mapping[str, object]) -> str:
    """Render a concise Markdown report for CI step summary."""

    lines = [
        "# SSOT Governance Report",
        "",
        f"Report-only baseline for [{SOURCE_ISSUE.rsplit('/', 1)[-1]}]({SOURCE_ISSUE}); "
        f"HLS direction is tracked in [{HLS_ISSUE.rsplit('/', 1)[-1]}]({HLS_ISSUE}).",
        "This report does not fail CI. Existing manifest and ownership checks remain the hard gates.",
        "",
        "| System | Entries | Owners | Duplicate owners | Orphan SSOT files | Missing family | Missing kind | Machine missing proof | High-risk missing proof |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for source in report.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        field_coverage = source.get("field_coverage")
        machine = source.get("machine_owner_entries")
        high_risk = source.get("high_risk_entries")
        if not isinstance(field_coverage, Mapping):
            field_coverage = {}
        if not isinstance(machine, Mapping):
            machine = {}
        if not isinstance(high_risk, Mapping):
            high_risk = {}
        family = field_coverage.get("family", {})
        kind = field_coverage.get("kind", {})
        if not isinstance(family, Mapping):
            family = {}
        if not isinstance(kind, Mapping):
            kind = {}

        lines.append(
            "| {system} | {entries} | {owners} | {duplicates} | {orphans} | "
            "{missing_family} | {missing_kind} | {machine_missing} | {risk_missing} |".format(
                system=source.get("system", "unknown"),
                entries=source.get("entry_count", 0),
                owners=source.get("owner_count", 0),
                duplicates=len(source.get("duplicate_owner_groups", [])),
                orphans=len(source.get("orphan_ssot_files", [])),
                missing_family=family.get("missing", 0),
                missing_kind=kind.get("missing", 0),
                machine_missing=len(machine.get("missing_proof", [])),
                risk_missing=len(high_risk.get("missing_proof", [])),
            )
        )

    for source in report.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        lines.extend(
            [
                "",
                f"## {source.get('system', 'unknown')}",
                "",
                f"- Manifest: `{source.get('manifest', '-')}`",
                f"- Entry key: `{source.get('entry_key', '-')}`",
                f"- Kind distribution: `{source.get('kind_distribution', {})}`",
                f"- Inferred family distribution: `{source.get('inferred_family_distribution', {})}`",
            ]
        )

        errors = source.get("errors", [])
        if isinstance(errors, list) and errors:
            lines.append(f"- Report errors: `{errors}`")

        candidates = source.get("future_gate_candidates", [])
        if isinstance(candidates, list):
            lines.append("- Future gate candidates:")
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                lines.append(
                    "  - `{code}`: {count} (sample: {sample})".format(
                        code=candidate.get("code", "unknown"),
                        count=candidate.get("count", 0),
                        sample=_join_sample(candidate.get("sample")),
                    )
                )

    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate report-only SSOT governance metrics."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--no-infra2",
        action="store_true",
        help="Only report the finance_report manifest.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path for machine-readable JSON output.",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        help="Optional path for Markdown output.",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero only when the report itself cannot parse a manifest.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args.repo_root, include_infra2=not args.no_infra2)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rendered = render_markdown(report)
    print(rendered, end="")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(rendered, encoding="utf-8")

    if args.fail_on_error and report["overall"]["errors"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
