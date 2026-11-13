"""Guard for the hook steps of runtime-hooks.manifest.json (#2912, #2914)."""

from __future__ import annotations

import ast
import json
import re
import runpy
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from common.testing import matrix
from common.testing.change_classifier import Environment, classify_changed_paths

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


HOOK_SLOTS_WITH_PYTHON = ("preview_gate", "staging_gate", "scheduled_audit")
SEPARATORS = {"&&", "||", ";", "|", "&"}
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
PYTHON_HEAD = re.compile(r"(?:.*/)?python[0-9.]*|\$\{?\w+\}?")
MODULE_NAME = re.compile(r"[A-Za-z_][\w.]*")
BOOTSTRAP_PREFIXES = (["uv", "pip", "install"], ["playwright", "install"])
HELP_KINDS = ("module", "pytest", "script")
Step = tuple[str, str]


def _commands(text: str) -> list[list[str]]:
    """Split shell text into simple commands (word lists) at `&&`, `||`, `;`, `|` and `&`."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    commands: list[list[str]] = [[]]
    for word in lexer:
        commands.append([]) if word in SEPARATORS else commands[-1].append(word)
    return [words for words in commands if words]


def _module_step(name: str) -> Step | None:
    if name == "pytest":
        return ("pytest", "pytest")
    return ("module", name) if MODULE_NAME.fullmatch(name) else None


def _python_step(args: list[str]) -> Step | None:
    """Return the module or script that the words after a Python interpreter run, or None."""
    index = 0
    while index < len(args):
        word = args[index]
        if word in ("-X", "-W"):
            index += 2
        elif re.fullmatch(r"-[A-Za-z]*c", word):
            return None
        elif re.fullmatch(r"-[A-Za-z]*m", word):
            return _module_step(args[index + 1] if index + 1 < len(args) else "")
        elif re.fullmatch(r"-m\S+", word):
            return _module_step(word[2:])
        elif word.startswith("-"):
            index += 1
        else:
            known = word.endswith(".py") and (ROOT / word).is_file()
            return ("script", word) if known else None
    return None


def _classify_words(words: list[str], *, bootstrap: bool) -> list[Step]:
    """Classify one simple command as bash, bootstrap, pytest, module, script or unknown."""
    text = " ".join(words)
    words = words[1:] if words[:1] == ["env"] else words
    while words and ASSIGNMENT.match(words[0]):
        words = words[1:]
    if not words:
        return [("unknown", text)]
    if bootstrap and any(
        words[: len(prefix)] == prefix for prefix in BOOTSTRAP_PREFIXES
    ):
        return [("bootstrap", text)]
    head, rest = words[0], words[1:]
    if (
        head in ("sh", "bash", "dash")
        and len(rest) > 1
        and re.fullmatch(r"-[a-z]*c", rest[0])
    ):
        return _classify_text(rest[1], bootstrap=bootstrap)
    if (
        head in ("sh", "bash", "dash")
        and rest
        and rest[0].endswith(".sh")
        and (ROOT / rest[0]).is_file()
    ):
        return [("bash", rest[0])]
    if head == "pytest":
        return [("pytest", "pytest")]
    if PYTHON_HEAD.fullmatch(head):
        return [_python_step(rest) or ("unknown", text)]
    return [("unknown", text)]


def _classify_text(text: str, *, bootstrap: bool = False) -> list[Step]:
    try:
        commands = _commands(text)
    except ValueError:
        return [("unknown", text)]
    steps = [
        s for words in commands for s in _classify_words(words, bootstrap=bootstrap)
    ]
    return steps or [("unknown", text)]


def _classify_step(step: str | list[str], *, bootstrap: bool = False) -> list[Step]:
    """Classify a manifest step: shell text of `run` and `bootstrap`, or the argv of a check."""
    if isinstance(step, str):
        return _classify_text(step, bootstrap=bootstrap)
    return _classify_words(list(step), bootstrap=bootstrap)


def _manifest_steps() -> list[tuple[str, str, str | list[str], bool]]:
    """Return (slot, step id, command, is bootstrap) for each step of each slot, read from the manifest."""
    steps: list[tuple[str, str, str | list[str], bool]] = []
    for slot, spec in SLOTS.items():
        steps += [
            (slot, key, spec[key], key == "bootstrap")
            for key in ("bootstrap", "run")
            if key in spec
        ]
        steps += [
            (slot, check["id"], check["argv"], False)
            for check in spec.get("checks", [])
        ]
    return steps


MANIFEST_STEPS = _manifest_steps()
SCANNED = [
    (slot, step_id, kind, target)
    for slot, step_id, step, bootstrap in MANIFEST_STEPS
    for kind, target in _classify_step(step, bootstrap=bootstrap)
]
HELP_CALLS = sorted({call for call in SCANNED if call[2] in HELP_KINDS})


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


@pytest.mark.parametrize(("slot", "step", "kind", "target"), HELP_CALLS)
def test_AC_testing_hook_main_2_each_manifest_python_step_prints_help(
    slot: str, step: str, kind: str, target: str
) -> None:
    """AC-testing.hook-main.2: each Python module or script step of the manifest exits 0 on `--help` and prints text."""
    argv = {
        "module": [sys.executable, "-m", target, "--help"],
        "pytest": [sys.executable, "-m", "pytest", "--help"],
        "script": [sys.executable, target, "--help"],
    }[kind]
    run = subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, timeout=40, check=False
    )
    assert run.returncode == 0, f"{slot}.{step}: {argv[1:]}: {run.stderr}"
    assert run.stdout.strip(), (
        f"{slot}.{step}: `{target} --help` printed nothing; the target has no main block"
    )


def test_AC_testing_hook_main_3_every_manifest_step_fits_a_known_form() -> None:
    """AC-testing.hook-main.3: each manifest step is bash, bootstrap, pytest, a module or a script; a step of any other form fails."""
    unknown = [
        (slot, step, text) for slot, step, kind, text in SCANNED if kind == "unknown"
    ]
    assert unknown == [], (
        f"hook steps that fit no known form; add the form to this test on purpose: {unknown}"
    )
    assert {(s, i) for s, i, _, _ in SCANNED} == {
        (s, i) for s, i, _, _ in MANIFEST_STEPS
    }
    for slot in HOOK_SLOTS_WITH_PYTHON:
        kinds = {kind for s, _, kind, _ in SCANNED if s == slot}
        assert kinds & set(HELP_KINDS), f"the scan finds no Python step in {slot}"
    assert (
        "staging_gate",
        "staging_core_e2e",
        "module",
        "common.testing.test_selection",
    ) in SCANNED
    assert len({target for _, _, kind, target in SCANNED if kind == "module"}) >= 3


@pytest.mark.parametrize(
    ("step", "bootstrap", "expected"),
    [
        (["python", "-m", "a.b", "--x"], False, [("module", "a.b")]),
        (["python3.12", "-m", "a.b"], False, [("module", "a.b")]),
        (["python", "-u", "-m", "a.b"], False, [("module", "a.b")]),
        (["python", "-X", "dev", "-m", "a.b"], False, [("module", "a.b")]),
        (["python", "-ma.b"], False, [("module", "a.b")]),
        (["python", "-um", "a.b"], False, [("module", "a.b")]),
        (["$PY", "-m", "a.b"], False, [("module", "a.b")]),
        (["env", "K=V", "python", "-m", "pytest", "-v"], False, [("pytest", "pytest")]),
        (["pytest", "tests/x.py"], False, [("pytest", "pytest")]),
        (
            ["sh", "-c", "python -m a.b && python3 -m c_d"],
            False,
            [("module", "a.b"), ("module", "c_d")],
        ),
        (
            ["sh", "-lc", 'bash common/runtime/shell/smoke_test.sh "$U"'],
            False,
            [("bash", "common/runtime/shell/smoke_test.sh")],
        ),
        (
            ["python", "tools/preflight.py", "--x"],
            False,
            [("script", "tools/preflight.py")],
        ),
        (
            "uv pip install x && playwright install chromium",
            True,
            [
                ("bootstrap", "uv pip install x"),
                ("bootstrap", "playwright install chromium"),
            ],
        ),
        (["node", "a.js"], False, [("unknown", "node a.js")]),
        (["python", "-c", "print(1)"], False, [("unknown", "python -c print(1)")]),
        (
            ["python", "tools/no_such_gate.py"],
            False,
            [("unknown", "python tools/no_such_gate.py")],
        ),
        (["python", "-m", "$MOD"], False, [("unknown", "python -m $MOD")]),
        ("uv pip install x", False, [("unknown", "uv pip install x")]),
    ],
)
def test_AC_testing_hook_main_6_the_classifier_reads_each_form_of_a_python_step(
    step: str | list[str], bootstrap: bool, expected: list[Step]
) -> None:
    """AC-testing.hook-main.6: the step classifier reads flags, `env`, `sh -c`, `$PY` and `-mx`, and marks any other form unknown."""
    assert _classify_step(step, bootstrap=bootstrap) == expected


def test_AC_testing_hook_main_4_module_exits_2_on_an_unknown_stage() -> None:
    """AC-testing.hook-main.4: `python -m common.testing.test_selection --stage no_such_stage` exits 2 and names the stage error on stderr."""
    run = _run_module("common.testing.test_selection", "--stage", "no_such_stage")
    assert run.returncode == 2, f"exit {run.returncode}: {run.stderr!r}"
    assert "unknown selection stage 'no_such_stage'" in run.stderr
    assert run.stdout == ""


def test_AC_testing_hook_main_5_main_block_exits_with_the_pytest_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.hook-main.5: the main block of the module raises SystemExit with the exit code of the selected pytest run."""
    calls: list[list[str]] = []

    def failing_run(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 3)

    monkeypatch.setattr(subprocess, "run", failing_run)
    monkeypatch.setattr(
        sys, "argv", ["test_selection", "--stage", "staging_core_e2e", "--run"]
    )
    with pytest.raises(SystemExit) as stop:
        runpy.run_path(
            str(ROOT / "common/testing/test_selection.py"), run_name="__main__"
        )
    assert stop.value.code == 3
    assert len(calls) == 1 and calls[0][1:3] == ["-m", "pytest"]


def _module_file(module: str) -> str:
    base = Path(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__main__.py"):
        if (ROOT / candidate).is_file():
            return candidate.as_posix()
    raise AssertionError(f"no file for module {module}")


def test_AC_testing_hook_main_7_the_classifier_marks_each_hook_python_file_as_staging_relevant() -> (
    None
):
    """AC-testing.hook-main.7: the change classifier marks the file of each `python -m common...` or `python common/...` hook step as staging-relevant."""
    modules = {
        _module_file(t)
        for _, _, k, t in SCANNED
        if k == "module" and t.startswith("common.")
    }
    scripts = {t for _, _, k, t in SCANNED if k == "script" and t.startswith("common/")}
    files = sorted(modules | scripts)
    assert "common/testing/test_selection.py" in files
    for file in files:
        staging = classify_changed_paths([file]).envs[Environment.STAGING]
        assert staging.required and staging.files == (file,), (
            f"{file} runs in a hook step but a change to it does not start the staging gate"
        )
