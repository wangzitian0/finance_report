"""AC-testing.benchmarks.2: the benchmark workflow fails when a case fails or is skipped (#2318).

Before this change the run step had `continue-on-error: true` and no browser, so the UI
case was SKIPPED, reported as PASS, and the workflow stayed green.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "benchmark.yml"
E2E_REQUIREMENTS = REPO_ROOT / "tests" / "e2e" / "requirements.txt"
LOCK = REPO_ROOT / "apps" / "backend" / "uv.lock"


def _steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["run-benchmark"]["steps"]


def _step(name_part: str) -> dict:
    matches = [s for s in _steps() if name_part in s.get("name", "")]
    assert len(matches) == 1, (
        f"expected one step with {name_part!r}, found {len(matches)}"
    )
    return matches[0]


def _lock_version(package: str) -> str:
    text = LOCK.read_text(encoding="utf-8")
    match = re.search(
        rf'\[\[package\]\]\nname = "{package}"\nversion = "([^"]+)"', text
    )
    assert match, f"{package} is not in {LOCK}"
    return match.group(1)


def test_the_playwright_version_is_pinned_and_matches_the_lockfile() -> None:
    """The benchmark takes Playwright from the E2E requirements, so the pin lives there.

    Unpinned, the version froze at whatever the venv cache held (1.60.0) and the
    release-critical benchmark changed browser whenever that cache was rebuilt.
    """
    lines = E2E_REQUIREMENTS.read_text(encoding="utf-8").split()

    assert f"playwright=={_lock_version('playwright')}" in lines


def test_the_run_step_does_not_swallow_a_failure() -> None:
    run = _step("Run Financial Scenario Benchmark Suite")

    assert "continue-on-error" not in run


def test_the_cached_browser_install_runs_before_the_run_step() -> None:
    """The E2E setup composite is the one cached Playwright install (#2688).

    A separate `playwright install` step took 9.3 minutes uncached in the v0.2.31 run.
    """
    names = [s.get("name", "") for s in _steps()]
    setup = _step("Set up the E2E toolchain and Playwright browser")

    assert setup["uses"] == "./.github/actions/setup-e2e-tests"
    assert names.index(setup["name"]) < names.index(
        "Run Financial Scenario Benchmark Suite"
    )
    assert not any("playwright install" in s.get("run", "") for s in _steps())


def test_the_benchmark_packages_come_from_the_e2e_requirements() -> None:
    """The run step no longer adds packages through `uv run --with`."""
    requirements = E2E_REQUIREMENTS.read_text(encoding="utf-8").split()

    for package in ("httpx", "reportlab", "pyyaml", "pytest-playwright"):
        assert package in requirements
    for step in _steps():
        assert "uv run" not in step.get("run", "")


def test_the_report_is_published_even_when_the_benchmark_fails() -> None:
    names = [s.get("name", "") for s in _steps()]
    after = _steps()[names.index("Run Financial Scenario Benchmark Suite") + 1 :]

    assert [step.get("name") for step in after] == [
        "Fetch the published benchmark history",
        "Update benchmark multi-version index & manifest",
        "Deploy Benchmark Observatory to GitHub Pages",
        "Write Step Summary with Observatory Links",
    ]
    assert all(step.get("if") == "always()" for step in after)


def test_the_run_step_does_not_allow_skipped_cases() -> None:
    run = _step("Run Financial Scenario Benchmark Suite")

    assert "--allow-skip" not in run["run"]
    assert "--case" in run["run"]
