"""CI workflow, change classifier, preflight, sharding, PR review threads, migration risk, and test selection contracts."""

from __future__ import annotations

import ast
import json
import re
import runpy
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from textwrap import dedent
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from infra2_sdk.manifests import load_hooks_manifest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.meta.base.gate_util import (  # noqa: E402
    clear_source_caches,
    parse_ast_cached,
    read_text_cached,
)
from common.meta.extension import migration_risk  # noqa: E402
from common.runtime import release_images  # noqa: E402
from common.testing import change_classifier as classifier  # noqa: E402
from common.testing import check_pr_review_threads as review_gate  # noqa: E402
from common.testing import invariant_core, matrix, preflight, test_selection  # noqa: E402
from common.testing.backend_shard import (  # noqa: E402
    discover_test_files,
    file_durations,
    main as shard_main,
    split_files,
)
from common.testing.change_classifier import classify_changed_paths  # noqa: E402
from tests.tooling.hook_text import hook_text  # noqa: E402

CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = BACKEND / "pyproject.toml"
SEED = BACKEND / "ci" / "backend-test-durations.json"
BASH = shutil.which("bash") or "/bin/bash"
ROUTE_DECORATOR = re.compile(r"@\w+\.(?:get|post|put|patch|delete|api_route)\(")
_NESTED_XDIST_LINE_RE = re.compile(
    r"""(?:pytest\b[^\n\r;]*?(?:-n|--numprocesses)\s*=?\s*(?:auto|[1-9]\d*)|(?:-n|--numprocesses)\s*=?\s*(?:auto|[1-9]\d*)[^\n\r;]*?pytest\b)"""
)
_NESTED_XDIST_CALL_RE = re.compile(
    r"""pytest[^\)\]]{0,240}(?:-n|--numprocesses)["'\s,=]+(?:auto|[1-9]\d*)""",
    re.DOTALL,
)
_DIGEST_OUTPUT = "Name: ghcr.io/example/backend:abc1234\nDigest: sha256:" + "a" * 64


def _lint_steps() -> list[dict]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["lint"]["steps"]


def _backend_job() -> dict:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["backend"]


def _route_defining_backend_files() -> list[str]:
    src = BACKEND / "src"
    found: list[str] = []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in {"APIRouter", "FastAPI"}:
                found.append(path.relative_to(ROOT).as_posix())
                break
    return found


def _paths_read_by(files: list[Path], pattern: str) -> set[str]:
    found: set[str] = set()
    chain_pat = (
        r"""['"]apps['"]\s*/\s*['"]frontend['"](?:\s*/\s*['"][^'"]+['"])*"""
        if "frontend" in pattern
        else r"""['"]apps['"]\s*/\s*['"]backend['"](?:\s*/\s*['"][^'"]+['"])*"""
    )
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found |= set(re.findall(pattern, text))
        for chain in re.findall(chain_pat, text):
            found.add("/".join(re.findall(r"""['"]([^'"]+)['"]""", chain)))
    return found


def _overlaps(literal: str, prefix: str) -> bool:
    return literal.startswith(prefix) or prefix.startswith(literal.rstrip("/"))


def _tooling_read_paths() -> set[str]:
    test_files = sorted((ROOT / "tests/tooling").glob("test_*.py"))
    path_pat = re.compile(r"""['"]([A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@-]+)*)['"]""")
    join_pat = re.compile(r"""(?:_?ROOT(?:_DIR)?|REPO(?:_ROOT)?)\s*/\s*([^\n;)]+)""")
    discovered: set[str] = set()
    for test_file in test_files:
        text = test_file.read_text(encoding="utf-8")
        for m in path_pat.finditer(text):
            cand = m.group(1).removeprefix("./")
            if (
                not cand
                or cand == "."
                or cand.startswith(("tools/", "tests/tooling/", ".git/"))
                or cand in {"tools", "tests", ".git"}
                or cand.isupper()
            ):
                continue
            if (ROOT / cand).exists():
                discovered.add(cand)
        for m in join_pat.finditer(text):
            parts = re.findall(r"""['"]([^'"]+)['"]""", m.group(1))
            if not parts:
                continue
            cand = "/".join(parts).removeprefix("./")
            if (
                not cand
                or cand == "."
                or cand.startswith(("tools/", "tests/tooling/", ".git/"))
                or cand in {"tools", "tests", ".git"}
            ):
                continue
            if (ROOT / cand).exists():
                discovered.add(cand)
    return discovered


# ---------------------------------------------------------------------------
# Preflight gates
# ---------------------------------------------------------------------------


def test_AC_testing_preflight_1_static_selection_and_watch_paths() -> None:
    """AC-testing.preflight.1"""
    assert preflight.TIERS == ("static",)
    assert {c.name for c in preflight.CHECKS} == {
        "migration-risk",
        "backend-format",
        "env-manifests",
        "openapi-spec",
        "api-reference",
        "toolchain-contract",
        "lockfile-registry",
        "app-boundary",
        "base-purity",
        "tier-imports",
        "frontend-static",
    }
    assert all(c.tier == "static" for c in preflight.CHECKS)

    assert "toolchain-contract" in {
        c.name
        for c in preflight.select_checks([".github/workflows/ci.yml"], tier="static")
    }
    assert {c.name for c in preflight.select_checks(["apps/backend/src/main.py"])} >= {
        "backend-format",
        "openapi-spec",
    }
    assert "migration-risk" in {
        c.name
        for c in preflight.select_checks(["apps/backend/migrations/versions/0099_x.py"])
    }
    assert {
        c.name for c in preflight.select_checks(["apps/backend/src/config.py"])
    } >= {"env-manifests", "backend-format"}
    assert [c.name for c in preflight.select_checks([".env.example"])] == [
        "env-manifests"
    ]
    assert [
        c.name for c in preflight.select_checks(["apps/frontend/src/app/layout.tsx"])
    ] == ["frontend-static"]
    assert preflight.select_checks(["Makefile"]) == []
    assert preflight.select_checks([]) == []

    changed = ["apps/backend/src/main.py", "apps/frontend/src/app/layout.tsx"]
    assert preflight.select_checks(changed, tier="static") == preflight.select_checks(
        changed, tier="full"
    )
    with pytest.raises(ValueError):
        preflight.select_checks(["common/x.py"], tier="bogus")

    optional_watch_paths = {".env", "package-lock.json"}
    missing = [
        f"{check.name}:{glob}"
        for check in preflight.CHECKS
        for glob in check.globs
        if "*" not in glob
        and "?" not in glob
        and not glob.endswith("/")
        and glob not in optional_watch_paths
        and not (ROOT / glob).exists()
    ]
    assert missing == [], f"Broken literal watch path(s) in preflight.CHECKS: {missing}"


