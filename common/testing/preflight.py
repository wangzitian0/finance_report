"""Diff-aware pre-push verification dispatcher."""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import hashlib
import importlib.util
import io
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
PY = "{python}"
MATCHING_PATHS = "{matching_paths}"

Runner = Callable[[Sequence[str], str], int]
Git = Callable[[Sequence[str]], str]

TIERS: tuple[str, ...] = ("static", "heavy")
DEFAULT_SUBPROCESS_TIMEOUT: int = 180


@dataclass(frozen=True)
class Check:
    """A named gate that runs ``commands`` when a changed path matches ``globs``."""

    name: str
    globs: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    why: str
    cwd: str = "."
    tier: str = "static"


def _py_check(
    name: str,
    globs: tuple[str, ...],
    script: str,
    *args: str,
    why: str,
    cwd: str = ".",
    tier: str = "static",
) -> Check:
    return Check(
        name=name,
        globs=globs,
        commands=((PY, script, *args),),
        why=why,
        cwd=cwd,
        tier=tier,
    )


OPENAPI_INPUT_GLOBS: tuple[str, ...] = (
    "apps/backend/src/routers/*.py",
    "apps/backend/src/*/extension/api/*.py",
    "apps/backend/src/schemas/*.py",
    "apps/backend/src/main.py",
)

