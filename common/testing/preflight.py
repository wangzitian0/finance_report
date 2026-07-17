"""Diff-aware pre-push verification dispatcher.

The repo enforces a strict set of gates in CI and pre-commit (EPIC -> AC -> test
traceability, SSOT ownership, doc-nav consistency, schema contracts, migration
risk, env-key consistency, ruff, the transaction-boundary meta-test). Knowing
*which* of those to run after a given change is tribal knowledge — easy to forget,
so failures surface only after pushing.

This module maps changed files to the relevant gate commands and runs only those,
so an agent or operator catches problems locally first. It does not replace any CI
gate; it mirrors a subset of them, scoped to the diff.

The deterministic check scripts stay where they are (``tools/`` + ``common/``);
this is only the dispatcher. ``runner`` and ``git`` are injectable so the mapping
and orchestration are unit-testable without spawning processes.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Placeholder in a command that is replaced with the running interpreter, so the
# sub-checks run under the same Python (and therefore the same dependencies).
PY = "{python}"
# A command can ask for exactly the paths that selected its check. This keeps
# debt-aware validators scoped to the diff instead of turning old violations
# into false failures for an unrelated schema edit.
MATCHING_PATHS = "{matching_paths}"

Runner = Callable[[Sequence[str], str], int]
Git = Callable[[Sequence[str]], str]


# Check tiers (#1810 G-static-parity): "static" gates are seconds-level file
# parsers — the mandatory pre-push parity set; "heavy" gates run whole test or
# build suites (minutes-level) and are opted into via --tier=heavy/full.
TIERS: tuple[str, ...] = ("static", "heavy")


@dataclass(frozen=True)
class Check:
    """A named gate: run ``commands`` when a changed path matches a ``glob``.

    ``cwd`` is the working directory (relative to the repo root) the commands run
    in. Backend gates use ``apps/backend`` so ``ruff`` discovers the backend Ruff
    config and ``pytest`` can import ``src.*`` — matching how CI invokes them.

    ``tier`` classifies the gate's cost (see :data:`TIERS`): ``static`` for the
    seconds-level checks, ``heavy`` for the expensive suite/build gates.
    """

    name: str
    globs: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    why: str
    cwd: str = "."
    tier: str = "static"


# Ordered cheapest/most-localizing first. ``fnmatch`` treats ``*`` as matching
# across ``/`` too, so a single ``*`` already spans nested directories.
CHECKS: tuple[Check, ...] = (
    Check(
        name="ac-traceability",
        globs=(
            "docs/project/EPIC*.md",
            "docs/ac_registry*.yaml",
            "docs/infra_registry*.yaml",
        ),
        commands=(
            (PY, "tools/generate_ac_registry.py"),
            # The single AC-index gate (matches CI): its INTEGRITY gate folds in
            # the former standalone CI-stage traceability and critical-proof-matrix
            # contracts, so local preflight runs exactly what CI enforces.
            (PY, "tools/check_ac_index.py"),
        ),
        why="EPIC/AC changed: regenerate the registry and re-run the single AC-index gate (folds in EPIC->AC->test traceability + critical-proof contract)",
    ),
    Check(
        name="ssot-ownership",
        # docs/ssot/ is retired (#1823); the concept registry lives at
        # common/meta/data/MANIFEST.yaml now, so that path (not the dead
        # directory) is what should re-trigger this gate.
        globs=("common/meta/data/MANIFEST.yaml",),
        commands=(
            (PY, "tools/check_ssot_ownership.py"),
            (PY, "tools/check_manifest.py"),
        ),
        why="Concept registry changed: enforce single-owner + manifest integrity",
    ),
    Check(
        name="authority-reconcile",
        globs=(
            "common/*/contract.py",
            "tests/*.py",
            "apps/backend/tests/*.py",
            "apps/frontend/*.test.ts",
            "apps/frontend/*.test.tsx",
            "apps/frontend/*.spec.ts",
            "apps/frontend/*.spec.tsx",
            "common/meta/base/authority_matrix.py",
            "common/meta/extension/authority_classifier.py",
            "common/meta/extension/check_authority_reconcile.py",
            "common/meta/extension/generate_ac_registry.py",
        ),
        commands=((PY, "tools/check_authority_reconcile.py"),),
        why="Authority input changed: declared package tiers must still match the CODE/LLM shape of their roadmap proofs",
    ),
    Check(
        name="doc-consistency",
        globs=("docs/*", "mkdocs.yml", "vision.md", "README.md"),
        commands=((PY, "tools/lint_doc_consistency.py"),),
        why="docs changed: nav coverage + cross-reference consistency",
    ),
    Check(
        name="taxonomy-drift",
        globs=(
            "*.md",
            "common/meta/data/*.yaml",
            "tests/*.py",
            "common/*.py",
            "tools/*.py",
        ),
        commands=((PY, "tools/check_taxonomy_drift.py"),),
        why="prose/tests changed: retired package-taxonomy vocabulary must not be presented as current (AC-meta.vocab.1)",
    ),
    Check(
        name="schema-validate",
        globs=("apps/backend/src/schemas/*.py",),
        commands=((PY, "tools/validate_schemas.py", "--paths", MATCHING_PATHS),),
        why="Pydantic schema changed: validate schema contracts",
    ),
    Check(
        name="api-reference",
        globs=(
            "apps/backend/src/routers/*.py",
            "apps/backend/src/schemas/*.py",
            "apps/backend/src/main.py",
        ),
        commands=((PY, "../../tools/generate_api_reference.py", "--check"),),
        why="router/schema changed: the generated OpenAPI reference (docs/reference/api.md) must be regenerated — mirrors the CI 'Generated API Reference Check' Lint gate",
        cwd="apps/backend",
    ),
    Check(
        name="router-contract",
        globs=("apps/backend/src/routers/*.py",),
        commands=(
            (
                PY,
                "-m",
                "pytest",
                "tests/tooling/test_audit_router_contracts.py::test_findings_doc_is_in_sync",
                "-q",
                "--no-cov",
            ),
        ),
        why="router changed: docs/reference/router-contract-maturity.md must be regenerated (tools/audit_router_contracts.py --output ...) — mirrors the CI Tooling/Common Coverage gate",
    ),
    Check(
        name="migration-risk",
        globs=("apps/backend/migrations/*",),
        commands=((PY, "tools/check_migration_risk.py"),),
        why="Alembic migration changed: classify migration risk",
    ),
    Check(
        name="env-keys",
        globs=(".env.example", ".env", ".env.*"),
        commands=((PY, "tools/check_env_keys.py"),),
        why="env files changed: env-var key consistency",
    ),
    Check(
        name="backend-format",
        globs=("apps/backend/*.py",),
        commands=(
            # Run Ruff from the same venv as the dispatcher.  Resolving a bare
            # shell command can select an unrelated global Ruff version.
            (PY, "-m", "ruff", "check", "src", "tests"),
            (PY, "-m", "ruff", "format", "--check", "src", "tests"),
        ),
        why="backend Python changed: ruff lint + format check",
        cwd="apps/backend",
    ),
    Check(
        name="transaction-boundary",
        globs=("apps/backend/src/extraction/extension/statement_*.py",),
        commands=(
            (
                PY,
                "-m",
                "pytest",
                "tests/infra/test_transaction_boundaries.py",
                "-q",
                "--no-cov",
            ),
        ),
        why="service changed: re-run the commit/transaction-boundary meta-test",
        cwd="apps/backend",
    ),
    Check(
        name="env-reference",
        globs=("apps/backend/src/config.py",),
        commands=((PY, "tools/generate_env_reference.py", "--check"),),
        why="config.py changed: regenerate .env.example + env reference and assert no drift",
    ),
    Check(
        name="openapi-spec",
        globs=(
            "apps/backend/src/routers/*.py",
            "apps/backend/src/schemas/*.py",
            "apps/backend/src/main.py",
        ),
        commands=((PY, "tools/generate_openapi_spec.py", "--check"),),
        why="router/schema changed: the committed apps/frontend/openapi.json (source for the generated FE api-types) must be regenerated — enforces the FE↔BE contract (#1004)",
    ),
    Check(
        name="gate-contracts",
        globs=("common/*", "tools/*", "tests/tooling/*.py"),
        commands=(
            (PY, "tools/check_gate_main_contract.py"),
            (PY, "tools/check_baseline_update_contract.py"),
            (PY, "tools/check_tool_shim_contract.py"),
        ),
        why="gate source or proof changed: prevent new gate, baseline-mutation, and fat-tool entry-point debt",
    ),
    Check(
        name="tooling",
        globs=("tools/*", "common/*"),
        commands=((PY, "-m", "pytest", "tests/tooling/", "-q", "--no-cov"),),
        why="tooling/common changed: run tests/tooling (tool-wrapper sys.path contract + dispatchers)",
        tier="heavy",
    ),
    Check(
        name="app-boundary",
        globs=("apps/backend/src/*.py",),
        commands=((PY, "tools/check_app_boundary.py"),),
        why="backend source changed: the L4 backend super-package edge ratchet — no NEW "
        "cross-boundary edge (remainder↔carved package) may appear; the baseline only shrinks",
    ),
    Check(
        name="frontend",
        globs=("apps/frontend/*",),
        commands=(
            ("npm", "run", "lint"),
            ("npm", "run", "test:coverage"),
            ("npm", "run", "build"),
        ),
        why="frontend changed: eslint + vitest coverage gate + next build (layout/route type rules)",
        cwd="apps/frontend",
        tier="heavy",
    ),
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool


def _matches(path: str, glob: str) -> bool:
    return fnmatch.fnmatch(path, glob)


def select_checks(
    changed_files: Iterable[str],
    *,
    checks: Sequence[Check] = CHECKS,
    tier: str = "full",
) -> list[Check]:
    """Return the checks whose globs match at least one changed file (in order).

    ``tier`` composes with the glob selection: ``"full"`` (default) keeps every
    matching check — the exact pre-tier behavior; a named tier (:data:`TIERS`)
    keeps only the matching checks of that tier.
    """
    if tier != "full" and tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}: expected one of {('full', *TIERS)}")
    files = list(changed_files)
    return [
        check
        for check in checks
        if (tier == "full" or check.tier == tier)
        and any(_matches(f, g) for f in files for g in check.globs)
    ]


def _default_git(args: Sequence[str]) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout


def changed_files(base: str | None = None, *, git: Git = _default_git) -> list[str]:
    """Union of committed-vs-base, staged, unstaged, and untracked paths.

    Untracked files are included (via ``ls-files --others``) so a brand-new file —
    which ``git diff`` does not report — is still checked before it is committed.
    """
    if base is None:
        base = git(["merge-base", "HEAD", "origin/main"]).strip() or "HEAD"
    out: set[str] = set()
    commands = (
        ["diff", "--name-only", base],
        ["diff", "--name-only"],
        ["diff", "--name-only", "--cached"],
        ["ls-files", "--others", "--exclude-standard"],
    )
    for args in commands:
        out.update(line for line in git(args).splitlines() if line.strip())
    return sorted(out)


def _default_runner(argv: Sequence[str], cwd: str) -> int:
    return subprocess.run(list(argv), cwd=cwd, check=False).returncode


def _resolve(
    command: tuple[str, ...],
    python: str,
    *,
    matching_paths: Sequence[str] = (),
) -> list[str]:
    resolved: list[str] = []
    for part in command:
        if part == PY:
            resolved.append(python)
        elif part == MATCHING_PATHS:
            resolved.extend(matching_paths)
        else:
            resolved.append(part)
    return resolved


def run_checks(
    checks: Sequence[Check],
    *,
    changed_files: Sequence[str] = (),
    runner: Runner = _default_runner,
    python: str | None = None,
) -> list[CheckResult]:
    """Run each check's commands; a check fails fast on the first non-zero command."""
    python = python or sys.executable
    results: list[CheckResult] = []
    for check in checks:
        cwd = str(REPO_ROOT / check.cwd)
        matching_paths = tuple(
            path
            for path in changed_files
            if any(_matches(path, glob) for glob in check.globs)
        )
        ok = True
        for command in check.commands:
            if runner(_resolve(command, python, matching_paths=matching_paths), cwd) != 0:
                ok = False
                break
        results.append(CheckResult(check.name, ok))
    return results


