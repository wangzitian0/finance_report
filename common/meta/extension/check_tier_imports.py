#!/usr/bin/env python3
"""Cross-tier AST gate: CODE-ONLY/financial-truth modules must not import the LLM layer."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_cli_command
from common.meta.base.gate_util import read_text_cached

REPO_ROOT = Path(__file__).resolve().parents[3]

PROTECTED_MODULE_GLOBS: tuple[str, ...] = (
    "apps/backend/src/audit/money/**/*.py",
    "apps/backend/src/ledger/**/*.py",
    "apps/backend/src/extraction/extension/deduplication.py",
    "apps/backend/src/ledger/extension/accounting.py",
    "apps/backend/src/ledger/extension/account_service.py",
    "apps/backend/src/portfolio/extension/accounting.py",
    "apps/backend/src/extraction/extension/statement_posting.py",
    "apps/backend/src/reporting/**/*.py",
    "apps/backend/src/pricing/extension/valuation.py",
    "apps/backend/src/extraction/base/validation.py",
    "apps/backend/src/extraction/extension/statement_validation.py",
    "apps/backend/src/pricing/extension/fx.py",
    "apps/backend/src/ledger/extension/fx_revaluation.py",
    "apps/backend/src/reconciliation/extension/fx_transfer.py",
    "apps/backend/src/reconciliation/extension/fx_transfer_discovery.py",
    "apps/backend/src/portfolio/extension/holdings.py",
    "apps/backend/src/portfolio/extension/performance.py",
    "apps/backend/src/portfolio/extension/performance_report.py",
    "apps/backend/src/portfolio/extension/allocation.py",
)

FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    "src.llm",
    "apps.backend.src.llm",
    "litellm",
    "openrouter",
    "anthropic",
    "openai",
)


def _matches_forbidden(module: str) -> str | None:
    """Return the matched forbidden prefix for *module*, or ``None``.

    Prefix match is on dotted-path boundaries: ``src.llm`` matches ``src.llm``
    and ``src.llm.extension.client`` but not ``src.llmx`` or ``src.llm_helpers``.
    """
    for prefix in FORBIDDEN_IMPORT_PREFIXES:
        if module == prefix or module.startswith(prefix + "."):
            return prefix
    return None


def imported_modules(source: str) -> list[str]:
    """Return the dotted module/name targets imported by *source* (direct only).

    Parses with :mod:`ast`. ``import a.b, c`` yields ``["a.b", "c"]``. For
    ``from a.b import x, y`` we yield the source module *and* each imported name
    qualified onto it (``["a.b", "a.b.x", "a.b.y"]``) — so that ``from src import
    llm`` surfaces ``src.llm`` and is caught, not just the bare parent ``src``.
    Relative imports (``from . import x``) yield nothing — they cannot reference
    the LLM layer by name and v1 does not resolve them.
    """
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # node.level > 0 => relative import; node.module may be None.
            if node.level == 0 and node.module:
                modules.append(node.module)
                # `from pkg import name` also pulls `pkg.name` into scope; check
                # it so the forbidden layer cannot be reached via its parent
                # package (e.g. `from src import llm` -> `src.llm`).
                modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def forbidden_imports_in_source(source: str) -> list[tuple[str, str]]:
    """Return ``(imported_module, matched_forbidden_prefix)`` pairs in *source*.

    Pure function over source text — used by the gate and by tests against
    synthetic fixtures (no need to touch the real tree).

    At most ONE pair is reported per matched forbidden prefix, keyed to the
    shortest imported target that triggered it. This keeps output deterministic
    and avoids double-reporting: ``from src.llm.extension.client import X`` expands (via
    :func:`imported_modules`) to both ``src.llm.extension.client`` and
    ``src.llm.extension.client.X`` — both match ``src.llm``, but only ``src.llm.extension.client``
    is reported.
    """
    best: dict[str, str] = {}
    for module in imported_modules(source):
        matched = _matches_forbidden(module)
        if matched is None:
            continue
        current = best.get(matched)
        if current is None or len(module) < len(current):
            best[matched] = module
    return [(module, matched) for matched, module in best.items()]


def resolve_protected_files(repo_root: Path) -> list[Path]:
    """Expand :data:`PROTECTED_MODULE_GLOBS` to existing files under *repo_root*.

    Sorted + de-duplicated. Globs that resolve to nothing are reported by
    :func:`missing_protected_globs` so the curated set stays honest as the tree
    evolves.
    """
    seen: set[Path] = set()
    for glob in PROTECTED_MODULE_GLOBS:
        for path in repo_root.glob(glob):
            if path.is_file():
                seen.add(path)
    return sorted(seen)


def missing_protected_globs(repo_root: Path) -> list[str]:
    """Return protected globs that currently match no file (curation drift)."""
    return [
        glob
        for glob in PROTECTED_MODULE_GLOBS
        if not any(p.is_file() for p in repo_root.glob(glob))
    ]


def violations(repo_root: Path) -> list[tuple[str, str, str]]:
    """Scan the protected set; return ``(module_path, imported, forbidden)`` triples.

    ``module_path`` is repo-root-relative for stable, readable output.
    """
    found: list[tuple[str, str, str]] = []
    for path in resolve_protected_files(repo_root):
        source = read_text_cached(path)
        rel = path.relative_to(repo_root).as_posix()
        for imported, matched in forbidden_imports_in_source(source):
            found.append((rel, imported, matched))
    return found


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-tier structural gate: CODE-ONLY/financial-truth modules MUST NOT "
            "import the LLM layer (common/meta/readme.md)."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def _main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()

    missing = missing_protected_globs(repo_root)
    if missing:
        for glob in missing:
            print(
                f"::error title=Tier import guard::protected glob {glob!r} matched "
                "no file — the curated PROTECTED_MODULE_GLOBS set has drifted from "
                "the tree (see common/meta/readme.md).",
                file=sys.stderr,
            )
        print(
            f"[TIER-IMPORTS] FAILED: {len(missing)} protected glob(s) resolve to "
            "no file; fix the curated set so the guard cannot silently shrink.",
            file=sys.stderr,
        )
        return 1

    found = violations(repo_root)
    if found:
        for module_path, imported, matched in found:
            print(
                f"::error title=Tier import guard::{module_path} imports {imported!r} "
                f"(forbidden LLM-layer target {matched!r}). A CODE-ONLY/financial-truth "
                "module MUST NOT depend on the LLM layer "
                "(common/meta/readme.md, cross-tier MUST rule 2).",
                file=sys.stderr,
            )
        print(
            f"[TIER-IMPORTS] FAILED: {len(found)} forbidden LLM-layer import(s) in "
            "CODE-ONLY/financial-truth modules. The deterministic core must stay pure.",
            file=sys.stderr,
        )
        return 1

    n_files = len(resolve_protected_files(repo_root))
    print(
        f"[TIER-IMPORTS] PASSED: {n_files} protected CODE-ONLY/financial-truth module(s) "
        "import no LLM layer (src.llm / litellm / openrouter / anthropic / openai)."
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli_command(_main, argv)


if __name__ == "__main__":
    raise SystemExit(main())
