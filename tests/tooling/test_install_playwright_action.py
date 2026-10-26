"""One Playwright install for every workflow (#2688).

The tag-to-staging run spent 9.3 minutes in an uncached `playwright install` inside the
benchmark. Four places installed Playwright and only some of them cached the browser.
`.github/actions/install-playwright` is now the only place that runs the install, and its
cache key is the Playwright version, because the browser revision follows that version.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ".github/actions/install-playwright/action.yml"
CI = ".github/workflows/ci.yml"


def _yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def _files_that_run_playwright_install() -> list[str]:
    candidates = sorted(
        [
            *(ROOT / ".github" / "workflows").glob("*.yml"),
            *(ROOT / ".github" / "actions").glob("*/action.yml"),
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
