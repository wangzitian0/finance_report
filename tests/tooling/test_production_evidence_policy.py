"""finance_report's own Production evidence contract stays true to real CI (#1977).

tools/production_evidence_policy.json declares this repo's own CI facts (which
workflow builds the release image / runs the staging deploy, and each run's exact
display title) in the infra2-sdk ProductionEvidencePolicy shape — the file infra2's
deploy receiver verifies production evidence against (infra2#576), replacing the
hardcoded PRODUCTION_EVIDENCE_POLICIES dict entry infra2 used to maintain for us.
These tests close the drift loop IN THIS REPO: a deploy.yml rename or run-name
edit that isn't reflected in the contract fails CI here, in the same PR — never
months later on a production release attempt against a stale infra2-side copy
(the infra2#571 failure mode).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from infra2_sdk.deploy import (
    PRODUCTION_EVIDENCE_POLICY_PATH,
    ProductionEvidencePolicy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = REPO_ROOT / PRODUCTION_EVIDENCE_POLICY_PATH
FIXTURES = Path(__file__).parent / "fixtures"
# Real captured runs (gh api /repos/wangzitian0/finance_report/actions/runs/<id>):
# 29717946445 = "Release Images v0.1.45" (tag push), 29664376825 = "Deploy Staging
# v0.1.44" (dispatch). Not hand-authored, so the contract is compared against what
# GitHub actually produced — not against the implementation's own assumptions.
RELEASE_RUN_FIXTURE = FIXTURES / "release_images_run.v1.json"
STAGING_RUN_FIXTURE = FIXTURES / "staging_dispatch_run.v1.json"


@pytest.fixture(scope="module")
def policy() -> ProductionEvidencePolicy:
    return ProductionEvidencePolicy.from_dict(
        json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    )


def test_contract_file_lives_at_the_sdk_canonical_path(policy) -> None:
    assert POLICY_FILE.is_file()
    assert policy.service == "finance_report/app"


def test_declared_workflow_file_exists(policy) -> None:
    # Both runs come from the one combined deploy.yml (unlike truealpha's split
    # ci-required/deploy-release layout) — a rename fails here, same PR.
    assert policy.source.workflow_path == policy.staging.workflow_path
    assert (REPO_ROOT / policy.source.workflow_path).is_file()


def test_run_name_renders_both_declared_titles(policy) -> None:
    workflow_text = (REPO_ROOT / policy.source.workflow_path).read_text(
        encoding="utf-8"
    )
    assert "format('Release Images {0}', github.ref_name)" in workflow_text
    assert "format('Deploy Staging {0}', inputs.version_ref)" in workflow_text
    assert policy.source.display_title_template == "Release Images {version_ref}"
    assert policy.staging.display_title_template == "Deploy Staging {version_ref}"


def test_contract_matches_a_real_captured_release_run(policy) -> None:
    run = json.loads(RELEASE_RUN_FIXTURE.read_text(encoding="utf-8"))
    assert run["path"] == policy.source.workflow_path
    assert run["event"] == policy.source.event
    assert run["display_title"] == policy.source.expected_display_title("v0.1.45")
    assert run["conclusion"] == "success"
    # A tag-push run IS the tag commit: head_sha check stays required.
    assert policy.source.require_head_sha is True
    assert run["head_branch"] == "v0.1.45"


def test_contract_matches_a_real_captured_staging_run(policy) -> None:
    run = json.loads(STAGING_RUN_FIXTURE.read_text(encoding="utf-8"))
    assert run["path"] == policy.staging.workflow_path
    assert run["event"] == policy.staging.event
    assert run["display_title"] == policy.staging.expected_display_title("v0.1.44")
    assert run["conclusion"] == "success"
    # Pure migration of the currently-enforced behavior (#1977: "no behavior
    # change"): staging keeps require_head_sha=True. NOTE the known fragility this
    # inherits, unchanged: the dispatch runs on main, so head_sha == the tag
    # commit only holds while nothing merges between tag-cut and dispatch (true
    # for this captured run and every release so far). If the release process
    # ever allows a gap, flip this to false the way truealpha's contract does —
    # in this file and the contract together.
    assert policy.staging.require_head_sha is True
    assert run["head_branch"] == "main"
