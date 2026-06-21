"""EPIC-007 AC7.18.1: build-time secret-scan gate on the image build context (#1277).

The lint job already content-scans the working tree with gitleaks. The image
build is a second, independent surface: a secret can enter the Docker build
context (``./apps/<component>``) and be baked into a published ``:<sha>`` image.
The CI ``container-images`` job must run a fail-closed gitleaks scan over the
build context BEFORE ``docker/build-push-action``, keeping the finding visible
in the logs.

AC7.19 owns the separate scheduled GHCR ``:<sha>`` retention lane.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _container_images_job() -> dict:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert "container-images" in jobs, "ci.yml must define the container-images job"
    return jobs["container-images"]


def _step_names(job: dict) -> list[str]:
    return [str(step.get("name", "")) for step in job.get("steps", [])]


def _secret_scan_step(job: dict) -> dict:
    for step in job.get("steps", []):
        text = (str(step.get("name", "")) + " " + str(step.get("run", ""))).lower()
        if "gitleaks" in text and "secret" in text:
            return step
    raise AssertionError(
        "container-images job has no build-context gitleaks secret-scan step"
    )


def test_AC7_18_1_container_images_job_has_build_context_secret_scan() -> None:
    job = _container_images_job()
    step = _secret_scan_step(job)
    run = str(step.get("run", ""))
    assert "gitleaks" in run, "secret-scan step must invoke gitleaks"
    # Scans the per-component build context directory, not just the repo root.
    assert "apps/" in run or "matrix.component" in run, (
        "secret-scan step must scan the per-component build context (apps/<component>)"
    )


def test_AC7_18_1_build_secret_scan_is_fail_closed_before_build() -> None:
    job = _container_images_job()
    step = _secret_scan_step(job)
    run = str(step.get("run", ""))

    # Fail-closed: gitleaks must exit non-zero on detection and scan the working
    # tree (--no-git so it is not tripped by history), and the step must not be
    # neutralized with `|| true` / `continue-on-error`.
    assert "--exit-code 1" in run or "--exit-code=1" in run, (
        "build-context gitleaks scan must fail closed (--exit-code 1)"
    )
    assert "--no-git" in run, (
        "build-context scan must use --no-git (scan the context tree)"
    )
    assert step.get("continue-on-error", False) is not True, (
        "secret-scan step must not be continue-on-error (would not fail the build)"
    )
    assert "|| true" not in run, (
        "secret-scan step must not swallow failures with `|| true`"
    )

    # The finding must stay visible: use --redact (mask the value, keep the
    # file/line finding) rather than fully suppressing output.
    assert "--redact" in run, "secret-scan must keep findings visible via --redact"

    # Gate ordering: the secret scan must come before the image build steps.
    names = _step_names(job)
    scan_idx = names.index(str(step.get("name", "")))
    build_idx = next(
        (
            i
            for i, n in enumerate(names)
            if "build" in n.lower() and "image" in n.lower()
        ),
        None,
    )
    assert build_idx is not None, "container-images job must have an image build step"
    assert scan_idx < build_idx, (
        "secret-scan must run BEFORE the image build (fail before a secret is baked in)"
    )