def test_AC_testing_preflight_2_openapi_spec_ci_and_route_coverage() -> None:
    """AC-testing.preflight.2"""
    route_files = _route_defining_backend_files()
    assert route_files, "the scan found no route-defining backend file"
    assert "apps/backend/src/identity/extension/api/auth.py" in route_files
    assert "apps/backend/src/main.py" in route_files
    unselected = [
        path
        for path in route_files
        if "openapi-spec"
        not in {c.name for c in preflight.select_checks([path], tier="static")}
    ]
    assert unselected == [], f"route files missing openapi-spec: {unselected}"

    src = BACKEND / "src"
    decorated = {
        path.relative_to(ROOT).as_posix()
        for path in sorted(src.rglob("*.py"))
        if ROUTE_DECORATOR.search(path.read_text(encoding="utf-8"))
    }
    assert decorated and decorated <= set(route_files)

    by_name = {c.name: c for c in preflight.CHECKS}
    assert by_name["openapi-spec"].globs == preflight.OPENAPI_INPUT_GLOBS
    assert by_name["backend-format"].cwd == "apps/backend"
    assert by_name["frontend-static"].cwd == "apps/frontend"
    assert by_name["frontend-static"].commands == (
        ("npm", "run", "lint"),
        ("npm", "run", "typecheck"),
        ("npm", "run", "check:api-types"),
    )
    assert any(
        "check_api_types" in " ".join(cmd) for cmd in by_name["openapi-spec"].commands
    )

    for check in preflight.CHECKS:
        for command in check.commands:
            if len(command) >= 3 and command[0] == preflight.PY and command[1] == "-m":
                mod = command[2]
                if mod.startswith(("common.", "tests.")):
                    rel_mod = f"{mod.replace('.', '/')}.py"
                    mod_path = ROOT / rel_mod
                    assert mod_path.exists(), f"{check.name}: missing {mod_path}"

    steps = _lint_steps()
    names = [step.get("name", "") for step in steps]
    matching = [
        i
        for i, step in enumerate(steps)
        if "--only openapi-spec" in step.get("run", "")
    ]
    assert len(matching) == 1
    openapi_step = steps[matching[0]]
    run_lines = [
        line.strip()
        for line in openapi_step["run"].splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert run_lines == [
        "uv run --project apps/backend --frozen python -m common.testing.preflight --only openapi-spec --ci",
    ]
    assert names.index("Set up backend environment") < matching[0]
    assert names.index("Install frontend dependencies") < matching[0]
    assert "if" not in openapi_step and not openapi_step.get("continue-on-error")

    referenced: set[str] = set()
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        referenced.update(
            re.findall(
                r"common\.testing\.preflight[^\n]*?--only[= ]([A-Za-z0-9_-]+)",
                workflow.read_text(encoding="utf-8"),
            )
        )
    assert "openapi-spec" in referenced
    assert referenced <= set(by_name), sorted(referenced - set(by_name))


def test_AC_testing_toolchain_3_backend_format_and_precommit_parity() -> None:
    """AC-testing.toolchain.3"""
    backend_format = next(c for c in preflight.CHECKS if c.name == "backend-format")
    assert backend_format.commands == (
        (preflight.PY, "-m", "ruff", "check", "src", "tests"),
        (preflight.PY, "-m", "ruff", "format", "--check", "src", "tests"),
    )
    precommit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert (
        "uv run --project apps/backend python -m common.runtime.env_manifests --check"
        in precommit
    )
    assert "check_env_keys.py" not in precommit
    assert "cd apps/backend && uv run --frozen ruff check src tests" in precommit
    assert (
        "cd apps/backend && uv run --frozen ruff format src tests --check" in precommit
    )
    assert "ruff-pre-commit" not in precommit
    assert "validate_schemas.py" not in precommit
    assert "mirrors-mypy" not in precommit


def test_AC_testing_preflight_3_run_list_cli_changed_files_and_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-testing.preflight.3"""
    seen_cwds: list[str] = []
    preflight.run_checks(
        [c for c in preflight.CHECKS if c.name == "backend-format"],
        runner=lambda _argv, cwd: seen_cwds.append(cwd) or 0,
        python="python3",
    )
    assert seen_cwds and all(c.endswith("apps/backend") for c in seen_cwds)

    mig = preflight.select_checks(["apps/backend/migrations/versions/0099_x.py"])
    assert all(
        r.ok
        for r in preflight.run_checks(mig, runner=lambda _a, _c: 0, python="python3")
    )
    assert all(
        not r.ok
        for r in preflight.run_checks(mig, runner=lambda _a, _c: 1, python="python3")
    )

    fail_fast_calls: list[list[str]] = []
    preflight.run_checks(
        [c for c in preflight.CHECKS if c.name == "backend-format"],
        runner=lambda argv, _c: fail_fast_calls.append(list(argv)) or 1,
        python="python3",
    )
    assert len(fail_fast_calls) == 1

    assert preflight.run(["--changed", "toolchain.toml"], runner=lambda _a, _c: 1) == 1
    assert preflight.run(["--changed", "toolchain.toml"], runner=lambda _a, _c: 0) == 0
    assert preflight.run(["--changed", "Makefile"], runner=lambda _a, _c: 1) == 0
    ran_list: list[list[str]] = []
    assert (
        preflight.run(
            ["--list", "--changed", "docs/project/EPIC-008.x.md"],
            runner=lambda argv, _c: ran_list.append(argv) or 0,
        )
        == 0
    )
    assert ran_list == []

    def _fake_git(args):
        if args[0] == "merge-base":
            return "base-sha\n"
        if args[0] == "ls-files":
            return "new_untracked.py\n"
        if args[-1] == "--cached":
            return "c.py\n"
        if args[-1] == "base-sha":
            return "a.py\nb.py\n"
        return "b.py\n"

    assert preflight.changed_files(git=_fake_git) == [
        "a.py",
        "b.py",
        "c.py",
        "new_untracked.py",
    ]
    assert (
        preflight.run(
            [],
            runner=lambda _a, _c: 0,
            git=lambda a: "toolchain.toml\n" if "diff" in a else "",
        )
        == 0
    )

    capsys.readouterr()
    assert preflight.run(["--list", "--changed"], runner=lambda _a, _c: 0) == 0
    inv_out = capsys.readouterr().out
    assert (
        "Registered preflight gate inventory" in inv_out
        and "frontend-static" in inv_out
    )

    assert (
        preflight.run(["--all", "--tier=static", "--list"], runner=lambda _a, _c: 0)
        == 0
    )
    assert "toolchain-contract" in capsys.readouterr().out

    def _collect(args: list[str], rc_of_runner: int = 0) -> tuple[int, list[list[str]]]:
        ran: list[list[str]] = []
        return preflight.run(
            args, runner=lambda argv, _c: ran.append(list(argv)) or rc_of_runner
        ), ran

    rc, ran = _collect(["--only", "openapi-spec"])
    assert (
        rc == 0 and "preflight: running 1 named gate(s)..." in capsys.readouterr().out
    )
    gate = next(c for c in preflight.CHECKS if c.name == "openapi-spec")
    assert ran == [
        preflight._resolve(cmd, python=preflight.sys.executable)
        for cmd in gate.commands
    ]

    fail_rc, fail_ran = _collect(["--only", "openapi-spec"], rc_of_runner=1)
    assert (
        fail_rc == 1
        and len(fail_ran) == 1
        and "[FAIL] openapi-spec" in capsys.readouterr().out
    )

    with pytest.raises(SystemExit) as bad_only:
        preflight.run(["--only", "openapi-specc"], runner=lambda _a, _c: 0)
    assert (
        bad_only.value.code == 2
        and "unknown gate name(s): openapi-specc" in capsys.readouterr().err
    )

    assert (
        preflight.run(
            ["--only", "openapi-spec"],
            runner=lambda _a, _c: 0,
            git=lambda a: (_ for _ in ()).throw(AssertionError(a)),
        )
        == 0
    )

    for extra in (["--all"], ["--changed", "Makefile"]):
        with pytest.raises(SystemExit) as exc:
            preflight.run(["--only", "openapi-spec", *extra], runner=lambda _a, _c: 0)
        assert exc.value.code == 2
        assert (
            "--only cannot combine with --all or --changed" in capsys.readouterr().err
        )

    picked = preflight.select_named_checks(["toolchain-contract", "openapi-spec"])
    assert [c.name for c in picked] == ["openapi-spec", "toolchain-contract"]
    with pytest.raises(ValueError, match="unknown gate name"):
        preflight.select_named_checks(["no-such-gate"])


def test_preflight_ci_logging_quiet_timeout_and_child_env(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pass_check = preflight.Check(
        name="test-pass",
        tier="static",
        globs=("*.py",),
        commands=(("echo", "ok"),),
        why="pass",
    )
    res = preflight.run_checks(
        [pass_check], changed_files=["foo.py"], runner=lambda _a, _c: 0, ci=True
    )
    assert len(res) == 1 and res[0].ok
    out = capsys.readouterr().out
    assert (
        "::group::Gate [static] test-pass" in out
        and "::endgroup::" in out
        and "::error::" not in out
    )

    fail_check = preflight.Check(
        name="test-fail",
        tier="static",
        globs=("*.py",),
        commands=(("echo", "fail"),),
        why="fail why",
    )
    fres = preflight.run_checks(
        [fail_check], changed_files=["foo.py"], runner=lambda _a, _c: 1, ci=True
    )
    assert not fres[0].ok
    fout = capsys.readouterr().out
    assert "::error::Gate test-fail failed: fail why" in fout

    assert (
        preflight.run(
            ["--tier=static", "--quiet", "--changed", "toolchain.toml"],
            runner=lambda _a, _c: 0,
        )
        == 0
    )
    qout = capsys.readouterr().out
    assert (
        "preflight: all" in qout
        and "preflight: running" not in qout
        and "[ok]" not in qout
    )

    assert (
        preflight.run(
            ["--tier=static", "-q", "--changed", "toolchain.toml"],
            runner=lambda _a, _c: 1,
        )
        == 1
    )
    assert "FAIL" in capsys.readouterr().out

    with monkeypatch.context() as mp:
        mp.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                a[0], 0, stdout="clean\n", stderr=""
            ),
        )
        assert preflight._default_quiet_runner(["echo"], cwd="/tmp") == 0
        cap = capsys.readouterr()
        assert cap.out == "" and cap.err == ""

        mp.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(
                a[0], 1, stdout="err line\n", stderr="warn\n"
            ),
        )
        assert preflight._default_quiet_runner(["x"], cwd="/tmp") == 1
        cap2 = capsys.readouterr()
        assert "err line" in cap2.out and "warn" in cap2.err

        def _timeout(*args, **_kw):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=180)

        mp.setattr(subprocess, "run", _timeout)
        assert preflight._default_runner(["sleep", "9"], cwd="/tmp") == 124
        assert "timed out after 180s" in capsys.readouterr().out
        assert preflight._default_quiet_runner(["sleep", "9"], cwd="/tmp") == 124
        assert "timed out after 180s" in capsys.readouterr().out

    monkeypatch.delenv("TEST_NAMESPACE", raising=False)
    assert preflight._child_env()["TEST_NAMESPACE"].startswith("preflight_")
    monkeypatch.setenv("TEST_NAMESPACE", "explicit_ns")
    assert preflight._child_env()["TEST_NAMESPACE"] == "explicit_ns"


def test_preflight_mutation_guard_pytest_changed_and_static_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for cmd in (
        ["git", "init"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True)
    tracked = tmp_path / "toolchain.toml"
    tracked.write_text('python = "3.12.12"\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "toolchain.toml"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "branch", "origin/main"], cwd=tmp_path, check=True, capture_output=True
    )

    # Mutation guard
    assert preflight._unquote_porcelain_path("plain.txt") == "plain.txt"
    assert preflight._unquote_porcelain_path('"dirty file.txt"') == "dirty file.txt"
    spaced = tmp_path / "dirty file.txt"
    spaced.write_text("v1\n", encoding="utf-8")
    mutating = preflight.Check(
        name="mut-gate",
        globs=("*.txt",),
        commands=(("touch", "dirty file.txt"),),
        why="guard",
    )
    res = preflight.run_checks(
        [mutating],
        changed_files=("dirty file.txt",),
        runner=lambda _a, cwd: (Path(cwd) / "dirty file.txt").write_text(
            "v2\n", encoding="utf-8"
        )
        and 0
        or 0,
        repo_root=tmp_path,
    )
    assert not res[0].ok and "mutated the working tree" in capsys.readouterr().err
    spaced.unlink()

    # Static cache stamp hits and invalidations
    tracked.write_text('python = "3.12.13"\n', encoding="utf-8")

    def _repo_git(args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=False
        ).stdout

    stamp = tmp_path / ".git" / "preflight-static.stamp"
    calls: list[list[str]] = []
    assert (
        preflight.run(
            ["--tier=static"],
            runner=lambda a, _c: calls.append(list(a)) or 0,
            git=_repo_git,
            repo_root=tmp_path,
            cache_file=stamp,
        )
        == 0
    )
    assert len(calls) == 1 and stamp.is_file()
    capsys.readouterr()
    assert (
        preflight.run(
            ["--tier=static"],
            runner=lambda a, _c: calls.append(list(a)) or 0,
            git=_repo_git,
            repo_root=tmp_path,
            cache_file=stamp,
        )
        == 0
    )
    assert len(calls) == 1 and "static cache hit" in capsys.readouterr().out
    assert (
        preflight.run(
            ["--tier=static", "--ci"],
            runner=lambda a, _c: calls.append(list(a)) or 0,
            git=_repo_git,
            repo_root=tmp_path,
            cache_file=stamp,
        )
        == 0
    )
    assert len(calls) == 2
    tracked.write_text('python = "3.12.14"\n', encoding="utf-8")
    assert (
        preflight.run(
            ["--tier=static"],
            runner=lambda a, _c: calls.append(list(a)) or 0,
            git=_repo_git,
            repo_root=tmp_path,
            cache_file=stamp,
        )
        == 0
    )
    assert len(calls) == 3

    # Diff-scoped pytest targets & stat cache
    clear_source_caches()
    sample = tmp_path / "sample.py"
    sample.write_text("VALUE = 1\n", encoding="utf-8")
    assert read_text_cached(sample) == "VALUE = 1\n"
    t1 = parse_ast_cached(sample)
    assert parse_ast_cached(sample) is t1
    sample.write_text("VALUE = 42  # changed size\n", encoding="utf-8")
    t2 = parse_ast_cached(sample)
    assert t2 is not t1 and t2.body[0].value.value == 42  # type: ignore[attr-defined]

    pt_root = tmp_path / "pt"
    (pt_root / "tests" / "tooling").mkdir(parents=True)
    (pt_root / "tests" / "tooling" / "test_preflight.py").write_text(
        "def test_ok(): pass\n", encoding="utf-8"
    )
    (pt_root / "tests" / "tooling" / "test_direct_root.py").write_text(
        "def test_ok(): pass\n", encoding="utf-8"
    )
    (pt_root / "apps" / "backend" / "tests" / "unit").mkdir(parents=True)
    (
        pt_root / "apps" / "backend" / "tests" / "unit" / "test_journal_service.py"
    ).write_text("def test_ok(): pass\n", encoding="utf-8")
    (
        pt_root / "apps" / "backend" / "tests" / "unit" / "test_direct_backend.py"
    ).write_text("def test_ok(): pass\n", encoding="utf-8")
    (pt_root / "apps" / "backend" / "tests" / "audit" / "money").mkdir(parents=True)
    (
        pt_root
        / "apps"
        / "backend"
        / "tests"
        / "audit"
        / "money"
        / "test_money_value_type.py"
    ).write_text("def test_ok(): pass\n", encoding="utf-8")

    root_targets, backend_targets = preflight.resolve_changed_pytest_targets(
        [
            "common/testing/__init__.py",
            "common/testing/preflight.py",
            "common/audit/money/money.py",
            "tests/tooling/test_direct_root.py",
            "apps/backend/src/services/journal_service.py",
            "apps/backend/tests/unit/test_direct_backend.py",
            "docs/README.md",
        ],
        repo_root=pt_root,
    )
    assert root_targets == [
        "tests/tooling/test_direct_root.py",
        "tests/tooling/test_preflight.py",
    ]
    assert backend_targets == [
        "tests/audit/money/test_money_value_type.py",
        "tests/unit/test_direct_backend.py",
        "tests/unit/test_journal_service.py",
    ]

    recorded: list[tuple[list[str], str]] = []
    capsys.readouterr()
    assert (
        preflight.run(
            [
                "--tier=static",
                "--pytest-changed",
                "--changed",
                "tests/tooling/test_ci_and_delivery_contracts.py",
                "apps/backend/tests/infra/test_transaction_boundaries.py",
            ],
            runner=lambda argv, cwd: recorded.append((list(argv), cwd)) or 0,
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "[ok] pytest-changed:root" in out and "[ok] pytest-changed:backend" in out
    pytest_cmds = [argv for argv, _c in recorded if "pytest" in argv]
    assert len(pytest_cmds) == 2
    assert all(
        "-x" in cmd and "--no-cov" in cmd and cmd[cmd.index("-n") + 1] == "0"
        for cmd in pytest_cmds
    )

    assert (
        preflight.run(
            [
                "--tier=static",
                "--quiet",
                "--pytest-changed",
                "--changed",
                "tests/tooling/test_ci_and_delivery_contracts.py",
            ],
            runner=lambda argv, _c: 1 if "pytest" in argv else 0,
        )
        == 1
    )
    qfail = capsys.readouterr().out
    assert (
        "[FAIL] pytest-changed:root" in qfail
        and "preflight: 1 gate(s) failed: pytest-changed:root" in qfail
    )

    assert (
        preflight.run(
            [
                "--tier=static",
                "--pytest-changed",
                "--changed",
                "nonexistent_dir/unmatched.txt",
            ],
            runner=lambda _a, _c: 0,
        )
        == 0
    )
    assert (
        "preflight: no relevant gates for the current diff." in capsys.readouterr().out
    )


# ---------------------------------------------------------------------------
# Change classifier & CI routing contracts
# ---------------------------------------------------------------------------


def test_AC8_13_20_classifier_lightweight_image_build_outputs_and_workflow_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-testing.classifier.2 AC8.13.20"""
    light = classify_changed_paths(
        ["README.md", "docs/ssot/README.md", ".github/workflows/docs.yml"]
    )
    assert (light.heavy_required, light.heavy_files, light.reason) == (
        False,
        (),
        "lightweight-docs-or-docs-workflow-only",
    )
    assert (
        light.image_build_required,
        light.image_build_files,
        light.frontend_changed,
    ) == (False, (), False)

    src_only = classify_changed_paths(
        ["apps/backend/src/main.py", "apps/frontend/src/app/page.tsx"]
    )
    assert (
        src_only.heavy_required is True
        and src_only.image_build_required is False
        and src_only.frontend_changed is True
    )

    for path in (
        "apps/backend/.dockerignore",
        "apps/backend/Dockerfile",
        "apps/backend/uv.lock",
        "apps/backend/pyproject.toml",
        "apps/frontend/.dockerignore",
        "apps/frontend/Dockerfile",
        "apps/frontend/package-lock.json",
        "apps/frontend/tsconfig.json",
        "apps/backend/scripts/entrypoint.sh",
    ):
        res = classify_changed_paths([path])
        assert res.image_build_required is True and res.image_build_files == (path,), (
            path
        )

    empty = classify_changed_paths([])
    assert (
        empty.heavy_required,
        empty.reason,
        empty.image_build_required,
        empty.frontend_changed,
    ) == (
        True,
        "no-changed-files-detected",
        True,
        True,
    )
    assert classify_changed_paths([".github/workflows/ci.yml"]).heavy_required is True
    assert (
        classify_changed_paths(["runtime-hooks.manifest.json"]).heavy_required is True
    )
    assert (
        classify_changed_paths([".github/workflows/docs.yml"]).heavy_required is False
    )
    assert classify_changed_paths(["apps/backend/README.md"]).heavy_required is True

    out_path = tmp_path / "github-output.txt"
    sum_path = tmp_path / "github-summary.md"
    mixed = classify_changed_paths(
        ["docs/ssot/README.md", "common/testing/change_classifier.py"]
    )
    classifier.write_github_outputs(mixed, out_path)
    classifier.write_github_summary(mixed, sum_path)
    out_map = dict(
        line.split("=", maxsplit=1)
        for line in out_path.read_text(encoding="utf-8").splitlines()
    )
    assert set(out_map) == {
        "heavy_required",
        "image_build_required",
        "reason",
        "frontend_changed",
        "vitest_required",
        "backend_required",
        "tooling_required",
    }
    assert out_map["heavy_required"] == "true" and out_map["frontend_changed"] == "true"
    assert "common/testing/change_classifier.py" in sum_path.read_text(encoding="utf-8")

    changed_file = tmp_path / "changed.txt"
    changed_file.write_text(
        "docs/ssot/README.md\n.github/workflows/docs.yml\n", encoding="utf-8"
    )
    gh_out2 = tmp_path / "out2.txt"
    gh_sum2 = tmp_path / "sum2.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ci_change_classifier.py",
            "--changed-files",
            str(changed_file),
            "--github-output",
            str(gh_out2),
            "--github-summary",
            str(gh_sum2),
        ],
    )
    assert classifier.main() == 0
    stdout = capsys.readouterr().out
    assert "heavy_required=false" in stdout and "changed_files=2" in stdout
    assert "heavy_required=false" in gh_out2.read_text(encoding="utf-8")
    assert "Changed files: `2`" in gh_sum2.read_text(encoding="utf-8")

    for exact_set in (classifier.IMAGE_BUILD_EXACT, classifier.CI_DEFINITION_PATHS):
        for path_str in exact_set:
            assert (ROOT / path_str).exists(), (
                f"Exact classifier path missing: {path_str}"
            )
    for prefix_tuple in (
        classifier.LIGHTWEIGHT_PREFIXES,
        classifier.IMAGE_BUILD_PREFIXES,
    ):
        for prefix in prefix_tuple:
            clean_prefix = prefix.rstrip("/")
            assert (ROOT / clean_prefix).exists(), (
                f"Classifier prefix missing: {prefix}"
            )

    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    gates_step = next(
        s for s in workflow["jobs"]["changes"]["steps"] if s.get("id") == "gates"
    )
    assert "steps.classify.outputs.heavy_required" in str(
        gates_step["env"]["HEAVY_REQUIRED"]
    )
    assert "steps.classify.outputs.reason" in str(gates_step["env"]["REASON"])


