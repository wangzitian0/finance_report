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
from infra2_sdk.manifests import load_hooks_manifest

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
    hooks = load_hooks_manifest(ROOT / "runtime-hooks.manifest.json").slots
    for gate in GATES:
        if gate["workflow"] == "runtime-hooks.manifest.json":
            assert gate["job"] in hooks, (
                f"gate {gate['id']!r} references hook slot {gate['job']!r} not in runtime-hooks.manifest.json"
            )
            continue
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
    """The required merge authority in .github/workflows/ci.yml is finish, which runs
    synchronously on pull_request."""
    ci_wf = _load(".github/workflows/ci.yml")
    assert "pull_request" in _workflow_on(ci_wf)
    finish = (ci_wf.get("jobs") or {}).get("finish")
    assert isinstance(finish, dict)
    assert finish.get("needs")


def test_staging_benchmark_is_wired_via_workflow_call():
    """Financial temporal benchmark and scheduled audit are wired into the scheduled_audit runtime hook slot."""
    gate = next(g for g in GATES if g["id"] == "staging-benchmark")
    assert gate["workflow"] == "runtime-hooks.manifest.json"
    assert gate["job"] == "scheduled_audit"
    assert gate["blocking"] is True
    hooks = load_hooks_manifest(ROOT / "runtime-hooks.manifest.json").slots
    assert "--corpus audit_replay" in hooks["scheduled_audit"].run


def test_every_referenced_workflow_and_job_exists():
    hooks = load_hooks_manifest(ROOT / "runtime-hooks.manifest.json").slots
    for gate in GATES:
        if gate["workflow"] == "runtime-hooks.manifest.json":
            assert gate["job"] in hooks, (
                f"gate {gate['id']!r} references hook slot {gate['job']!r} not in {gate['workflow']}."
            )
            continue
        jobs = _load(gate["workflow"]).get("jobs") or {}
        assert gate["job"] in jobs, (
            f"gate {gate['id']!r} references job {gate['job']!r} not in {gate['workflow']}."
        )
