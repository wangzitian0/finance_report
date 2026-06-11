"""SSOT governance metrics and incremental gates.

The baseline report remains advisory. The optional #823 gate fails on changed
SSOT debt and protected base/head governance regressions so legacy debt can be
governed incrementally without allowing the quality watermark to fall.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
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
GATE_ISSUE = "https://github.com/wangzitian0/finance_report/issues/823"
GATE_EXCEPTION_PATH = Path("docs/ssot/governance-exceptions.yaml")
GATE_HLS_RULE = (
    "HLS governance loop: promote only incremental and high-risk findings into "
    "CI gates after the report baseline is visible."
)

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
RATIO_EPSILON = 1e-9
PROTECTED_RATIO_LABELS = {
    "manifest_family_coverage": "Manifest family coverage",
    "manifest_kind_coverage": "Manifest kind coverage",
    "machine_proof_coverage": "Machine-owned proof coverage",
    "high_risk_proof_coverage": "High-risk proof coverage",
}
PROTECTED_DEBT_LABELS = {
    "missing_family": "Manifest entries missing family",
    "missing_kind": "Manifest entries missing kind",
    "machine_owner_entries_missing_proof": "Machine-owned entries missing proof",
    "high_risk_entries_missing_proof": "High-risk entries missing proof",
}


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


@dataclass(frozen=True)
class GateViolation:
    code: str
    system: str
    target: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "system": self.system,
            "target": self.target,
            "message": self.message,
            "issue": GATE_ISSUE,
            "hls_rule": GATE_HLS_RULE,
        }


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


def _coverage_ratio(present: int, total: int) -> float:
    return 1.0 if total == 0 else present / total


def _quality_ratio(present: int, total: int) -> dict[str, float | int]:
    return {
        "present": present,
        "total": total,
        "ratio": _coverage_ratio(present, total),
    }


def _governance_quality_snapshot(
    entries: list[GovernanceEntry],
) -> dict[str, dict[str, dict[str, float | int]] | dict[str, int]]:
    machine_entries = [entry for entry in entries if _is_machine_owned(entry)]
    high_risk_entries = [entry for entry in entries if _is_high_risk(entry)]
    missing_family = [entry for entry in entries if not entry.family]
    missing_kind = [entry for entry in entries if not entry.kind]
    machine_missing_proof = [
        entry for entry in machine_entries if not _has_proof(entry)
    ]
    high_risk_missing_proof = [
        entry for entry in high_risk_entries if not _has_proof(entry)
    ]

    return {
        "ratios": {
            "manifest_family_coverage": _quality_ratio(
                len(entries) - len(missing_family),
                len(entries),
            ),
            "manifest_kind_coverage": _quality_ratio(
                len(entries) - len(missing_kind),
                len(entries),
            ),
            "machine_proof_coverage": _quality_ratio(
                len(machine_entries) - len(machine_missing_proof),
                len(machine_entries),
            ),
            "high_risk_proof_coverage": _quality_ratio(
                len(high_risk_entries) - len(high_risk_missing_proof),
                len(high_risk_entries),
            ),
        },
        "debts": {
            "missing_family": len(missing_family),
            "missing_kind": len(missing_kind),
            "machine_owner_entries_missing_proof": len(machine_missing_proof),
            "high_risk_entries_missing_proof": len(high_risk_missing_proof),
        },
    }


def _compare_governance_trends(
    system: str,
    base_entries: list[GovernanceEntry],
    current_entries: list[GovernanceEntry],
) -> tuple[int, list[GateViolation]]:
    """Compare protected #823 quality ratios and debt counts for one system."""

    base_snapshot = _governance_quality_snapshot(base_entries)
    current_snapshot = _governance_quality_snapshot(current_entries)
    base_ratios = base_snapshot["ratios"]
    current_ratios = current_snapshot["ratios"]
    base_debts = base_snapshot["debts"]
    current_debts = current_snapshot["debts"]
    violations: list[GateViolation] = []
    check_count = 0

    for metric, label in PROTECTED_RATIO_LABELS.items():
        check_count += 1
        base_metric = base_ratios[metric]
        current_metric = current_ratios[metric]
        base_ratio = float(base_metric["ratio"])
        current_ratio = float(current_metric["ratio"])
        if current_ratio + RATIO_EPSILON >= base_ratio:
            continue
        violations.append(
            GateViolation(
                code="governance_ratio_decreased",
                system=system,
                target=_gate_target(system, f"ratio:{metric}"),
                message=(
                    f"{label} decreased ({base_ratio:.4f} -> {current_ratio:.4f}). "
                    "#823 requires protected SSOT governance ratios to be "
                    "non-decreasing."
                ),
            )
        )

    for metric, label in PROTECTED_DEBT_LABELS.items():
        check_count += 1
        base_count = int(base_debts[metric])
        current_count = int(current_debts[metric])
        if current_count <= base_count:
            continue
        violations.append(
            GateViolation(
                code="governance_debt_increased",
                system=system,
                target=_gate_target(system, f"debt:{metric}"),
                message=(
                    f"{label} increased ({base_count} -> {current_count}). "
                    "#823 requires protected SSOT debt counts to be "
                    "non-increasing."
                ),
            )
        )

    return check_count, violations


