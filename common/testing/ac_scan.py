"""Shared AC-reference file discovery and collection primitives."""

from __future__ import annotations

import functools
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeAlias

from common.testing.ac_traceability_refs import AC_PATTERN, classify_reference_file
from common.testing.test_surface import default_ac_test_dirs

EXCLUDED_DIRS = {"node_modules", "__pycache__", ".next", "dist", ".cache"}
TEST_FILE_SUFFIXES = ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")

DisplayPath: TypeAlias = str | Path


@dataclass(frozen=True)
class ScanFile:
    """A test file and, optionally, the test surface it belongs to."""

    path: Path
    source: str = ""


@dataclass
class ACReferenceStats:
    """Every reference class for one AC across the scanned test files."""

    real_files: set[DisplayPath] = field(default_factory=set)
    ci_real_files: set[DisplayPath] = field(default_factory=set)
    placeholder_files: set[DisplayPath] = field(default_factory=set)
    stub_files: set[DisplayPath] = field(default_factory=set)
    real_sources: set[str] = field(default_factory=set)
    placeholder_sources: set[str] = field(default_factory=set)
    stub_sources: set[str] = field(default_factory=set)

    @property
    def all_files(self) -> set[DisplayPath]:
        return self.real_files | self.placeholder_files | self.stub_files

    def files_for_report(self) -> list[tuple[str, DisplayPath]]:
        rows: list[tuple[str, DisplayPath]] = []
        rows.extend(("real", path) for path in self.real_files)
        rows.extend(("placeholder", path) for path in self.placeholder_files)
        rows.extend(("stub", path) for path in self.stub_files)
        return sorted(rows, key=lambda row: (row[0], str(row[1])))


def find_test_files(
    test_dirs: list[Path],
    *,
    excluded_dirs: set[str] = EXCLUDED_DIRS,
    suffixes: tuple[str, ...] = TEST_FILE_SUFFIXES,
) -> list[Path]:
    """Return sorted Python, Vitest, and Playwright test files below directories."""

    found: list[Path] = []
    for base in test_dirs:
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [
                directory for directory in dirs if directory not in excluded_dirs
            ]
            for filename in files:
                if filename.startswith("test_") or filename.endswith(suffixes):
                    found.append(Path(root) / filename)
    return sorted(found)


def discover_paths(base: Path, patterns: tuple[str, ...]) -> list[Path]:
    """Return a sorted union of glob patterns for one test surface."""

    if not base.exists():
        return []
    paths: set[Path] = set()
    for pattern in patterns:
        paths.update(path for path in base.glob(pattern) if path.is_file())
    return sorted(paths)


@functools.lru_cache(maxsize=8192)
def _scan_file_cached(
    path_str: str, mtime_ns: int, size: int
) -> tuple[str, tuple[str, ...]]:
    path = Path(path_str)
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ("missing", ())
    kind = classify_reference_file(path, content)
    matches = tuple(m.group(0) for m in AC_PATTERN.finditer(content))
    return (kind, matches)


def collect_references(
    files: list[Path | ScanFile],
    *,
    display_path: Callable[[Path], DisplayPath] | None = None,
    is_ci_file: Callable[[DisplayPath], bool] | None = None,
) -> dict[str, ACReferenceStats]:
    """Classify and collect AC references from test files once for all consumers."""

    references: dict[str, ACReferenceStats] = defaultdict(ACReferenceStats)
    render_path = display_path or (lambda path: path)
    for item in files:
        scan_file = item if isinstance(item, ScanFile) else ScanFile(path=item)
        try:
            st = scan_file.path.stat()
            kind, matches = _scan_file_cached(
                str(scan_file.path), st.st_mtime_ns, st.st_size
            )
        except OSError:
            continue
        rendered_path = render_path(scan_file.path)
        for match in matches:
            stats = references[match]
            if kind == "stub":
                stats.stub_files.add(rendered_path)
                if scan_file.source:
                    stats.stub_sources.add(scan_file.source)
            elif kind == "placeholder":
                stats.placeholder_files.add(rendered_path)
                if scan_file.source:
                    stats.placeholder_sources.add(scan_file.source)
            else:
                stats.real_files.add(rendered_path)
                if is_ci_file is not None and is_ci_file(rendered_path):
                    stats.ci_real_files.add(rendered_path)
                if scan_file.source:
                    stats.real_sources.add(scan_file.source)
    return dict(references)


def collect_real_refs(repo_root: Path) -> dict[str, set[str]]:
    """Return {ac_id: {rel_path, ...}} for real (non-stub/placeholder) refs."""
    files = find_test_files(list(default_ac_test_dirs(repo_root)))
    stats = collect_references(
        files, display_path=lambda p: p.relative_to(repo_root).as_posix()
    )
    return {
        ac: set(str(p) for p in s.real_files) for ac, s in stats.items() if s.real_files
    }
