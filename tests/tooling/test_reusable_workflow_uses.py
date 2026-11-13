"""A reusable workflow reference is not an action; a plain action still is.

AC7.15.1: the workflow contract gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.meta.extension import workflow_contract as contract  # noqa: E402

REUSABLE = "wangzitian0/.github/.github/workflows/issue-form.yml@main"


def test_reusable_workflow_reference_is_not_an_action():
    value = {"jobs": {"form": {"uses": REUSABLE}}}
    assert contract.iter_action_uses(value) == set()


def test_plain_action_is_still_an_action():
    value = {"jobs": {"s": {"steps": [{"uses": "actions/checkout@v7"}]}}}
    assert contract.iter_action_uses(value) == {"actions/checkout@v7"}


def test_composite_action_under_workflows_dir_is_still_an_action():
    value = {"steps": [{"uses": "owner/repo/.github/workflows/my-action@v1"}]}
    assert contract.iter_action_uses(value) == {
        "owner/repo/.github/workflows/my-action@v1"
    }


def test_real_repo_passes_the_workflow_contract():
    root = Path(__file__).resolve().parents[2]
    assert contract.run_contract(root) == 0
