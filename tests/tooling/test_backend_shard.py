"""File-level backend CI shard split (AC-testing.ci-structure.13, #2050)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from common.testing.backend_shard import (
    discover_test_files,
    file_durations,
    main,
    split_files,
)

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps/backend"
SEED = BACKEND / "ci/backend-test-durations.json"
BASH = shutil.which("bash") or "/bin/bash"


def _real_partition() -> tuple[list[str], list[list[str]]]:
    files = discover_test_files(BACKEND)
    durations = json.loads(SEED.read_text(encoding="utf-8"))
    return files, split_files(files, durations, 8)


def test_AC_testing_ci_structure_13_real_split_is_exhaustive_disjoint_and_balanced() -> (
    None
):
    """AC-testing.ci-structure.13: every backend test file runs in exactly one of the
    eight shards, and the seeded file-level split stays as balanced as the
    item-level split it replaces."""
    files, groups = _real_partition()

    assigned = [path for group in groups for path in group]
    assert len(groups) == 8
    assert all(groups)
    assert sorted(assigned) == files
    assert len(assigned) == len(set(assigned))

    per_file = file_durations(json.loads(SEED.read_text(encoding="utf-8")))
    weights = [sum(per_file.get(path, 0.0) for path in group) for group in groups]
    assert max(weights) <= 1.10 * (sum(weights) / len(weights))


def test_AC_testing_ci_structure_13_discovery_matches_pytest_configuration() -> None:
    """AC-testing.ci-structure.13: discovery mirrors how pytest finds backend tests, and
    nothing in the suite can hide a file from an explicit-path run."""
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    options = pyproject["tool"]["pytest"]["ini_options"]
    assert options["testpaths"] == ["tests"]
    assert options["python_files"] == ["test_*.py"]
    assert options.get("norecursedirs") is None

    # Explicit paths bypass collect_ignore / pytest_ignore_collect, so the
    # split must not coexist with either.
    hiding_hooks = ("collect_ignore", "pytest_ignore_collect")
    offenders = [
        conftest
        for conftest in (BACKEND / "tests").rglob("conftest.py")
        if any(hook in conftest.read_text(encoding="utf-8") for hook in hiding_hooks)
    ]
    assert offenders == []


def test_AC_testing_ci_structure_13_split_is_deterministic_and_seed_weighted(
    tmp_path: Path,
) -> None:
    """AC-testing.ci-structure.13: the least_duration rule places the heaviest file
    first, prices unseeded files at the seeded median, and ignores input order."""
    durations = {
        "tests/test_heavy.py::test_a": 30.0,
        "tests/test_heavy.py::test_b": 30.0,
        "tests/test_mid.py::test_a": 40.0,
        "tests/test_light.py::test_a": 10.0,
        "tests/test_tiny.py::test_a": 1.0,
    }
    files = [
        "tests/test_tiny.py",
        "tests/test_new.py",
        "tests/test_light.py",
        "tests/test_mid.py",
        "tests/test_heavy.py",
    ]
    assert file_durations(durations)["tests/test_heavy.py"] == 60.0

    # Weights: heavy 60, mid 40, new 25 (median of 60/40/10/1), light 10,
    # tiny 1 -> heavy|mid, then new->mid (65), light->heavy (70), tiny->mid.
    groups = split_files(files, durations, 2)
    assert groups == [
        ["tests/test_heavy.py", "tests/test_light.py"],
        ["tests/test_mid.py", "tests/test_new.py", "tests/test_tiny.py"],
    ]
    assert split_files(reversed(files), durations, 2) == groups
    # No seed at all: equal weights, round-robin in path order.
    assert split_files(files, {}, 3) == [
        ["tests/test_heavy.py", "tests/test_new.py"],
        ["tests/test_light.py", "tests/test_tiny.py"],
        ["tests/test_mid.py"],
    ]
    with pytest.raises(ValueError):
        split_files(files, durations, 0)


def test_AC_testing_ci_structure_13_cli_prints_one_group(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-testing.ci-structure.13: the workflow CLI prints exactly one shard's files and
    fails closed on a bad group or an empty test tree."""
    for name in ("test_a.py", "test_b.py", "sub/test_c.py", "helpers.py"):
        path = tmp_path / "tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    seed = tmp_path / "seed.json"
    seed.write_text(
        json.dumps({"tests/test_a.py::t": 5.0, "tests/sub/test_c.py::t": 3.0}),
        encoding="utf-8",
    )
    common = [
        "--splits",
        "2",
        "--durations-path",
        "seed.json",
        "--backend-root",
        str(tmp_path),
    ]

    printed = []
    for group in ("1", "2"):
        assert main([*common, "--group", group]) == 0
        printed.append(capsys.readouterr().out.split())
    assert sorted(printed[0] + printed[1]) == [
        "tests/sub/test_c.py",
        "tests/test_a.py",
        "tests/test_b.py",
    ]
    assert main([*common, "--group", "3"]) == 2

    empty = tmp_path / "empty"
    (empty / "tests").mkdir(parents=True)
    assert (
        main([*common[:-1], str(empty), "--group", "1", "--durations-path", str(seed)])
        == 1
    )