def _future_candidate(code: str, count: int, sample: object) -> dict[str, object]:
    return {"code": code, "count": count, "sample": sample}


def _entries_from_manifest_data(
    source: ManifestSource,
    data: object,
) -> tuple[list[GovernanceEntry], list[str]]:
    if not isinstance(data, Mapping):
        return [], [f"{source.system}: manifest must be a YAML mapping"]

    raw_entries = data.get(source.entry_key)
    if not isinstance(raw_entries, Mapping):
        return [], [f"{source.system}: missing '{source.entry_key}' mapping"]

    entries: list[GovernanceEntry] = []
    errors: list[str] = []
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


def _load_manifest_entries_from_text(
    source: ManifestSource,
    text: str,
) -> tuple[list[GovernanceEntry], list[str]]:
    _require_yaml()
    try:
        data = yaml.safe_load(text) or {}
    except Exception as exc:  # pragma: no cover - exact parser errors vary
        return [], [f"{source.system}: invalid YAML: {exc}"]
    return _entries_from_manifest_data(source, data)


def _load_manifest_entries(
    source: ManifestSource,
) -> tuple[list[GovernanceEntry], list[str]]:
    if not source.manifest_path.exists():
        manifest = _source_relative_path(source.manifest_path, source.source_root)
        return [], [f"{source.system}: manifest not found: {manifest}"]

    return _load_manifest_entries_from_text(
        source,
        source.manifest_path.read_text(encoding="utf-8"),
    )


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
    sources = _manifest_sources(repo_root, include_infra2=include_infra2)

    source_reports = [build_source_report(source, repo_root) for source in sources]
    errors = [
        error for source_report in source_reports for error in source_report["errors"]
    ]
    return {
        "version": REPORT_VERSION,
        "report_only": True,
        "source_issue": SOURCE_ISSUE,
        "hls_issue": HLS_ISSUE,
        "gate_issue": GATE_ISSUE,
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


def _manifest_sources(
    repo_root: Path, include_infra2: bool = True
) -> list[ManifestSource]:
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
    return sources


def _gate_target(system: str, target: str) -> str:
    return f"{system}:{target}"


def _manifest_entry_target(system: str, key: str) -> str:
    return _gate_target(system, f"manifest:{key}")


def _contains_high_risk_terms(*values: str) -> bool:
    haystack = " ".join(values).lower()
    tokens = set(re.findall(r"[a-z0-9]+", haystack))
    return any(term in haystack for term in HIGH_RISK_SUBSTRINGS) or bool(
        HIGH_RISK_TOKENS & tokens
    )


def _source_changed_files(
    source: ManifestSource,
    repo_root: Path,
    changed_files: list[str],
) -> list[str]:
    try:
        source_prefix = source.source_root.relative_to(repo_root).as_posix()
    except ValueError:
        source_prefix = "."

    if source_prefix in ("", "."):
        return [path for path in changed_files if path and not path.startswith("repo/")]

    prefix = f"{source_prefix}/"
    return [
        path.removeprefix(prefix)
        for path in changed_files
        if path == source_prefix or path.startswith(prefix)
    ]


def _changed_ssot_files(source_changed_files: list[str]) -> list[str]:
    files: list[str] = []
    for path in source_changed_files:
        rel = Path(path)
        if len(rel.parts) < 3 or rel.parts[0] != "docs" or rel.parts[1] != "ssot":
            continue
        if rel.name in SSOT_FILE_EXCLUDES or rel.suffix not in SSOT_FILE_SUFFIXES:
            continue
        files.append(rel.as_posix())
    return sorted(set(files))


def _source_has_ssot_change(source_changed_files: list[str]) -> bool:
    return any(
        path == "docs/ssot" or path.startswith("docs/ssot/")
        for path in source_changed_files
    )


def _load_changed_files(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [
        line.strip().removeprefix("./")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _source_manifest_repo_path(source: ManifestSource, repo_root: Path) -> str:
    try:
        return source.manifest_path.relative_to(repo_root).as_posix()
    except ValueError:
        return source.manifest_path.as_posix()


def _read_base_manifest_text(
    repo_root: Path,
    source: ManifestSource,
    base_ref: str | None,
) -> str | None:
    if not base_ref:
        return None
    manifest_path = _source_manifest_repo_path(source, repo_root)
    result = subprocess.run(
        ["git", "-C", repo_root.as_posix(), "show", f"{base_ref}:{manifest_path}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        try:
            submodule_path = source.source_root.relative_to(repo_root).as_posix()
            manifest_in_submodule = source.manifest_path.relative_to(
                source.source_root
            ).as_posix()
        except ValueError:
            return None

        submodule_result = subprocess.run(
            ["git", "-C", repo_root.as_posix(), "ls-tree", base_ref, submodule_path],
            check=False,
            capture_output=True,
            text=True,
        )
        if submodule_result.returncode != 0:
            return None
        parts = submodule_result.stdout.split()
        if len(parts) < 3 or parts[1] != "commit":
            return None
        submodule_sha = parts[2]
        result = subprocess.run(
            [
                "git",
                "-C",
                source.source_root.as_posix(),
                "show",
                f"{submodule_sha}:{manifest_in_submodule}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
    return result.stdout


def _resolve_repo_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _exception_path_for_report(repo_root: Path, exceptions_path: Path | None) -> str:
    configured_path = exceptions_path or GATE_EXCEPTION_PATH
    return _display_path(_resolve_repo_path(repo_root, configured_path), repo_root)


def _load_exception_targets(repo_root: Path, exceptions_path: Path | None) -> set[str]:
    path = _resolve_repo_path(repo_root, exceptions_path or GATE_EXCEPTION_PATH)
    if not path.exists():
        return set()

    _require_yaml()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - exact parser errors vary
        display_path = _display_path(path, repo_root)
        raise RuntimeError(
            f"Invalid SSOT governance exceptions YAML in {display_path}: {exc}"
        ) from exc
    if not isinstance(data, Mapping):
        return set()
    raw_exceptions = data.get("exceptions", [])
    if not isinstance(raw_exceptions, list):
        return set()

    targets: set[str] = set()
    for item in raw_exceptions:
        if not isinstance(item, Mapping):
            continue
        target = item.get("target")
        issue = item.get("issue")
        if not isinstance(target, str) or not isinstance(issue, str):
            continue
        if "/issues/" not in issue:
            continue
        targets.add(target)
    return targets


def _entry_by_key(entries: list[GovernanceEntry]) -> dict[str, GovernanceEntry]:
    return {entry.key: entry for entry in entries}


def evaluate_incremental_gate(
    repo_root: Path,
    changed_files: list[str],
    *,
    base_ref: str | None = None,
    base_manifest_texts: Mapping[str, str] | None = None,
    include_infra2: bool = True,
    exceptions_path: Path | None = None,
) -> dict[str, object]:
    """Evaluate #823 prevent-worse SSOT governance gates.

    Only files or manifest entries touched by the current change are gated.
    Historical report findings remain advisory until a later cleanup issue
    explicitly selects a threshold.
    """

    repo_root = repo_root.resolve()
    normalized_changed_files = [
        path.strip().removeprefix("./") for path in changed_files if path.strip()
    ]
    exceptions = _load_exception_targets(repo_root, exceptions_path)
    used_exceptions: set[str] = set()
    violations: list[GateViolation] = []
    trend_check_count = 0

    def add_violation(violation: GateViolation) -> None:
        if violation.target in exceptions:
            used_exceptions.add(violation.target)
            return
        violations.append(violation)

    for source in _manifest_sources(repo_root, include_infra2=include_infra2):
        current_entries, current_errors = _load_manifest_entries(source)
        current_by_key = _entry_by_key(current_entries)
        owner_files = {_file_part(entry.owner) for entry in current_entries}
        source_changed = _source_changed_files(
            source, repo_root, normalized_changed_files
        )
        base_entries: list[GovernanceEntry] | None = None
        if _source_has_ssot_change(source_changed):
            base_text = (
                base_manifest_texts.get(source.system)
                if base_manifest_texts and source.system in base_manifest_texts
                else _read_base_manifest_text(repo_root, source, base_ref)
            )
            if base_text is not None:
                base_entries, base_errors = _load_manifest_entries_from_text(
                    source, base_text
                )
                if not current_errors and not base_errors:
                    (
                        source_trend_checks,
                        source_trend_violations,
                    ) = _compare_governance_trends(
                        source.system,
                        base_entries,
                        current_entries,
                    )
                    trend_check_count += source_trend_checks
                    for violation in source_trend_violations:
                        add_violation(violation)

        for ssot_file in _changed_ssot_files(source_changed):
            target = _gate_target(source.system, ssot_file)
            owner_entries = [
                entry
                for entry in current_entries
                if _file_part(entry.owner) == ssot_file
            ]
            if ssot_file not in owner_files:
                add_violation(
                    GateViolation(
                        code="changed_ssot_file_without_owner",
                        system=source.system,
                        target=target,
                        message=(
                            f"{ssot_file} changed but is not owned by "
                            f"{source.entry_key} in {source.manifest_path.name}. "
                            "Register it or add a temporary exception."
                        ),
                    )
                )
                continue

            if not (
                _contains_high_risk_terms(ssot_file)
                or any(_is_high_risk(entry) for entry in owner_entries)
            ):
                continue
            if not any(_has_proof(entry) for entry in owner_entries):
                add_violation(
                    GateViolation(
                        code="changed_high_risk_ssot_file_missing_proof",
                        system=source.system,
                        target=target,
                        message=(
                            f"{ssot_file} changed in a high-risk SSOT area but "
                            "its owner entry has no proof path."
                        ),
                    )
                )

        manifest_relative = source.manifest_path.relative_to(
            source.source_root
        ).as_posix()
        if manifest_relative not in source_changed:
            continue
        if base_entries is None:
            continue
        base_by_key = _entry_by_key(base_entries)

        added_entry_keys = sorted(set(current_by_key) - set(base_by_key))
        changed_entry_keys = sorted(
            key
            for key, entry in current_by_key.items()
            if key not in base_by_key or entry != base_by_key[key]
        )

        for key in added_entry_keys:
            entry = current_by_key[key]
            target = _manifest_entry_target(source.system, key)
            if not entry.family:
                add_violation(
                    GateViolation(
                        code="new_manifest_entry_missing_family",
                        system=source.system,
                        target=target,
                        message=(
                            f"New manifest entry '{key}' has no family. "
                            "Add family before introducing new scoreable SSOT."
                        ),
                    )
                )
            if (entry.kind or "").lower() == "clause" and not entry.parent:
                add_violation(
                    GateViolation(
                        code="new_clause_missing_parent",
                        system=source.system,
                        target=target,
                        message=(
                            f"New clause entry '{key}' has no parent concept. "
                            "Bind clauses to their parent SSOT concept."
                        ),
                    )
                )

        for key in changed_entry_keys:
            entry = current_by_key[key]
            target = _manifest_entry_target(source.system, key)
            if not (_is_high_risk(entry) or _is_machine_owned(entry)):
                continue
            if _has_proof(entry):
                continue
            add_violation(
                GateViolation(
                    code="changed_high_risk_entry_missing_proof",
                    system=source.system,
                    target=target,
                    message=(
                        f"Changed high-risk or machine-owned entry '{key}' "
                        "has no proof path in proofs/cross_refs."
                    ),
                )
            )

    return {
        "enabled": bool(normalized_changed_files),
        "issue": GATE_ISSUE,
        "hls_rule": GATE_HLS_RULE,
        "exception_path": _exception_path_for_report(repo_root, exceptions_path),
        "changed_file_count": len(normalized_changed_files),
        "trend_check_count": trend_check_count,
        "exception_count": len(used_exceptions),
        "violation_count": len(violations),
        "violations": [violation.as_dict() for violation in violations],
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
        "Baseline metrics are advisory. The optional Incremental Gate section can fail CI for changed-surface violations or protected governance regressions.",
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

    gate = report.get("gate")
    if isinstance(gate, Mapping):
        violations = gate.get("violations", [])
        if not isinstance(violations, list):
            violations = []
        lines.extend(
            [
                "",
                "## Incremental Gate",
                "",
                f"- Issue: [{GATE_ISSUE.rsplit('/', 1)[-1]}]({GATE_ISSUE})",
                f"- HLS rule: {gate.get('hls_rule', GATE_HLS_RULE)}",
                f"- Changed files: {gate.get('changed_file_count', 0)}",
                f"- Trend checks: {gate.get('trend_check_count', 0)}",
                f"- Exception registry: `{gate.get('exception_path', GATE_EXCEPTION_PATH.as_posix())}`",
                f"- Exceptions used: {gate.get('exception_count', 0)}",
                f"- Result: {'PASS' if not violations else 'FAIL'}",
            ]
        )
        if violations:
            lines.append("- Violations:")
            for violation in violations[:20]:
                if not isinstance(violation, Mapping):
                    continue
                lines.append(
                    "  - `{code}` `{target}`: {message}".format(
                        code=violation.get("code", "unknown"),
                        target=violation.get("target", "unknown"),
                        message=violation.get("message", ""),
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
        description="Generate SSOT governance metrics and optional incremental gates."
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
    parser.add_argument(
        "--changed-files",
        type=Path,
        help="Optional newline-delimited changed-files list for #823 incremental gates.",
    )
    parser.add_argument(
        "--base-ref",
        help="Optional base git ref used to compare changed manifest entries.",
    )
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit non-zero when #823 incremental gate violations are found.",
    )
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=GATE_EXCEPTION_PATH,
        help="Path to SSOT governance gate exceptions, relative to repo root.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args.repo_root, include_infra2=not args.no_infra2)
        changed_files = _load_changed_files(args.changed_files)
        if changed_files:
            report["gate"] = evaluate_incremental_gate(
                args.repo_root,
                changed_files,
                base_ref=args.base_ref,
                include_infra2=not args.no_infra2,
                exceptions_path=args.exceptions,
            )
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
    gate = report.get("gate")
    if (
        args.fail_on_gate
        and isinstance(gate, Mapping)
        and int(gate.get("violation_count", 0)) > 0
    ):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
