#!/usr/bin/env python3
"""Validate product E2E test ownership by project EPIC."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_E2E_ROOTS = (
    "tests/e2e",
    "apps/backend/tests/e2e",
)
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
    project_epics: list[str]
    readme_epics: list[str]
    tests: list[E2ETest]
    e2e_assets: list[str]
    unclassified_e2e_assets: list[str]
    parse_errors: list[ParseError] = field(default_factory=list)
    readme_errors: list[str] = field(default_factory=list)

    @property
    def covered_epics(self) -> list[str]:
        known = set(self.project_epics)
        return sorted(
            {epic for test in self.tests for epic in test.epic_ids if epic in known}
        )

    @property
    def tests_without_epics(self) -> list[E2ETest]:
        return [test for test in self.tests if not test.epic_ids]

    @property
    def missing_epics(self) -> list[str]:
        return sorted(set(self.project_epics) - set(self.covered_epics))

    @property
    def unknown_epic_refs(self) -> dict[str, list[E2ETest]]:
        known = set(self.project_epics)
        refs: dict[str, list[E2ETest]] = {}
        for test in self.tests:
            for epic in test.epic_ids:
                if epic not in known:
                    refs.setdefault(epic, []).append(test)
        return refs

    @property
    def readme_epic_map_errors(self) -> list[str]:
        errors = list(self.readme_errors)
        project = set(self.project_epics)
        readme = set(self.readme_epics)
        missing = sorted(project - readme)
        unknown = sorted(readme - project)
        if missing:
            errors.append(
                f"README EPIC map missing project EPICs: {', '.join(missing)}"
            )
        if unknown:
            errors.append(
                f"README EPIC map includes unknown EPICs: {', '.join(unknown)}"
            )
        return errors

    @property
    def errors(self) -> list[str]:
        errors: list[str] = []
        errors.extend(self.readme_epic_map_errors)
        for parse_error in self.parse_errors:
            errors.append(
                f"{parse_error.file}: could not parse Python AST: {parse_error.message}"
            )
        for asset in self.unclassified_e2e_assets:
            errors.append(
                f"{asset}: unclassified E2E-like asset outside declared product or non-product roots"
            )
        for test in self.tests_without_epics:
            errors.append(f"{test.anchor}: missing EPIC ID")
        for epic, tests in sorted(self.unknown_epic_refs.items()):
            for test in tests:
                errors.append(f"{test.anchor}: unknown EPIC ID {epic}")
        for epic in self.missing_epics:
            errors.append(f"{epic}: no product E2E owner test")
        return errors


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def discover_project_epics(repo_root: Path) -> list[str]:
    project_root = repo_root / "docs" / "project"
    if not project_root.exists():
        return []
    return sorted(
        {path.name.split(".", 1)[0] for path in project_root.glob("EPIC-*.md")}
    )


def _markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _validate_readme_epic_link(
    repo_root: Path,
    epic_id: str,
    target: str,
    row_number: int,
) -> list[str]:
    errors: list[str] = []
    clean_target = target.split("#", 1)[0]
    target_epic = Path(clean_target).name.split(".", 1)[0]
    if not clean_target.startswith("docs/project/") or target_epic != epic_id:
        errors.append(
            f"README.md:{row_number} {epic_id} link target does not match row EPIC: {target}"
        )
    elif not (repo_root / clean_target).exists():
        errors.append(
            f"README.md:{row_number} {epic_id} link target does not exist: {target}"
        )
    return errors


def discover_readme_epics(repo_root: Path) -> tuple[list[str], list[str]]:
    readme = repo_root / "README.md"
    if not readme.exists():
        return [], ["README.md missing"]

    lines = readme.read_text(encoding="utf-8").splitlines()
    section_start: int | None = None
    for index, line in enumerate(lines):
        if re.fullmatch(r"#{2,6}\s+EPIC Map\s*", line.strip()):
            section_start = index + 1
            break
    if section_start is None:
        return [], ["README.md missing `## EPIC Map` section"]

    table_start: int | None = None
    for index in range(section_start, len(lines)):
        line = lines[index]
        if re.match(r"^#{2,6}\s+", line):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.lower() for cell in _markdown_cells(line)]
        if cells and cells[0] == "epic":
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
        if not cells:
            continue
        first = cells[0]
        if not first or set(first.strip()) <= {"-", ":"}:
            continue
        link_matches = README_EPIC_LINK_RE.findall(first)
        matches = [epic_id for epic_id, _target in link_matches]
        if not matches:
            matches = EPIC_RE.findall(first)
        if matches:
            epic_ids.extend(matches)
            if not link_matches:
                for epic_id in matches:
                    errors.append(
                        f"README.md:{index + 1} {epic_id} row must link to docs/project/{epic_id}*.md"
                    )
                continue
            for epic_id, target in link_matches:
                errors.extend(
                    _validate_readme_epic_link(
                        repo_root,
                        epic_id,
                        target,
                        index + 1,
                    )
                )

    duplicates = _duplicate_values(epic_ids)
    for epic_id in duplicates:
        errors.append(f"README EPIC map duplicates EPIC row: {epic_id}")

    if not epic_ids:
        return [], ["README.md EPIC Map table has no EPIC rows"]
    return sorted(set(epic_ids)), errors


def discover_e2e_files(
    repo_root: Path, e2e_roots: tuple[str, ...] = DEFAULT_E2E_ROOTS
) -> list[Path]:
    files: list[Path] = []
    for root in e2e_roots:
        base = repo_root / root
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("test_*.py")))
    return sorted(files)


def _has_excluded_part(path: Path) -> bool:
    return any(part in EXCLUDED_SCAN_DIRS for part in path.parts)


def _is_e2e_like_asset(path: Path, repo_root: Path) -> bool:
    if not path.is_file() or path.suffix not in E2E_ASSET_SUFFIXES:
        return False
    rel_parts = Path(_rel(path, repo_root)).parts
    if _has_excluded_part(Path(*rel_parts)):
        return False
    parent_parts = [part.lower() for part in rel_parts[:-1]]
    file_name = rel_parts[-1].lower()
    return any("e2e" in part for part in parent_parts) or file_name == "e2e-test.sh"


def _under_any(rel_path: str, roots: tuple[str, ...]) -> bool:
    return any(rel_path == root or rel_path.startswith(f"{root}/") for root in roots)


def discover_e2e_assets(repo_root: Path) -> list[str]:
    if not repo_root.exists():
        return []
    return sorted(
        _rel(path, repo_root)
        for path in repo_root.rglob("*")
        if _is_e2e_like_asset(path, repo_root)
    )


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


def _decorator_markers(node: ast.AST) -> set[str]:
    markers: set[str] = set()
    for decorator in getattr(node, "decorator_list", []):
        text = ast.unparse(decorator)
        prefix = "pytest.mark."
        if text.startswith(prefix):
            marker = text[len(prefix) :].split("(", 1)[0].split(".", 1)[0]
            markers.add(marker)
    return markers


def _collect_tests_from_file(
    path: Path, repo_root: Path
) -> tuple[list[E2ETest], ParseError | None]:
    rel_path = _rel(path, repo_root)
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [], ParseError(file=rel_path, message=str(exc))

    tests: list[E2ETest] = []
    for node in ast.walk(module):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        markers = _decorator_markers(node) & E2E_MARKERS
        doc = ast.get_docstring(node) or ""
        stable_anchor_text = f"{node.name}\n{doc}"
        tests.append(
            E2ETest(
                file=rel_path,
                line=node.lineno,
                name=node.name,
                markers=tuple(sorted(markers)),
                epic_ids=tuple(sorted(set(EPIC_RE.findall(stable_anchor_text)))),
            )
        )
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
    return sorted(
        tests, key=lambda test: (test.file, test.line, test.name)
    ), parse_errors


def check_traceability(
    repo_root: Path = REPO_ROOT,
    e2e_roots: tuple[str, ...] = DEFAULT_E2E_ROOTS,
) -> TraceabilityResult:
    project_epics = discover_project_epics(repo_root)
    readme_epics, readme_errors = discover_readme_epics(repo_root)
    tests, parse_errors = collect_e2e_tests(repo_root, e2e_roots)
    e2e_assets, unclassified_e2e_assets = find_unclassified_e2e_assets(
        repo_root,
        product_roots=e2e_roots,
    )
    return TraceabilityResult(
        project_epics=project_epics,
        readme_epics=readme_epics,
        tests=tests,
        e2e_assets=e2e_assets,
        unclassified_e2e_assets=unclassified_e2e_assets,
        parse_errors=parse_errors,
        readme_errors=readme_errors,
    )


def render_report(result: TraceabilityResult) -> str:
    lines = [
        "# E2E EPIC Traceability Report",
        "",
        f"Project EPICs: {len(result.project_epics)}",
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
        lines.extend(["## Errors", ""])
        lines.extend(f"- {error}" for error in result.errors)
        lines.append("")
    else:
        lines.extend(["No E2E EPIC traceability errors found.", ""])

    lines.extend(
        ["## Test Owners", "", "| Test | Markers | EPIC IDs |", "|---|---|---|"]
    )
    for test in result.tests:
        markers = ", ".join(test.markers) if test.markers else "-"
        epics = ", ".join(test.epic_ids) if test.epic_ids else "-"
        lines.append(f"| `{test.anchor}` | {markers} | {epics} |")

    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check that product E2E test functions and project EPICs are linked."
        )
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root)
    result = check_traceability(repo_root, tuple(args.e2e_roots))
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


if __name__ == "__main__":
    sys.exit(main())
