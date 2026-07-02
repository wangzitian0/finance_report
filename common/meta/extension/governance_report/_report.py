"""Report building."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CLI guard
    yaml = None


from common.meta.extension.governance_report._base import (
    GATE_ISSUE,
    HIGH_RISK_SUBSTRINGS,
    HIGH_RISK_TOKENS,
    HLS_ISSUE,
    REPORT_VERSION,
    SOURCE_ISSUE,
)
from common.meta.extension.governance_report._manifest import (
    _load_manifest_entries,
    _orphan_ssot_files,
)
from common.meta.extension.governance_report._metrics import _field_coverage, _future_candidate
from common.meta.extension.governance_report._types import ManifestSource
from common.meta.extension.governance_report._util import (
    _display_path,
    _has_proof,
    _infer_family,
    _is_high_risk,
    _is_machine_owned,
)


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


def _contains_high_risk_terms(*values: str) -> bool:
    haystack = " ".join(values).lower()
    tokens = set(re.findall(r"[a-z0-9]+", haystack))
    return any(term in haystack for term in HIGH_RISK_SUBSTRINGS) or bool(
        HIGH_RISK_TOKENS & tokens
    )