def test_cross_layer_routing_skip_sets_and_tooling_lane_coverage() -> None:
    """AC-testing.classifier.11"""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    expected_backend_if = (
        "needs.changes.outputs.pr_required == 'true' "
        "&& (github.event_name != 'pull_request' || needs.changes.outputs.backend_required == 'true')"
    )
    for job_name in ("schema-migrations", "backend", "backend-integration"):
        assert jobs[job_name]["if"] == expected_backend_if

    assert classifier.VITEST_SKIP_PREFIXES == ("apps/backend/",)
    assert classifier.BACKEND_TESTS_SKIP_PREFIXES == ("apps/frontend/",)
    assert (
        classify_changed_paths(
            ["apps/backend/src/main.py", "apps/backend/tests/t.py"]
        ).vitest_required
        is False
    )
    assert (
        classify_changed_paths(
            ["apps/backend/src/main.py", "common/audit/money/x.py"]
        ).vitest_required
        is True
    )
    assert (
        classify_changed_paths(["apps/frontend/src/app/page.tsx"]).backend_required
        is False
    )
    assert (
        classify_changed_paths(
            ["apps/frontend/src/app/page.tsx", "common/meta/x.py"]
        ).backend_required
        is True
    )
    assert (
        classify_changed_paths(["docs/project/EPIC-001.md"]).tooling_required is False
    )
    assert (
        classify_changed_paths(["docs/reference/user-cases.md"]).tooling_required
        is True
    )
    assert classify_changed_paths([]).tooling_required is True
    assert classify_changed_paths(["unlisted/unrelated.txt"]).tooling_required is False

    assert "frontend-telemetry-e2e" not in jobs
    assert "frontend-build" in jobs["frontend-playwright"]["needs"]
    pw_steps = jobs["frontend-playwright"]["steps"]
    pw_uses = [str(s.get("uses", "")) for s in pw_steps if isinstance(s, dict)]
    pw_with = [s.get("with", {}).get("name") for s in pw_steps if isinstance(s, dict)]
    pw_runs = "\n".join(str(s.get("run", "")) for s in pw_steps if isinstance(s, dict))
    assert any("download-artifact" in u for u in pw_uses) and "frontend-next-build" in pw_with
    assert "npm run test:e2e" in pw_runs and "npm run test:e2e:telemetry" in pw_runs

    # Ensure Vitest does not read backend paths (cross-layer isolation)
    fe_files = [f for f in (ROOT / "apps/frontend/src").rglob("*") if f.is_file()] + [
        ROOT / "apps/frontend/package.json",
        ROOT / "apps/frontend/vitest.config.ts",
        ROOT / "apps/frontend/vitest.setup.ts",
    ]
    direct = _paths_read_by(
        fe_files, r"(?:apps/backend|common|tools)(?:/[A-Za-z0-9_./@-]*)?"
    )
    assert "common/audit/money/conformance/vectors.json" in direct
    fe_sources = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore")
        for f in (ROOT / "apps/frontend/src").rglob("*")
        if f.is_file()
    )
    assert "backend_test_ref" not in fe_sources
    indirect: set[str] = set()
    for p in direct:
        if p == "common/meta/flows/user_cases_ssot.json":
            continue
        target = ROOT / p.rstrip(".")
        if target.is_file() and target.suffix == ".json":
            indirect |= _paths_read_by([target], r"apps/backend[A-Za-z0-9_./@-]*")
    clashes = sorted(
        (r, p)
        for r in (direct | indirect)
        for p in classifier.VITEST_SKIP_PREFIXES
        if _overlaps(r, p)
    )
    assert clashes == [], f"Vitest reads a skipped path: {clashes}"

    be_files = [
        f
        for d in (
            "apps/backend/tests",
            "apps/backend/scripts",
            "apps/backend/migrations",
        )
        for f in (ROOT / d).rglob("*")
        if f.is_file()
    ]
    be_read = _paths_read_by(be_files, r"apps/frontend(?:/[A-Za-z0-9_./@-]*)?")
    be_clashes = sorted(
        (r, p)
        for r in be_read
        for p in classifier.BACKEND_TESTS_SKIP_PREFIXES
        if _overlaps(r, p)
    )
    assert be_clashes == [], f"Backend tests read a skipped path: {be_clashes}"

    read_paths = _tooling_read_paths()
    assert read_paths, (
        "expected tests/tooling/ to read repo paths outside tools/ and tests/tooling/"
    )
    assert (
        "apps/backend/src/routers" in read_paths
        or any(p.startswith("apps/backend/src/routers") for p in read_paths)
        or "apps/backend/src" in read_paths
        or "apps" in read_paths
    )
    sample_inputs: set[str] = {"apps/backend/src/routers/statements.py"}
    for path in read_paths:
        target = ROOT / path
        sample_inputs.add(f"{path.rstrip('/')}/example.py" if target.is_dir() else path)
    uncovered = sorted(
        p for p in sample_inputs if not classify_changed_paths([p]).tooling_required
    )
    assert uncovered == [], (
        f"Tooling lane misses paths read by tests/tooling/: {uncovered}"
    )

    assert "tooling" in jobs and jobs["tooling"]["needs"] == ["changes"]
    assert "needs.changes.outputs.tooling_required == 'true'" in str(
        jobs["tooling"].get("if", "")
    )
    assert "tests/tooling/" in "\n".join(
        str(s.get("run", "")) for s in jobs["tooling"]["steps"] if isinstance(s, dict)
    )
    assert "tooling" in jobs["finish"]["needs"]
    finish_cmds = "\n".join(
        str(s.get("run", "")) for s in jobs["finish"]["steps"] if isinstance(s, dict)
    )
    assert (
        '"${{ needs.tooling.result }}" != "success" && "${{ needs.tooling.result }}" != "skipped"'
        in finish_cmds
    )


