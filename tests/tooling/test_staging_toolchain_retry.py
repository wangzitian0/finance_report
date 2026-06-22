"""Tests for transient toolchain-download retry in the staging deploy path (issue #412).

The staging deploy path runs shell steps that download tools over the network:
the shared ``setup-e2e-tests`` composite (``uv pip install`` + ``playwright
install``) and the staging deploy_v2 dependency install (``pip install``). These
are genuine transient-failure surfaces (timeout/504) and must retry with bounded
exponential backoff, mirroring the established "AI Provider Connectivity Smoke"
idiom (``for n in $(seq 1 "$attempts")`` + ``delay=$((delay * 2))``). The
original external error must stay visible in the logs on exhaustion.

Application deploy/test execution steps stay fail-fast: only the toolchain
download commands are wrapped. ``astral-sh/setup-uv`` / ``actions/setup-python``
action steps already retry internally and are left untouched.

Covers:
  * AC7.16.1 — the shared E2E toolchain-setup composite retries transient
    dependency/browser download failures with bounded backoff and keeps the
    original error visible on exhaustion, without wrapping test execution.
  * AC7.16.2 — the staging deploy_v2 dependency install retries transient
    download failures with bounded backoff; deploy/test steps remain fail-fast.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

SETUP_E2E_ACTION = ".github/actions/setup-e2e-tests/action.yml"
STAGING_DEPLOY_WORKFLOW = ".github/workflows/deploy.yml"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _step_run_by_id(steps: list[dict], step_id: str) -> str:
    """Return the ``run:`` shell body of the step with the given ``id``."""
    for step in steps:
        if isinstance(step, dict) and step.get("id") == step_id:
            run = step.get("run")
            assert isinstance(run, str), f"step {step_id!r} has no shell 'run' body"
            return run
    raise AssertionError(f"no step with id={step_id!r} found")


def _has_bounded_backoff_retry(shell: str) -> bool:
    """A step retries with bounded exponential backoff via the repo idiom."""
    return (
        'for n in $(seq 1 "$attempts")' in shell
        and "delay=$((delay * 2))" in shell
        and "sleep " in shell
    )


def test_AC7_16_1_setup_e2e_composite_retries_toolchain_downloads() -> None:
    """AC7.16.1: setup-e2e composite retries uv/playwright downloads with backoff.

    The download commands (``uv pip install -r tests/e2e/requirements.txt`` and
    ``playwright install chromium``) must be wrapped in the bounded
    exponential-backoff retry idiom, and the original external error must be
    tee'd to a log and printed when the retries are exhausted.
    """
    action_text = read(SETUP_E2E_ACTION)
    action = yaml.safe_load(action_text)
    steps = action["runs"]["steps"]

    install_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Install Test Dependencies"
    )
    shell = install_step["run"]

    # The transient download commands are still present...
    assert "uv pip install -r tests/e2e/requirements.txt" in shell
    assert "playwright install chromium --with-deps" in shell

    # ...wrapped in the established bounded exponential-backoff retry idiom.
    assert _has_bounded_backoff_retry(shell), (
        "Install Test Dependencies must use the bounded backoff retry idiom"
    )
    # Attempts/base delay are env-configurable (mirrors PROVIDER_CONNECTIVITY_*).
    assert "TOOLCHAIN_DOWNLOAD_RETRIES" in shell
    assert "TOOLCHAIN_DOWNLOAD_BACKOFF_SECONDS" in shell

    # On exhaustion the original external error stays visible (tee + print).
    assert "tee " in shell
    assert "::group::" in shell


def test_AC7_16_1_setup_e2e_composite_does_not_wrap_test_execution() -> None:
    """AC7.16.1: the composite only sets up the toolchain; it never runs tests.

    The retry wrapper must stay scoped to downloads — the composite must not
    start invoking pytest / the app under a retry loop.
    """
    action_text = read(SETUP_E2E_ACTION)
    action = yaml.safe_load(action_text)
    steps = action["runs"]["steps"]

    for step in steps:
        if not isinstance(step, dict):
            continue
        shell = step.get("run", "") or ""
        # No application/test execution is introduced by the retry change. Only
        # inspect command lines (ignore '#'-prefixed comments that may mention
        # pytest/playwright in passing).
        command_lines = [
            line for line in shell.splitlines() if not line.lstrip().startswith("#")
        ]
        for line in command_lines:
            assert "pytest " not in line, "setup composite must not run pytest"


def test_AC7_16_2_staging_deploy_v2_dependency_install_retries() -> None:
    """AC7.16.2: staging deploy_v2 dependency install retries with backoff.

    The ``Install deploy_v2 dependencies`` step (``pip install httpx
    python-dotenv rich``) is a transient network download and must be wrapped in
    the bounded exponential-backoff retry idiom, with the original error visible
    on exhaustion.
    """
    workflow_text = read(STAGING_DEPLOY_WORKFLOW)
    workflow = yaml.safe_load(workflow_text)

    steps = workflow["jobs"]["build-and-deploy"]["steps"]
    shell = _step_run_by_id(steps, "install_deploy_v2")

    assert "pip install" in shell
    assert "httpx" in shell and "python-dotenv" in shell and "rich" in shell
    assert _has_bounded_backoff_retry(shell), (
        "Install deploy_v2 dependencies must use the bounded backoff retry idiom"
    )
    assert "TOOLCHAIN_DOWNLOAD_RETRIES" in shell
    assert "TOOLCHAIN_DOWNLOAD_BACKOFF_SECONDS" in shell
    assert "tee " in shell
    assert "::group::" in shell


def test_AC7_16_2_staging_deploy_and_e2e_steps_stay_fail_fast() -> None:
    """AC7.16.2: deploy/test execution steps are NOT wrapped in retry.

    Only the toolchain download commands gain retry. The actual staging deploy
    (``Deploy to Staging``) and the End-to-End test execution stay fail-fast so
    application/test failures are not masked by retries.
    """
    workflow_text = read(STAGING_DEPLOY_WORKFLOW)
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]
    deploy_steps = jobs["build-and-deploy"]["steps"]

    deploy_shell = _step_run_by_id(deploy_steps, "deploy_staging")
    assert not _has_bounded_backoff_retry(deploy_shell), (
        "Deploy to Staging must remain fail-fast (no download-retry wrapper)"
    )

    # The End-to-End test execution step must not be wrapped in the toolchain
    # download retry idiom. (The provider smoke retry is a separate, pre-existing
    # construct and is intentionally left alone.)
    e2e_run_steps = [
        step
        for step in deploy_steps
        if isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and step.get("name") == "End-to-End Tests"
    ]
    assert e2e_run_steps, "expected an 'End-to-End Tests' step in build-and-deploy"
    for step in e2e_run_steps:
        assert "TOOLCHAIN_DOWNLOAD_RETRIES" not in step["run"], (
            "End-to-End Tests execution must stay fail-fast"
        )
