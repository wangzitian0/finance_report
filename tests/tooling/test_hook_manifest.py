"""Guard for the hook steps of runtime-hooks.manifest.json (#2912, #2914)."""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from common.testing import matrix

ROOT = Path(__file__).resolve().parents[2]
SLOTS = json.loads((ROOT / "runtime-hooks.manifest.json").read_text("utf-8"))["slots"]
SH_C = ["sh", "-c"]


def _check_line(check: dict) -> str:
    """Return the shell text of a check, or its argv joined with spaces when it runs without a shell."""
    argv = check["argv"]
    return argv[2] if argv[:2] == SH_C else " ".join(argv)


STEPS = [(s, k, v[k]) for s, v in SLOTS.items() for k in ("bootstrap", "run") if k in v]
STEPS += [
    (s, "check", _check_line(c)) for s, v in SLOTS.items() for c in v.get("checks", [])
]
CHECKS = [(s, c) for s, v in SLOTS.items() for c in v.get("checks", [])]
BASH_ONLY = ("[@]", "${#", "[[", "<(", "sudo", "ln -sf")
RUN_CALL = r"--stage (\S+)(?: --corpus (\S+))? --run"


def _violations(line: str) -> list[str]:
    found = [token for token in BASH_ONLY if token in line]
    found += ["eval"] if re.search(r"\beval\b", line) else []
    if re.search(r"\bpytest\b", line) and "python -m pytest" not in line:
        found.append(f"bare pytest: {line}")
    strict = line.endswith(" --run") or "STRICT_E2E_GATES=1" in line
    if re.search(r"\bpytest\b|test_selection", line) and not strict:
        found.append(f"not a strict gate: {line}")
    return found


def _dash_error(line: str) -> str:
    dash = shutil.which("dash")
    assert dash, "dash is missing: install dash, infra2 runs hook steps with sh -lc"
    run = subprocess.run([dash, "-n", "-c", line], capture_output=True, text=True)
    return run.stderr if run.returncode else ""


def test_AC_testing_deploy_gates_46_hook_steps_are_posix_strict_gates() -> None:
    """AC-testing.deploy-gates.46: every hook step parses under dash and starts each pytest as a strict gate."""
    assert len(CHECKS) >= 10, "the manifest lost a hook check"
    for slot, step, line in STEPS:
        assert _dash_error(line) == "", f"{slot}.{step} fails dash -n"
        assert _violations(line) == [], f"{slot}.{step}: {_violations(line)}"


def test_no_slot_run_chains_with_and() -> None:
    """AC-testing.deploy-gates.46: a slot holds one `run` step or a `checks` list, never an `&&` chain."""
    assert len(CHECKS) >= 10, "the manifest has no check list to guard"
    for slot, spec in SLOTS.items():
        assert "&&" not in spec.get("run", ""), (
            f"{slot}.run chains steps with &&: use checks"
        )
        for check in spec.get("checks", []):
            assert "&&" not in _check_line(check), (
                f"{slot}.{check['id']} chains steps with &&"
            )


def test_every_slot_check_id_is_unique_and_named() -> None:
    """AC-testing.deploy-gates.46: a slot holds `run` or a non-empty `checks`; check ids are unique snake_case names."""
    for slot, spec in SLOTS.items():
        checks = spec.get("checks", [])
        assert bool(spec.get("run")) != bool(checks), (
            f"{slot} needs exactly one of run and a non-empty checks"
        )
        ids = [check["id"] for check in checks]
        assert len(ids) == len(set(ids)), f"{slot} repeats a check id: {ids}"
        for check_id in ids:
            assert re.fullmatch(r"[a-z][a-z0-9_]*", check_id), (
                f"{slot}: check id {check_id!r} is not a snake_case name"
            )
        assert all(check["argv"] for check in checks), (
            f"{slot} has a check with an empty argv"
        )