# ---------------------------------------------------------------------------
# Staging / audit test selection & JUnit emission (from matrix + test_selection)
# ---------------------------------------------------------------------------


def test_AC_testing_deploy_gates_37_corpus_disjointness_and_junit_emission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-testing.deploy-gates.37"""
    manifest = load_hooks_manifest(ROOT / "runtime-hooks.manifest.json")
    for cell, corpus in (
        ("staging.post", "canary"),
        ("scheduled_audit", "audit_replay"),
    ):
        cmd = hook_text(manifest, cell)
        assert (
            f"common.testing.test_selection --stage staging_ai_ocr --corpus {corpus} --run"
            in cmd
        )

    replay_files = set(matrix.audit_replay_files())
    core_files = {node.split("::", 1)[0] for node in matrix.core_journey_tests()}
    assert core_files.isdisjoint(replay_files)
    assert core_files == set(matrix.CORE_JOURNEY_ONLY_FILES)

    canary = set(matrix.canary_files())
    assert list(matrix.canary_files()) == matrix.CANARY_FILES
    assert canary & replay_files == set()
    assert canary | replay_files == set(matrix.gate_files())
    heavy_audit_journeys = (
        "tests/e2e/test_statement_full_journey.py",
        "tests/e2e/test_four_asset_net_worth_golden_path.py",
        "tests/e2e/test_personal_financial_report_package.py",
        "tests/e2e/test_institution_statement_journeys.py",
    )
    assert all(h in replay_files and h not in canary for h in heavy_audit_journeys)

    with pytest.raises(SystemExit, match="Unknown corpus"):
        matrix.corpus_files("unknown")

    with monkeypatch.context() as mp:
        mp.setattr(
            matrix,
            "E2E_ROWS",
            (
                SimpleNamespace(
                    file="tests/e2e/test_statement_full_journey.py",
                    needs=(matrix.NEEDS_LLM_PROVIDER,),
                ),
                SimpleNamespace(
                    file="tests/e2e/test_ai_provider_connectivity.py",
                    needs=(matrix.NEEDS_LLM_PROVIDER,),
                ),
                SimpleNamespace(file="tests/e2e/test_not_llm.py", needs=()),
            ),
        )
        assert matrix.gate_files() == [
            "tests/e2e/test_statement_full_journey.py",
            "tests/e2e/test_statement_upload_e2e.py",
        ]
        with pytest.raises(
            SystemExit, match="Canary files are not in the derived AI/OCR corpus"
        ):
            matrix.canary_files()

    new_heavy = "tests/e2e/test_hypothetical_new_heavy_proof.py"
    with monkeypatch.context() as mp:
        original_gate_files = matrix.gate_files
        mp.setattr(
            matrix,
            "gate_files",
            lambda: sorted(set(original_gate_files()) | {new_heavy}),
        )
        assert new_heavy in set(matrix.audit_replay_files())
        assert new_heavy not in set(matrix.canary_files())

    shell = matrix.emit_shell("staging_ai_ocr", corpus="canary")
    expected_canary_shell = " ".join(matrix.CANARY_FILES)
    assert f"STAGING_AI_OCR_TESTS=({expected_canary_shell})" in shell
    assert "STAGING_AI_OCR_MARKER=" in shell
    assert "STAGING_AI_OCR_EXPECTED_" not in shell

    calls: list[list[str]] = []

    def _fake_run(argv: list[str], **_kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0)

    artifacts_dir = tmp_path / "hook_artifacts"
    monkeypatch.setenv("HOOK_ARTIFACTS_DIR", str(artifacts_dir))
    assert (
        test_selection.main(
            ["--stage", "staging_ai_ocr", "--corpus", "audit_replay", "--run"],
            runner=_fake_run,
        )
        == 0
    )
    assert (
        f"--junitxml={artifacts_dir / 'staging_ai_ocr_audit_replay.junit.xml'}"
        in calls[-1]
    )
    assert artifacts_dir.is_dir()

    explicit = tmp_path / "custom" / "result.xml"
    assert (
        test_selection.main(
            ["--stage", "staging_core_e2e", "--run", "--junit-path", str(explicit)],
            runner=_fake_run,
        )
        == 0
    )
    assert f"--junitxml={explicit}" in calls[-1] and explicit.parent.is_dir()

    monkeypatch.delenv("HOOK_ARTIFACTS_DIR", raising=False)
    assert (
        test_selection.main(
            ["--stage", "staging_ai_ocr", "--corpus", "all", "--run"], runner=_fake_run
        )
        == 0
    )
    assert not any(arg.startswith("--junitxml=") for arg in calls[-1])

    monkeypatch.setenv("HOOK_ARTIFACTS_DIR", str(artifacts_dir))
    assert (
        test_selection.main(
            ["--stage", "staging_ai_ocr", "--corpus", "all", "--run"], runner=_fake_run
        )
        == 0
    )
    assert f"--junitxml={artifacts_dir / 'staging_ai_ocr.junit.xml'}" in calls[-1]
    assert (
        test_selection.main(
            [
                "--touched-files",
                "apps/frontend/src/components/journal/EntryForm.tsx",
                "--run",
            ],
            runner=_fake_run,
        )
        == 0
    )
    assert f"--junitxml={artifacts_dir / 'touched_files.junit.xml'}" in calls[-1]


def test_core_e2e_stages_run_in_xdist_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#3241: the core E2E stages run in parallel; the node set stays the same."""
    monkeypatch.delenv("HOOK_ARTIFACTS_DIR", raising=False)
    calls: list[list[str]] = []

    def _fake_run(argv: list[str], **_kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0)

    workers_flag = "--numprocesses"
    for stage in (matrix.STAGING_CORE_E2E_STAGE, matrix.PREVIEW_MINIMUM_E2E_STAGE):
        assert test_selection.main(["--stage", stage, "--run"], runner=_fake_run) == 0
        argv = calls[-1]
        assert argv[argv.index(workers_flag) + 1] == str(
            matrix.STAGING_CORE_E2E_PARALLELISM
        )
        assert matrix.STAGING_CORE_E2E_PARALLELISM > 1
        nodes = tuple(argv[argv.index("pytest") + 1 : argv.index("-v")])
        assert nodes == matrix.staging_core_e2e_selection()

    assert (
        test_selection.main(
            ["--stage", "staging_ai_ocr", "--corpus", "canary", "--run"],
            runner=_fake_run,
        )
        == 0
    )
    assert workers_flag not in calls[-1]


