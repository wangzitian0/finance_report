"""Contract: each delivery gate's workflow matches its declared trigger in
common/meta/data/delivery-gates.yaml (the SSOT).

This is the verifier half of the "one manifest, derive everywhere" decoupling. It
parses each workflow's `on:`/`jobs:` STRUCTURE and checks it against the manifest, so a
trigger change is one manifest edit + one workflow edit — and prose rewording (job
comments, the PR-status comment body) can never break it. Behavioral docs (ci-cd.md,
environments.md, EPIC-008) cross-ref the manifest instead of re-stating the mechanism.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def _workflow_on(wf: dict) -> dict:
    # PyYAML parses the GitHub Actions `on:` key as the boolean True.
    return wf.get(True) or wf.get("on") or {}


# manifest trigger -> the `on:` key the workflow must declare
_TRIGGER_ON_KEY = {
    "pull_request": "pull_request",
    "workflow_run": "workflow_run",
    "workflow_dispatch": "workflow_dispatch",
    "workflow_call": "workflow_call",
    "tag": "push",  # release tags live under on.push.tags
}

GATES = _load("common/meta/data/delivery-gates.yaml")["gates"]


def test_every_gate_workflow_declares_its_manifest_trigger():
    for gate in GATES:
        on = _workflow_on(_load(gate["workflow"]))
        key = _TRIGGER_ON_KEY[gate["trigger"]]
        assert key in on, (
            f"gate {gate['id']!r} declares trigger={gate['trigger']} but "
            f"{gate['workflow']} `on:` has no `{key}` (delivery-gates.yaml is the SSOT)."
        )
        if gate["trigger"] == "tag":
            assert (on.get("push") or {}).get("tags"), (
                f"gate {gate['id']!r} is tag-triggered but on.push has no tags filter."
            )


def test_merge_authority_gate_is_synchronous_not_bypassable():
    """The required merge authority in ci-gate-inventory.yaml is ci.yml#finish, which runs
    synchronously on pull_request (pull_request trigger, branch_required_context=finish)."""
    inv = _load("common/meta/data/ci-gate-inventory.yaml")
    gates = inv["gates"]
    finish = next(g for g in gates if g["id"] == "ci.finish")
    assert finish["workflow"] == ".github/workflows/ci.yml"
    assert finish["job"] == "finish"
    assert finish["branch_required_context"] == "finish"
    assert finish["blocks_workflow"] is True
    assert "pull_request" in finish["triggers"]


def test_staging_benchmark_is_wired_via_workflow_call():
    """Financial temporal benchmark is wired via workflow_call and blocking in Staging Batch Train."""
    gate = next(g for g in GATES if g["id"] == "staging-benchmark")
    assert gate["trigger"] == "workflow_call"
    assert gate["blocking"] is True
    on = _workflow_on(_load(gate["workflow"]))
    assert "workflow_call" in on


def test_every_referenced_workflow_and_job_exists():
    for gate in GATES:
        jobs = _load(gate["workflow"]).get("jobs") or {}
        assert gate["job"] in jobs, (
            f"gate {gate['id']!r} references job {gate['job']!r} not in {gate['workflow']}."
        )
