"""Guard for the hook steps of runtime-hooks.manifest.json (#2912, #2914)."""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from common.testing import matrix

ROOT = Path(__file__).resolve().parents[2]
SLOTS = json.loads((ROOT / "runtime-hooks.manifest.json").read_text("utf-8"))["slots"]
STEPS = [(s, k, v[k]) for s, v in SLOTS.items() for k in ("bootstrap", "run") if k in v]
BASH_ONLY = ("[@]", "${#", "[[", "<(", "sudo", "ln -sf")
RUN_CALL = r"--stage (\S+)(?: --corpus (\S+))? --run"


def _violations(line: str) -> list[str]:
    found = [token for token in BASH_ONLY if token in line]
    found += ["eval"] if re.search(r"\beval\b", line) else []
    for segment in (part.strip() for part in line.split("&&")):
        if re.search(r"\bpytest\b", segment) and "python -m pytest" not in segment:
            found.append(f"bare pytest: {segment}")
        strict = segment.endswith(" --run") or segment.startswith("STRICT_E2E_GATES=1 ")
        if re.search(r"\bpytest\b|tools/test_selection\.py", segment) and not strict:
            found.append(f"not a strict gate: {segment}")
    return found


def _dash_error(line: str) -> str:
    dash = shutil.which("dash")
    assert dash, "dash is missing: install dash, infra2 runs hook steps with sh -lc"
    run = subprocess.run([dash, "-n", "-c", line], capture_output=True, text=True)
    return run.stderr if run.returncode else ""


def test_AC_testing_deploy_gates_46_hook_steps_are_posix_strict_gates() -> None:
    """AC-testing.deploy-gates.46: every hook step parses under dash and starts each pytest as a strict gate."""
    assert len(STEPS) >= 7, "the manifest lost a hook step"
    for slot, step, line in STEPS:
        assert _dash_error(line) == "", f"{slot}.{step} fails dash -n"
        assert _violations(line) == [], f"{slot}.{step}: {_violations(line)}"


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
    runs = " ".join(line for _, step, line in STEPS if step == "run")
    checked = 0
    for stage, corpus in re.findall(RUN_CALL, runs):
        nodes, _ = matrix.stage_selection(stage, corpus=corpus or "all")
        for file in sorted({node.split("::")[0] for node in nodes}):
            for test, names in _env_skips(ROOT / file):
                checked += 1
                gap = sorted(names - set(matrix.stage_env(stage)))
                assert not gap, f"{file}::{test}: STAGE_ENV[{stage!r}] lacks {gap}"
    assert checked >= 1, "no critical test with an env skip condition was scanned"
