"""Incremental governance gate."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CLI guard
    yaml = None


from common.meta.extension.governance_report._base import (
    GATE_EXCEPTION_PATH,
    GATE_HLS_RULE,
    GATE_ISSUE,
    SSOT_FILE_EXCLUDES,
    SSOT_FILE_SUFFIXES,
    _require_yaml,
    in_ssot_territory,
    yaml,
)
from common.meta.extension.governance_report._manifest import (
    _load_manifest_entries,
    _load_manifest_entries_from_text,
)
from common.meta.extension.governance_report._metrics import _compare_governance_trends
from common.meta.extension.governance_report._report import (
    _contains_high_risk_terms,
    _manifest_sources,
)
from common.meta.extension.governance_report._types import (
    GateViolation,
    GovernanceEntry,
    ManifestSource,
)
from common.meta.extension.governance_report._util import (
    _display_path,
    _file_part,
    _gate_target,
    _has_proof,
    _is_high_risk,
    _is_machine_owned,
    _manifest_entry_target,
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
        return [path for path in changed_files if path]

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
        if len(rel.parts) < 3 or not in_ssot_territory(rel):
            continue
        if rel.name in SSOT_FILE_EXCLUDES or rel.suffix not in SSOT_FILE_SUFFIXES:
            continue
        files.append(rel.as_posix())
    return sorted(set(files))


def _source_has_ssot_change(source_changed_files: list[str]) -> bool:
    return any(in_ssot_territory(Path(path)) for path in source_changed_files)


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