def test_AC8_13_109_ai_ocr_gate_e2e_hygiene() -> None:
    """AC-testing.deploy-gates.23 AC8.13.109"""
    shared_user_fixtures = {"authenticated_page", "shared_auth_state"}
    forbidden_snippets = (
        "localStorage.getItem('finance_access_token')",
        'localStorage.getItem("finance_access_token")',
        '"Authorization": f"Bearer {access_token}"',
        "'Authorization': f'Bearer {access_token}'",
        "networkidle",
        'locator("a").filter(has_text=',
        "locator('a').filter(has_text=",
        "locator(f'a[href=",
        'locator(f"a[href=',
    )
    home_landmark = "Three-statement cockpit"
    relative_prefixes = ("/api/", "/assets/")

    def _rel_url_prefix(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr) and node.values:
            first = node.values[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return first.value
        return None

    offenders: list[str] = []
    landmark_calls = 0
    for relative_path in matrix.gate_files():
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in source:
                offenders.append(f"{relative_path} contains {snippet}")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and node.name.startswith("test_"):
                shared = sorted(
                    {arg.arg for arg in node.args.args} & shared_user_fixtures
                )
                if shared:
                    offenders.append(
                        f"{relative_path}::{node.name} uses {', '.join(shared)}"
                    )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "get_by_label" and node.args:
                    first = node.args[0]
                    is_home = (
                        isinstance(first, ast.Constant) and first.value == home_landmark
                    )
                    exact_kw = next(
                        (kw for kw in node.keywords if kw.arg == "exact"), None
                    )
                    is_exact = (
                        exact_kw is not None
                        and isinstance(exact_kw.value, ast.Constant)
                        and exact_kw.value.value is True
                    )
                    if is_home and not is_exact:
                        offenders.append(
                            f"{relative_path}:{node.lineno} uses inexact {home_landmark} label"
                        )
                    landmark_calls += int(is_home)
                if (
                    node.func.attr in {"get", "post", "put", "patch", "delete"}
                    and node.args
                ):
                    prefix = _rel_url_prefix(node.args[0])
                    if prefix and prefix.startswith(relative_prefixes):
                        offenders.append(
                            f"{relative_path}:{node.lineno} uses relative API URL {prefix!r}"
                        )

    assert landmark_calls > 0
    assert offenders == []


# ---------------------------------------------------------------------------
# PR review thread weighted gate
# ---------------------------------------------------------------------------


def _review_thread(
    *,
    is_resolved: bool = False,
    is_outdated: bool = False,
    author: str = "some-human",
    body: str = "please fix this",
    url: str = "https://github.com/o/r/pull/1#discussion_r1",
) -> dict[str, Any]:
    return {
        "isResolved": is_resolved,
        "isOutdated": is_outdated,
        "comments": {
            "nodes": [{"author": {"login": author}, "body": body, "url": url}]
        },
    }


def _review_payload(*threads: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": {
            "repository": {"pullRequest": {"reviewThreads": {"nodes": list(threads)}}}
        }
    }


def _run_review_gate(payload: dict[str, Any]) -> int:
    return review_gate.run(
        pr_number=1, repo="o/r", fetch_threads=lambda _pr, _repo: payload
    )


