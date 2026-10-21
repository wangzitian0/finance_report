"""AC-testing.backend-test-timeout.1/.2/.3: a backend test that never returns fails by name (#2398).

Backend shards ran to the 15-minute job timeout at least 12 times in 4 days. A rerun of the same
shard passed in about 2.5 minutes. The job log held no name for the stuck test. A per-test timeout
turns a hang into a named failure inside the PR budget. In an xdist worker the stack dump of
pytest-timeout is lost, so faulthandler prints the stack of every thread before the timeout.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "apps" / "backend" / "pyproject.toml"
SLOWEST_GREEN_TEST_SECONDS = 8.77  # 3800 backend tests, green run 38359010909
HANG_SECONDS = 30
PROOF_TIMEOUT_SECONDS = 2
XDIST_PROOF_TIMEOUT_SECONDS = 3
XDIST_PROOF_DUMP_SECONDS = 1


def _pytest_options() -> dict:
    return tomllib.loads(PYPROJECT.read_text())["tool"]["pytest"]["ini_options"]


def test_AC_testing_backend_test_timeout_1_config_sets_a_thread_timeout_that_fits_the_pr_budget():
    """AC-testing.backend-test-timeout.1: the backend config sets a thread timeout that fits the PR budget."""
    config = tomllib.loads(PYPROJECT.read_text())
    options = _pytest_options()

    assert options["timeout_method"] == "thread"
    # The limit sits well above the slowest green test and far below the 15-minute job limit.
    assert SLOWEST_GREEN_TEST_SECONDS * 5 <= options["timeout"] <= 120
    assert any(
        item.startswith("pytest-timeout") for item in config["dependency-groups"]["dev"]
    )


def test_AC_testing_backend_test_timeout_2_a_hung_test_fails_by_name_with_the_project_method(
    tmp_path,
):
    """AC-testing.backend-test-timeout.2: a hung test fails the run, and the output names the test."""
    test_file = tmp_path / "test_hangs_forever.py"
    test_file.write_text(
        f"import time\n\n\ndef test_never_returns():\n    time.sleep({HANG_SECONDS})\n"
    )
    (tmp_path / "pytest.ini").write_text(
        f"[pytest]\ntimeout = {PROOF_TIMEOUT_SECONDS}\ntimeout_method = {_pytest_options()['timeout_method']}\n"
    )

    started = time.monotonic()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            str(test_file),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=HANG_SECONDS,
        check=False,
    )
    elapsed = time.monotonic() - started

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Timeout" in output
    assert "test_never_returns" in output
    assert elapsed < HANG_SECONDS / 2, (
        f"the hung test ran {elapsed:.1f}s; the timeout did not stop it"
    )


def _run_hung_test_in_an_xdist_worker(tmp_path: Path, extra_ini: str) -> str:
    tmp_path.mkdir()
    test_file = tmp_path / "test_hangs_forever.py"
    test_file.write_text(
        f"import time\n\n\ndef test_never_returns():\n    time.sleep({HANG_SECONDS})\n"
    )
    (tmp_path / "pytest.ini").write_text(
        f"[pytest]\ntimeout = {XDIST_PROOF_TIMEOUT_SECONDS}\n"
        f"timeout_method = {_pytest_options()['timeout_method']}\n{extra_ini}"
    )
    # Only the two plugins under test load, so each run starts in about one second.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "xdist.plugin",
            "-p",
            "pytest_timeout",
            "-p",
            "no:cacheprovider",
            "-n",
            "1",
            "--max-worker-restart",
            "0",
            "-q",
            str(test_file),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
        timeout=HANG_SECONDS,
        check=False,
    )
    assert result.returncode != 0
    return result.stdout + result.stderr


def test_AC_testing_backend_test_timeout_3_a_hung_xdist_worker_prints_its_stack_before_the_timeout(
    tmp_path,
):
    """AC-testing.backend-test-timeout.3: in an xdist worker a hung test prints its stack to the job log."""
    options = _pytest_options()
    # The stack dump fires after the slowest green test and before the timeout ends the worker.
    assert (
        SLOWEST_GREEN_TEST_SECONDS
        < options["faulthandler_timeout"]
        < options["timeout"]
    )

    # Without faulthandler the worker dies with no stack: the pytest-timeout dump goes to stdout,
    # which execnet points at /dev/null in a worker. The frame text is absent from the output.
    without = _run_hung_test_in_an_xdist_worker(tmp_path / "without", "")
    assert "crashed while running" in without
    assert "in test_never_returns" not in without

    with_dump = _run_hung_test_in_an_xdist_worker(
        tmp_path / "with", f"faulthandler_timeout = {XDIST_PROOF_DUMP_SECONDS}\n"
    )
    assert f"Timeout (0:00:0{XDIST_PROOF_DUMP_SECONDS})!" in with_dump
    assert "in test_never_returns" in with_dump
