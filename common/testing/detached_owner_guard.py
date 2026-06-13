"""Static guard for legacy detached user-owner shortcuts in backend tests."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TEST_ROOTS = (Path("apps/backend/tests"),)
DEFAULT_MAX_DETACHED_OWNER_SHORTCUTS = 59
OWNER_KEYWORD = "user_id"
PATTERN = "user_id=uuid4()"


@dataclass(frozen=True, order=True)
class DetachedOwnerFinding:
    """One direct user_id=uuid4() shortcut in a backend test."""

    relative_path: str
    line: int
    pattern: str
    source: str


@dataclass(frozen=True)
class BudgetResult:
    """Detached-owner budget evaluation result."""

    ok: bool
    count: int
    max_allowed: int
    message: str


def _is_uuid4_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "uuid4"
    if isinstance(func, ast.Attribute):
        return func.attr == "uuid4"
    return False


def _iter_python_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            yield path
            continue
        if path.is_dir():
            yield from sorted(path.rglob("*.py"))


def _relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


class _DetachedOwnerVisitor(ast.NodeVisitor):
    def __init__(self, *, source_text: str, relative_path: str) -> None:
        self._source_text = source_text
        self._relative_path = relative_path
        self.findings: list[DetachedOwnerFinding] = []

    def visit_Call(self, node: ast.Call) -> None:
        for keyword in node.keywords:
            if keyword.arg == OWNER_KEYWORD and _is_uuid4_call(keyword.value):
                source = ast.get_source_segment(self._source_text, node) or PATTERN
                self.findings.append(
                    DetachedOwnerFinding(
                        relative_path=self._relative_path,
                        line=keyword.value.lineno,
                        pattern=PATTERN,
                        source=" ".join(source.split()),
                    )
                )
        self.generic_visit(node)


def scan_file(path: Path, *, repo_root: Path) -> list[DetachedOwnerFinding]:
    """Return direct detached-owner shortcuts found in one Python file."""
    source_text = path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(path))
    visitor = _DetachedOwnerVisitor(
        source_text=source_text,
        relative_path=_relative_path(path, repo_root),
    )
    visitor.visit(tree)
    return visitor.findings


def scan_paths(paths: Sequence[Path], *, repo_root: Path) -> list[DetachedOwnerFinding]:
    """Return direct detached-owner shortcuts under the given files or directories."""
    findings: list[DetachedOwnerFinding] = []
    for path in _iter_python_files(paths):
        findings.extend(scan_file(path, repo_root=repo_root))
    return sorted(findings)


def scan_default_paths(repo_root: Path) -> list[DetachedOwnerFinding]:
    """Scan the default backend test roots."""
    return scan_paths([repo_root / path for path in DEFAULT_TEST_ROOTS], repo_root=repo_root)


def evaluate_budget(
    findings: Sequence[DetachedOwnerFinding],
    *,
    max_allowed: int = DEFAULT_MAX_DETACHED_OWNER_SHORTCUTS,
) -> BudgetResult:
    """Evaluate whether the detached-owner count stays within the non-growth budget."""
    count = len(findings)
    if count <= max_allowed:
        return BudgetResult(
            ok=True,
            count=count,
            max_allowed=max_allowed,
            message=f"Detached-owner shortcut count {count} is within allowed budget {max_allowed}.",
        )
    return BudgetResult(
        ok=False,
        count=count,
        max_allowed=max_allowed,
        message=f"Detached-owner shortcut count {count} exceeds allowed budget {max_allowed}.",
    )


def _format_findings(findings: Sequence[DetachedOwnerFinding], *, limit: int) -> str:
    shown = findings[:limit]
    lines = [f"{finding.relative_path}:{finding.line}: {finding.pattern}: {finding.source}" for finding in shown]
    remaining = len(findings) - len(shown)
    if remaining > 0:
        lines.append(f"... {remaining} more")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail if direct user_id=uuid4() shortcuts in backend tests exceed the configured budget.",
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--path",
        action="append",
        type=Path,
        dest="paths",
        help="Path to scan relative to --repo-root. Defaults to apps/backend/tests.",
    )
    parser.add_argument(
        "--max-allowed",
        type=int,
        default=DEFAULT_MAX_DETACHED_OWNER_SHORTCUTS,
        help="Maximum allowed direct detached-owner shortcuts.",
    )
    parser.add_argument(
        "--list-findings",
        action="store_true",
        help="Print matching shortcuts even when the budget passes.",
    )
    parser.add_argument("--show-limit", type=int, default=20)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    paths = (
        [repo_root / path for path in args.paths] if args.paths else [repo_root / path for path in DEFAULT_TEST_ROOTS]
    )
    findings = scan_paths(paths, repo_root=repo_root)
    result = evaluate_budget(findings, max_allowed=args.max_allowed)

    stream = sys.stdout if result.ok else sys.stderr
    print(result.message, file=stream)
    if findings and (args.list_findings or not result.ok):
        print(_format_findings(findings, limit=args.show_limit), file=stream)
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
