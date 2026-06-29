"""Narrow-waist guard — keep the money standard from eroding (#1167 / #1172).

Two invariants this guard enforces so the money "narrow waist" cannot silently
decay back into ad-hoc money handling:

1. **No ``float`` in the money modules.** The whole point of the value types is
   that ``float`` is unrepresentable for money. A ``float(...)`` cast or a
   ``: float`` annotation inside the money modules would reopen the red line.
   (``isinstance(x, float)`` — the *rejection* of float — is explicitly allowed.)

2. **A conformance suite per stack.** The cross-language standard
   (``common/money/conformance/vectors.json``) is only meaningful if every stack
   actually runs it. If a stack's conformance suite is deleted/renamed, the two
   ends can drift again — so its absence is a violation.

Pure functions over text/paths so the gate test can both scan the real tree
(expects clean) and an injected sample (expects a violation).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _annotation_is_float(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Name) and node.id == "float"


def scan_text_for_float(text: str) -> list[str]:
    """Return offending ``float`` uses in money *type positions*.

    Uses ``ast`` so it flags only the real things — a ``float(...)`` call or a
    ``: float`` / ``-> float`` annotation — and never docstring/comment prose or
    ``isinstance(x, float)`` (which is the *rejection* of float, the desired
    behaviour). Returns ``"<lineno>: float as <kind>"`` strings.
    """
    tree = ast.parse(text)
    offending: list[str] = []
    for node in ast.walk(tree):
        # float(...) cast
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "float"
        ):
            offending.append(f"{node.lineno}: float as cast")
        # def / async def f(x: float, *args: float, **kwargs: float) -> float
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _annotation_is_float(node.returns):
                offending.append(f"{node.lineno}: float as return annotation")
            args = node.args
            for arg in [
                *args.args,
                *args.posonlyargs,
                *args.kwonlyargs,
                args.vararg,
                args.kwarg,
            ]:
                if arg is not None and _annotation_is_float(arg.annotation):
                    offending.append(f"{arg.lineno}: float as parameter annotation")
        # x: float = ...
        elif isinstance(node, ast.AnnAssign) and _annotation_is_float(node.annotation):
            offending.append(f"{node.lineno}: float as variable annotation")
    return sorted(set(offending))


def python_money_module_paths(repo_root: Path = REPO_ROOT) -> list[Path]:
    """Python files that make up the money narrow waist (the runtime impls)."""
    roots = [
        repo_root / "common" / "money",
        repo_root / "apps" / "backend" / "src" / "money",
    ]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(
                sorted(p for p in root.rglob("*.py") if "conformance" not in p.parts)
            )
    return files


def float_violations(repo_root: Path = REPO_ROOT) -> list[str]:
    """Scan the money modules; return ``path:line`` violations (empty == clean)."""
    violations: list[str] = []
    for path in python_money_module_paths(repo_root):
        for hit in scan_text_for_float(path.read_text(encoding="utf-8")):
            violations.append(f"{path.relative_to(repo_root).as_posix()}:{hit}")
    return violations


# One conformance suite per stack that consumes the standard. Absence == drift.
REQUIRED_CONFORMANCE_SUITES = (
    "tests/tooling/test_money_conformance.py",  # Python reference impl
    "apps/backend/tests/money/test_money_conformance_backend.py",  # shipped backend path
    "apps/frontend/src/lib/money/money.conformance.test.ts",  # frontend impl
)


def missing_conformance_suites(repo_root: Path = REPO_ROOT) -> list[str]:
    """Return required conformance suites that are absent (empty == all present)."""
    return [
        rel for rel in REQUIRED_CONFORMANCE_SUITES if not (repo_root / rel).exists()
    ]