def _run_slot(slot: str, tmp_path: Path, fail_at: int | None = None):
    from infra2_sdk.manifests import load_hooks_manifest, run_hook_slot

    calls: list[list[str]] = []

    def runner(argv, **_kwargs):
        calls.append(list(argv))
        # call 0 is the bootstrap of a slot that has one; checks follow it
        failed = fail_at is not None and len(calls) - 1 == fail_at
        return subprocess.CompletedProcess(
            argv,
            1 if failed else 0,
            "",
            "boom: first error\nsecond line" if failed else "",
        )

    manifest = load_hooks_manifest(ROOT / "runtime-hooks.manifest.json")
    result = run_hook_slot(
        manifest,
        slot,
        app_url="https://fake.invalid",
        cwd=tmp_path,
        ambient_env={},
        runner=runner,
    )
    checks_file = tmp_path / manifest.slots[slot].artifacts_dir / "checks.jsonl"
    record = json.loads(checks_file.read_text("utf-8").splitlines()[-1])
    return result, record["checks"], calls


@pytest.mark.parametrize("slot", sorted(SLOTS))
def test_AC2_each_slot_reports_each_check_with_seconds(
    slot: str, tmp_path: Path
) -> None:
    """Every slot writes one passing record per check id, in manifest order, with seconds."""
    result, records, calls = _run_slot(slot, tmp_path)
    expected = [c["id"] for c in SLOTS[slot].get("checks", [])] or [slot]
    assert result.status == "pass"
    assert [r["name"] for r in records] == expected
    assert all(r["ok"] is True and isinstance(r["seconds"], float) for r in records)
    assert len(calls) == len(expected) + ("bootstrap" in SLOTS[slot])


def test_AC3_the_first_failing_check_is_listed_with_its_first_error_line(
    tmp_path: Path,
) -> None:
    """A forced failure of the 2nd check of staging_gate stops the slot and names that check."""
    ids = [c["id"] for c in SLOTS["staging_gate"]["checks"]]
    offset = 1 if "bootstrap" in SLOTS["staging_gate"] else 0
    result, records, calls = _run_slot("staging_gate", tmp_path, fail_at=offset + 1)
    assert result.status == "fail"
    assert [r["name"] for r in records] == ids[:2]
    assert records[0]["ok"] is True
    assert records[1]["ok"] is False and records[1]["detail"] == "boom: first error"
    assert len(calls) == offset + 2


@pytest.mark.parametrize(
    "mutant",
    [
        'eval "$(python tools/test_selection.py --stage staging_core_e2e --shell)"',
        "uv pip install x && pytest tests/e2e/a.py",
        "python tools/test_selection.py --stage staging_core_e2e",
        "python -m pytest tests/e2e/test_ai_provider_connectivity.py -v",
        "sudo ln -sf /bin/bash /bin/sh",
    ],
)
def test_the_checks_reject_a_mutant(mutant: str) -> None:
    assert _violations(mutant)


def test_dash_rejects_an_array_assignment() -> None:
    assert _dash_error("TESTS=(a b) && echo ${TESTS[@]}")


def _env_skips(path: Path) -> list[tuple[str, set[str]]]:
    """Return (test, env names) of each critical test with a skipif on an env-derived name."""
    tree = ast.parse(path.read_text("utf-8"))
    env: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            getter = r"os\.(?:getenv|environ\.get)\('(\w+)'"
            env[node.targets[0].id] = set(re.findall(getter, ast.unparse(node.value)))
    found = []
    for node in ast.walk(tree):
        decorators = getattr(node, "decorator_list", [])
        if "pytest.mark.critical" not in [ast.unparse(d) for d in decorators]:
            continue
        for d in decorators:
            if isinstance(d, ast.Call) and ast.unparse(d.func) == "pytest.mark.skipif":
                names = re.findall(r"\w+", ast.unparse(d.args[0]))
                used = set().union(*(env.get(name, set()) for name in names))
                found += [(node.name, used)] if used else []
    return found


