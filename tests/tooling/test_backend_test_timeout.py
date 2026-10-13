"""AC-testing.backend-test-timeout.1/.2: a backend test that never returns fails by name (#2398).

Backend shards ran to the 15-minute job timeout at least 12 times in 4 days. A rerun of the same
shard passed in about 2.5 minutes. The job log held no name for the stuck test. A per-test timeout
turns a hang into a named failure inside the PR budget.
"""

from __future__ import annotations

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
