#!/usr/bin/env python3
"""Cross-tier STRUCTURAL gate: CODE-ONLY / financial-truth modules MUST NOT import the LLM layer.

EPIC-026 phase 3. The authority-tier SSOT (``common/meta/readme.md``,
"Cross-tier MUST rules", rule 2) states:

    **CODE-ONLY stays pure.** A CODE-ONLY AC MUST NOT depend on an LLM client; its outcome is
    produced and proven by deterministic code alone.

Phases 1 and 2 made the *per-AC* tier and proof-kind contracts machine-checkable.
This gate makes the *structural* half of rule 2 deterministic: a curated set of
deterministic financial-truth (CODE-ONLY) modules is statically proven, via the ``ast``
module, to contain no import of the LLM layer (``src.llm``) or of any raw LLM
SDK/provider (``litellm`` / ``openrouter`` / ``anthropic`` / ``openai``).

This is a *guard against regression*: on ``main`` today none of the protected
modules imports the LLM layer, so the gate starts GREEN. Its job is to keep the
deterministic core deterministic — to stop an LLM client from silently leaking
into a money/accounting/reporting path where a wrong, unverifiable output could
become financial truth.

Scope (v1, deliberately simple + false-positive-free):

- **Direct imports only.** We flag a module only for the imports written in its
  own source (``import X`` / ``from X import ...``). We do not follow the import
  graph transitively — a v2 follow-up. Direct detection already enforces the
  structural MUST rule at the boundary that matters (a CODE-ONLY module reaching for an
  LLM client) without guessing at deep, conditional, or runtime imports.
- **Name-prefixed matching.** ``src.llm`` matches ``src.llm`` and any submodule
  (``src.llm.extension.client``), but never an unrelated module that merely starts with the
  same letters (``src.llmx`` would not match; ``src.llm_helpers`` would not match).

The protected set and forbidden targets below are the machine-checkable mirror of
the SSOT rule; ``common/meta/readme.md`` is the single source of truth.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# --- The contract (mirror of common/meta/readme.md "Cross-tier MUST
# --- rules", rule 2). Keep these in sync with the SSOT subsection.

# Protected CODE-ONLY / financial-truth modules, as path globs relative to the repo
# root. These are deterministic modules whose output can become financial truth;
# none of them may import the LLM layer. Each glob is confirmed to resolve to at
# least one real file (see ``missing_protected_globs``).
PROTECTED_MODULE_GLOBS: tuple[str, ...] = (
    # money primitives + the ledger/journal core
    "apps/backend/src/audit/money/**/*.py",
    "apps/backend/src/ledger/**/*.py",
    "apps/backend/src/models/journal.py",
    # deterministic financial-truth services
    "apps/backend/src/extraction/extension/deduplication.py",
    "apps/backend/src/services/accounting.py",
    "apps/backend/src/services/account_service.py",
    "apps/backend/src/portfolio/extension/accounting.py",
    "apps/backend/src/services/statement_posting.py",
    "apps/backend/src/services/reporting/**/*.py",
    "apps/backend/src/services/reporting_calc.py",
    "apps/backend/src/services/reporting_snapshot.py",
    "apps/backend/src/extraction/base/validation.py",
    "apps/backend/src/services/statement_validation.py",
    # FX (deterministic conversion / revaluation / transfer math)
    "apps/backend/src/services/fx.py",
    "apps/backend/src/services/fx_revaluation.py",
    "apps/backend/src/services/fx_transfer.py",
    "apps/backend/src/services/fx_transfer_discovery.py",
    # portfolio / performance / allocation deterministic calc
    "apps/backend/src/services/portfolio.py",
    "apps/backend/src/services/performance.py",
    "apps/backend/src/services/performance_report.py",
    "apps/backend/src/services/allocation.py",
)

# Forbidden import targets. A protected module may not import any of these, nor
# any submodule of them (prefix match on the dotted module path).
FORBIDDEN_IMPORT_PREFIXES: tuple[str, ...] = (
    # the project's own LLM layer (the backend imports it as ``src.llm``)
    "src.llm",
    "apps.backend.src.llm",
    # raw LLM SDKs / provider clients
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
        source = path.read_text(encoding="utf-8")
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args([] if argv is None else argv)
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
