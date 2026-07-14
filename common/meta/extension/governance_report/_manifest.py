"""Manifest entry loading + orphan detection."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CLI guard
    yaml = None


from common.meta.extension.governance_report._base import (
    SSOT_FILE_EXCLUDES,
    SSOT_FILE_SUFFIXES,
    SSOT_TERRITORY_ROOTS,
    _require_yaml,
    yaml,
)
from common.meta.extension.governance_report._types import (
    GovernanceEntry,
    ManifestSource,
)
from common.meta.extension.governance_report._util import (
    _as_strings,
    _display_ref,
    _file_part,
    _source_relative_path,
)


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
    """Files under this source's SSOT territory that no manifest entry owns.

    Scans every :data:`SSOT_TERRITORY_ROOTS` root under the source (``docs/ssot``
    — the legacy convention, still live for infra2 — plus ``common/meta/data``,
    where finance_report's own concept registry relocated in #1823). A root
    that does not exist under this source (e.g. infra2 has no
    ``common/meta/data``) is skipped, not an error.
    """
    owner_files = {_file_part(entry.owner) for entry in entries if entry.owner}
    orphan_files: list[str] = []
    for root_parts in SSOT_TERRITORY_ROOTS:
        territory_dir = source.source_root.joinpath(*root_parts)
        if not territory_dir.exists():
            continue
        for path in sorted(territory_dir.iterdir()):
            if not path.is_file():
                continue
            if path.name in SSOT_FILE_EXCLUDES or path.suffix not in SSOT_FILE_SUFFIXES:
                continue
            relative = path.relative_to(source.source_root).as_posix()
            if relative not in owner_files:
                orphan_files.append(
                    _display_ref(source.source_root, relative, workspace_root)
                )
    return sorted(set(orphan_files))
