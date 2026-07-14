"""Tests for the CI/deploy workflow contract gate (issue #531).

The contract mechanically checks that:
  * CI/deploy SSOT prose references the live workflow job ids and triggers
    (AC7.15.1), so stale strings such as ``classify-changes`` or
    ``Push to main (apps/** changed)`` cannot survive.
  * issue templates use only existing repository labels (AC7.15.2).
  * the checker FAILS when any of those drift (AC7.15.3).
"""

from __future__ import annotations

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


def _write_infra2_workflow_set(target_root: Path) -> None:
    for relative_path in contract.INFRA2_WORKFLOW_FILES:
        target = target_root / "repo" / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("name: placeholder\n", encoding="utf-8")


def test_AC7_15_1_real_repo_passes_the_workflow_contract() -> None:
    """AC7.15.1: The real CI/deploy SSOT matches the live workflow contract."""
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
    """AC7.15.3: A stale `classify-changes` reference in ci-cd.md fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / "common/testing/ci-cd.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nThe classify-changes job runs.\n",
        encoding="utf-8",
    )
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_3_stale_backend_shard_count_prose_fails(tmp_path) -> None:
    """AC7.15.3: Stale 8-shard backend prose fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / "common/testing/ci-cd.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace("Shards 1-5", "Shards 1-8"),
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


def test_AC7_15_1_infra2_submodule_workflow_set_is_consolidated() -> None:
    """AC7.15.1: The checked-out infra2 submodule exposes the target workflow set."""
    assert contract.workflow_file_set(ROOT, "repo/.github/workflows") == set(
        contract.INFRA2_WORKFLOW_FILES
    )


def test_AC7_15_3_infra2_workflow_drift_message_uses_submodule_prefix(
    tmp_path,
    capsys,
) -> None:
    """AC7.15.3: infra2 workflow drift reports point at the submodule path."""
    _copy_inputs(tmp_path)
    _write_infra2_workflow_set(tmp_path)
    extra = tmp_path / "repo/.github/workflows/legacy.yml"
    extra.write_text("name: legacy\n", encoding="utf-8")

    assert contract.run_contract(tmp_path) == 1
    captured = capsys.readouterr()
    assert "repo/.github/workflows/legacy.yml" in captured.err


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
    """AC7.15.2: A template using the stale `infra`/`feature` label fails."""
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
