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

from common.ci import workflow_contract as contract  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# Inputs the contract reads; copied into a tmp repo so drift can be injected
# without mutating the real tree.
_CONTRACT_INPUTS = (
    ".github/workflows/ci.yml",
    ".github/workflows/staging-deploy.yml",
    ".github/workflows/release-images.yml",
    ".github/workflows/production-release.yml",
    ".github/workflows/docs.yml",
    "docs/ssot/ci-cd.md",
    "docs/ssot/deployment.md",
    "docs/ssot/environments.md",
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
    """AC7.15.1: The real CI/deploy SSOT matches the live workflow contract."""
    assert contract.run_contract(ROOT) == 0


def test_AC7_15_3_stale_ci_classifier_job_name_fails(tmp_path) -> None:
    """AC7.15.3: A stale `classify-changes` reference in ci-cd.md fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / "docs/ssot/ci-cd.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nThe classify-changes job runs.\n",
        encoding="utf-8",
    )
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_3_stale_staging_push_trigger_prose_fails(tmp_path) -> None:
    """AC7.15.3: Stale `Push to main (apps/** changed)` prose fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / "docs/ssot/deployment.md"
    target.write_text(
        target.read_text(encoding="utf-8")
        + "\nStaging trigger: Push to main (apps/** changed).\n",
        encoding="utf-8",
    )
    assert contract.run_contract(tmp_path) == 1


def test_AC7_15_3_staging_push_trigger_in_workflow_fails(tmp_path) -> None:
    """AC7.15.3: Re-adding a `push` trigger to staging-deploy.yml fails."""
    _copy_inputs(tmp_path)
    target = tmp_path / ".github/workflows/staging-deploy.yml"
    content = target.read_text(encoding="utf-8")
    content = content.replace(
        "on:\n  workflow_dispatch:",
        "on:\n  push:\n    branches: [main]\n  workflow_dispatch:",
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
    target = tmp_path / "docs/ssot/environments.md"
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
