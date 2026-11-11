#!/usr/bin/env python3
"""Validate product E2E test ownership by project EPIC."""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from common.meta.base.gate_cli import run_cli_command
from common.meta.base.gate_util import (
    display_path,
    duplicate_values,
    markdown_table_cells,
    pytest_decorator_markers,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_E2E_ROOTS = ("tests/e2e",)
DECLARED_NON_PRODUCT_E2E_ROOTS = ("repo/e2e_regressions",)
DECLARED_NON_PRODUCT_E2E_FILES = ("repo/finance/appwrite/scripts/e2e-test.sh",)
E2E_ASSET_SUFFIXES = {".py", ".sh", ".ts", ".tsx", ".js", ".jsx"}
EXCLUDED_SCAN_DIRS = {
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "coverage",
    "dist",
    "htmlcov",
    "node_modules",
}
E2E_MARKERS = {"e2e", "smoke"}
EPIC_RE = re.compile(r"\bEPIC-\d{3}\b")
README_EPIC_LINK_RE = re.compile(r"\[(EPIC-\d{3})\]\(([^)]+)\)")
EPIC_FILE_KIND_RE = re.compile(r"<!--\s*epic-file:\s*(design-doc|goal-stub)\s*-->")

_markdown_cells = markdown_table_cells
_decorator_markers = pytest_decorator_markers


class ProjectEpicKind(StrEnum):
    RESIDUE = "residue"
    DESIGN_DOC = "design-doc"
    GOAL_STUB = "goal-stub"


@dataclass(frozen=True)
class ProjectEpic:
    id: str
    path: str
    kind: ProjectEpicKind
    has_epic_residue: bool

    @property
    def requires_product_e2e(self) -> bool:
        return self.kind is ProjectEpicKind.RESIDUE or self.has_epic_residue


@dataclass(frozen=True)
class E2ETest:
    file: str
    line: int
    name: str
    markers: tuple[str, ...]
    epic_ids: tuple[str, ...]

    @property
    def anchor(self) -> str:
        return f"{self.file}:{self.line} {self.name}"


@dataclass(frozen=True)
class ParseError:
    file: str
    message: str


@dataclass
class TraceabilityResult:
    project_epics: list[ProjectEpic]
    readme_epics: list[str]
    tests: list[E2ETest]
    e2e_assets: list[str]
    unclassified_e2e_assets: list[str]
    parse_errors: list[ParseError] = field(default_factory=list)
    readme_errors: list[str] = field(default_factory=list)

    @property
    def project_epic_ids(self) -> list[str]:
        return [epic.id for epic in self.project_epics]

    @property
    def required_project_epics(self) -> list[str]:
        return [epic.id for epic in self.project_epics if epic.requires_product_e2e]

    @property
    def covered_epics(self) -> list[str]:
        known = set(self.project_epic_ids)
        return sorted(
            {epic for t in self.tests for epic in t.epic_ids if epic in known}
        )

    @property
    def tests_without_epics(self) -> list[E2ETest]:
        return [test for test in self.tests if not test.epic_ids]

    @property
    def missing_epics(self) -> list[str]:
        return sorted(set(self.required_project_epics) - set(self.covered_epics))

    @property
    def unknown_epic_refs(self) -> dict[str, list[E2ETest]]:
        known = set(self.project_epic_ids)
        refs: dict[str, list[E2ETest]] = {}
        for test in self.tests:
            for epic in test.epic_ids:
                if epic not in known:
                    refs.setdefault(epic, []).append(test)
        return refs

    @property
    def readme_epic_map_errors(self) -> list[str]:
        errors = list(self.readme_errors)
        project, readme = set(self.project_epic_ids), set(self.readme_epics)
        if missing := sorted(project - readme):
            errors.append(
                f"README EPIC map missing project EPICs: {', '.join(missing)}"
            )
        if unknown := sorted(readme - project):
            errors.append(
                f"README EPIC map includes unknown EPICs: {', '.join(unknown)}"
            )
        return errors

    @property
    def errors(self) -> list[str]:
        return [
            *self.readme_epic_map_errors,
            *(
                f"{pe.file}: could not parse Python AST: {pe.message}"
                for pe in self.parse_errors
            ),
            *(
                f"{asset}: unclassified E2E-like asset outside declared product or non-product roots"
                for asset in self.unclassified_e2e_assets
            ),
            *(f"{test.anchor}: missing EPIC ID" for test in self.tests_without_epics),
            *(
                f"{test.anchor}: unknown EPIC ID {epic}"
                for epic, tests in sorted(self.unknown_epic_refs.items())
                for test in tests
            ),
            *(f"{epic}: no product E2E owner test" for epic in self.missing_epics),
        ]


def discover_project_epics(repo_root: Path) -> list[ProjectEpic]:
    project_root = repo_root / "docs" / "project"
    if not project_root.exists():
        return []
    epics: dict[str, ProjectEpic] = {}
    for path in sorted(project_root.glob("EPIC-*.md")):
        epic_id = path.name.split(".", 1)[0]
        text = path.read_text(encoding="utf-8", errors="ignore")
        marker = EPIC_FILE_KIND_RE.search(text)
        kind = ProjectEpicKind(marker.group(1)) if marker else ProjectEpicKind.RESIDUE
        has_epic_residue = "<!-- epic-owned:" in text
        if epic_id not in epics or kind is ProjectEpicKind.RESIDUE or has_epic_residue:
            epics[epic_id] = ProjectEpic(
                id=epic_id,
                path=display_path(path, repo_root),
                kind=kind,
                has_epic_residue=has_epic_residue,
            )
    return [epics[epic_id] for epic_id in sorted(epics)]


def _validate_readme_epic_link(
    repo_root: Path, epic_id: str, target: str, row_number: int
) -> list[str]:
    clean_target = target.split("#", 1)[0]
    target_epic = Path(clean_target).name.split(".", 1)[0]
    if not clean_target.startswith("docs/project/") or target_epic != epic_id:
        return [
            f"README.md:{row_number} {epic_id} link target does not match row EPIC: {target}"
        ]
    if not (repo_root / clean_target).exists():
        return [
            f"README.md:{row_number} {epic_id} link target does not exist: {target}"
        ]
    return []


def discover_readme_epics(repo_root: Path) -> tuple[list[str], list[str]]:
    readme = repo_root / "README.md"
    if not readme.exists():
        return [], ["README.md missing"]

    lines = readme.read_text(encoding="utf-8").splitlines()
    section_start = next(
        (
            idx + 1
            for idx, line in enumerate(lines)
            if re.fullmatch(r"#{2,6}\s+EPIC Map\s*", line.strip())
        ),
        None,
    )
    if section_start is None:
        return [], ["README.md missing `## EPIC Map` section"]

    table_start: int | None = None
    for index in range(section_start, len(lines)):
        line = lines[index]
        if re.match(r"^#{2,6}\s+", line):
            break
        if (
            line.lstrip().startswith("|")
            and (_markdown_cells(line) or [""])[0].lower() == "epic"
        ):
            table_start = index + 1
            break
    if table_start is None:
        return [], ["README.md missing parseable EPIC Map table"]

    errors: list[str] = []
    epic_ids: list[str] = []
    for index in range(table_start, len(lines)):
        line = lines[index]
        if not line.lstrip().startswith("|"):
            if epic_ids:
                break
            continue
        cells = _markdown_cells(line)
        if not cells or not cells[0] or set(cells[0].strip()) <= {"-", ":"}:
            continue
        first = cells[0]
        link_matches = README_EPIC_LINK_RE.findall(first)
        matches = [eid for eid, _ in link_matches] or EPIC_RE.findall(first)
        if not matches:
            continue
        epic_ids.extend(matches)
        if not link_matches:
            errors.extend(
                f"README.md:{index + 1} {eid} row must link to docs/project/{eid}*.md"
                for eid in matches
            )
            continue
        for eid, target in link_matches:
            errors.extend(_validate_readme_epic_link(repo_root, eid, target, index + 1))

    errors.extend(
        f"README EPIC map duplicates EPIC row: {eid}"
        for eid in duplicate_values(epic_ids)
    )
    if not epic_ids:
        return [], ["README.md EPIC Map table has no EPIC rows"]
    return sorted(set(epic_ids)), errors


def discover_e2e_files(
    repo_root: Path, e2e_roots: tuple[str, ...] = DEFAULT_E2E_ROOTS
) -> list[Path]:
    return sorted(
        path
        for root in e2e_roots
        if (repo_root / root).exists()
        for path in (repo_root / root).rglob("test_*.py")
    )


def _has_excluded_part(path: Path) -> bool:
    return any(part in EXCLUDED_SCAN_DIRS for part in path.parts)


def _is_e2e_like_asset(path: Path, repo_root: Path) -> bool:
    if not path.is_file() or path.suffix not in E2E_ASSET_SUFFIXES:
        return False
    rel_parts = Path(display_path(path, repo_root)).parts
    if _has_excluded_part(Path(*rel_parts)):
        return False
    return (
        any("e2e" in part.lower() for part in rel_parts[:-1])
        or rel_parts[-1].lower() == "e2e-test.sh"
    )


def _under_any(rel_path: str, roots: tuple[str, ...]) -> bool:
    return any(rel_path == root or rel_path.startswith(f"{root}/") for root in roots)


def discover_e2e_assets(repo_root: Path) -> list[str]:
    if not repo_root.exists():
        return []
    assets: list[str] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_SCAN_DIRS]
        for fname in files:
            path = Path(root) / fname
            if _is_e2e_like_asset(path, repo_root):
                assets.append(display_path(path, repo_root))
    return sorted(assets)