def test_AC_testing_ci_structure_13_shim_runs_without_backend_dependencies() -> None:
    """AC-testing.ci-structure.13: the shard step runs before `uv sync`, so the tool
    must work on an isolated interpreter with no third-party packages."""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "tools/backend_shard_files.py"),
            "--splits",
            "8",
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
    assert completed.stdout.split() == _real_partition()[1][0]


def _backend_run_script(shard: int) -> str:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    (script,) = [
        str(step["run"])
        for step in workflow["jobs"]["backend"]["steps"]
        if isinstance(step, dict) and "pytest" in str(step.get("run", ""))
    ]
    return script.replace("${{ matrix.shard }}", str(shard))


@pytest.mark.parametrize("shard", [1, 8])
def test_AC_testing_ci_structure_13_workflow_runs_exactly_the_selected_files(
    tmp_path: Path, shard: int
) -> None:
    """AC-testing.ci-structure.13: executing the backend shard step itself (with a
    stub `uv` that records its arguments) hands pytest exactly this shard's
    files, and pytest is not asked to re-split them."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    recorded = tmp_path / "uv-args.json"
    (bin_dir / "uv").write_text(
        "#!/bin/sh\n"
        f'exec "{sys.executable}" -c "import json, sys; '
        f"json.dump(sys.argv[1:], open('{recorded}', 'w'))\" \"$@\"\n",
        encoding="utf-8",
    )
    (bin_dir / "python").symlink_to(sys.executable)
    (bin_dir / "uv").chmod(0o755)

    subprocess.run(
        [BASH, "-e", "-c", _backend_run_script(shard)],
        cwd=ROOT,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path)},
        check=True,
        capture_output=True,
        text=True,
    )
    args = json.loads(recorded.read_text(encoding="utf-8"))
    expected = _real_partition()[1][shard - 1]

    assert args[:2] == ["run", "pytest"]
    assert args[-len(expected) :] == expected
    assert not {"--splits", "--group", "--durations-path"} & set(args)


def test_AC_testing_ci_structure_13_workflow_fails_closed_on_empty_selection(
    tmp_path: Path,
) -> None:
    """AC-testing.ci-structure.13: a selector that prints nothing stops the step before
    pytest runs, instead of letting pytest fall back to the whole suite."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "uv-ran"
    (bin_dir / "uv").write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    (bin_dir / "uv").chmod(0o755)
    (bin_dir / "python").write_text(
        f'#!/bin/sh\ncase "$1" in *backend_shard_files.py) exit 0;; esac\n'
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    (bin_dir / "python").chmod(0o755)

    completed = subprocess.run(
        [BASH, "-e", "-c", _backend_run_script(1)],
        cwd=ROOT,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert not marker.exists()
