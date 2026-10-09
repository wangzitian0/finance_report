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


def test_the_run_step_does_not_swallow_a_failure() -> None:
    run = _step("Run Financial Scenario Benchmark Suite")

    assert "continue-on-error" not in run


def test_a_browser_is_installed_before_the_run_step() -> None:
    names = [s.get("name", "") for s in _steps()]
    install = _step("Install Playwright browser")

    assert names.index(install["name"]) < names.index(
        "Run Financial Scenario Benchmark Suite"
    )
    assert "playwright install" in install["run"]
    assert "chromium" in install["run"]


def test_the_playwright_version_matches_the_lockfile_in_both_steps() -> None:
    locked = _lock_version("playwright")
    pin = f"playwright=={locked}"

    assert pin in _step("Install Playwright browser")["run"]
    assert pin in _step("Run Financial Scenario Benchmark Suite")["run"]


def test_the_report_is_published_even_when_the_benchmark_fails() -> None:
    names = [s.get("name", "") for s in _steps()]
    after = _steps()[names.index("Run Financial Scenario Benchmark Suite") + 1 :]

    assert len(after) == 3
    assert all(step.get("if") == "always()" for step in after)


def test_the_run_step_does_not_allow_skipped_cases() -> None:
    run = _step("Run Financial Scenario Benchmark Suite")

    assert "--allow-skip" not in run["run"]
    assert "--case" in run["run"]
