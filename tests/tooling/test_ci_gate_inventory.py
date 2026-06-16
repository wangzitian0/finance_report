"""CI gate inventory contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "ssot" / "ci-gate-inventory.yaml"
WORKFLOWS = ROOT / ".github" / "workflows"

EXPECTED_CATEGORIES = {
    "aggregate",
    "classify",
    "static_contract",
    "runtime_test",
    "evidence_fan_in",
    "audit_artifact",
    "deploy_ops",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path
    return data


def _workflow_jobs() -> set[tuple[str, str]]:
    jobs: set[tuple[str, str]] = set()
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        data = _load_yaml(workflow)
        for job_id in (data.get("jobs") or {}):
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


def test_AC8_13_142_ci_gate_inventory_uses_one_mece_category_per_job() -> None:
    """AC8.13.142: every workflow job has one MECE gate category."""

    data = _load_yaml(INVENTORY)
    categories = data.get("categories")
    assert isinstance(categories, dict)
    assert set(categories) == EXPECTED_CATEGORIES

    gates = _inventory_gates()
    assert {gate["id"] for gate in gates}
    assert len({gate["id"] for gate in gates}) == len(gates)

    inventory_jobs = {(gate["workflow"], gate["job"]) for gate in gates}
    assert inventory_jobs == _workflow_jobs()

    for gate in gates:
        assert gate["category"] in EXPECTED_CATEGORIES
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
    assert finish_gate["category"] == "aggregate"
    assert finish_gate["branch_required_context"] == "finish"

    inventory_finish_needs = {
        gate["job"]
        for gate in gates
        if gate["workflow"] == ".github/workflows/ci.yml"
        and gate.get("required_by_finish")
    }
    assert inventory_finish_needs == finish_needs


def test_AC8_13_142_duplicate_candidates_are_explicit_not_implicit() -> None:
    """AC8.13.142: duplicate gate candidates are recorded before any deletion."""

    data = _load_yaml(INVENTORY)
    candidates = data.get("duplicate_candidates")
    assert isinstance(candidates, list)
    assert candidates

    audit_candidate = next(
        item for item in candidates if item["id"] == "frontend_prod_audit_duplicate"
    )
    assert audit_candidate["status"] == "strict_duplicate_candidate"
    assert audit_candidate["proposed_owner"] == "ci.lint"
    assert audit_candidate["next_action"] == "remove_frontend_duplicate_in_followup"

    workflow = _load_yaml(ROOT / ".github" / "workflows" / "ci.yml")
    assert "npm run audit:prod" in _job_run_commands(workflow, "lint")
    assert "npm run audit:prod" in _job_run_commands(workflow, "frontend")
