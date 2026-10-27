"""One Playwright install for every workflow (#2688).

The tag-to-staging run spent 9.3 minutes in an uncached `playwright install` inside the
benchmark. Four places installed Playwright and only some of them cached the browser.
`.github/actions/install-playwright` is now the only place that runs the install, and its
cache key is the Playwright version, because the browser revision follows that version.
"""

from __future__ import annotations

from pathlib import Path

import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ".github/actions/install-playwright/action.yml"
CI = ".github/workflows/ci.yml"


def _yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def _files_that_run_playwright_install() -> list[str]:
    candidates = sorted(
        [
            *(ROOT / ".github" / "workflows").glob("*.y*ml"),
            *(ROOT / ".github" / "actions").glob("*/action.y*ml"),
        ]
    )
    found: list[str] = []
    for path in candidates:
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0]
            if "playwright" in code and " install" in code and "uses:" not in code:
                found.append(path.relative_to(ROOT).as_posix())
                break
    return found


def test_only_the_install_action_runs_playwright_install() -> None:
    """AC-testing.toolchain.11: one composite runs `playwright install` for every workflow."""
    assert _files_that_run_playwright_install() == [ACTION]


def test_both_frontend_jobs_and_the_e2e_setup_call_the_install_action() -> None:
    """AC-testing.toolchain.11: the frontend jobs and the E2E setup share the one install."""
    jobs = _yaml(CI)["jobs"]
    for job_id in ("frontend-playwright", "frontend-telemetry-e2e"):
        installs = [
            step
            for step in jobs[job_id]["steps"]
            if step.get("uses") == "./.github/actions/install-playwright"
        ]
        assert len(installs) == 1, job_id
        assert installs[0]["with"] == {
            "command": "npx playwright",
            "working-directory": "apps/frontend",
        }

    e2e_steps = _yaml(".github/actions/setup-e2e-tests/action.yml")["runs"]["steps"]
    assert [
        step["with"]["command"]
        for step in e2e_steps
        if step.get("uses") == "./.github/actions/install-playwright"
    ] == ["./.venv/bin/playwright"]


def test_the_cache_key_is_the_playwright_version_and_the_browser() -> None:
    """AC-testing.toolchain.11: the browser cache key follows the Playwright version."""
    steps = _yaml(ACTION)["runs"]["steps"]
    cache = next(
        step for step in steps if step.get("uses", "").startswith("actions/cache@")
    )

    assert cache["with"]["path"] == "~/.cache/ms-playwright"
    assert cache["with"]["key"] == (
        "playwright-${{ runner.os }}-${{ steps.version.outputs.version }}"
        "-${{ inputs.browser }}"
    )
    # A fallback key would restore a browser revision that this version cannot launch.
    assert "restore-keys" not in cache["with"]

    ids = [step.get("id") for step in steps]
    assert ids.index("version") < steps.index(cache)


def test_no_step_of_the_install_action_is_skipped_by_a_cache_hit() -> None:
    """AC-testing.toolchain.11: a cache hit never skips the install.

    The install is idempotent and fast on a warm cache. Skipping it on `cache-hit`
    would let a restored browser from another revision pass unchecked.
    """
    steps = _yaml(ACTION)["runs"]["steps"]

    assert [step["name"] for step in steps if "if" in step] == []
    assert "cache-hit" not in (ROOT / ACTION).read_text(encoding="utf-8")


def _run_install_step(
    tmp_path: Path, *, fail_first: int
) -> tuple[subprocess.CompletedProcess[str], int]:
    """Run the real install step under GitHub's shell flags with a fake playwright.

    The fake fails with exit code 7 on its first `fail_first` calls. A `sleep` shim keeps
    the backoff out of the test. Returns the process and the number of playwright calls.
    """
    install = next(
        step["run"]
        for step in _yaml(ACTION)["runs"]["steps"]
        if "$PLAYWRIGHT_BROWSER" in step.get("run", "") and " install " in step["run"]
    )
    counter = tmp_path / "calls"
    counter.write_text("0", encoding="utf-8")
    fake = tmp_path / "fake-playwright"
    fake.write_text(
        "#!/bin/sh\n"
        f"n=$(($(cat {counter}) + 1)); echo $n > {counter}\n"
        'echo "browser download attempt $n: network down"\n'
        f'[ "$n" -le {fail_first} ] && exit 7\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    (tmp_path / "sleep").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tmp_path / "sleep").chmod(0o755)
    completed = subprocess.run(
        # GitHub runs `shell: bash` steps as `bash --noprofile --norc -eo pipefail {0}`.
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", install],
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "PLAYWRIGHT_COMMAND": str(fake),
            "PLAYWRIGHT_BROWSER": "chromium",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, int(counter.read_text(encoding="utf-8"))


def test_the_install_retries_a_failed_download_under_githubs_shell(tmp_path) -> None:
    """AC-testing.toolchain.11: a download that fails once is retried and the step passes.

    Under `bash -eo pipefail` a pipeline that is not guarded by `set +e` ends the step on
    the first failure, so a source-text check of the loop cannot see the defect.
    """
    completed, calls = _run_install_step(tmp_path, fail_first=1)

    assert (completed.returncode, calls) == (0, 2)
    assert "retrying in 10s" in completed.stdout


def test_the_install_keeps_the_original_error_when_the_retries_run_out(
    tmp_path,
) -> None:
    """AC-testing.toolchain.11: three failed attempts exit with the tool's code and its last error."""
    completed, calls = _run_install_step(tmp_path, fail_first=99)

    assert (completed.returncode, calls) == (7, 3)
    error_at = completed.stdout.index("::error::playwright install chromium failed")
    assert "(rc=7). Original error:" in completed.stdout
    # The last attempt's output is printed again after the final error line.
    assert "browser download attempt 3: network down" in completed.stdout[error_at:]


def test_the_install_adds_one_browser_and_no_apt_packages() -> None:
    """AC-testing.toolchain.11: the install adds one browser and takes no apt mirror time.

    `--with-deps` fetched fonts from the Azure Ubuntu mirror at 35-48 kB/s for 9 and
    11 minutes in two runs (#2688); the hosted image already has the libraries.
    """
    action = _yaml(ACTION)

    assert action["inputs"]["browser"]["default"] == "chromium"
    install = next(
        step["run"]
        for step in action["runs"]["steps"]
        if "$PLAYWRIGHT_BROWSER" in step.get("run", "") and " install " in step["run"]
    )
    assert '"${playwright[@]}" install "$PLAYWRIGHT_BROWSER"' in install
    assert "--with-deps" not in install and "install-deps" not in install
    assert "apt" not in install
    assert "firefox" not in install and "webkit" not in install