def test_AC8_20_review_threads_weights_blocking_pagination_and_docs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-testing.review-threads.3 AC8.20.1 AC8.20.2 AC8.20.3 EPIC-008"""
    assert review_gate.thread_weight(_review_thread(body="severity: high\nbug")) == (
        "High",
        1.0,
    )
    assert review_gate.thread_weight(_review_thread(body="Severity: MIDDLE")) == (
        "Medium",
        0.5,
    )
    assert review_gate.thread_weight(_review_thread(body="severity: medium")) == (
        "Medium",
        0.5,
    )
    assert review_gate.thread_weight(_review_thread(body="severity: low\nnit")) == (
        "Low",
        0.25,
    )
    assert review_gate.thread_weight(_review_thread(body="plain comment")) == (
        "Medium (default)",
        0.5,
    )
    assert review_gate.thread_weight(
        _review_thread(author="copilot-pull-request-reviewer[bot]", body="suggestion")
    ) == ("Medium (default)", 0.5)
    assert review_gate.thread_weight(
        _review_thread(author="github-copilot[bot]", body="severity: low")
    ) == ("Low", 0.25)
    for body in ("P0 blocker", "P1 regression", "nit: rename var", "P2/P3 polish"):
        assert review_gate.thread_weight(_review_thread(body=body)) == (
            "Medium (default)",
            0.5,
        )
    assert (
        _run_review_gate(
            _review_payload(_review_thread(body="P0 blocker without severity tag"))
        )
        == 0
    )

    assert (
        _run_review_gate(
            _review_payload(_review_thread(body="severity: high: corrupts ledger"))
        )
        == 1
    )
    assert (
        _run_review_gate(
            _review_payload(
                _review_thread(body="severity: middle: one"),
                _review_thread(body="severity: medium: two"),
            )
        )
        == 1
    )
    assert (
        _run_review_gate(
            _review_payload(_review_thread(body="first"), _review_thread(body="second"))
        )
        == 1
    )
    assert (
        _run_review_gate(
            _review_payload(*[_review_thread(body="severity: low") for _ in range(4)])
        )
        == 1
    )

    url = "https://github.com/o/r/pull/1#discussion_r999"
    assert (
        _run_review_gate(
            _review_payload(
                _review_thread(body="severity: high", url=url),
                _review_thread(body="severity: low"),
            )
        )
        == 1
    )
    cap = capsys.readouterr()
    assert (
        url in cap.err
        and "weighted score 1.25" in cap.out
        and "unresolved review score 1.25 >= 1.00" in cap.err
    )

    assert (
        _run_review_gate(
            _review_payload(
                _review_thread(
                    author="copilot-pull-request-reviewer[bot]", body="consider"
                )
            )
        )
        == 0
    )
    assert (
        _run_review_gate(_review_payload(_review_thread(body="severity: middle"))) == 0
    )
    assert (
        _run_review_gate(
            _review_payload(*[_review_thread(body="severity: low") for _ in range(3)])
        )
        == 0
    )
    assert (
        _run_review_gate(
            _review_payload(_review_thread(body="severity: high", is_resolved=True))
        )
        == 0
    )
    assert (
        _run_review_gate(
            _review_payload(_review_thread(body="severity: high", is_outdated=True))
        )
        == 0
    )
    assert _run_review_gate(_review_payload()) == 0
    assert (
        _run_review_gate(
            _review_payload(_review_thread(body="severity: low: rename var"))
        )
        == 0
    )
    cap2 = capsys.readouterr()
    assert "rename var" in (cap2.out + cap2.err).lower()

    monkeypatch.delenv("PR_NUMBER", raising=False)
    assert review_gate.main(["--repo", "o/r"]) == 0
    assert (
        review_gate.run(
            pr_number=None,
            repo="o/r",
            fetch_threads=lambda *_: (_ for _ in ()).throw(AssertionError()),
        )
        == 0
    )
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert review_gate.main(["--pr-number", "1"]) == 1
    with monkeypatch.context() as mp:
        mp.setattr(
            review_gate,
            "fetch_threads",
            lambda _pr, _repo: _review_payload(
                _review_thread(body="severity: high", is_resolved=False)
            ),
        )
        assert review_gate.main(["--repo", "o/r", "--pr-number", "1"]) == 1

    def _page(
        nodes: list[dict[str, Any]], *, has_next: bool, cursor: str | None
    ) -> Any:
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "pageInfo": {
                                        "hasNextPage": has_next,
                                        "endCursor": cursor,
                                    },
                                    "nodes": nodes,
                                }
                            }
                        }
                    }
                }
            )
        )

    pages = [
        _page([_review_thread(body="t1")], has_next=True, cursor="c1"),
        _page([_review_thread(body="t2")], has_next=True, cursor="c2"),
        _page([_review_thread(body="t3")], has_next=False, cursor=None),
    ]
    calls: list[list[str]] = []
    with monkeypatch.context() as mp:
        mp.setattr(
            review_gate.subprocess,
            "run",
            lambda cmd, **_kw: calls.append(cmd) or pages[len(calls) - 1],
        )
        merged = review_gate.fetch_threads(1, "o/r")
        assert len(review_gate._thread_nodes(merged)) == 3 and len(calls) == 3
        assert any("after=c1" in p for p in calls[1]) and any(
            "after=c2" in p for p in calls[2]
        )

        mp.setattr(
            review_gate.subprocess,
            "run",
            lambda _cmd, **_kw: _page([_review_thread()], has_next=True, cursor=None),
        )
        with pytest.raises(RuntimeError):
            review_gate.fetch_threads(1, "o/r")

    ci_cd = (ROOT / "common/testing/ci-cd.md").read_text(encoding="utf-8")
    section = ci_cd.split("## PR Review Thread Merge Gate", 1)[1].split("\n## ", 1)[0]
    lower = " ".join(section.lower().replace("`", "").split())
    assert f"high = {review_gate.SEVERITY_WEIGHTS['high'][1]}" in lower
    assert f"middle/medium = {review_gate.SEVERITY_WEIGHTS['middle'][1]}" in lower
    assert f"low = {review_gate.SEVERITY_WEIGHTS['low'][1]}" in lower
    assert f"unlabelled = {review_gate.UNLABELLED_WEIGHT[1]}" in lower
    assert f">= {review_gate.REVIEW_BLOCK_SCORE}" in lower
    assert "resolved and outdated threads do not count" in lower
    assert "copilot review is optional and non-blocking" in lower


# ---------------------------------------------------------------------------
# Migration risk, release image verification, backend sharding, CI & xdist
# ---------------------------------------------------------------------------


def _write_mig(path: Path, content: str) -> None:
    path.write_text(dedent(content).lstrip(), encoding="utf-8")


def _write_mig_manifest(path: Path, migrations: dict[str, object]) -> None:
    path.write_text(
        yaml.safe_dump({"version": 1, "migrations": migrations}), encoding="utf-8"
    )


def test_AC7_11_migration_risk_contract_classification_and_ci(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-meta.migration-risk.1 AC-meta.migration-risk.4 AC-meta.migration-risk.5 AC7.11.1 AC7.11.2 AC7.11.3 AC7.11.4 AC7.11.5"""
    result = migration_risk.validate_repository(ROOT)
    assert result.ok and result.errors == [] and len(result.migrations) >= 40
    assert result.manifest_path == ROOT / "common/meta/data/migration-risk.yaml"
    assert all(
        rec.risk in migration_risk.RISK_LEVELS for rec in result.migrations.values()
    )

    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    assert (
        "Migration Risk Contract Check" in ci
        and "python -m common.meta.extension.migration_risk" in ci
    )

    assert migration_risk.classify_risk('op.create_table("t")') == "low"
    assert migration_risk.classify_risk('op.alter_column("t", "c")') == "medium"
    assert migration_risk.classify_risk('op.execute("UPDATE t SET c = 1")') == "high"
    assert migration_risk.classify_risk('op.drop_table("t")') == "critical"

    m_high = tmp_path / "high_dir"
    m_high.mkdir()
    _write_mig(
        m_high / "0001_high.py",
        'from alembic import op\nrevision = "0001_high"\ndown_revision = None\ndef upgrade():\n    op.execute("UPDATE accounts SET name = name")\n',
    )
    man_high = tmp_path / "m_high.yaml"
    _write_mig_manifest(
        man_high,
        {"0001_high": {"file": "0001_high.py", "risk": "high", "proof": "Need proof."}},
    )
    res_high = migration_risk.validate(manifest_path=man_high, migrations_dir=m_high)
    for token in ("staging_validation", "production_preflight", "rollback_strategy"):
        assert any("0001_high" in e and token in e for e in res_high.errors)

    m_crit = tmp_path / "crit_dir"
    m_crit.mkdir()
    _write_mig(
        m_crit / "0002_drop_legacy.py",
        'from alembic import op\nrevision = "0002_drop_legacy"\ndown_revision = None\ndef upgrade():\n    op.drop_table("legacy_rows")\n',
    )
    man_crit = tmp_path / "m_crit.yaml"
    _write_mig_manifest(
        man_crit,
        {
            "0002_drop_legacy": {
                "file": "0002_drop_legacy.py",
                "risk": "high",
                "proof": "Under-classified.",
                "issue": "#815",
                "staging_validation": "s",
                "production_preflight": "p",
                "rollback_strategy": "r",
            }
        },
    )
    assert any(
        "0002_drop_legacy" in e and "critical" in e
        for e in migration_risk.validate(
            manifest_path=man_crit, migrations_dir=m_crit
        ).errors
    )

    m_edge = tmp_path / "edge_dir"
    m_edge.mkdir()
    _write_mig(m_edge / "bad_syntax.py", "def upgrade(:\n    pass\n")
    _write_mig(
        m_edge / "missing_revision.py",
        "down_revision = None\ndef upgrade():\n    pass\n",
    )
    _write_mig(
        m_edge / "additive.py",
        'from alembic import op\nrevision = "additive"\ndown_revision = None\ndef upgrade():\n    op.create_table("w")\n',
    )
    _write_mig(
        m_edge / "mutated.py",
        'from alembic import op\nrevision = "mutated"\ndown_revision = "additive"\ndef upgrade():\n    op.execute("UPDATE w SET n = n")\n',
    )
    man_edge = tmp_path / "edge.yaml"
    _write_mig_manifest(
        man_edge,
        {
            "extra_revision": {
                "file": "extra_revision.py",
                "risk": "low",
                "proof": "Extra",
            }
        },
    )
    edge_res = migration_risk.validate(manifest_path=man_edge, migrations_dir=m_edge)
    assert any("bad_syntax.py: cannot parse" in e for e in edge_res.errors)
    assert any(
        "missing_revision.py: missing string Alembic revision" in e
        for e in edge_res.errors
    )
    assert any(
        "mutated: auto-classified high migration requires a manifest entry" in e
        for e in edge_res.errors
    )
    assert any(
        "extra_revision: manifest entry has no matching migration file" in e
        for e in edge_res.errors
    )
    assert edge_res.migrations["additive"].risk == "low"

    m_cli = tmp_path / "cli_dir"
    m_cli.mkdir()
    _write_mig(
        m_cli / "0001_low.py",
        'revision = "0001_low"\ndown_revision = None\ndef upgrade():\n    pass\n',
    )
    man_cli = tmp_path / "cli.yaml"
    _write_mig_manifest(
        man_cli,
        {"0001_low": {"file": "0001_low.py", "risk": "low", "proof": "CLI pass."}},
    )
    sum_path = tmp_path / "ci-context/migration-risk.md"
    assert (
        migration_risk.main(
            [
                "--repo-root",
                str(tmp_path),
                "--manifest",
                str(man_cli),
                "--migrations-dir",
                str(m_cli),
                "--summary",
                str(sum_path),
            ]
        )
        == 0
    )
    assert (
        "Status: pass" in capsys.readouterr().out
        and "Status: pass" in sum_path.read_text(encoding="utf-8")
    )
    assert (
        migration_risk.main(
            [
                "--repo-root",
                str(tmp_path),
                "--manifest",
                str(tmp_path / "missing.yaml"),
                "--migrations-dir",
                str(m_cli),
            ]
        )
        == 1
    )
    assert "Status: fail" in capsys.readouterr().err


