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
E2E_MARKERS = {"e2e", "smoke"}
EPIC_RE = re.compile(r"\bEPIC-\d{3}\b")


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
    tests: list[E2ETest]
    parse_errors: list[ParseError] = field(default_factory=list)

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
    def errors(self) -> list[str]:
        errors: list[str] = []
        for parse_error in self.parse_errors:
            errors.append(
                f"{parse_error.file}: could not parse Python AST: {parse_error.message}"
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
    tests, parse_errors = collect_e2e_tests(repo_root, e2e_roots)
    return TraceabilityResult(
        project_epics=project_epics,
        tests=tests,
        parse_errors=parse_errors,
    )


def render_report(result: TraceabilityResult) -> str:
    lines = [
        "# E2E EPIC Traceability Report",
        "",
        f"Project EPICs: {len(result.project_epics)}",
        f"Product E2E test functions: {len(result.tests)}",
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
