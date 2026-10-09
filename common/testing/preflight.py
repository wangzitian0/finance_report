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
import os
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

    ``advisory`` classifies whether the gate can be relaxed: under ``--relaxed``
    or ``PREFLIGHT_RELAXED=1``, advisory checks emit warnings instead of
    blocking exit with non-zero status.
    """

    name: str
    globs: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    why: str
    cwd: str = "."
    tier: str = "static"
    advisory: bool = False


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
        name="ac-proof-traceability",
        globs=(
            "tests/*.py",
            "apps/backend/tests/*.py",
            "apps/frontend/*.test.ts",
            "apps/frontend/*.test.tsx",
            "apps/frontend/*.spec.ts",
            "apps/frontend/*.spec.tsx",
        ),
        commands=((PY, "tools/check_ac_index.py"),),
        why="Test proof changed: re-run the single AC-index integrity gate so every declared AC reference remains discoverable before CI",
    ),
    Check(
        name="ssot-ownership",
        # docs/ssot/ is retired (#1823); the concept registry lives at
        # common/meta/data/MANIFEST.yaml now, so that path (not the dead
        # directory) is what should re-trigger this gate.
        globs=("common/meta/data/MANIFEST.yaml", "common/*/contract.py"),
        commands=(
            (PY, "tools/check_ssot_ownership.py"),
            (PY, "tools/check_manifest.py"),
        ),
        why="Concept registry or contract changed: enforce single-owner + manifest integrity",
    ),
    Check(
        name="doc-consistency",
        globs=("docs/*", "mkdocs.yml", "vision.md", "README.md"),
        commands=((PY, "tools/lint_doc_consistency.py"),),
        why="docs changed: nav coverage + cross-reference consistency",
        advisory=True,
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
        advisory=True,
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
            "apps/backend/src/*/extension/api/*.py",
            "apps/backend/src/schemas/*.py",
            "apps/backend/src/main.py",
        ),
        commands=((PY, "../../tools/generate_api_reference.py", "--check"),),
        why="router/schema changed: the generated OpenAPI reference (docs/reference/api.md) must be regenerated — mirrors the CI 'Generated API Reference Check' Lint gate",
        cwd="apps/backend",
        advisory=True,
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
        advisory=True,
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
        name="bench-articulation",
        globs=(
            "apps/backend/src/ledger/*.py",
            "apps/backend/src/pricing/*.py",
            "apps/backend/src/reporting/*.py",
            "apps/backend/tests/reporting/test_bench_articulation_matrix.py",
        ),
        commands=(
            (
                PY,
                "-m",
                "pytest",
                "tests/reporting/test_bench_articulation_matrix.py",
                "-q",
                "--no-cov",
            ),
        ),
        why="financial calculation logic changed: in-memory BenchV2 articulation matrix must balance",
        cwd="apps/backend",
        tier="static",
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
        commands=(
            (PY, "tools/generate_openapi_spec.py", "--check"),
            ("npm", "--prefix", "apps/frontend", "run", "check:api-types"),
        ),
        why="router/schema changed: openapi.json and frontend api-types must remain in sync (#1004, #2134)",
    ),
    Check(
        name="package-migration-safety",
        globs=(
            "common/*",
            "tools/*",
            "tests/*",
            "apps/backend/tests/*",
            "apps/frontend/*.test.ts",
            "apps/frontend/*.test.tsx",
            "apps/frontend/*.spec.ts",
            "apps/frontend/*.spec.tsx",
            "docs/project/EPIC*.md",
        ),
        commands=((PY, "tools/check_package_migration_safety.py"),),
        why="gate source, contracts, or test proofs changed: validate consolidated package migration safety gates",
    ),
    Check(
        name="workflow-contract",
        globs=(
            ".github/workflows/*.yml",
            ".github/ISSUE_TEMPLATE/*.yml",
            "common/testing/ci-cd.md",
            "common/runtime/deployment.md",
            "common/runtime/environments.md",
            "tools/check_workflow_contract.py",
            "common/meta/extension/workflow_contract.py",
        ),
        commands=((PY, "tools/check_workflow_contract.py"),),
        why="CI workflows, deployment/environment docs, or issue templates changed: validate workflow contract and taxonomy",
        advisory=True,
    ),
    Check(
        name="governance-exceptions",
        globs=(
            "common/meta/data/governance-exceptions.yaml",
            "tools/check_governance_exceptions.py",
            "common/meta/extension/check_governance_exceptions.py",
        ),
        commands=((PY, "tools/check_governance_exceptions.py"),),
        why="governance exceptions changed: validate bottom-up proof-exception registry",
        advisory=True,
    ),
    Check(
        name="context-contract",
        globs=(
            "common/*/contract.py",
            "common/meta/base/package_contract.py",
            "common/meta/extension/check_context_contract.py",
            "tools/check_context_contract.py",
        ),
        commands=((PY, "tools/check_context_contract.py"),),
        why="package contract or context gate changed: context declarations and dependency semantics only shrink from the audited baseline",
        advisory=True,
    ),
    Check(
        name="semantic-ownership",
        globs=(
            "common/*/contract.py",
            "common/meta/base/package_contract.py",
            "common/meta/extension/check_semantic_ownership.py",
            "tools/check_semantic_ownership.py",
        ),
        commands=((PY, "tools/check_semantic_ownership.py"),),
        why="package semantic declarations changed: every governed DDD concept must retain one canonical owner",
        advisory=True,
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
        advisory=True,
    ),
    Check(
        name="public-orm-exports",
        globs=(
            "apps/backend/src/*/__init__.py",
            "common/meta/data/public-orm-export-baseline.json",
            "common/meta/extension/public_orm_exports.py",
            "common/meta/extension/check_public_orm_exports.py",
            "tools/check_public_orm_exports.py",
        ),
        commands=((PY, "tools/check_public_orm_exports.py"),),
        why="package-root public language or ORM-export ratchet changed: persistence "
        "types must remain an exact shrink-only baseline",
        advisory=True,
    ),
    Check(
        name="base-purity",
        globs=(
            "apps/backend/src/*.py",
            "common/meta/data/base-purity-baseline.json",
            "common/meta/extension/base_purity.py",
            "common/meta/extension/check_base_purity.py",
            "tools/check_base_purity.py",
        ),
        commands=((PY, "tools/check_base_purity.py"),),
        why="package base-layer or base-purity gate changed: ORM, config, observability, "
        "network, and session debt must remain an exact shrink-only baseline",
        advisory=True,
    ),
    Check(
        name="unit-accountability",
        globs=(
            "common/*/contract.py",
            "common/meta/data/unit-accountability-baseline.json",
            "common/meta/extension/check_unit_accountability.py",
            "tools/check_unit_accountability.py",
        ),
        commands=((PY, "tools/check_unit_accountability.py"),),
        why="package unit declarations changed: unbound units and incomplete repository "
        "pairs must remain an exact shrink-only baseline",
        advisory=True,
    ),
    Check(
        name="toolchain-contract",
        globs=(
            "toolchain.toml",
            ".python-version",
            ".node-version",
            ".tool-versions",
            ".moon/toolchain.yml",
            "apps/frontend/package.json",
            "tools/check_toolchain_contract.py",
            "common/runtime/check_toolchain_contract.py",
            "tools/generate_workflows.py",
            "common/runtime/generate_workflows.py",
        ),
        commands=((PY, "tools/check_toolchain_contract.py"),),
        why="toolchain contracts and version declarations must not drift",
        advisory=True,
    ),
    Check(
        name="workflow-projection",
        globs=(
            ".github/workflows/*.yml",
            ".github/actions/**/*.yml",
            "docker-compose*.yml",
            "apps/*/Dockerfile",
            "tools/generate_workflows.py",
            "common/runtime/generate_workflows.py",
        ),
        commands=((PY, "tools/generate_workflows.py", "--check"),),
        why="projected workflows, actions, and container files must match toolchain SSOT",
        advisory=True,
    ),
    Check(
        name="ci-metrics-contract",
        globs=(
            ".github/workflows/ci.yml",
            "common/testing/ci-cd.md",
            "tools/check_ci_metrics_contract.py",
            "common/meta/extension/metrics_contract.py",
        ),
        commands=((PY, "tools/check_ci_metrics_contract.py"),),
        why="CI workflow metrics contract must not drift",
        advisory=True,
    ),
    Check(
        name="detached-owner-shortcuts",
        globs=(
            "apps/backend/tests/**.py",
            "tools/check_detached_owner_shortcuts.py",
            "common/testing/detached_owner_guard.py",
        ),
        commands=((PY, "tools/check_detached_owner_shortcuts.py"),),
        why="backend tests must not reintroduce un-baselined detached owner uuid4 shortcuts",
        advisory=True,
    ),
    Check(
        name="epic-status",
        globs=(
            "README.md",
            "docs/project/EPIC*.md",
            "tools/generate_epic_status.py",
            "common/meta/extension/epic_status.py",
        ),
        commands=((PY, "tools/generate_epic_status.py", "--check"),),
        why="EPIC status pointer block in README must not drift",
        advisory=True,
    ),
    Check(
        name="ac-tier-baseline",
        globs=(
            "common/meta/data/ac-tier-baseline.json",
            "tools/check_ac_tier_baseline.py",
            "common/meta/extension/check_ac_tier_baseline.py",
        ),
        commands=((PY, "tools/check_ac_tier_baseline.py"),),
        why="AC authority tier debt only shrinks",
        advisory=True,
    ),
    Check(
        name="ac-proof-kind",
        globs=(
            "docs/project/EPIC*.md",
            "tools/check_ac_proof_kind.py",
            "common/meta/extension/check_ac_proof_kind.py",
        ),
        commands=((PY, "tools/check_ac_proof_kind.py"),),
        why="enforce tier -> valid proof kind matrix",
        advisory=True,
    ),
    Check(
        name="tier-imports",
        globs=(
            "apps/backend/src/*.py",
            "tools/check_tier_imports.py",
            "common/meta/extension/tier_imports.py",
        ),
        commands=((PY, "tools/check_tier_imports.py"),),
        why="CODE-ONLY financial core must not import LLM layer",
    ),
    Check(
        name="llm-cassettes",
        globs=(
            "common/testing/fixtures/llm_cassettes/**.json",
            "tools/check_llm_cassettes.py",
            "common/testing/check_llm_cassettes.py",
        ),
        commands=((PY, "tools/check_llm_cassettes.py"),),
        why="statement extraction cassettes must satisfy balance-chain invariant",
    ),
    Check(
        name="cassette-graded-eval",
        globs=(
            "common/testing/fixtures/llm_cassettes/**.json",
            "tools/check_cassette_graded_eval.py",
            "common/testing/check_cassette_graded_eval.py",
        ),
        commands=((PY, "tools/check_cassette_graded_eval.py"),),
        why="cassette graded accuracy eval ratchet",
    ),
    Check(
        name="frontend-static",
        globs=(
            "apps/frontend/src/*",
            "apps/frontend/package.json",
            "apps/frontend/tsconfig.json",
            "apps/frontend/openapi.json",
        ),
        commands=(
            ("npm", "run", "lint"),
            ("npm", "run", "typecheck"),
            ("npm", "run", "check:api-types"),
        ),
        why="frontend changed: eslint + tsc typecheck + openapi api-types contract sync",
        cwd="apps/frontend",
        tier="static",
    ),
    Check(
        name="frontend",
        globs=("apps/frontend/*",),
        commands=(
            ("npm", "run", "test:coverage"),
            ("npm", "run", "build"),
        ),
        why="frontend changed: vitest coverage gate + next build (layout/route type rules)",
        cwd="apps/frontend",
        tier="heavy",
    ),
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    advisory: bool = False


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


def _default_quiet_runner(argv: Sequence[str], cwd: str) -> int:
    proc = subprocess.run(
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        if proc.stdout:
            sys.stdout.write(proc.stdout)
            sys.stdout.flush()
        if proc.stderr:
            sys.stderr.write(proc.stderr)
            sys.stderr.flush()
    return proc.returncode


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
    ci: bool = False,
    quiet: bool = False,
    relaxed: bool = False,
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
        if ci and not quiet:
            print(f"::group::Gate [{check.tier}] {check.name}", flush=True)
        ok = True
        for command in check.commands:
            if (
                runner(_resolve(command, python, matching_paths=matching_paths), cwd)
                != 0
            ):
                ok = False
                break
        if ci:
            if not quiet:
                print("::endgroup::", flush=True)
            if not ok:
                severity = "warning" if (relaxed and check.advisory) else "error"
                print(
                    f"::{severity}::Gate {check.name} "
                    f"{'warned (relaxed)' if (relaxed and check.advisory) else 'failed'}: {check.why}",
                    flush=True,
                )
        results.append(CheckResult(check.name, ok, advisory=check.advisory))
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
    default_relaxed = os.getenv("PREFLIGHT_STRICT", "0").lower() not in (
        "1",
        "true",
        "yes",
    ) and os.getenv("PREFLIGHT_RELAXED", "1").lower() in ("1", "true", "yes")
    parser.add_argument(
        "--relaxed",
        "--soft",
        dest="relaxed",
        action="store_true",
        default=default_relaxed,
        help="Run in relaxed mode: non-critical advisory gates emit warnings rather than blocking exit (default).",
    )
    parser.add_argument(
        "--strict",
        dest="relaxed",
        action="store_false",
        help="Run in strict mode: all gates (including advisory) block exit on failure.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Select all registered checks for the tier regardless of diff.",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Format logs with GitHub Actions ::group:: folding and ::error:: annotations.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print single summary line when checks pass. Print full details when a check fails.",
    )
    args = parser.parse_args(argv)

    if args.all:
        files = ()
        selected = [
            check for check in CHECKS if args.tier == "full" or check.tier == args.tier
        ]
    else:
        files = (
            args.changed
            if args.changed is not None
            else changed_files(args.base, git=git)
        )
        selected = select_checks(files, tier=args.tier)

    if args.list:
        if not selected or args.all:
            inventory = [
                check
                for check in CHECKS
                if args.tier == "full" or check.tier == args.tier
            ]
            print(
                f"Registered preflight gate inventory ({args.tier} tier, {len(inventory)} gates):"
            )
            for check in inventory:
                status_suffix = " (advisory)" if check.advisory else ""
                print(f"  [{check.tier}] {check.name}{status_suffix}: {check.why}")
            return 0
        for check in selected:
            status_suffix = " (advisory)" if check.advisory else ""
            print(f"  [{check.tier}] {check.name}{status_suffix}: {check.why}")
        return 0

    if not selected:
        print("preflight: no relevant gates for the current diff.")
        return 0

    if not args.quiet:
        print(
            f"preflight: running {len(selected)} gate(s) for {len(files)} changed file(s)..."
        )
    effective_runner = (
        _default_quiet_runner if runner is _default_runner and args.quiet else runner
    )
    results = run_checks(
        selected,
        changed_files=files,
        runner=effective_runner,
        ci=args.ci,
        quiet=args.quiet,
        relaxed=args.relaxed,
    )
    failed_strict = [
        r.name for r in results if not r.ok and not (args.relaxed and r.advisory)
    ]
    failed_advisory = [
        r.name for r in results if not r.ok and (args.relaxed and r.advisory)
    ]

    for result in results:
        if result.ok:
            if not args.quiet:
                print(f"  [ok] {result.name}")
        else:
            status_str = (
                "WARN (relaxed)" if (args.relaxed and result.advisory) else "FAIL"
            )
            print(f"  [{status_str}] {result.name}")
    if failed_strict:
        print(
            f"preflight: {len(failed_strict)} gate(s) failed: {', '.join(failed_strict)}"
        )
        return 1
    if failed_advisory:
        print(
            f"preflight: all required gates passed ({len(failed_advisory)} advisory gate(s) warned under --relaxed mode)."
        )
    elif args.quiet:
        print(f"preflight: all {len(selected)} gates passed.")
    else:
        print("preflight: all relevant gates passed.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)