def find_unclassified_e2e_assets(
    repo_root: Path,
    *,
    product_roots: tuple[str, ...] = DEFAULT_E2E_ROOTS,
    non_product_roots: tuple[str, ...] = DECLARED_NON_PRODUCT_E2E_ROOTS,
    non_product_files: tuple[str, ...] = DECLARED_NON_PRODUCT_E2E_FILES,
) -> tuple[list[str], list[str]]:
    assets = discover_e2e_assets(repo_root)
    classified_files = set(non_product_files)
    unclassified = [
        asset
        for asset in assets
        if not _under_any(asset, product_roots)
        and not _under_any(asset, non_product_roots)
        and asset not in classified_files
    ]
    return assets, sorted(unclassified)


def _collect_tests_from_file(
    path: Path, repo_root: Path
) -> tuple[list[E2ETest], ParseError | None]:
    rel_path = display_path(path, repo_root)
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [], ParseError(file=rel_path, message=str(exc))

    tests = [
        E2ETest(
            file=rel_path,
            line=node.lineno,
            name=node.name,
            markers=tuple(sorted(_decorator_markers(node) & E2E_MARKERS)),
            epic_ids=tuple(
                sorted(
                    set(
                        EPIC_RE.findall(f"{node.name}\n{ast.get_docstring(node) or ''}")
                    )
                )
            ),
        )
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    return tests, None


def collect_e2e_tests(
    repo_root: Path,
    e2e_roots: tuple[str, ...] = DEFAULT_E2E_ROOTS,
) -> tuple[list[E2ETest], list[ParseError]]:
    tests: list[E2ETest] = []
    parse_errors: list[ParseError] = []
    for path in discover_e2e_files(repo_root, e2e_roots):
        file_tests, parse_error = _collect_tests_from_file(path, repo_root)
        tests.extend(file_tests)
        if parse_error is not None:
            parse_errors.append(parse_error)
    return sorted(tests, key=lambda t: (t.file, t.line, t.name)), parse_errors


def check_traceability(
    repo_root: Path = REPO_ROOT,
    e2e_roots: tuple[str, ...] = DEFAULT_E2E_ROOTS,
) -> TraceabilityResult:
    project_epics = discover_project_epics(repo_root)
    readme_epics, readme_errors = discover_readme_epics(repo_root)
    tests, parse_errors = collect_e2e_tests(repo_root, e2e_roots)
    e2e_assets, unclassified = find_unclassified_e2e_assets(
        repo_root, product_roots=e2e_roots
    )
    return TraceabilityResult(
        project_epics=project_epics,
        readme_epics=readme_epics,
        tests=tests,
        e2e_assets=e2e_assets,
        unclassified_e2e_assets=unclassified,
        parse_errors=parse_errors,
        readme_errors=readme_errors,
    )


def render_report(result: TraceabilityResult) -> str:
    lines = [
        "# E2E EPIC Traceability Report",
        "",
        f"Project EPICs: {len(result.project_epics)}",
        f"E2E-required EPICs: {len(result.required_project_epics)}",
        f"README EPIC Map entries: {len(result.readme_epics)}",
        f"Product E2E test functions: {len(result.tests)}",
        f"E2E-like assets scanned: {len(result.e2e_assets)}",
        f"Unclassified E2E-like assets: {len(result.unclassified_e2e_assets)}",
        f"Covered EPICs: {len(result.covered_epics)}",
        f"Missing EPICs: {len(result.missing_epics)}",
        f"Tests without EPIC IDs: {len(result.tests_without_epics)}",
        f"Unknown EPIC refs: {len(result.unknown_epic_refs)}",
        "",
    ]
    if result.errors:
        lines.extend(["## Errors", "", *(f"- {e}" for e in result.errors), ""])
    else:
        lines.extend(["No E2E EPIC traceability errors found.", ""])

    lines.extend(
        ["## Test Owners", "", "| Test | Markers | EPIC IDs |", "|---|---|---|"]
    )
    for test in result.tests:
        markers = ", ".join(test.markers) or "-"
        epics = ", ".join(test.epic_ids) or "-"
        lines.append(f"| `{test.anchor}` | {markers} | {epics} |")
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that product E2E test functions and project EPICs are linked."
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--e2e-roots",
        nargs="+",
        default=list(DEFAULT_E2E_ROOTS),
        help="Product E2E roots to scan.",
    )
    parser.add_argument("--output", help="Optional Markdown report path.")
    parser.add_argument("--report-only", action="store_true")
    return parser.parse_args(argv)


def _main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = check_traceability(Path(args.repo_root), tuple(args.e2e_roots))
    report = render_report(result)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"Wrote E2E EPIC traceability report: {output_path}")
    else:
        print(report)

    if result.errors and not args.report_only:
        print(
            f"E2E EPIC TRACEABILITY GATE FAILED: {len(result.errors)} issue(s) found.",
            file=sys.stderr,
        )
        return 1
    print("E2E EPIC TRACEABILITY GATE PASSED")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli_command(_main, argv)


if __name__ == "__main__":
    raise SystemExit(main())