CHECKS: tuple[Check, ...] = (
    _py_check(
        "ac-traceability",
        ("docs/project/EPIC*.md",),
        "tools/check_ac_index.py",
        why="EPIC/AC changed: re-run the single AC-index gate",
    ),
    _py_check(
        "ac-proof-traceability",
        (
            "tests/*.py",
            "apps/backend/tests/*.py",
            "apps/frontend/*.test.ts",
            "apps/frontend/*.test.tsx",
            "apps/frontend/*.spec.ts",
            "apps/frontend/*.spec.tsx",
        ),
        "tools/check_ac_index.py",
        why="Test proof changed: re-run the single AC-index integrity gate",
    ),
    Check(
        name="ssot-ownership",
        globs=("common/meta/data/MANIFEST.yaml", "common/*/contract.py"),
        commands=(
            (PY, "tools/check_ssot_ownership.py"),
            (PY, "tools/check_manifest.py"),
        ),
        why="Concept registry or contract changed: enforce single-owner + manifest integrity",
    ),
    _py_check(
        "doc-consistency",
        ("docs/*", "mkdocs.yml", "vision.md", "README.md"),
        "tools/lint_doc_consistency.py",
        why="docs changed: nav coverage + cross-reference consistency",
    ),
    _py_check(
        "taxonomy-drift",
        (
            "*.md",
            "common/meta/data/*.yaml",
            "tests/*.py",
            "common/*.py",
            "tools/*.py",
        ),
        "tools/check_taxonomy_drift.py",
        why="prose/tests changed: retired package-taxonomy vocabulary must not be presented as current (AC-meta.vocab.1)",
    ),
    _py_check(
        "schema-validate",
        ("apps/backend/src/schemas/*.py",),
        "tools/validate_schemas.py",
        "--paths",
        MATCHING_PATHS,
        why="Pydantic schema changed: validate schema contracts",
    ),
    _py_check(
        "api-reference",
        OPENAPI_INPUT_GLOBS,
        "../../tools/generate_api_reference.py",
        "--check",
        why="router/schema changed: docs/reference/api.md must be regenerated",
        cwd="apps/backend",
    ),
    _py_check(
        "router-contract",
        ("apps/backend/src/routers/*.py",),
        "-m",
        "pytest",
        "tests/tooling/test_audit_router_contracts.py::test_findings_doc_is_in_sync",
        "-q",
        "--no-cov",
        why="router changed: docs/reference/router-contract-maturity.md must be in sync",
    ),
    _py_check(
        "migration-risk",
        ("apps/backend/migrations/*",),
        "tools/check_migration_risk.py",
        why="Alembic migration changed: classify migration risk",
    ),
    _py_check(
        "env-keys",
        (".env.example", ".env", ".env.*"),
        "tools/check_env_keys.py",
        why="env files changed: env-var key consistency",
    ),
    Check(
        name="backend-format",
        globs=("apps/backend/*.py",),
        commands=(
            (PY, "-m", "ruff", "check", "src", "tests"),
            (PY, "-m", "ruff", "format", "--check", "src", "tests"),
        ),
        why="backend Python changed: ruff lint + format check",
        cwd="apps/backend",
    ),
    _py_check(
        "transaction-boundary",
        ("apps/backend/src/extraction/extension/statement_*.py",),
        "-m",
        "pytest",
        "tests/infra/test_transaction_boundaries.py",
        "-q",
        "--no-cov",
        "-n",
        "0",
        why="service changed: re-run the commit/transaction-boundary meta-test",
        cwd="apps/backend",
    ),
    _py_check(
        "bench-articulation",
        (
            "apps/backend/src/ledger/*.py",
            "apps/backend/src/pricing/*.py",
            "apps/backend/src/reporting/*.py",
            "apps/backend/tests/reporting/test_bench_articulation_matrix.py",
        ),
        "-m",
        "pytest",
        "tests/reporting/test_bench_articulation_matrix.py",
        "-q",
        "--no-cov",
        why="financial calculation logic changed: BenchV2 articulation matrix must balance",
        cwd="apps/backend",
    ),
    _py_check(
        "money-mutation",
        (
            "apps/backend/src/ledger/*.py",
            "apps/backend/src/extraction/extension/classification.py",
            "apps/backend/src/extraction/extension/transaction_classification.py",
            "apps/backend/src/extraction/extension/statement_posting.py",
            "apps/backend/src/reporting/extension/cash_flow.py",
            "common/testing/mutation_check.py",
            "common/testing/data/money-mutations.json",
            "tools/check_mutations.py",
        ),
        "tools/check_mutations.py",
        "--advisory",
        why="money/classification code changed: run advisory mutation reproof (#2448)",
    ),
    _py_check(
        "env-reference",
        ("apps/backend/src/config.py",),
        "tools/generate_env_reference.py",
        "--check",
        why="config.py changed: regenerate .env.example + env reference and assert no drift",
    ),
    Check(
        name="openapi-spec",
        globs=OPENAPI_INPUT_GLOBS,
        commands=(
            (PY, "tools/generate_openapi_spec.py", "--check"),
            ("npm", "--prefix", "apps/frontend", "run", "check:api-types"),
        ),
        why="router/schema changed: openapi.json and frontend api-types must remain in sync (#1004, #2134)",
    ),
    _py_check(
        "package-contract",
        (
            "common/*/contract.py",
            "common/meta/extension/check_package_contract.py",
            "tools/check_package_contract.py",
            "apps/backend/src/*/__init__.py",
            "tests/tooling/*.py",
            "apps/backend/tests/*.py",
        ),
        "tools/check_package_contract.py",
        why="package contract, published interface, or invariant test ref changed: validate all package contracts (#2713)",
    ),
    _py_check(
        "package-migration-safety",
        (
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
        "tools/check_package_migration_safety.py",
        why="gate source, contracts, or test proofs changed: validate consolidated package migration safety gates",
    ),
    _py_check(
        "workflow-contract",
        (
            ".github/workflows/*.yml",
            "common/testing/ci-cd.md",
            "common/runtime/deployment.md",
            "common/runtime/environments.md",
            "tools/check_workflow_contract.py",
            "common/meta/extension/workflow_contract.py",
        ),
        "tools/check_workflow_contract.py",
        why="CI workflows, deployment/environment docs, or issue templates changed: validate workflow contract and taxonomy",
    ),
    _py_check(
        "governance-exceptions",
        (
            "common/meta/data/governance-exceptions.yaml",
            "tools/check_governance_exceptions.py",
            "common/meta/extension/check_governance_exceptions.py",
        ),
        "tools/check_governance_exceptions.py",
        why="governance exceptions changed: validate bottom-up proof-exception registry",
    ),
    _py_check(
        "context-contract",
        (
            "common/*/contract.py",
            "common/meta/base/package_contract.py",
            "common/meta/extension/check_context_contract.py",
            "tools/check_context_contract.py",
        ),
        "tools/check_context_contract.py",
        why="package contract or context gate changed: context declarations and dependency semantics only shrink",
    ),
    _py_check(
        "semantic-ownership",
        (
            "common/*/contract.py",
            "common/meta/base/package_contract.py",
            "common/meta/extension/check_semantic_ownership.py",
            "tools/check_semantic_ownership.py",
        ),
        "tools/check_semantic_ownership.py",
        why="package semantic declarations changed: every governed DDD concept must retain one canonical owner",
    ),
    _py_check(
        "tooling",
        ("tools/*", "common/*"),
        "-m",
        "pytest",
        "tests/tooling/",
        "-q",
        "--no-cov",
        why="tooling/common changed: run tests/tooling",
        tier="heavy",
    ),
    _py_check(
        "app-boundary",
        ("apps/backend/src/*.py",),
        "tools/check_app_boundary.py",
        why="backend source changed: L4 backend super-package edge ratchet",
    ),
    _py_check(
        "public-orm-exports",
        (
            "apps/backend/src/*/__init__.py",
            "common/meta/extension/public_orm_exports.py",
            "common/meta/extension/check_public_orm_exports.py",
            "tools/check_public_orm_exports.py",
        ),
        "tools/check_public_orm_exports.py",
        why="package-root public language or ORM-export ratchet changed",
    ),
    _py_check(
        "base-purity",
        (
            "apps/backend/src/*.py",
            "common/meta/extension/base_purity.py",
            "common/meta/extension/check_base_purity.py",
            "tools/check_base_purity.py",
        ),
        "tools/check_base_purity.py",
        why="package base-layer or base-purity gate changed",
    ),
    _py_check(
        "unit-accountability",
        (
            "common/*/contract.py",
            "common/meta/data/unit-accountability-baseline.json",
            "common/meta/extension/check_unit_accountability.py",
            "tools/check_unit_accountability.py",
        ),
        "tools/check_unit_accountability.py",
        why="package unit declarations changed: unbound units and incomplete repository pairs must remain shrink-only",
    ),
    _py_check(
        "toolchain-contract",
        (
            "toolchain.toml",
            ".python-version",
            ".node-version",
            ".tool-versions",
            ".moon/toolchain.yml",
            "apps/frontend/package.json",
            "tools/check_toolchain_contract.py",
            "common/runtime/check_toolchain_contract.py",
            ".github/workflows/*.yml",
            ".github/actions/**/*.yml",
            "docker-compose*.yml",
            "apps/*/Dockerfile",
        ),
        "tools/check_toolchain_contract.py",
        why="toolchain contracts and version declarations must not drift",
    ),
    _py_check(
        "ci-metrics-contract",
        (
            ".github/workflows/ci.yml",
            "common/testing/ci-cd.md",
            "tools/check_ci_metrics_contract.py",
            "common/meta/extension/metrics_contract.py",
        ),
        "tools/check_ci_metrics_contract.py",
        why="CI workflow metrics contract must not drift",
    ),
    _py_check(
        "detached-owner-shortcuts",
        (
            "apps/backend/tests/**.py",
            "tools/check_detached_owner_shortcuts.py",
            "common/testing/detached_owner_guard.py",
        ),
        "tools/check_detached_owner_shortcuts.py",
        why="backend tests must not reintroduce un-baselined detached owner uuid4 shortcuts",
    ),
    _py_check(
        "epic-status",
        (
            "README.md",
            "docs/project/EPIC*.md",
            "tools/generate_epic_status.py",
            "common/meta/extension/epic_status.py",
        ),
        "tools/generate_epic_status.py",
        "--check",
        why="EPIC status pointer block in README must not drift",
    ),
    _py_check(
        "ac-tier-baseline",
        (
            "common/meta/data/ac-tier-baseline.json",
            "tools/check_ac_tier_baseline.py",
            "common/meta/extension/check_ac_tier_baseline.py",
        ),
        "tools/check_ac_tier_baseline.py",
        why="AC authority tier debt only shrinks",
    ),
    _py_check(
        "ac-proof-kind",
        (
            "docs/project/EPIC*.md",
            "tools/check_ac_proof_kind.py",
            "common/meta/extension/check_ac_proof_kind.py",
        ),
        "tools/check_ac_proof_kind.py",
        why="enforce tier -> valid proof kind matrix",
    ),
    _py_check(
        "tier-imports",
        (
            "apps/backend/src/*.py",
            "tools/check_tier_imports.py",
            "common/meta/extension/tier_imports.py",
        ),
        "tools/check_tier_imports.py",
        why="CODE-ONLY financial core must not import LLM layer",
    ),
    _py_check(
        "llm-cassettes",
        (
            "common/testing/fixtures/llm_cassettes/**.json",
            "tools/check_llm_cassettes.py",
            "common/testing/check_llm_cassettes.py",
            "apps/backend/src/extraction/base/validation.py",
        ),
        "tools/check_llm_cassettes.py",
        why="statement extraction cassettes must satisfy balance-chain invariant",
    ),
    _py_check(
        "cassette-graded-eval",
        (
            "common/testing/fixtures/llm_cassettes/**.json",
            "tools/check_cassette_graded_eval.py",
            "common/testing/check_cassette_graded_eval.py",
        ),
        "tools/check_cassette_graded_eval.py",
        why="cassette graded accuracy eval ratchet",
    ),
    _py_check(
        "lockfile-registry",
        (
            "package-lock.json",
            "*package-lock.json",
            "apps/frontend/package.json",
            "tools/check_lockfile_registry.py",
            "common/testing/lockfile_registry.py",
        ),
        "tools/check_lockfile_registry.py",
        why="lockfile or registry gate changed: every resolved package URL must use https://registry.npmjs.org/ (#2668)",
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
    ),
    Check(
        name="frontend",
        globs=("apps/frontend/*",),
        commands=(
            ("npm", "run", "test:coverage"),
            ("npm", "run", "build"),
        ),
        why="frontend changed: vitest coverage gate + next build",
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
    """Return checks whose globs match at least one changed file for ``tier``."""
    if tier != "full" and tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}: expected one of {('full', *TIERS)}")
    files = list(changed_files)
    return [
        check
        for check in checks
        if (tier == "full" or check.tier == tier)
        and any(_matches(f, g) for f in files for g in check.globs)
    ]


def select_named_checks(
    names: Iterable[str],
    *,
    checks: Sequence[Check] = CHECKS,
) -> list[Check]:
    """Return checks with the given names in registry order, failing on unknowns."""
    wanted = list(dict.fromkeys(names))
    known = {check.name for check in checks}
    unknown = [name for name in wanted if name not in known]
    if unknown:
        raise ValueError(
            f"unknown gate name(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}"
        )
    return [check for check in checks if check.name in wanted]


def _default_git(args: Sequence[str]) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout


def changed_files(base: str | None = None, *, git: Git = _default_git) -> list[str]:
    """Union of committed-vs-base, staged, unstaged, and untracked paths."""
    if base is None:
        base = git(["merge-base", "HEAD", "origin/main"]).strip() or "HEAD"
    out: set[str] = set()
    for args in (
        ["diff", "--name-only", base],
        ["diff", "--name-only"],
        ["diff", "--name-only", "--cached"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        out.update(line for line in git(args).splitlines() if line.strip())
    return sorted(out)


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("TEST_NAMESPACE", f"preflight_{os.getpid()}")
    return env


_INPROCESS_EXCLUDED_TOOLS: frozenset[str] = frozenset({"check_mutations.py"})
_TOOL_MODULE_CACHE: dict[Path, ModuleType] = {}


def _resolve_inprocess_tool(argv: Sequence[str], cwd: str) -> Path | None:
    if len(argv) < 2:
        return None
    exe = Path(argv[0]).name
    if argv[0] != sys.executable and not exe.startswith("python"):
        return None
    if argv[1].startswith("-"):
        return None
    candidate = (Path(cwd) / argv[1]).resolve()
    tools_dir = (REPO_ROOT / "tools").resolve()
    if (
        candidate.parent != tools_dir
        or candidate.suffix != ".py"
        or candidate.name in _INPROCESS_EXCLUDED_TOOLS
        or not candidate.is_file()
    ):
        return None
    return candidate


def _load_tool_module(script_path: Path) -> ModuleType:
    cached = _TOOL_MODULE_CACHE.get(script_path)
    if cached is not None:
        return cached
    for extra in (REPO_ROOT, REPO_ROOT / "apps" / "backend"):
        extra_str = str(extra)
        if extra_str not in sys.path:
            sys.path.insert(0, extra_str)
    spec = importlib.util.spec_from_file_location(
        f"_preflight_tool_{script_path.stem}", script_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load tool script {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _TOOL_MODULE_CACHE[script_path] = module
    return module


def _run_tool_inprocess(
    script_path: Path, args: Sequence[str], cwd: str, *, quiet: bool
) -> int:
    module = _load_tool_module(script_path)
    main_fn = getattr(module, "main", None)
    if not callable(main_fn):
        raise AttributeError(f"{script_path} has no callable main()")
    had_ns = "TEST_NAMESPACE" in os.environ
    prev_ns = os.environ.get("TEST_NAMESPACE")
    if not had_ns:
        os.environ["TEST_NAMESPACE"] = f"preflight_{os.getpid()}"
    prev_argv = sys.argv[:]
    prev_cwd = Path.cwd()
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
        sys.argv = [str(script_path), *args]
        os.chdir(cwd)
        with (
            contextlib.redirect_stdout(stdout_buf)
            if quiet
            else contextlib.nullcontext(),
            contextlib.redirect_stderr(stderr_buf)
            if quiet
            else contextlib.nullcontext(),
        ):
            try:
                try:
                    result = main_fn(list(args))
                except TypeError as exc:
                    if "positional argument" not in str(exc):
                        raise
                    result = main_fn()
            except SystemExit as exc:
                rc = (
                    0
                    if exc.code is None
                    else (exc.code if isinstance(exc.code, int) else 1)
                )
            else:
                rc = int(result) if isinstance(result, int) else 0
    finally:
        os.chdir(prev_cwd)
        sys.argv = prev_argv
        if not had_ns:
            os.environ.pop("TEST_NAMESPACE", None)
        elif prev_ns is not None:
            os.environ["TEST_NAMESPACE"] = prev_ns
    if quiet and rc != 0:
        for stream, buf in (
            (sys.stdout, stdout_buf.getvalue()),
            (sys.stderr, stderr_buf.getvalue()),
        ):
            if buf:
                stream.write(buf)
                stream.flush()
    return rc


def _exec_runner(argv: Sequence[str], cwd: str, *, quiet: bool = False) -> int:
    tool_script = _resolve_inprocess_tool(argv, cwd)
    if tool_script is not None:
        return _run_tool_inprocess(tool_script, argv[2:], cwd, quiet=quiet)
    try:
        kwargs = (
            {"capture_output": True, "text": True, "errors": "replace"} if quiet else {}
        )
        proc = subprocess.run(
            list(argv),
            cwd=cwd,
            env=_child_env(),
            check=False,
            timeout=DEFAULT_SUBPROCESS_TIMEOUT,
            **kwargs,
        )
        if quiet and proc.returncode != 0:
            for stream, buf in ((sys.stdout, proc.stdout), (sys.stderr, proc.stderr)):
                if buf:
                    stream.write(buf)
                    stream.flush()
        return proc.returncode
    except subprocess.TimeoutExpired:
        print(
            f"::error::Gate command timed out after {DEFAULT_SUBPROCESS_TIMEOUT}s: {' '.join(argv)}",
            flush=True,
        )
        return 124


def _default_runner(argv: Sequence[str], cwd: str) -> int:
    return _exec_runner(argv, cwd, quiet=False)


def _default_quiet_runner(argv: Sequence[str], cwd: str) -> int:
    return _exec_runner(argv, cwd, quiet=True)


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


def _unquote_porcelain_path(raw: str) -> str:
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw


def _working_tree_snapshot(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:  # pragma: no cover - non-git dir fallback
        return {}
    snapshot: dict[str, str] = {"__porcelain__": proc.stdout}
    for line in proc.stdout.splitlines():
        rel_path = line[3:]
        if " -> " in rel_path:
            rel_path = rel_path.split(" -> ", 1)[1]
        rel_path = _unquote_porcelain_path(rel_path)
        full_path = repo_root / rel_path
        snapshot[rel_path] = (
            hashlib.sha256(full_path.read_bytes()).hexdigest()
            if full_path.is_file()
            else "<non-file>"
        )
    return snapshot


def run_checks(
    checks: Sequence[Check],
    *,
    changed_files: Sequence[str] = (),
    runner: Runner = _default_runner,
    python: str | None = None,
    ci: bool = False,
    quiet: bool = False,
    repo_root: Path | None = None,
) -> list[CheckResult]:
    """Run each check's commands, failing fast on the first non-zero command."""
    python = python or sys.executable
    root = repo_root or REPO_ROOT
    is_default_runner = runner in (_default_runner, _default_quiet_runner)
    guard_tree = is_default_runner or repo_root is not None
    dedup_results: dict[tuple[tuple[str, ...], str], bool] = {}
    results: list[CheckResult] = []
    for check in checks:
        cwd = str(root / check.cwd)
        matching_paths = tuple(
            path
            for path in changed_files
            if any(_matches(path, glob) for glob in check.globs)
        )
        resolved_cmds = [
            tuple(_resolve(command, python, matching_paths=matching_paths))
            for command in check.commands
        ]
        if ci and not quiet:
            print(f"::group::Gate [{check.tier}] {check.name}", flush=True)
        if is_default_runner and all(
            dedup_results.get((cmd, cwd)) is True for cmd in resolved_cmds
        ):
            ok = True
        else:
            before_snapshot = _working_tree_snapshot(root) if guard_tree else {}
            ok = True
            for cmd in resolved_cmds:
                if is_default_runner and dedup_results.get((cmd, cwd)) is True:
                    continue
                cmd_ok = runner(list(cmd), cwd) == 0
                if not cmd_ok:
                    ok = False
                    break
                if is_default_runner:
                    dedup_results[(cmd, cwd)] = True
            if guard_tree and _working_tree_snapshot(root) != before_snapshot:
                ok = False
                for cmd in resolved_cmds:
                    dedup_results.pop((cmd, cwd), None)
                print(
                    f"::error::Gate {check.name} mutated the working tree during execution",
                    file=sys.stderr,
                    flush=True,
                )
        if ci:
            if not quiet:
                print("::endgroup::", flush=True)
            if not ok:
                print(f"::error::Gate {check.name} failed: {check.why}", flush=True)
        results.append(CheckResult(check.name, ok))
    return results


def _collect_matching_tests(
    search_dir: Path, base_root: Path, stem: str, dest: set[str]
) -> None:
    if search_dir.is_dir():
        for match in search_dir.rglob(f"test_{stem}*.py"):
            if match.is_file():
                dest.add(str(match.relative_to(base_root)))


def resolve_changed_pytest_targets(
    changed_files_list: Iterable[str],
    *,
    repo_root: Path = REPO_ROOT,
) -> tuple[list[str], list[str]]:
    """Map changed repo-relative paths to (root_test_targets, backend_test_targets)."""
    root_selected: set[str] = set()
    backend_selected: set[str] = set()
    backend_root = repo_root / "apps" / "backend"
    backend_tests_dir = backend_root / "tests"
    root_tests_dir = repo_root / "tests"

    for rel in changed_files_list:
        path_obj = Path(rel)
        if not rel.endswith(".py"):
            continue
        if rel.startswith("apps/backend/tests/") and path_obj.name.startswith("test_"):
            if (repo_root / rel).is_file():
                backend_selected.add(rel.removeprefix("apps/backend/"))
            continue
        if rel.startswith("tests/") and path_obj.name.startswith("test_"):
            if (repo_root / rel).is_file():
                root_selected.add(rel)
            continue
        stem = path_obj.stem
        if stem == "__init__":
            continue
        if rel.startswith("apps/backend/src/"):
            _collect_matching_tests(
                backend_tests_dir, backend_root, stem, backend_selected
            )
        elif rel.startswith(("common/", "tools/")):
            _collect_matching_tests(root_tests_dir, repo_root, stem, root_selected)
            if rel.startswith("common/"):
                _collect_matching_tests(
                    backend_tests_dir, backend_root, stem, backend_selected
                )

    return sorted(root_selected), sorted(backend_selected)


def run(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _default_runner,
    git: Git = _default_git,
) -> int:
    parser = argparse.ArgumentParser(
        description="Run the gate checks relevant to the current diff."
    )
    parser.add_argument("--base", default=None)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--changed", nargs="*", default=None)
    parser.add_argument("--tier", choices=("full", *TIERS), default="full")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--only", action="append", default=None, metavar="NAME")
    parser.add_argument("--pytest-changed", action="store_true")
    parser.add_argument("--ci", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.only:
        if args.all or args.changed is not None:
            parser.error("--only cannot combine with --all or --changed")
        try:
            selected = select_named_checks(args.only)
        except ValueError as exc:
            parser.error(str(exc))
        files: Sequence[str] = ()
    elif args.all:
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
                print(f"  [{check.tier}] {check.name}: {check.why}")
            return 0
        for check in selected:
            print(f"  [{check.tier}] {check.name}: {check.why}")
        return 0

    effective_runner = (
        _default_quiet_runner if runner is _default_runner and args.quiet else runner
    )
    root_targets, backend_targets = (
        resolve_changed_pytest_targets(files) if args.pytest_changed else ([], [])
    )
    if not selected and not root_targets and not backend_targets:
        print("preflight: no relevant gates for the current diff.")
        return 0

    def _report_result(name: str, ok: bool) -> None:
        if not args.quiet:
            print(f"  [{'ok' if ok else 'FAIL'}] {name}")
        elif not ok:
            print(f"  [FAIL] {name}")

    failed: list[str] = []
    if selected:
        if not args.quiet:
            msg = (
                f"preflight: running {len(selected)} named gate(s)..."
                if args.only
                else f"preflight: running {len(selected)} gate(s) for {len(files)} changed file(s)..."
            )
            print(msg)
        results = run_checks(
            selected,
            changed_files=files,
            runner=effective_runner,
            ci=args.ci,
            quiet=args.quiet,
        )
        for result in results:
            _report_result(result.name, result.ok)
            if not result.ok:
                failed.append(result.name)

    pytest_suites_ran = 0
    if args.pytest_changed and not failed:
        for label, targets, target_cwd in (
            ("pytest-changed:root", root_targets, REPO_ROOT),
            ("pytest-changed:backend", backend_targets, REPO_ROOT / "apps" / "backend"),
        ):
            if not targets or failed:
                continue
            pytest_suites_ran += 1
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                *targets,
                "-x",
                "-q",
                "--no-cov",
                "-n",
                "0",
            ]
            ok = effective_runner(cmd, str(target_cwd)) == 0
            _report_result(label, ok)
            if not ok:
                failed.append(label)

    if failed:
        print(f"preflight: {len(failed)} gate(s) failed: {', '.join(failed)}")
        return 1
    if args.quiet:
        print(f"preflight: all {len(selected) + pytest_suites_ran} gates passed.")
    else:
        print("preflight: all relevant gates passed.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)
