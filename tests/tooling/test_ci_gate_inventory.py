"""CI workflow gate and proof-execution vocabulary contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from common.testing import evidence_bundle as eb
from common.testing.ac_proof_execution import (
    PROOF_EXECUTION_STAGES,
    PROOF_TASK_CATEGORIES,
)

ROOT = Path(__file__).resolve().parents[2]
RETIRED_INVENTORY = ROOT / "common" / "meta" / "data" / "ci-gate-inventory.yaml"
WORKFLOWS = ROOT / ".github" / "workflows"

EXPECTED_STAGES = set(PROOF_EXECUTION_STAGES)
EXPECTED_TASK_CATEGORIES = set(PROOF_TASK_CATEGORIES)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path
    return data


def _workflow_jobs() -> set[tuple[str, str]]:
    jobs: set[tuple[str, str]] = set()
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        data = _load_yaml(workflow)
        for job_id in data.get("jobs") or {}:
            jobs.add((f".github/workflows/{workflow.name}", str(job_id)))
    return jobs


def _job_run_commands(workflow: dict[str, Any], job_id: str) -> str:
    job = workflow["jobs"][job_id]
    return "\n".join(
        str(step.get("run", ""))
        for step in job.get("steps", [])
        if isinstance(step, dict)
    )


def test_AC8_13_151_ci_gate_inventory_uses_shared_proof_execution_vocabulary() -> None:
    """AC-testing.gate-inventory.3: AC8.13.151: proof execution vocabulary is documented in ci-cd.md with no YAML mirror."""
    assert not RETIRED_INVENTORY.exists()
    ci_cd = (ROOT / "common" / "testing" / "ci-cd.md").read_text(encoding="utf-8")
    assert all(f"`{stage}`" in ci_cd for stage in PROOF_EXECUTION_STAGES)
    assert all(f"`{task_category}`" in ci_cd for task_category in PROOF_TASK_CATEGORIES)


def test_AC8_13_142_ci_gate_inventory_uses_stage_and_task_category_per_job() -> None:
    """AC-testing.gate-inventory.1: AC8.13.142: workflows are the single source of truth for CI jobs and finish.needs."""
    assert not RETIRED_INVENTORY.exists()
    assert _workflow_jobs()
    workflow = _load_yaml(WORKFLOWS / "ci.yml")
    finish_needs = set(workflow["jobs"]["finish"]["needs"])
    gate_map_jobs = {entry["job"] for entry in eb.load_gate_map(ROOT)}
    assert gate_map_jobs == finish_needs


def test_AC8_13_142_finish_inventory_matches_ci_fan_in() -> None:
    """AC8.13.142: ci.yml keeps finish as the sole aggregate merge gate."""
    workflow = _load_yaml(ROOT / ".github" / "workflows" / "ci.yml")
    finish = workflow["jobs"]["finish"]
    finish_needs = set(finish["needs"])
    assert "evidence-bundle" not in finish_needs
    assert "pipeline-budget" not in finish_needs
    assert "unified-coverage-baseline-pr" not in finish_needs


def test_AC8_13_153_staging_ai_ocr_gate_is_a_single_reusable_workflow() -> None:
    """AC-testing.gate-inventory.4: AC8.13.153: both AI/OCR entrances call one reusable workflow; no duplicate body."""
    deploy = _load_yaml(WORKFLOWS / "deploy.yml")
    reusable_path = WORKFLOWS / "staging-ai-ocr-gate.yml"
    reusable = _load_yaml(reusable_path)
    reusable_text = reusable_path.read_text(encoding="utf-8")

    # The reusable workflow is workflow_call; the corpus is its only behavioral
    # input. The blocking input is gone: the gate always exits with the real
    # status (#2370: red means red).
    on = reusable.get("on", reusable.get(True))
    assert isinstance(on, dict) and "workflow_call" in on
    inputs = on["workflow_call"]["inputs"]
    assert {"commit_ref", "expected_sha", "corpus"} <= set(inputs)
    assert "blocking" not in inputs
    assert "run" in reusable["jobs"]
    # The ~120-line gate body lives here exactly once.
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in reusable_text
    assert 'pytest "${STAGING_AI_OCR_TESTS[@]}"' in reusable_text

    # A failed gate fails the job for every caller; no BLOCKING switch exists.
    assert 'exit "$status"' in reusable_text
    assert "BLOCKING" not in reusable_text

    # Both deploy.yml entrances use the reusable workflow and fail closed. The
    # separate audit-replay workflow is the only caller that nothing depends on.
    ref = "./.github/workflows/staging-ai-ocr-gate.yml"
    for job_id in ("ai-ocr-gate", "manual-ai-ocr-gate"):
        job = deploy["jobs"][job_id]
        assert job["uses"] == ref
        assert "blocking" not in job["with"]
        assert job.get("secrets") == "inherit"
        # A caller cannot also inline steps — the body must not be duplicated.
        assert "steps" not in job


def test_AC8_13_154_production_release_line_lives_in_release_yml() -> None:
    """AC-testing.gate-inventory.5: AC8.13.154: production release split into release.yml; deploy.yml keeps staging + promote."""
    from common.meta.extension.workflow_contract import (
        APP_WORKFLOW_FILES,
        WORKFLOW_CONTRACT,
    )

    release = _load_yaml(WORKFLOWS / "release.yml")
    deploy = _load_yaml(WORKFLOWS / "deploy.yml")

    # release.yml is manual-dispatch only and hosts exactly the prod jobs.
    on = release.get("on", release.get(True))
    assert isinstance(on, dict) and set(on) == {"workflow_dispatch"}
    assert set(release["jobs"]) == {"journey-board", "dry-run", "deploy"}
    # The board row (#2370) never gates production: deploy runs on !cancelled().
    assert release["jobs"]["deploy"]["needs"] == ["journey-board"]
    assert release["jobs"]["deploy"]["if"] == "${{ !cancelled() && !inputs.dry_run }}"
    assert "environment" not in release["jobs"]["journey-board"]

    # Serialized per version_ref so two production releases never run concurrently.
    concurrency = release["concurrency"]
    assert "production-release-" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is False

    # deploy.yml no longer hosts the prod jobs but keeps staging + tag-push promote.
    assert "dry-run" not in deploy["jobs"]
    assert "deploy" not in deploy["jobs"]
    assert {"build-and-deploy", "promote"} <= set(deploy["jobs"])

    # The workflow contract tracks the new file and re-homed job ids.
    assert ".github/workflows/release.yml" in APP_WORKFLOW_FILES
    assert WORKFLOW_CONTRACT[".github/workflows/release.yml"]["jobs"] == (
        "journey-board",
        "dry-run",
        "deploy",
    )
    assert "dry-run" not in WORKFLOW_CONTRACT[".github/workflows/deploy.yml"]["jobs"]


def test_AC8_13_142_duplicate_cleanup_is_explicit_not_implicit() -> None:
    """AC8.13.142: duplicate frontend prod audit stays removed from frontend build/test jobs."""
    workflow = _load_yaml(ROOT / ".github" / "workflows" / "ci.yml")
    assert "npm run audit:prod" in _job_run_commands(workflow, "lint")
    for job_id in (
        "frontend-build",
        "frontend-vitest",
        "frontend-playwright",
        "frontend-telemetry-e2e",
    ):
        assert "npm run audit:prod" not in _job_run_commands(workflow, job_id)
