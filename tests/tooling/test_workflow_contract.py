"""Tests for the CI/deploy workflow contract gate (issue #531).

The contract mechanically checks that:
  * CI/deploy SSOT prose references the live workflow job ids and triggers
    (AC7.15.1), so stale strings such as ``classify-changes`` or
    ``Push to main (apps/** changed)`` cannot survive.
  * issue templates use only existing repository labels (AC7.15.2).
  * the checker FAILS when any of those drift (AC7.15.3).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.meta.extension import workflow_contract as contract  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# Inputs the contract reads; copied into a tmp repo so drift can be injected
# without mutating the real tree.
_CONTRACT_INPUTS = (
    ".github/workflows/ci.yml",
    ".github/workflows/deploy.yml",
    ".github/workflows/docs.yml",
    ".github/workflows/preview.yml",
    ".github/workflows/maintenance.yml",
    ".github/workflows/notify-infra2.yml",
    ".github/actions/setup-e2e-tests/action.yml",
    "common/testing/ci-cd.md",
    "common/testing/data/github-action-runtime.yaml",
    "common/runtime/deployment.md",
    "common/runtime/environments.md",
    ".github/ISSUE_TEMPLATE/issue.yml",
    ".github/ISSUE_TEMPLATE/task.yml",
    ".github/ISSUE_TEMPLATE/idea.yml",
    ".github/ISSUE_TEMPLATE/incident.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
)


def _copy_inputs(target_root: Path) -> None:
    for relative_path in _CONTRACT_INPUTS:
        source = ROOT / relative_path
        target = target_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def test_AC7_15_1_real_repo_passes_the_workflow_contract() -> None:
    """AC-testing.governance.11: AC7.15.1: The real CI/deploy SSOT matches the live workflow contract."""
    assert contract.run_contract(ROOT) == 0


def test_AC7_15_1_container_images_publishes_on_every_main_release_push() -> None:
    """AC7.15.1: container-images must build+push :<sha> images on EVERY main/release
    push, not only when image_build_required is true.

    Regression guard for #1411 -> #1433. main/release push CI is the only path that
    publishes :<sha> images to GHCR, and deploy_v2 is promote-not-rebuild (it pulls
    images by exact SHA). #1411 right-moved container-images onto image_build_required
    for ALL events, so source-only main pushes skipped the build and downstream
    auto-deploy failed on a missing image. Right-moving for PR events is fine, but the
    job `if` must keep an unconditional main/release-push (plus workflow_dispatch)
    clause that does NOT depend on image_build_required.
    """
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    condition = workflow["jobs"]["container-images"]["if"]

    # The publish-on-main/release clause and the dispatch clause must be present.
    assert "github.event_name == 'push'" in condition, condition
    assert "refs/heads/main" in condition, condition
    assert "refs/heads/release/" in condition, condition
    assert "workflow_dispatch" in condition, condition

    # And that publish clause must sit BEFORE the image_build_required right-move, so
    # the right-move can only narrow PR runs, never gate the main/release publish.
    if "image_build_required" in condition:
        assert condition.index("refs/heads/main") < condition.index(
            "image_build_required"
        ), condition


def test_AC7_15_3_stale_ci_classifier_job_name_fails(tmp_path) -> None:
    """AC-testing.governance.13: AC7.15.3: A stale `classify-changes` reference in ci-cd.md fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / "common/testing/ci-cd.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nThe classify-changes job runs.\n",
        encoding="utf-8",
    )
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_3_stale_backend_shard_count_prose_fails(tmp_path) -> None:
    """AC7.15.3: Stale 5-shard backend prose fails (the matrix is 8-way,
    AC-testing.ci-structure.8)."""
    _copy_inputs(tmp_path)
    target = tmp_path / "common/testing/ci-cd.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace("Shards 1-8", "Shards 1-5"),
        encoding="utf-8",
    )
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_3_extra_app_workflow_file_fails(tmp_path) -> None:
    """AC7.15.3: Reintroducing an app workflow entrypoint fails."""
    _copy_inputs(tmp_path)
    extra = tmp_path / ".github/workflows/release-images.yml"
    extra.write_text(
        "name: Retired Release Images\n"
        "on: workflow_dispatch\n"
        "jobs:\n"
        "  noop:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: true\n",
        encoding="utf-8",
    )
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_3_stale_staging_push_trigger_prose_fails(tmp_path) -> None:
    """AC7.15.3: Stale `Push to main (apps/** changed)` prose fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / "common/runtime/deployment.md"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\nStaging trigger: Push to main (apps/** changed).\n",
        encoding="utf-8",
    )
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_3_staging_push_trigger_in_workflow_fails(tmp_path) -> None:
    """AC7.15.3: Re-adding a push-to-main trigger to deploy.yml fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / ".github/workflows/deploy.yml"
    content = target.read_text(encoding="utf-8")
    content = content.replace(
        "  push:\n    tags: ['v[0-9]+.[0-9]+.[0-9]+']",
        "  push:\n    branches: [main]\n    tags: ['v[0-9]+.[0-9]+.[0-9]+']",
    )
    target.write_text(content, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_3_renamed_classifier_job_in_workflow_fails(tmp_path) -> None:
    """AC7.15.3: Renaming the `changes` job id fails the contract."""
    _copy_inputs(tmp_path)
    target = tmp_path / ".github/workflows/ci.yml"
    content = target.read_text(encoding="utf-8")
    content = content.replace("\n  changes:\n", "\n  classify-changes:\n")
    target.write_text(content, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_2_stale_issue_template_label_fails(tmp_path) -> None:
    """AC-testing.governance.12: AC7.15.2: A template using the stale `infra`/`feature` label fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / ".github/ISSUE_TEMPLATE/task.yml"
    content = target.read_text(encoding="utf-8")
    content = content.replace('labels: ["enhancement"]', 'labels: ["feature"]')
    target.write_text(content, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_2_unknown_issue_template_label_fails(tmp_path) -> None:
    """AC7.15.2: A template using a label outside the taxonomy fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / ".github/ISSUE_TEMPLATE/idea.yml"
    content = target.read_text(encoding="utf-8")
    content = content.replace('labels: ["idea"]', 'labels: ["not-a-real-label"]')
    target.write_text(content, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_3_main_cli_returns_contract_result(tmp_path, capsys) -> None:
    """AC7.15.3: The CLI wrapper exits non-zero on injected drift."""
    _copy_inputs(tmp_path)
    target = tmp_path / "common/runtime/environments.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nLocal CI matches GitHub CI exactly.\n",
        encoding="utf-8",
    )
    assert contract.main(["--repo-root", str(tmp_path)]) == 1
    assert contract.main(["--repo-root", str(ROOT)]) == 0


def test_AC7_15_1_ci_workflow_wires_the_workflow_contract_gate() -> None:
    """AC7.15.1: CI lint runs the workflow contract checker."""
    workflow = contract.load_yaml(ROOT, ".github/workflows/ci.yml")
    lint_job = workflow["jobs"]["lint"]
    lint_run_commands = "\n".join(
        str(step.get("run", "")) for step in lint_job.get("steps", [])
    )
    assert "tools/check_workflow_contract.py" in lint_run_commands


def test_action_runtime_inventory_rejects_uninventoried_workflow_actions(
    tmp_path,
) -> None:
    _copy_inputs(tmp_path)
    target = tmp_path / "common/testing/data/github-action-runtime.yaml"
    content = target.read_text(encoding="utf-8")
    content = content.replace(
        "  - uses: actions/checkout@v7\n"
        "    runtime_status: node24_native\n"
        "    owner: ci_workflow\n",
        "",
    )
    target.write_text(content, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_action_runtime_inventory_requires_exceptions_for_forced_node20_metadata(
    tmp_path,
) -> None:
    _copy_inputs(tmp_path)
    target = tmp_path / "common/testing/data/github-action-runtime.yaml"
    content = target.read_text(encoding="utf-8")
    content = content.replace(
        "  - uses: actions/cache@v5\n"
        "    runtime_status: node24_native\n"
        "    owner: ci_workflow\n",
        "  - uses: actions/cache@v5\n"
        "    runtime_status: forced_node20_metadata\n"
        "    owner: ci_workflow\n",
    )
    target.write_text(content, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_action_runtime_inventory_rejects_forced_count_drift(tmp_path) -> None:
    _copy_inputs(tmp_path)
    target = tmp_path / "common/testing/data/github-action-runtime.yaml"
    content = target.read_text(encoding="utf-8")
    content = content.replace(
        "forced_node20_metadata_count_must_be: 0",
        "forced_node20_metadata_count_must_be: 1",
    )
    target.write_text(content, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_action_runtime_inventory_rejects_forced_runtime_env_without_exceptions(
    tmp_path,
) -> None:
    _copy_inputs(tmp_path)
    workflow = tmp_path / ".github/workflows/ci.yml"
    content = workflow.read_text(encoding="utf-8")
    content = content.replace(
        "env:\n  REGISTRY: ghcr.io\n",
        'env:\n  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"\n  REGISTRY: ghcr.io\n',
    )
    workflow.write_text(content, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_AC_testing_ci_structure_15_main_only_jobs_declare_rehearsal_or_isolation() -> (
    None
):
    """AC-testing.ci-structure.15: Main-only CI jobs declare pre-main PR rehearsal or failure isolation (#1811)."""
    import subprocess
    import yaml

    ci_yaml = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    detected = contract.find_main_only_jobs(ci_yaml)
    declared = set(contract.MAIN_ONLY_JOBS.keys())
    assert detected == declared

    # Execute all declared rehearsals behaviorally via subprocess
    for job_id, spec in contract.MAIN_ONLY_JOBS.items():
        rehearsal = spec.get("pr_rehearsal")
        if rehearsal:
            cmd = [sys.executable if arg == "python" else arg for arg in rehearsal]
            proc = subprocess.run(
                cmd, cwd=ROOT, capture_output=True, text=True, timeout=30
            )
            assert proc.returncode == 0, (
                f"Rehearsal for {job_id} failed: {proc.stderr}\n{proc.stdout}"
            )

    # Verify failure isolation: isolated jobs do not block finish
    finish_needs = set(ci_yaml.get("jobs", {}).get("finish", {}).get("needs", []))
    for job_id, spec in contract.MAIN_ONLY_JOBS.items():
        if spec.get("failure_isolation"):
            assert job_id not in finish_needs
            job_steps = ci_yaml.get("jobs", {}).get(job_id, {}).get("steps", [])
            has_isolated_step = any(
                isinstance(step, dict)
                and step.get("continue-on-error") is True
                and "run" in step
                for step in job_steps
            )
            assert has_isolated_step is True


def test_AC_testing_ci_structure_15_undeclared_main_only_job_fails(tmp_path) -> None:
    """AC-testing.ci-structure.15: Adding an undeclared main-only job fails contract check."""
    _copy_inputs(tmp_path)
    target = tmp_path / ".github/workflows/ci.yml"
    content = target.read_text(encoding="utf-8")
    extra_job = (
        "\n  unrehearsed-main-job:\n"
        "    runs-on: ubuntu-latest\n"
        "    if: github.event_name == 'push' && github.ref == 'refs/heads/main'\n"
        "    steps:\n"
        "      - run: echo hello\n"
    )
    target.write_text(content + extra_job, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_AC_testing_ci_structure_15_unisolated_main_only_job_fails(tmp_path) -> None:
    """AC-testing.ci-structure.15: An isolated main-only job missing continue-on-error fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / ".github/workflows/ci.yml"
    content = target.read_text(encoding="utf-8")
    broken = content.replace(
        "        continue-on-error: true\n        env:\n          GH_TOKEN:",
        "        env:\n          GH_TOKEN:",
    )
    target.write_text(broken, encoding="utf-8")
    assert contract.run_contract(tmp_path) == 1


def test_AC_testing_ci_structure_15_open_baseline_pr_rise_calculation() -> None:
    from common.testing.unified_coverage_baseline_pr import calculate_rise_merge

    old_cov = {
        "coverage_percent": 80.0,
        "breakdown": {
            "backend": {
                "coverage_percent": 80.0,
                "total_lines": 100,
                "covered_lines": 80,
            },
            "frontend": {
                "coverage_percent": 80.0,
                "total_lines": 100,
                "covered_lines": 80,
            },
        },
    }
    # 1. Rising breakdown component
    new_cov_rise = {
        "coverage_percent": 80.0,
        "breakdown": {
            "backend": {
                "coverage_percent": 85.0,
                "total_lines": 100,
                "covered_lines": 85,
            },
            "frontend": {
                "coverage_percent": 79.5,
                "total_lines": 100,
                "covered_lines": 79,
            },
        },
    }
    merged, rises, kept = calculate_rise_merge(old_cov, new_cov_rise)
    backend_key = "backend"
    frontend_key = "frontend"
    assert backend_key in rises
    assert frontend_key in kept
    assert merged["breakdown"]["frontend"]["coverage_percent"] == 80.0

    # 2. No rise (jitter or drop)
    new_cov_drop = {
        "coverage_percent": 79.9,
        "breakdown": {
            "backend": {
                "coverage_percent": 79.9,
                "total_lines": 100,
                "covered_lines": 79,
            },
            "frontend": {
                "coverage_percent": 79.9,
                "total_lines": 100,
                "covered_lines": 79,
            },
        },
    }
    merged_drop, rises_drop, kept_drop = calculate_rise_merge(old_cov, new_cov_drop)
    assert not bool(rises_drop)
    assert len(kept_drop) == 3


def test_AC_testing_ci_structure_15_open_baseline_pr_dry_run_execution() -> None:
    from common.testing.unified_coverage_baseline_pr import (
        open_unified_coverage_baseline_pr,
    )

    rc = open_unified_coverage_baseline_pr(repo_root=ROOT, dry_run=True)
    assert rc == 0


def test_workflow_contract_main_only_job_edge_cases(tmp_path: Path) -> None:
    # 1. find_main_only_jobs with non-dict jobs or non-dict job
    assert contract.find_main_only_jobs({"jobs": "not-a-dict"}) == set()
    assert contract.find_main_only_jobs({"jobs": {"invalid": "not-a-dict"}}) == set()

    # 2. check_main_only_jobs with missing ci.yml
    errs: list[str] = []
    contract.check_main_only_jobs(tmp_path, errs)
    assert len(errs) > 0

    # 3. check_main_only_jobs with stale declared job in MAIN_ONLY_JOBS
    import unittest.mock

    errs_stale: list[str] = []
    with unittest.mock.patch.dict(
        contract.MAIN_ONLY_JOBS,
        {"nonexistent-job-xyz": {"pr_rehearsal": "echo"}},
        clear=False,
    ):
        contract.check_main_only_jobs(ROOT, errs_stale)
    assert any("nonexistent-job-xyz" in e for e in errs_stale)

    # 4. check_main_only_jobs with job lacking rehearsal and isolation
    errs_empty: list[str] = []
    with unittest.mock.patch.dict(
        contract.MAIN_ONLY_JOBS,
        {"unified-coverage-baseline-pr": {}},
        clear=False,
    ):
        contract.check_main_only_jobs(ROOT, errs_empty)
    assert any("unified-coverage-baseline-pr" in e for e in errs_empty)

    # 5. check_main_only_jobs with job in finish_needs declaring failure_isolation
    errs_finish: list[str] = []
    with unittest.mock.patch.dict(
        contract.MAIN_ONLY_JOBS,
        {"lint": {"failure_isolation": True}},
        clear=False,
    ):
        contract.check_main_only_jobs(ROOT, errs_finish)
    assert any("blocking dependency of the 'finish' job" in e for e in errs_finish)


def test_unified_coverage_baseline_pr_edge_cases(tmp_path: Path) -> None:
    from common.testing import unified_coverage_baseline_pr as ucb
    import unittest.mock

    # 1. calculate_rise_merge when unified coverage rises
    old_data = {
        "coverage_percent": 80.0,
        "breakdown": {"backend": {"coverage_percent": 80.0}},
    }
    new_data = {
        "coverage_percent": 85.0,
        "breakdown": {"backend": {"coverage_percent": 80.0}},
    }
    merged, rises, kept = ucb.calculate_rise_merge(old_data, new_data)
    unified_key = "unified"
    assert unified_key in rises
    assert merged["coverage_percent"] == 85.0

    # 2. render_pr_body
    body = ucb.render_pr_body()
    assert len(body) > 0

    # 3. open_unified_coverage_baseline_pr: missing baseline file
    assert ucb.open_unified_coverage_baseline_pr(repo_root=tmp_path, dry_run=False) == 1

    # Setup fake repo directory
    baseline_file = tmp_path / "unified-coverage.json"
    baseline_file.write_text(json.dumps(old_data), encoding="utf-8")

    # 4. Missing coverage context when dry_run=False
    missing_ctx = tmp_path / "nonexistent-ctx.json"
    assert (
        ucb.open_unified_coverage_baseline_pr(
            repo_root=tmp_path, coverage_context=missing_ctx, dry_run=False
        )
        == 1
    )

    # 5. Existing coverage context with dry_run=True
    ctx_file = tmp_path / "ctx.json"
    ctx_file.write_text(json.dumps(new_data), encoding="utf-8")
    assert (
        ucb.open_unified_coverage_baseline_pr(
            repo_root=tmp_path, coverage_context=ctx_file, dry_run=True
        )
        == 0
    )

    # 6. Existing coverage context with dry_run=False and no rises
    no_rise_ctx = tmp_path / "no_rise.json"
    no_rise_ctx.write_text(json.dumps(old_data), encoding="utf-8")
    assert (
        ucb.open_unified_coverage_baseline_pr(
            repo_root=tmp_path, coverage_context=no_rise_ctx, dry_run=False
        )
        == 0
    )

    # 7. Non-dry-run with rises, mocking subprocess.run (PR exists -> edit)
    with unittest.mock.patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        with unittest.mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "test/repo"}):
            rc_edit = ucb.open_unified_coverage_baseline_pr(
                repo_root=tmp_path, coverage_context=ctx_file, dry_run=False
            )
            assert rc_edit == 0

    # 8. Non-dry-run with rises, mocking subprocess.run (PR does not exist -> create)
    baseline_file.write_text(json.dumps(old_data), encoding="utf-8")
    with unittest.mock.patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        with unittest.mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "test/repo"}):
            rc_create = ucb.open_unified_coverage_baseline_pr(
                repo_root=tmp_path, coverage_context=ctx_file, dry_run=False
            )
            assert rc_create == 0

    # 9. main CLI invocation with --dry-run and --coverage-context
    rc_main = ucb.main(
        [
            "--repo-root",
            str(tmp_path),
            "--coverage-context",
            str(ctx_file),
            "--dry-run",
        ]
    )
    assert rc_main == 0