def test_AC_testing_deploy_gates_46_stage_env_covers_critical_env_skips() -> None:
    """AC-testing.deploy-gates.46: the stage env sets each env name that skips a critical test the stage selects."""
    runs = " ".join(line for _, step, line in STEPS if step in ("run", "check"))
    checked = 0
    for stage, corpus in re.findall(RUN_CALL, runs):
        nodes, _ = matrix.stage_selection(stage, corpus=corpus or "all")
        for file in sorted({node.split("::")[0] for node in nodes}):
            for test, names in _env_skips(ROOT / file):
                checked += 1
                gap = sorted(names - set(matrix.stage_env(stage)))
                assert not gap, f"{file}::{test}: STAGE_ENV[{stage!r}] lacks {gap}"
    assert checked >= 1, "no critical test with an env skip condition was scanned"


PYTHON_MODULE = re.compile(r"\bpython3?\s+-m\s+([A-Za-z_][\w.]*)")
HOOK_SLOTS_WITH_MODULES = ("preview_gate", "staging_gate", "scheduled_audit")


def _python_modules(line: str) -> list[str]:
    """Return the module name of each `python -m <module>` in a shell line."""
    return PYTHON_MODULE.findall(line)


def _module_checks() -> list[tuple[str, str, str]]:
    """Return (slot, step id, module) for each `python -m <module>` step of the manifest."""
    steps: list[tuple[str, str, str]] = []
    for slot, spec in SLOTS.items():
        steps += [(slot, key, spec[key]) for key in ("bootstrap", "run") if key in spec]
        steps += [(slot, c["id"], _check_line(c)) for c in spec.get("checks", [])]
    return [(s, i, m) for s, i, line in steps for m in _python_modules(line)]


MODULE_CHECKS = _module_checks()


def _run_module(*args: str) -> subprocess.CompletedProcess[str]:
    """Run `<this python> -m <args>` in the repository root, as the SDK runs a hook step."""
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )


@pytest.mark.parametrize(
    ("stage", "corpus"), [("staging_core_e2e", None), ("staging_ai_ocr", "canary")]
)
def test_AC_testing_hook_main_1_module_prints_each_node_of_the_matrix_selection(
    stage: str, corpus: str | None
) -> None:
    """AC-testing.hook-main.1: `python -m common.testing.test_selection --stage <stage>` exits 0 and prints each node of the matrix selection."""
    nodes, _ = matrix.stage_selection(stage, corpus=corpus or "all")
    assert nodes, f"the matrix selects no test for {stage}"
    extra = ["--corpus", corpus] if corpus else []
    run = _run_module("common.testing.test_selection", "--stage", stage, *extra)
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines() == list(nodes), (
        f"{stage}: the module printed {run.stdout!r}"
    )


@pytest.mark.parametrize(("slot", "step", "module"), MODULE_CHECKS)
def test_AC_testing_hook_main_2_each_manifest_module_check_prints_help(
    slot: str, step: str, module: str
) -> None:
    """AC-testing.hook-main.2: each `python -m <module>` step of the manifest exits 0 on `--help` and prints text."""
    run = _run_module(module, "--help")
    assert run.returncode == 0, f"{slot}.{step}: {module} --help: {run.stderr}"
    assert run.stdout.strip(), (
        f"{slot}.{step}: `python -m {module} --help` printed nothing; the module has no main block"
    )


def test_AC_testing_hook_main_3_the_scan_covers_every_hook_slot_with_a_module() -> None:
    """AC-testing.hook-main.3: the scan reads the manifest and finds a module in each gate slot."""
    found = {slot: {m for s, _, m in MODULE_CHECKS if s == slot} for slot in SLOTS}
    for slot in HOOK_SLOTS_WITH_MODULES:
        assert found[slot], f"the scan finds no `python -m` step in {slot}"
    assert "common.testing.test_selection" in found["staging_gate"]
    assert len({m for _, _, m in MODULE_CHECKS}) >= 3, "the scan lost a module"
    assert _python_modules("env A=1 python3 -m a.b --x; sh -c 'python -m c_d'") == [
        "a.b",
        "c_d",
    ]
    assert _python_modules("python tools/test_selection.py --stage x") == []
