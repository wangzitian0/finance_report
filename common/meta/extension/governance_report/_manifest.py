"""Manifest entry loading + orphan detection."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
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
    # finance_report's concept registry is now the computed union of the
    # residual MANIFEST.yaml and every package's own declared `concepts`
    # (#1799) — same source `check_manifest.py` validates. infra2 (and any
    # synthetic test fixture) keeps reading its manifest file as plain YAML;
    # only the real finance_report system, at its real source_root, has
    # package contracts to discover.
    if _uses_computed_concepts(source):
        # check_manifest.py does its own independent `import yaml` (needed
        # regardless of this branch), so route through the same
        # _require_yaml() gate the plain-YAML path below uses — otherwise a
        # simulated "PyYAML missing" run would silently succeed here instead
        # of failing the same way for both branches.
        _require_yaml()
        from common.meta.extension.check_manifest import load_computed_concepts

        computed = load_computed_concepts(source.source_root, source.manifest_path)
        return _entries_from_manifest_data(source, {source.entry_key: computed})

    if not source.manifest_path.exists():
        manifest = _source_relative_path(source.manifest_path, source.source_root)
        return [], [f"{source.system}: manifest not found: {manifest}"]

    return _load_manifest_entries_from_text(
        source,
        source.manifest_path.read_text(encoding="utf-8"),
    )


def _uses_computed_concepts(source: ManifestSource) -> bool:
    return (
        source.system == "finance_report" and (source.source_root / "common").exists()
    )


def _load_computed_manifest_entries_at_ref(
    source: ManifestSource,
    repo_root: Path,
    base_ref: str,
) -> tuple[list[GovernanceEntry], list[str]]:
    """Load a git ref's computed registry with that ref's own package code."""

    runner = """
import json
import sys
from pathlib import Path

repo_root = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(repo_root), str(repo_root / "apps" / "backend")]

from common.meta.extension.check_manifest import load_computed_concepts

manifest_path = repo_root / sys.argv[2]
concepts = load_computed_concepts(repo_root, manifest_path)
Path(sys.argv[3]).write_text(json.dumps(concepts), encoding="utf-8")
"""
    manifest_relative = source.manifest_path.relative_to(source.source_root)
    with tempfile.TemporaryDirectory(prefix="governance-base-") as temp_dir:
        snapshot_root = Path(temp_dir) / "snapshot"
        archive_path = Path(temp_dir) / "snapshot.tar"
        snapshot_root.mkdir()
        archive = subprocess.run(
            [
                "git",
                "-C",
                repo_root.as_posix(),
                "archive",
                "--format=tar",
                f"--output={archive_path}",
                base_ref,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if archive.returncode != 0:
            detail = archive.stderr.strip() or "git archive failed"
            raise RuntimeError(
                f"Unable to load computed concept registry at {base_ref!r}: {detail}"
            )

        try:
            with tarfile.open(archive_path) as archive_file:
                archive_file.extractall(snapshot_root, filter="data")
        except (OSError, tarfile.TarError) as exc:
            raise RuntimeError(
                f"Unable to extract computed concept registry at {base_ref!r}: {exc}"
            ) from exc

        output_path = Path(temp_dir) / "concepts.json"
        load = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                runner,
                snapshot_root.as_posix(),
                manifest_relative.as_posix(),
                output_path.as_posix(),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if load.returncode != 0 or not output_path.exists():
            detail = load.stderr.strip() or load.stdout.strip() or "loader failed"
            raise RuntimeError(
                f"Unable to load computed concept registry at {base_ref!r}: {detail}"
            )
        try:
            concepts = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Invalid computed concept registry at {base_ref!r}: {exc}"
            ) from exc

    return _entries_from_manifest_data(source, {source.entry_key: concepts})


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