def run(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _default_runner,
    git: Git = _default_git,
) -> int:
    parser = argparse.ArgumentParser(
        description="Run the gate checks relevant to the current diff."
    )
    parser.add_argument(
        "--base", default=None, help="Diff base (default: merge-base with origin/main)."
    )
    parser.add_argument(
        "--list", action="store_true", help="List the checks that would run, then exit."
    )
    parser.add_argument(
        "--changed",
        nargs="*",
        default=None,
        help="Explicit changed-file list (overrides git; for scripting/tests).",
    )
    parser.add_argument(
        "--tier",
        choices=("full", *TIERS),
        default="full",
        help=(
            "Which cost tier to run: 'static' = the seconds-level pre-push "
            "parity gates, 'heavy' = the expensive suite/build gates, "
            "'full' (default) = both."
        ),
    )
    args = parser.parse_args(argv)

    files = (
        args.changed if args.changed is not None else changed_files(args.base, git=git)
    )
    selected = select_checks(files, tier=args.tier)

    if not selected:
        print("preflight: no relevant gates for the current diff.")
        return 0

    if args.list:
        for check in selected:
            print(f"  [{check.tier}] {check.name}: {check.why}")
        return 0

    print(
        f"preflight: running {len(selected)} gate(s) for {len(files)} changed file(s)..."
    )
    results = run_checks(selected, changed_files=files, runner=runner)
    for result in results:
        print(f"  [{'ok' if result.ok else 'FAIL'}] {result.name}")
    failed = [r.name for r in results if not r.ok]
    if failed:
        print(f"preflight: {len(failed)} gate(s) failed: {', '.join(failed)}")
        return 1
    print("preflight: all relevant gates passed.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)
