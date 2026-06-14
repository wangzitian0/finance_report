"""Router contract-maturity audit: find HTTP endpoints with no typed response model.

The kickoff slice of #1000 (end-to-end module maturity audit). An endpoint that
declares no ``response_model`` returns an *untyped* body — the OpenAPI schema and
the generated API reference cannot describe its contract, and clients have no
typed shape to bind to. That is the clearest, most mechanical contract gap, so it
is the first thing this audit pins.

This is a **budget gate**, not a big-bang cleanup: the current count of untyped
endpoints is a non-growth ceiling (like ``detached_owner_guard``). New untyped
endpoints fail the gate; the ceiling only ratchets *down* as gaps are typed.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROUTER_DIR = Path("apps/backend/src/routers")
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

# Non-growth ceiling. Lower this as endpoints gain a response_model; never raise it.
# The remaining 10 are legitimately-bodiless handlers (204 DELETEs, file/stream
# exports) — see the generated findings doc. #1008 typed the last two real gaps
# (list_report_snapshots, update_prices), ratcheting this from 12 down to 10.
# The gate stops the count growing; it ratchets down as gaps close.
DEFAULT_MAX_UNTYPED_ENDPOINTS = 10


@dataclass(frozen=True, order=True)
class UntypedEndpoint:
    """One HTTP endpoint declared without a response_model."""

    relative_path: str
    line: int
    method: str
    route: str
    handler: str


def _router_names(tree: ast.AST) -> set[str]:
    """Names bound to an ``APIRouter()`` in this module (plus the conventional ``app``).

    A module may declare more than one router (e.g. ``router`` and ``conflicts_router``
    in review.py); hardcoding ``{"router", "app"}`` would let endpoints on any other
    router bypass the gate, so the set is derived from the actual assignments.
    """
    names = {"app"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            callee = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if callee == "APIRouter":
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _route_decorators(node: ast.AST, router_names: set[str]) -> Iterable[tuple[str, ast.Call]]:
    """Yield (http_method, call) for each @<router>.<method>(...) decorator on a function."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return
    for deco in node.decorator_list:
        if (
            isinstance(deco, ast.Call)
            and isinstance(deco.func, ast.Attribute)
            and deco.func.attr in _HTTP_METHODS
            and isinstance(deco.func.value, ast.Name)
            and deco.func.value.id in router_names
        ):
            yield deco.func.attr, deco


def _has_response_model(call: ast.Call) -> bool:
    """True only if a *non-None* response_model is declared.

    ``response_model=None`` is an untyped/undocumented contract — counting it as
    typed would let the gate be silenced without actually adding a schema.
    """
    for kw in call.keywords:
        if kw.arg == "response_model":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
    return False


def _route_literal(call: ast.Call) -> str:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return "?"


def scan_file(path: Path, *, repo_root: Path) -> list[UntypedEndpoint]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError:
        rel = path.as_posix()

    router_names = _router_names(tree)
    findings: list[UntypedEndpoint] = []
    for node in ast.walk(tree):
        for method, call in _route_decorators(node, router_names):
            if not _has_response_model(call):
                # Status-only / 204 handlers are legitimately bodiless, but they should
                # still be explicit; we surface them so the decision is recorded, not hidden.
                findings.append(
                    UntypedEndpoint(
                        relative_path=rel,
                        line=node.lineno,
                        method=method.upper(),
                        route=_route_literal(call),
                        handler=node.name,
                    )
                )
    return findings


def scan_dir(router_dir: Path, *, repo_root: Path) -> list[UntypedEndpoint]:
    findings: list[UntypedEndpoint] = []
    for path in sorted(router_dir.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        findings.extend(scan_file(path, repo_root=repo_root))
    return sorted(findings)


def render_markdown(findings: Sequence[UntypedEndpoint]) -> str:
    lines = [
        "# Router Contract Maturity — Untyped Endpoints",
        "",
        "Kickoff of [#1000](https://github.com/wangzitian0/finance_report/issues/1000). "
        "Endpoints below declare no (non-`None`) `response_model`, so their response "
        "contract is absent from the OpenAPI schema. Type them (or document why a "
        "status-only handler is intentional) and lower the budget "
        "(`DEFAULT_MAX_UNTYPED_ENDPOINTS` in `common/ssot/audit_router_contracts.py`).",
        "",
        f"**Untyped endpoints: {len(findings)}**",
        "",
        "The `Route` column is **router-relative** — it excludes the `APIRouter(prefix=...)` "
        "(e.g. `/accounts`), so combine it with the router's prefix to get the full path.",
        "",
        "| Method | Route (router-relative) | Handler | File:line |",
        "|--------|-------------------------|---------|-----------|",
    ]
    for f in findings:
        lines.append(f"| `{f.method}` | `{f.route}` | `{f.handler}` | {f.relative_path}:{f.line} |")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit router endpoints for missing response_model contracts.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--router-dir", type=Path, default=None)
    parser.add_argument("--max-allowed", type=int, default=DEFAULT_MAX_UNTYPED_ENDPOINTS)
    parser.add_argument("--output", type=Path, default=None, help="Write the findings markdown here.")
    parser.add_argument("--check", action="store_true", help="Exit nonzero if the budget is exceeded.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    router_dir = (args.router_dir or (repo_root / DEFAULT_ROUTER_DIR)).resolve()
    findings = scan_dir(router_dir, repo_root=repo_root)

    if args.output:
        args.output.write_text(render_markdown(findings), encoding="utf-8")

    count = len(findings)
    if args.check and count > args.max_allowed:
        print(
            f"Untyped-endpoint count {count} exceeds budget {args.max_allowed}. "
            f"Add a response_model or lower the budget.",
            file=sys.stderr,
        )
        for f in findings:
            print(f"  {f.relative_path}:{f.line}: {f.method} {f.route} ({f.handler})", file=sys.stderr)
        return 1

    print(f"Untyped endpoints: {count} (budget {args.max_allowed}).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