def test_AC_runtime_release_images_retries_and_validation() -> None:
    """AC-runtime.release-images.1 AC-runtime.release-images.2 AC-runtime.release-images.3 AC-runtime.release-images.4 AC-runtime.release-images.5 AC-runtime.release-images.6"""
    calls: list[str] = []
    digests = release_images.verify_release_images(
        registry="ghcr.io",
        image_prefix="example",
        version_ref="abc1234",
        inspect_image=lambda img: (calls.append(img) or (0, _DIGEST_OUTPUT)),
        sleep=lambda _s: (_ for _ in ()).throw(
            AssertionError("sleep should not run on first-attempt hit")
        ),
    )
    assert (
        digests
        == {
            "backend_digest": "sha256:" + "a" * 64,
            "frontend_digest": "sha256:" + "a" * 64,
        }
        and len(calls) == 2
    )

    attempts: dict[str, int] = {}
    sleeps: list[float] = []

    def _retry_inspect(image: str) -> tuple[int, str]:
        attempts[image] = attempts.get(image, 0) + 1
        return (1, "") if attempts[image] < 3 else (0, _DIGEST_OUTPUT)

    release_images.verify_release_images(
        registry="ghcr.io",
        image_prefix="example",
        version_ref="abc1234",
        inspect_image=_retry_inspect,
        sleep=sleeps.append,
    )
    assert all(n == 3 for n in attempts.values()) and len(sleeps) == 4

    with pytest.raises(RuntimeError, match="not found after 4 attempts"):
        release_images.verify_release_images(
            registry="ghcr.io",
            image_prefix="example",
            version_ref="abc1234",
            inspect_image=lambda _i: (1, ""),
            sleep=lambda _s: None,
        )
    with pytest.raises(ValueError, match="max_attempts must be >= 1"):
        release_images.verify_release_images(
            registry="ghcr.io",
            image_prefix="example",
            version_ref="abc1234",
            inspect_image=lambda _i: (0, _DIGEST_OUTPUT),
            max_attempts=0,
            sleep=lambda _s: None,
        )
    with pytest.raises(ValueError, match="retry_delay_seconds must be >= 0"):
        release_images.verify_release_images(
            registry="ghcr.io",
            image_prefix="example",
            version_ref="abc1234",
            inspect_image=lambda _i: (1, ""),
            retry_delay_seconds=-1.0,
            sleep=lambda _s: None,
        )
    assert (
        release_images.main(
            [
                "--registry",
                "ghcr.io",
                "--image-prefix",
                "example",
                "--version-ref",
                "abc1234",
                "--dry-run",
            ]
        )
        == 0
    )


