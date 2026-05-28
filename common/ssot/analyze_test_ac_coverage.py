#!/usr/bin/env python3
"""Analyze AC-to-test coverage across backend, frontend, scripts, and E2E suites.

This analyzer scans AC references (``ACx.y.z``) in:
- ``apps/backend/tests/**/*.py``
- ``apps/frontend/src/**/*.test.ts(x)``
- ``scripts/tests/**/*.py``
- ``tests/e2e/**/*.py``

Coverage accounting follows EPIC-008 rules:
- Only references from real (non-``_ac_stubs`` and non-placeholder) tests count
  as passing-test candidates.
- ``_ac_stubs``, trivial assertions, pure ``pass``, and pure skipped tests are
  excluded from covered counts.
- Deprecated strikethrough ACs are excluded from coverage/untested counts.
- Invalid/unregistered AC references are reported with file paths.
- Registered ACs missing real references are reported as untested.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from common.ssot.ac_registry_format import load_registry_entries
from common.ssot.ac_traceability_refs import AC_PATTERN, classify_reference_file

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATHS = (
    REPO_ROOT / "docs" / "ac_registry.yaml",
    REPO_ROOT / "docs" / "infra_registry.yaml",
)
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "analysis" / "test-ac-coverage-report.md"

SCAN_TARGETS: tuple[tuple[str, Path, tuple[str, ...]], ...] = (
    ("backend", REPO_ROOT / "apps" / "backend" / "tests", ("**/*.py",)),
    (
        "frontend",
        REPO_ROOT / "apps" / "frontend" / "src",
        ("**/*.test.ts", "**/*.test.tsx"),
    ),
    ("scripts_tests", REPO_ROOT / "scripts" / "tests", ("**/*.py",)),
    ("e2e", REPO_ROOT / "tests" / "e2e", ("**/*.py",)),
)


@dataclass(frozen=True)
class ACRecord:
    id: str
    epic: int
    epic_name: str
    description: str
    deprecated: bool = False


@dataclass
class ACReferenceStats:
    real_files: set[str] = field(default_factory=set)
    placeholder_files: set[str] = field(default_factory=set)
    stub_files: set[str] = field(default_factory=set)
    real_sources: set[str] = field(default_factory=set)
    placeholder_sources: set[str] = field(default_factory=set)
    stub_sources: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ScanFile:
    source: str
    path: Path


@dataclass
class AnalysisResult:
    registry: dict[str, ACRecord]
    references: dict[str, ACReferenceStats]
    source_file_counts: dict[str, int]
    source_real_ref_counts: dict[str, int]
    source_placeholder_ref_counts: dict[str, int]
    source_stub_ref_counts: dict[str, int]
    covered_ids: set[str]
    placeholder_only_ids: set[str]
    stub_only_ids: set[str]
    untested_ids: list[str]
    invalid_real_refs: dict[str, list[str]]
    invalid_placeholder_refs: dict[str, list[str]]
    invalid_stub_refs: dict[str, list[str]]
    deprecated_ids: set[str]


@dataclass
class EpicStats:
    epic: int
    epic_name: str
    registered: int = 0
    covered: int = 0
    placeholder_only: int = 0
    stub_only: int = 0
    untested: int = 0
    deprecated: int = 0


def _ac_sort_key(ac_id: str) -> tuple[int, ...]:
    parts = [int(value) for value in re.findall(r"\d+", ac_id)]
    return tuple(parts) if parts else (999_999,)


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _is_deprecated_description(description: str) -> bool:
    stripped = description.strip()
    return stripped.startswith("~~") and stripped.endswith("~~") and len(stripped) > 4


def _is_ignored_script_fixture_invalid_ref(rel_path: str) -> bool:
    path = Path(rel_path)
    return (
        len(path.parts) >= 2 and path.parts[0] == "scripts" and path.parts[1] == "tests"
    )


def _invalid_files(paths: set[str]) -> list[str]:
    return sorted(
        path for path in paths if not _is_ignored_script_fixture_invalid_ref(path)
    )


def load_registry(
    registry_paths: tuple[Path, ...] = DEFAULT_REGISTRY_PATHS,
) -> dict[str, ACRecord]:
    registry: dict[str, ACRecord] = {}
    for registry_path in registry_paths:
        if not registry_path.exists():
            continue

        for ac in load_registry_entries(registry_path):
            ac_id = str(ac["id"])
            if ac_id in registry:
                continue
            description = str(ac.get("description", "")).strip()
            registry[ac_id] = ACRecord(
                id=ac_id,
                epic=int(ac["epic"]),
                epic_name=str(ac.get("epic_name", "")).strip()
                or f"EPIC-{int(ac['epic']):03d}",
                description=description,
                deprecated=_is_deprecated_description(description),
            )
    return registry


def discover_test_files(
    repo_root: Path = REPO_ROOT,
) -> tuple[list[ScanFile], dict[str, int]]:
    scan_files: list[ScanFile] = []
    source_file_counts: dict[str, int] = {}

    for source, _default_base, patterns in SCAN_TARGETS:
        base = repo_root / _relative(_default_base, REPO_ROOT)
        if not base.exists():
            source_file_counts[source] = 0
            continue

        source_paths: set[Path] = set()
        for pattern in patterns:
            source_paths.update(path for path in base.glob(pattern) if path.is_file())

        ordered_paths = sorted(source_paths)
        source_file_counts[source] = len(ordered_paths)
        scan_files.extend(ScanFile(source=source, path=path) for path in ordered_paths)

    return scan_files, source_file_counts


def collect_references(
    scan_files: list[ScanFile],
    repo_root: Path = REPO_ROOT,
) -> tuple[
    dict[str, ACReferenceStats],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    references: dict[str, ACReferenceStats] = defaultdict(ACReferenceStats)
    source_real_refs: dict[str, set[str]] = defaultdict(set)
    source_placeholder_refs: dict[str, set[str]] = defaultdict(set)
    source_stub_refs: dict[str, set[str]] = defaultdict(set)

    for scan_file in scan_files:
        try:
            content = scan_file.path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        kind = classify_reference_file(scan_file.path, content)
        rel_path = _relative(scan_file.path, repo_root)

        for match in AC_PATTERN.finditer(content):
            ac_id = match.group(0)
            ref_stats = references[ac_id]
            if kind == "stub":
                ref_stats.stub_files.add(rel_path)
                ref_stats.stub_sources.add(scan_file.source)
                source_stub_refs[scan_file.source].add(ac_id)
            elif kind == "placeholder":
                ref_stats.placeholder_files.add(rel_path)
                ref_stats.placeholder_sources.add(scan_file.source)
                source_placeholder_refs[scan_file.source].add(ac_id)
            else:
                ref_stats.real_files.add(rel_path)
                ref_stats.real_sources.add(scan_file.source)
                source_real_refs[scan_file.source].add(ac_id)

    return references, source_real_refs, source_placeholder_refs, source_stub_refs


def analyze_repo(repo_root: Path = REPO_ROOT) -> AnalysisResult:
    registry = load_registry(
        registry_paths=(
            repo_root / "docs" / "ac_registry.yaml",
            repo_root / "docs" / "infra_registry.yaml",
        )
    )
    scan_files, source_file_counts = discover_test_files(repo_root)
    references, source_real_refs, source_placeholder_refs, source_stub_refs = (
        collect_references(scan_files, repo_root)
    )
    active_registry_ids = {ac_id for ac_id, ac in registry.items() if not ac.deprecated}
    deprecated_ids = {ac_id for ac_id, ac in registry.items() if ac.deprecated}

    covered_ids = {
        ac_id
        for ac_id, ref_stats in references.items()
        if ac_id in active_registry_ids and ref_stats.real_files
    }
    stub_only_ids = {
        ac_id
        for ac_id, ref_stats in references.items()
        if ac_id in active_registry_ids
        and not ref_stats.real_files
        and not ref_stats.placeholder_files
        and ref_stats.stub_files
    }
    placeholder_only_ids = {
        ac_id
        for ac_id, ref_stats in references.items()
        if ac_id in active_registry_ids
        and not ref_stats.real_files
        and ref_stats.placeholder_files
    }

    untested_ids = sorted(
        (ac_id for ac_id in active_registry_ids if ac_id not in covered_ids),
        key=_ac_sort_key,
    )

    invalid_real_refs = {
        ac_id: files
        for ac_id, ref_stats in references.items()
        if ac_id not in registry and (files := _invalid_files(ref_stats.real_files))
    }
    invalid_stub_refs = {
        ac_id: files
        for ac_id, ref_stats in references.items()
        if ac_id not in registry and (files := _invalid_files(ref_stats.stub_files))
    }
    invalid_placeholder_refs = {
        ac_id: files
        for ac_id, ref_stats in references.items()
        if ac_id not in registry
        and (files := _invalid_files(ref_stats.placeholder_files))
    }

    source_real_ref_counts = {
        source: len(source_real_refs.get(source, set())) for source, *_ in SCAN_TARGETS
    }
    source_placeholder_ref_counts = {
        source: len(source_placeholder_refs.get(source, set()))
        for source, *_ in SCAN_TARGETS
    }
    source_stub_ref_counts = {
        source: len(source_stub_refs.get(source, set())) for source, *_ in SCAN_TARGETS
    }

    return AnalysisResult(
        registry=registry,
        references=dict(references),
        source_file_counts=source_file_counts,
        source_real_ref_counts=source_real_ref_counts,
        source_placeholder_ref_counts=source_placeholder_ref_counts,
        source_stub_ref_counts=source_stub_ref_counts,
        covered_ids=covered_ids,
        placeholder_only_ids=placeholder_only_ids,
        stub_only_ids=stub_only_ids,
        untested_ids=untested_ids,
        invalid_real_refs=dict(
            sorted(invalid_real_refs.items(), key=lambda item: _ac_sort_key(item[0]))
        ),
        invalid_placeholder_refs=dict(
            sorted(
                invalid_placeholder_refs.items(), key=lambda item: _ac_sort_key(item[0])
            )
        ),
        invalid_stub_refs=dict(
            sorted(invalid_stub_refs.items(), key=lambda item: _ac_sort_key(item[0]))
        ),
        deprecated_ids=deprecated_ids,
    )


def _epic_stats(result: AnalysisResult) -> list[EpicStats]:
    by_epic: dict[int, EpicStats] = {}
    for ac in result.registry.values():
        stats = by_epic.setdefault(
            ac.epic, EpicStats(epic=ac.epic, epic_name=ac.epic_name)
        )
        stats.registered += 1
        if ac.id in result.deprecated_ids:
            stats.deprecated += 1
        elif ac.id in result.covered_ids:
            stats.covered += 1
        elif ac.id in result.placeholder_only_ids:
            stats.placeholder_only += 1
            stats.untested += 1
        elif ac.id in result.stub_only_ids:
            stats.stub_only += 1
            stats.untested += 1
        else:
            stats.untested += 1

    return [by_epic[epic] for epic in sorted(by_epic)]


def _group_untested_by_epic(result: AnalysisResult) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    for ac_id in result.untested_ids:
        ac = result.registry[ac_id]
        grouped[ac.epic].append(ac_id)
    return dict(sorted(grouped.items()))


def _render_file_list(paths: list[str]) -> str:
    return "<br>".join(f"`{path}`" for path in paths)


def render_markdown(result: AnalysisResult, generated_at: datetime) -> str:
    total_registered = len(result.registry)
    active_registered = total_registered - len(result.deprecated_ids)
    covered_count = len(result.covered_ids)
    placeholder_only_count = len(result.placeholder_only_ids)
    stub_only_count = len(result.stub_only_ids)
    untested_count = len(result.untested_ids)
    invalid_real_count = len(result.invalid_real_refs)
    invalid_placeholder_count = len(result.invalid_placeholder_refs)
    invalid_stub_count = len(result.invalid_stub_refs)

    coverage_pct = (
        (covered_count / active_registered * 100.0) if active_registered else 100.0
    )

    lines: list[str] = []
    lines.append("# AC Coverage Analysis Report")
    lines.append("")
    lines.append(
        f"> Generated: {generated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} by `tools/analyze_test_ac_coverage.py`"
    )
    lines.append(
        "> Snapshot: this checked-in report is a generated artifact. Regenerate it or inspect CI artifacts for current values; do not copy these counts into prose docs."
    )
    lines.append("")
    lines.append("## Coverage accounting (EPIC-008 aligned)")
    lines.append("")
    lines.append(
        "- Covered AC = has at least one real test reference outside `_ac_stubs`, trivial placeholder assertions, pure `pass`, and pure skipped tests."
    )
    lines.append(
        "- `expect(true).toBe(true)`, pure `pass`, and pure skipped references are tracked as placeholder-only and **do not** count as covered."
    )
    lines.append(
        "- `_ac_stubs` references are tracked as placeholders (`stub-only`) and **do not** count as covered."
    )
    lines.append(
        "- Strikethrough deprecated ACs are excluded from active coverage and untested counts."
    )
    lines.append(
        "- Synthetic AC IDs inside `scripts/tests` fixtures are excluded from invalid-ref counts; fixture-only mismatches are audited separately."
    )
    lines.append(
        "- Invalid AC references are other AC IDs found in tests but missing from registries."
    )
    lines.append(
        "- Untested AC = registered AC without any real passing-test candidate reference."
    )
    lines.append("")
    lines.append("## Executive summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---:|")
    lines.append(f"| Registered ACs | {total_registered} |")
    lines.append(f"| Active ACs | {active_registered} |")
    lines.append(
        f"| Deprecated ACs excluded from coverage gate | {len(result.deprecated_ids)} |"
    )
    lines.append(
        f"| Covered by real test candidates | {covered_count} ({coverage_pct:.1f}%) |"
    )
    lines.append(f"| Placeholder-only assertions | {placeholder_only_count} |")
    lines.append(f"| Stub-only placeholders (`_ac_stubs`) | {stub_only_count} |")
    lines.append(f"| Active registered but untested | {untested_count} |")
    lines.append(f"| Invalid AC refs in real tests | {invalid_real_count} |")
    lines.append(f"| Invalid AC refs in placeholders | {invalid_placeholder_count} |")
    lines.append(f"| Invalid AC refs in stubs | {invalid_stub_count} |")
    lines.append("")

    lines.append("## Scan scope summary")
    lines.append("")
    lines.append(
        "| Source | Files scanned | Unique AC refs (real) | Unique AC refs (placeholder) | Unique AC refs (stub) |"
    )
    lines.append("|---|---:|---:|---:|---:|")
    for source, *_ in SCAN_TARGETS:
        lines.append(
            f"| {source} | {result.source_file_counts.get(source, 0)} | "
            f"{result.source_real_ref_counts.get(source, 0)} | "
            f"{result.source_placeholder_ref_counts.get(source, 0)} | "
            f"{result.source_stub_ref_counts.get(source, 0)} |"
        )
    lines.append("")

    lines.append("## Coverage by EPIC")
    lines.append("")
    lines.append(
        "| EPIC | Name | Registered | Deprecated | Covered | Placeholder-only | Stub-only | Untested | Coverage |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for epic in _epic_stats(result):
        active_epic_registered = epic.registered - epic.deprecated
        epic_coverage_pct = (
            epic.covered / active_epic_registered * 100.0
            if active_epic_registered
            else 100.0
        )
        lines.append(
            f"| EPIC-{epic.epic:03d} | {epic.epic_name} | {epic.registered} | "
            f"{epic.deprecated} | {epic.covered} | {epic.placeholder_only} | {epic.stub_only} | "
            f"{epic.untested} | {epic_coverage_pct:.1f}% |"
        )
    lines.append("")

    lines.append("## Invalid AC references (unregistered)")
    lines.append("")
    if (
        result.invalid_real_refs
        or result.invalid_placeholder_refs
        or result.invalid_stub_refs
    ):
        lines.append("| AC ID | Real test files | Placeholder files | Stub files |")
        lines.append("|---|---|---|---|")
        invalid_ids = sorted(
            set(result.invalid_real_refs)
            | set(result.invalid_placeholder_refs)
            | set(result.invalid_stub_refs),
            key=_ac_sort_key,
        )
        for ac_id in invalid_ids:
            real_files = result.invalid_real_refs.get(ac_id, [])
            placeholder_files = result.invalid_placeholder_refs.get(ac_id, [])
            stub_files = result.invalid_stub_refs.get(ac_id, [])
            lines.append(
                f"| `{ac_id}` | "
                f"{_render_file_list(real_files) if real_files else '_none_'} | "
                f"{_render_file_list(placeholder_files) if placeholder_files else '_none_'} | "
                f"{_render_file_list(stub_files) if stub_files else '_none_'} |"
            )
    else:
        lines.append("No invalid AC references found.")
    lines.append("")

    lines.append("## Stub-only AC placeholders (`_ac_stubs`)")
    lines.append("")
    if result.stub_only_ids:
        lines.append("| AC ID | Stub file references |")
        lines.append("|---|---|")
        for ac_id in sorted(result.stub_only_ids, key=_ac_sort_key):
            files = sorted(result.references[ac_id].stub_files)
            lines.append(f"| `{ac_id}` | {_render_file_list(files)} |")
    else:
        lines.append("No stub-only AC placeholders found.")
    lines.append("")

    lines.append("## Placeholder-only AC assertions")
    lines.append("")
    if result.placeholder_only_ids:
        lines.append("| AC ID | Placeholder file references |")
        lines.append("|---|---|")
        for ac_id in sorted(result.placeholder_only_ids, key=_ac_sort_key):
            files = sorted(result.references[ac_id].placeholder_files)
            lines.append(f"| `{ac_id}` | {_render_file_list(files)} |")
    else:
        lines.append("No placeholder-only AC assertions found.")
    lines.append("")

    lines.append("## Active registered ACs with no real test reference")
    lines.append("")
    grouped_untested = _group_untested_by_epic(result)
    if grouped_untested:
        for epic_number, ac_ids in grouped_untested.items():
            epic_name = result.registry[ac_ids[0]].epic_name
            lines.append(
                f"### EPIC-{epic_number:03d} ({epic_name}) — {len(ac_ids)} untested"
            )
            lines.append("")
            lines.append(", ".join(f"`{ac_id}`" for ac_id in ac_ids))
            lines.append("")
    else:
        lines.append("All active registered ACs have at least one real test reference.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze AC coverage across test suites."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root path (default: auto-detected root)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Markdown report output path",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print report content to stdout",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()

    result = analyze_repo(repo_root=repo_root)
    report = render_markdown(result, generated_at=datetime.now(timezone.utc))

    output_path = args.output if args.output.is_absolute() else repo_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    print(f"Wrote AC coverage report: {output_path}")
    print(
        "Summary: "
        f"registered={len(result.registry)}, active={len(result.registry) - len(result.deprecated_ids)}, "
        f"covered={len(result.covered_ids)}, "
        f"placeholder_only={len(result.placeholder_only_ids)}, "
        f"stub_only={len(result.stub_only_ids)}, untested={len(result.untested_ids)}, "
        f"invalid_real={len(result.invalid_real_refs)}"
    )

    if args.stdout:
        print()
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
