"""Application-owned deployment and environment verification contracts."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def read(path: Path | str) -> str:
    path = ROOT / path if isinstance(path, str) else path
    return path.read_text(encoding="utf-8")


def load_yaml(path: Path | str) -> dict:
    data = yaml.safe_load(read(path))
    assert isinstance(data, dict), f"{path} must parse as a YAML mapping"
    return data


def test_pr_preview_gate_exercises_health_smoke_e2e_and_storage_paths() -> None:
    """AC7.9.1 AC7.9.2 AC7.9.3 AC7.9.4 AC7.9.5: PR preview validates runtime health, API, domain, and storage upload paths."""
    workflow = read(".github/workflows/preview.yml")
    smoke = read("tools/_lib/shell/smoke_test.sh")
    hard_gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")

    assert "workflow_run:" not in workflow
    assert "types: [opened, synchronize, reopened, closed]" in workflow
    assert 'action_reason = "pull-request-sync"' in workflow
    assert "name: In-runner Preview E2E" in workflow
    assert "python tools/pr_preview_lifecycle.py" in workflow
    assert "--action cleanup" not in workflow
    assert "preview-teardown" in workflow
    assert "Deploy preview lifecycle" in workflow
    assert "--action deploy" in workflow
    assert "Wait for API readiness" not in workflow
    assert 'echo "S3_BUCKET=statements"' in workflow or "S3_BUCKET:-statements" in read(
        "docker-compose.yml"
    )
    readiness_block = workflow.split("- name: Wait for stack readiness", 1)[1].split(
        "- name: End-to-End Tests", 1
    )[0]
    assert 'curl -fsS "$APP_URL/api/health"' in readiness_block
    assert "stack did not become healthy within 300s" in readiness_block
    assert "bash tools/smoke_test.sh" in workflow
    assert (
        'eval "$(python tools/test_selection.py --stage pr_preview_e2e --shell)"'
        in workflow
    )
    assert (
        'pytest "${PR_PREVIEW_E2E_TESTS[@]}" -v -m "$PR_PREVIEW_E2E_MARKER"' in workflow
    )
    assert "no PR preview image is pushed" in workflow

    assert 'wait_for_endpoint "API Health" "$BASE_URL/api/health"' in smoke
    assert 'wait_for_endpoint "Frontend Ready" "$BASE_URL/"' in smoke
    assert (
        'check_endpoint "DB Connectivity" "$BASE_URL/api/health" "\\"status\\":\\"healthy\\""'
        in smoke
    )
    assert 'check_endpoint "Ping API" "$BASE_URL/api/ping"' in smoke
    assert 'check_endpoint "API Docs" "$BASE_URL/api/docs"' in smoke

    assert "test_statement_upload_to_dashboard_vision_hard_gate" in hard_gate
    assert "/api/statements/upload" in hard_gate
    assert "dashboard" in hard_gate.lower()


def test_pr_preview_follows_successful_ci_without_dokploy_deploy() -> None:
    """Issue #839: PR preview follows CI and does not build/push PR images."""
    workflow = load_yaml(".github/workflows/preview.yml")
    workflow_text = read(".github/workflows/preview.yml")
    jobs = workflow["jobs"]

    assert "preview_opt_in" not in yaml.safe_dump(workflow)
    assert "workflow_run:" not in workflow_text
    assert "types: [opened, synchronize, reopened, closed]" in workflow_text
    assert 'action_reason = "pull-request-sync"' in workflow_text
    assert 'action = "cleanup"' in workflow_text
    assert "build-preview-backend-image" not in jobs
    assert "build-preview-frontend-image" not in jobs
    assert "deploy" not in jobs
    assert "docker/build-push-action@v7" not in workflow_text
    assert "Delete GHCR images" not in workflow_text

    e2e_blob = yaml.safe_dump(jobs["e2e"])
    assert "smoke_test.sh" in e2e_blob
    assert "pytest" in e2e_blob
    assert "tools/test_selection.py" in e2e_blob
    from common.testing import matrix

    assert "tests/e2e/test_core_journeys.py" in matrix.pr_preview_e2e_selection()
    assert "pr_preview_lifecycle" not in e2e_blob

    cleanup_blob = yaml.safe_dump(jobs["cleanup"])
    assert "pr_preview_lifecycle.py" not in cleanup_blob
    assert "--action cleanup" not in cleanup_blob
    assert "preview-teardown" in cleanup_blob
    assert "infra2/dispatches" in cleanup_blob

    env_doc = read("common/runtime/environments.md")
    assert "pull_request" in env_doc
    assert "No automatic persistent Dokploy URL" in env_doc


def test_in_runner_e2e_is_image_free_and_self_cleaning() -> None:
    """Issue #839: full-stack E2E runs in-runner, image-free, and never leaks."""
    workflow = load_yaml(".github/workflows/preview.yml")
    e2e = workflow["jobs"]["e2e"]

    assert "pr_preview_required == 'true'" in e2e["if"]
    assert "preview_opt_in" not in e2e["if"]

    blob = yaml.safe_dump(e2e)
    assert "docker compose up --build" in blob
    assert "push: true" not in blob
    assert "pr_preview_lifecycle" not in blob
    assert "DOKPLOY_API" not in blob

    teardown = [
        step
        for step in e2e["steps"]
        if "down --volumes --remove-orphans" in str(step.get("run", ""))
    ]
    assert teardown, "e2e job must tear the stack down"
    assert "always()" in str(teardown[0].get("if", ""))

    assert (ROOT / "docker-compose.ci-e2e.yml").is_file()
    assert (ROOT / "tools" / "ci" / "e2e-nginx.conf").is_file()
