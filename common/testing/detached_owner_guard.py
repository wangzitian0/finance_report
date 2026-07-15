"""Static guard for legacy detached user-owner shortcuts in backend tests."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TEST_ROOTS = (Path("apps/backend/tests"),)
# Counts only persisted (session-written) detached owners — the real foreign-key risk.
# The two remaining are intentional cross-user isolation tests that must own a
# different user's row; transient in-memory / service-argument uses do not count.
DEFAULT_MAX_DETACHED_OWNER_SHORTCUTS = 2
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


_PERSIST_METHODS = ("add", "add_all", "merge", "bulk_save_objects")


def _persisted_construction_ids(scope: ast.AST) -> set[int]:
    """Return ids of model-construction Call nodes persisted via a session write.

    Only persisted rows carry the production foreign key, so only they can hide the
    ownership / cascade / cross-user bugs this guard exists to catch. A
    ``user_id=uuid4()`` on a transient in-memory object or a bare service argument
    is not a detached-owner shortcut — it never reaches the database.

    Persistence is detected for ``add`` / ``add_all`` / ``merge`` /
    ``bulk_save_objects`` calls, including rows collected into a list variable and
    bulk-added later. This is a deliberate **lower bound**: a row persisted only
    through a cross-function helper or factory (``db.add(make_row())``) is not
    counted, so the budget bounds the *directly-visible* detached owners, not the
    total. The durable fix is keeping the test ``users`` foreign key and owning
    rows with the ``test_user`` fixture.
    """
    added_var_names: set[str] = set()
    construction_ids: set[int] = set()

    def _collect_added(node: ast.expr) -> None:
        """From a session-write argument: record variable names and mark constructions."""
        if isinstance(node, ast.Name):
            added_var_names.add(node.id)
        elif isinstance(node, ast.Call):
            construction_ids.add(id(node))
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for element in node.elts:
                _collect_added(element)

    def _mark_constructions(node: ast.expr) -> None:
        """Mark a construction, or every construction inside a literal collection."""
        if isinstance(node, ast.Call):
            construction_ids.add(id(node))
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for element in node.elts:
                _mark_constructions(element)

    # Any session write in _PERSIST_METHODS (db.add / db.add_all / db.merge /
    # db.bulk_save_objects). A Name argument (or Name list element) records the
    # variable so rows collected into a list and bulk-added later are still persisted.
    for node in ast.walk(scope):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _PERSIST_METHODS:
            for arg in node.args:
                _collect_added(arg)

    # Constructions reaching an added variable: var = Model(...) / var = [Model(...), ...]
    # and var.append(Model(...)) / var.extend([Model(...), ...]).
    for node in ast.walk(scope):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in added_var_names
        ):
            _mark_constructions(node.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("append", "extend")
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in added_var_names
        ):
            for arg in node.args:
                _mark_constructions(arg)
    return construction_ids


def scan_file(path: Path, *, repo_root: Path) -> list[DetachedOwnerFinding]:
    """Return persisted detached-owner shortcuts found in one Python file.

    A finding is counted only when its enclosing model construction is written to a
    session (``db.add`` / ``db.add_all`` / ``db.merge`` / ``db.bulk_save_objects``) —
    the real foreign-key risk. Transient in-memory constructions and bare service
    arguments are not counted.
    """
    source_text = path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(path))
    relative_path = _relative_path(path, repo_root)
    # Judge persistence within each function so a var name added in one test
    # cannot mark a same-named transient construction in another test.
    scopes: list[ast.AST] = [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    findings: list[DetachedOwnerFinding] = []
    seen: set[int] = set()
    for scope in scopes:
        persisted = _persisted_construction_ids(scope)
        for call in ast.walk(scope):
            if not isinstance(call, ast.Call) or id(call) not in persisted:
                continue
            for keyword in call.keywords:
                if keyword.arg == OWNER_KEYWORD and _is_uuid4_call(keyword.value) and id(keyword) not in seen:
                    seen.add(id(keyword))
                    source = ast.get_source_segment(source_text, call) or PATTERN
                    findings.append(
                        DetachedOwnerFinding(
                            relative_path=relative_path,
                            line=keyword.value.lineno,
                            pattern=PATTERN,
                            source=" ".join(source.split()),
                        )
                    )
    return findings


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
