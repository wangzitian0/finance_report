"""The production deploy job must outlive every request that it sends (#2452)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"

#: Time for the steps around the two waits: setup, evidence checks, health checks and smoke tests.
OTHER_STEPS_SECONDS = 10 * 60


def _transport_waits(job: dict) -> list[int]:
    """Return the --timeout value (seconds) of every transport call in the job."""
    waits: list[int] = []
    for step in job["steps"]:
        script = step.get("run", "")
        if "tools.app_deploy_transport" in script:
            waits.extend(
                int(value) for value in re.findall(r"--timeout\s+(\d+)", script)
            )
    return waits


def test_AC_runtime_release_job_timeout_1_the_deploy_job_outlives_both_receiver_waits() -> (
    None
):
    """AC-runtime.release-job-timeout.1: the job limit covers the forward wait, the rollback wait and the steps between."""
    job = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["deploy"]
    waits = _transport_waits(job)
    assert len(waits) == 2, (
        f"expected the forward and the rollback request, found {waits}"
    )
    needed = sum(waits) + OTHER_STEPS_SECONDS
    assert job["timeout-minutes"] * 60 >= needed, (
        f"deploy job limit {job['timeout-minutes']} min is below the {needed // 60} min "
        "that two receiver waits and the steps between can take: a rollback request "
        "would be left without a sender that watches it (#2452)"
    )
