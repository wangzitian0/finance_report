"""CI gate inventory contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "ssot" / "ci-gate-inventory.yaml"
WORKFLOWS = ROOT / ".github" / "workflows"

EXPECTED_STAGES = {
    "local.advisory",
    "github_ci.merge_authority",
    "preview.runtime",
    "staging.release_validation",
    "staging.provider_regression",
    "prod.release_integrity",
    "ops.scheduled_cleanup",
    "manual.adjudication",
}

EXPECTED_TASK_CATEGORIES = {
    "aggregate",
    "classify",
    "static_contract",
    "ac_traceability",
    "backend_unit",
    "backend_integration",
    "backend_api_e2e",
    "frontend_build",
    "frontend_unit",
    "frontend_browser_e2e",
    "image_build",
    "tooling_contract",
    "coverage_fan_in",
    "behavioral_ratchet",
    "deploy_smoke",
    "provider_gate",
    "release_integrity",
    "cleanup_retention",
}


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


def _inventory_gates() -> list[dict[str, Any]]:
    data = _load_yaml(INVENTORY)
    gates = data.get("gates")
    assert isinstance(gates, list)
    return gates


def _job_run_commands(workflow: dict[str, Any], job_id: str) -> str:
    job = workflow["jobs"][job_id]
    return "\n".join(
        str(step.get("run", ""))
        for step in job.get("steps", [])
        if isinstance(step, dict)
    )


def test_AC8_13_142_ci_gate_inventory_uses_stage_and_task_category_per_job() -> None:
    """AC8.13.142: every workflow job has one stage and one task_category."""

    data = _load_yaml(INVENTORY)
    assert "categories" not in data
    stages = data.get("stages")
    task_categories = data.get("task_categories")
    assert isinstance(stages, dict)
    assert isinstance(task_categories, dict)
    assert set(stages) == EXPECTED_STAGES
    assert set(task_categories) == EXPECTED_TASK_CATEGORIES

    gates = _inventory_gates()
    assert {gate["id"] for gate in gates}
    assert len({gate["id"] for gate in gates}) == len(gates)

    inventory_jobs = {(gate["workflow"], gate["job"]) for gate in gates}
    assert inventory_jobs == _workflow_jobs()

    for gate in gates:
        assert "category" not in gate
        assert gate["stage"] in EXPECTED_STAGES
        assert gate["task_category"] in EXPECTED_TASK_CATEGORIES
        assert isinstance(gate["owner"], str) and gate["owner"]
        assert isinstance(gate["failure_semantics"], str) and gate["failure_semantics"]
        assert gate["action"] in {
            "keep",
            "observe",
            "candidate_remove_duplicate",
            "candidate_merge_later",
        }


def test_AC8_13_142_finish_inventory_matches_ci_fan_in() -> None:
    """AC8.13.142: inventory keeps finish as the sole aggregate merge gate."""

    workflow = _load_yaml(ROOT / ".github" / "workflows" / "ci.yml")
    finish_needs = set(workflow["jobs"]["finish"]["needs"])

    gates = _inventory_gates()
    finish_gate = next(gate for gate in gates if gate["id"] == "ci.finish")
    assert finish_gate["stage"] == "github_ci.merge_authority"
    assert finish_gate["task_category"] == "aggregate"
    assert finish_gate["branch_required_context"] == "finish"

    inventory_finish_needs = {
        gate["job"]
        for gate in gates
        if gate["workflow"] == ".github/workflows/ci.yml"
        and gate.get("required_by_finish")
    }
    assert inventory_finish_needs == finish_needs


def test_AC8_13_142_duplicate_cleanup_is_explicit_not_implicit() -> None:
    """AC8.13.142: duplicate gate cleanup stays recorded after deletion."""

    data = _load_yaml(INVENTORY)
    cleanups = data.get("resolved_duplicate_cleanups")
    assert isinstance(cleanups, list)
    assert cleanups

    audit_cleanup = next(
        item for item in cleanups if item["id"] == "frontend_prod_audit_duplicate"
    )
    assert audit_cleanup["status"] == "removed"
    assert audit_cleanup["retained_owner"] == "ci.lint"
    assert audit_cleanup["removed_from"] == ["ci.frontend_build"]

    workflow = _load_yaml(ROOT / ".github" / "workflows" / "ci.yml")
    assert "npm run audit:prod" in _job_run_commands(workflow, "lint")
    for job_id in (
        "frontend-build",
        "frontend-vitest",
        "frontend-playwright",
        "frontend-telemetry-e2e",
    ):
        assert "npm run audit:prod" not in _job_run_commands(workflow, job_id)
