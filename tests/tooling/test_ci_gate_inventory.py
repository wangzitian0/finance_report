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
    """AC-testing.gate-inventory.4: AC8.13.153: both staging_gate and scheduled_audit hook slots invoke the single staging AI/OCR selection stage."""
    from infra2_sdk.manifests import load_hooks_manifest

    manifest = load_hooks_manifest(ROOT / "runtime-hooks.manifest.json")
    slots = manifest.slots
    for slot in ("staging_gate", "scheduled_audit"):
        cmd = slots[slot].run
        assert "tools/test_selection.py --stage staging_ai_ocr" in cmd
        assert 'pytest "${STAGING_AI_OCR_TESTS[@]}"' in cmd


def test_AC8_13_154_production_release_line_lives_in_release_yml() -> None:
    """AC-testing.gate-inventory.5: AC8.13.154: App repository retains only ci.yml and docs.yml workflows; CD and release orchestration live in infra2 via runtime-hooks.manifest.json."""
    from common.meta.extension.workflow_contract import (
        APP_WORKFLOW_FILES,
        WORKFLOW_CONTRACT,
    )

    assert APP_WORKFLOW_FILES == (
        ".github/workflows/ci.yml",
        ".github/workflows/docs.yml",
    )
    assert set(WORKFLOW_CONTRACT) == set(APP_WORKFLOW_FILES)
    assert not (WORKFLOWS / "release.yml").exists()
    assert not (WORKFLOWS / "deploy.yml").exists()


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
