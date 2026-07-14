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
    """The blocking PR e2e gate must be a synchronous pull_request check, never async
    workflow_run — that could be outrun by a fast/auto merge (#943)."""
    gate = next(g for g in GATES if g["id"] == "pr-in-runner-e2e")
    assert gate["trigger"] == "pull_request"
    assert gate["blocking"] is True
    on = _workflow_on(_load(gate["workflow"]))
    assert "workflow_run" not in on, (
        "the merge-authority e2e gate must not use async workflow_run; a fast/auto "
        "merge could land before it runs as a required check (delivery-gates.yaml)."
    )


def test_every_referenced_workflow_and_job_exists():
    for gate in GATES:
        jobs = _load(gate["workflow"]).get("jobs") or {}
        assert gate["job"] in jobs, (
            f"gate {gate['id']!r} references job {gate['job']!r} not in {gate['workflow']}."
        )
