"""CI gate inventory contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from common.ssot.ac_proof_execution import (
    PROOF_EXECUTION_STAGES,
    PROOF_TASK_CATEGORIES,
)

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "ssot" / "ci-gate-inventory.yaml"
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


def test_AC8_13_151_ci_gate_inventory_uses_shared_proof_execution_vocabulary() -> None:
    """AC8.13.151: inventory vocabulary is shared with proof execution helpers."""

    data = _load_yaml(INVENTORY)
    stages = data.get("stages")
    task_categories = data.get("task_categories")
    assert isinstance(stages, dict)
    assert isinstance(task_categories, dict)
    assert tuple(stages) == PROOF_EXECUTION_STAGES
    assert tuple(task_categories) == PROOF_TASK_CATEGORIES


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


def test_AC8_13_142_inventory_artifacts_match_live_workflows() -> None:
    """AC8.13.142: declared gate artifacts stay anchored to live workflow names."""

    workflow_text_by_path = {
        f".github/workflows/{workflow.name}": workflow.read_text(encoding="utf-8")
        for workflow in sorted(WORKFLOWS.glob("*.yml"))
    }

    for gate in _inventory_gates():
        artifacts = gate.get("artifacts") or []
        assert isinstance(artifacts, list)
        workflow_text = workflow_text_by_path[gate["workflow"]]
        for artifact in artifacts:
            assert isinstance(artifact, str)
            assert artifact in workflow_text, (gate["id"], artifact)


def test_AC8_13_153_staging_ai_ocr_gate_is_a_single_reusable_workflow() -> None:
    """AC8.13.153: both AI/OCR entrances call one reusable workflow; no duplicate body."""
    deploy = _load_yaml(WORKFLOWS / "deploy.yml")
    reusable_path = WORKFLOWS / "staging-ai-ocr-gate.yml"
    reusable = _load_yaml(reusable_path)
    reusable_text = reusable_path.read_text(encoding="utf-8")

    # The reusable workflow is workflow_call with the parameterized blocking input.
    on = reusable.get("on", reusable.get(True))
    assert isinstance(on, dict) and "workflow_call" in on
    inputs = on["workflow_call"]["inputs"]
    assert {"commit_ref", "expected_sha", "blocking"} <= set(inputs)
    assert "run" in reusable["jobs"]
    # The ~120-line gate body lives here exactly once.
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in reusable_text
    assert 'pytest "${STAGING_AI_OCR_TESTS[@]}"' in reusable_text

    # Record-only (blocking=false) must NOT fail the job: a non-zero exit is
    # guarded by BLOCKING == "true", and the record-only path exits 0 so it keeps
    # the old inline continue-on-error semantics (#1365 Copilot fix).
    assert (
        'if [ "$status" -ne 0 ] && [ "$BLOCKING" = "true" ]; then' in reusable_text
    )
    assert "exit 0" in reusable_text

    # Both deploy.yml entrances are uses: callers of the reusable workflow that
    # differ only by the blocking input (and checkout/expected_sha).
    ref = "./.github/workflows/staging-ai-ocr-gate.yml"
    for job_id, blocking in (("ai-ocr-gate", False), ("manual-ai-ocr-gate", True)):
        job = deploy["jobs"][job_id]
        assert job["uses"] == ref
        assert job["with"]["blocking"] is blocking
        assert job.get("secrets") == "inherit"
        # A caller cannot also inline steps — the body must not be duplicated.
        assert "steps" not in job

    # The duplicate cleanup is recorded explicitly, like every other resolved one.
    inventory = _load_yaml(INVENTORY)
    cleanup = next(
        item
        for item in inventory["resolved_duplicate_cleanups"]
        if item["id"] == "staging_ai_ocr_gate_duplicate"
    )
    assert cleanup["status"] == "removed"
    assert cleanup["retained_owner"] == "staging_ai_ocr_gate.reusable_run"


def test_AC8_13_154_production_release_line_lives_in_release_yml() -> None:
    """AC8.13.154: production release split into release.yml; deploy.yml keeps staging + promote."""
    from common.ci.workflow_contract import APP_WORKFLOW_FILES, WORKFLOW_CONTRACT

    release = _load_yaml(WORKFLOWS / "release.yml")
    deploy = _load_yaml(WORKFLOWS / "deploy.yml")

    # release.yml is manual-dispatch only and hosts exactly the prod jobs.
    on = release.get("on", release.get(True))
    assert isinstance(on, dict) and set(on) == {"workflow_dispatch"}
    assert set(release["jobs"]) == {"dry-run", "deploy"}

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
        "dry-run",
        "deploy",
    )
    assert "dry-run" not in WORKFLOW_CONTRACT[".github/workflows/deploy.yml"]["jobs"]


def test_AC8_13_155_pr_preview_reclaim_is_dispatched_to_infra2() -> None:
    """AC8.13.155: the app-side reclaim split is retired — preview.yml#cleanup only
    dispatches a teardown signal to infra2, maintenance.yml#cleanup is GHCR-only."""
    preview = (WORKFLOWS / "preview.yml").read_text(encoding="utf-8")
    maintenance = (WORKFLOWS / "maintenance.yml").read_text(encoding="utf-8")

    # On PR close the app dispatches a vendor-neutral teardown to infra2; it runs
    # no Dokploy reclaim itself.
    cleanup_block = preview.split("  cleanup:", 1)[1]
    assert "preview-teardown" in cleanup_block
    assert "infra2/dispatches" in cleanup_block
    assert "--action cleanup" not in preview
    # The scheduled maintenance job no longer reconciles Dokploy previews; it only
    # prunes the app's own GHCR PR image tags.
    assert "--action reconcile" not in maintenance
    assert "Prune stale PR preview GHCR tags" in maintenance

    # The former keep_separate reclaim split is recorded as retired, not drift.
    inventory = _load_yaml(INVENTORY)
    candidate = next(
        item
        for item in inventory["deferred_candidates"]
        if item["id"] == "pr_preview_cleanup_event_vs_scheduled"
    )
    assert candidate["status"] == "removed"
    assert candidate["retained_owner"] == "infra2:preview-teardown.yml"


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