def test_AC_testing_ci_structure_13_backend_shard_and_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-testing.ci-structure.13"""
    shard_count = len(_backend_job()["strategy"]["matrix"]["shard"])
    files = discover_test_files(BACKEND)
    durations = json.loads(SEED.read_text(encoding="utf-8"))
    groups = split_files(files, durations, shard_count)
    assigned = [path for group in groups for path in group]
    assert (
        len(groups) == shard_count
        and all(groups)
        and sorted(assigned) == files
        and len(assigned) == len(set(assigned))
    )
    per_file = file_durations(durations)
    weights = [sum(per_file.get(p, 0.0) for p in group) for group in groups]
    assert max(weights) <= 1.1 * (sum(weights) / len(weights))

    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    options = pyproject["tool"]["pytest"]["ini_options"]
    assert (
        options["testpaths"] == ["tests"]
        and options["python_files"] == ["test_*.py"]
        and options.get("norecursedirs") is None
    )
    for conftest in (BACKEND / "tests").rglob("conftest.py"):
        text = conftest.read_text(encoding="utf-8")
        assert not any(
            hook in text for hook in ("collect_ignore", "pytest_ignore_collect")
        )

    synth_durs = {
        "tests/test_heavy.py::test_a": 30.0,
        "tests/test_heavy.py::test_b": 30.0,
        "tests/test_mid.py::test_a": 40.0,
        "tests/test_light.py::test_a": 10.0,
        "tests/test_tiny.py::test_a": 1.0,
    }
    synth_files = [
        "tests/test_tiny.py",
        "tests/test_new.py",
        "tests/test_light.py",
        "tests/test_mid.py",
        "tests/test_heavy.py",
    ]
    assert file_durations(synth_durs)["tests/test_heavy.py"] == 60.0
    assert split_files(synth_files, synth_durs, 2) == [
        ["tests/test_heavy.py", "tests/test_light.py"],
        ["tests/test_mid.py", "tests/test_new.py", "tests/test_tiny.py"],
    ]
    with pytest.raises(ValueError):
        split_files(synth_files, synth_durs, 0)

    cli_tmp = tmp_path / "shard_cli"
    for name in ("test_a.py", "test_b.py", "sub/test_c.py", "helpers.py"):
        p = cli_tmp / "tests" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    (cli_tmp / "seed.json").write_text(
        json.dumps({"tests/test_a.py::t": 5.0, "tests/sub/test_c.py::t": 3.0}),
        encoding="utf-8",
    )
    printed = []
    for grp in ("1", "2"):
        assert (
            shard_main(
                [
                    "--splits",
                    "2",
                    "--durations-path",
                    "seed.json",
                    "--backend-root",
                    str(cli_tmp),
                    "--group",
                    grp,
                ]
            )
            == 0
        )
        printed.append(capsys.readouterr().out.split())
    assert sorted(printed[0] + printed[1]) == [
        "tests/sub/test_c.py",
        "tests/test_a.py",
        "tests/test_b.py",
    ]
    assert (
        shard_main(
            [
                "--splits",
                "2",
                "--durations-path",
                "seed.json",
                "--backend-root",
                str(cli_tmp),
                "--group",
                "3",
            ]
        )
        == 2
    )
    empty_dir = tmp_path / "empty_shard_root"
    (empty_dir / "tests").mkdir(parents=True)
    assert (
        shard_main(
            [
                "--splits",
                "2",
                "--durations-path",
                str(cli_tmp / "seed.json"),
                "--backend-root",
                str(empty_dir),
                "--group",
                "1",
            ]
        )
        == 1
    )

    from common.testing import backend_shard as backend_shard_files

    argv = [
        "--splits",
        str(shard_count),
        "--group",
        "1",
        "--splitting-algorithm=least_duration",
        "--durations-path",
        str(SEED),
        "--backend-root",
        str(BACKEND),
    ]
    assert (
        backend_shard_files.main(argv) == 0
        and capsys.readouterr().out.split() == groups[0]
    )
    monkeypatch.setattr(sys, "argv", ["common.testing.backend_shard", *argv])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(
            str(ROOT / "common/testing/backend_shard.py"), run_name="__main__"
        )
    assert exc.value.code == 0 and capsys.readouterr().out.split() == groups[0]
    isolated = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "common/testing/backend_shard.py"),
            "--splits",
            str(shard_count),
            "--group",
            "1",
            "--splitting-algorithm=least_duration",
            "--durations-path",
            "ci/backend-test-durations.json",
        ],
        cwd=BACKEND,
        check=True,
        capture_output=True,
        text=True,
    )
    assert isolated.stdout.split() == groups[0]

    script = next(
        str(s["run"])
        for s in _backend_job()["steps"]
        if isinstance(s, dict) and "pytest" in str(s.get("run", ""))
    )
    empty_shard_dir = tmp_path / "empty_shard_bin"
    empty_shard_dir.mkdir()
    uv_marker = tmp_path / "uv-should-not-run"
    (empty_shard_dir / "uv").write_text(
        f"#!/bin/sh\ntouch {uv_marker}\n", encoding="utf-8"
    )
    (empty_shard_dir / "uv").chmod(0o755)
    (empty_shard_dir / "python").write_text(
        f'#!/bin/sh\ncase "$*" in *common.testing.backend_shard*) exit 0;; esac\nexec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    (empty_shard_dir / "python").chmod(0o755)
    empty_res = subprocess.run(
        [
            BASH,
            "-e",
            "-c",
            script.replace("${{ matrix.shard }}", "1").replace(
                "${{ strategy.job-total }}", str(shard_count)
            ),
        ],
        cwd=ROOT,
        env={"PATH": f"{empty_shard_dir}:/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert empty_res.returncode == 1 and not uv_marker.exists()
    for shard in (1, shard_count):
        bin_dir = tmp_path / f"bin_{shard}"
        bin_dir.mkdir()
        recorded = tmp_path / f"uv-args-{shard}.json"
        (bin_dir / "uv").write_text(
            f'#!/bin/sh\nexec "{sys.executable}" -c "import json, sys; json.dump(sys.argv[1:], open(\'{recorded}\', \'w\'))" "$@"\n',
            encoding="utf-8",
        )
        (bin_dir / "python").symlink_to(sys.executable)
        (bin_dir / "uv").chmod(0o755)
        rendered_script = script.replace("${{ matrix.shard }}", str(shard)).replace(
            "${{ strategy.job-total }}", str(shard_count)
        )
        subprocess.run(
            [BASH, "-e", "-c", rendered_script],
            cwd=ROOT,
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path)},
            check=True,
            capture_output=True,
            text=True,
        )
        args = json.loads(recorded.read_text(encoding="utf-8"))
        assert (
            args[:2] == ["run", "pytest"]
            and args[-len(groups[shard - 1]) :] == groups[shard - 1]
        )
        assert not {"--splits", "--group", "--durations-path"} & set(args)


def test_moon_ci_compose_addopts_and_corpus_contracts() -> None:
    ci_workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    for obsolete in (
        ".moon",
        "moon.yml",
        "apps/backend/moon.yml",
        "apps/frontend/moon.yml",
        "opencode.json",
        ".opencode",
    ):
        assert not (ROOT / obsolete).exists(), f"Obsolete path still present: {obsolete}"
    assert "moonrepo/setup-toolchain@v0" not in ci_workflow

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose.get("services") or {}
    assert "postgres" in services and services["postgres"]["image"].startswith(
        "postgres:15"
    )
    assert (
        services["backend"]["environment"]["S3_ENDPOINT"]
        == "${S3_ENDPOINT:-http://minio:9000}"
    )
    assert "$$(seq 1 10)" in services["minio-init"]["entrypoint"]

    if (ROOT / ".github/workflows").exists() and (
        actionlint := shutil.which("actionlint")
    ):
        al_res = subprocess.run(
            [actionlint, "-color"], cwd=ROOT, capture_output=True, text=True
        )
        assert al_res.returncode == 0, (
            f"GitHub Actions Lint Failed:\n{al_res.stdout}\n{al_res.stderr}"
        )

    addopts = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["pytest"][
        "ini_options"
    ]["addopts"]
    joined = " ".join(addopts)
    assert (
        "-n" not in addopts
        and "--cov=src" not in joined
        and "--cov-branch" not in addopts
        and "--cov-fail-under" not in joined
    )

    offenders: list[str] = []
    for search_root in (ROOT / "tests", ROOT / "apps" / "backend" / "tests"):
        for path in sorted(search_root.rglob("*.py")):
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            matched = {
                f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}"
                for lineno, line in enumerate(text.splitlines(), 1)
                if _NESTED_XDIST_LINE_RE.search(line)
            }
            for m in _NESTED_XDIST_CALL_RE.finditer(text):
                lineno = text.count("\n", 0, m.start()) + 1
                matched.add(
                    f"{path.relative_to(ROOT)}:{lineno}: {m.group(0).splitlines()[0].strip()}"
                )
            offenders.extend(sorted(matched))
    assert offenders == [], f"Nested pytest xdist worker calls found: {offenders}"
    assert _NESTED_XDIST_CALL_RE.search('subprocess.run(["pytest",\n "-n",\n "4"])')
    assert not _NESTED_XDIST_CALL_RE.search('subprocess.run(["pytest", "-n", "0"])')

    corpus_file = (
        ROOT / "apps/backend/tests/integration/test_statement_corpus_journeys.py"
    )
    assert corpus_file.is_file()
    assert (
        matrix.classify_stage(
            "apps/backend/tests/integration/test_statement_corpus_journeys.py"
        )
        in matrix.PR_EVIDENCE_STAGES
    )


def test_L3_invariant_core_pillars_and_collection() -> None:
    """Verify the seven MECE L3 invariant pillars and pytest marker collection."""
    pillars = invariant_core.INVARIANT_CORE_PILLARS
    assert set(pillars) == {
        "double_entry_conservation",
        "decimal_precision",
        "three_statement_articulation",
        "ledger_and_fact_schema_invariants",
        "multi_tenant_isolation",
        "authz_and_route_boundaries",
        "pii_redaction_and_sanitization",
    }
    ordered = [path for paths in pillars.values() for path in paths]
    assert all(paths for paths in pillars.values())
    assert len(ordered) == len(set(ordered)), "Duplicate file across L3 pillars"
    assert invariant_core.ALL_INVARIANT_CORE_FILES == frozenset(ordered)

    for rel_path in ordered:
        target = ROOT / rel_path
        assert target.is_file(), f"Missing L3 invariant core file: {rel_path}"
        text = target.read_text(encoding="utf-8")
        if rel_path.endswith(".py"):
            assert re.search(r"^\s*(?:async\s+)?def\s+test_", text, re.MULTILINE), (
                rel_path
            )
        else:
            assert re.search(
                r"\b(?:it|test)(?:\.(?:each|concurrent|skipIf|runIf))?\s*\(", text
            ), rel_path

    backend_markers = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"][
        "pytest"
    ]["ini_options"]["markers"]
    root_markers = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert any(m.startswith("invariant_core:") for m in backend_markers)
    assert re.search(r"^\s*invariant_core\s*:", root_markers, re.MULTILINE)

    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            "invariant_core",
            "--no-cov",
            "-o",
            "addopts=",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, collected.stdout + "\n" + collected.stderr
    collected_files = {
        line.strip().split("::", 1)[0]
        for line in collected.stdout.splitlines()
        if "::" in line and not line.startswith(("=", "-"))
    }
    assert collected_files == invariant_core.BACKEND_INVARIANT_CORE_REL_FILES


def test_backend_ruff_format_is_enabled_and_non_empty() -> None:
    """Verify ruff format inspects real backend source and test files cleanly."""
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    fmt_cfg = pyproject.get("tool", {}).get("ruff", {}).get("format", {})
    excluded = fmt_cfg.get("exclude", [])
    assert "src/**" not in excluded and "tests/**" not in excluded
    lint_ignore = (
        pyproject.get("tool", {}).get("ruff", {}).get("lint", {}).get("ignore", [])
    )
    assert "E401" not in lint_ignore and "E702" not in lint_ignore

    res = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "src", "tests"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stdout + "\n" + res.stderr
    match = re.search(r"(\d+)\s+files?\s+already\s+formatted", res.stdout)
    assert match is not None and int(match.group(1)) > 500, res.stdout
