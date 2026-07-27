"""Build package-governance observations from independent raw inputs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml

from common.meta.base.package_contract import PackageContract
from common.meta.extension.check_package_contract import discover_packages

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ObservationInputError(ValueError):
    """A governance input cannot establish its claimed observation."""


def _module_for(test_file: str) -> str:
    path = test_file[:-3] if test_file.endswith(".py") else test_file
    if path.startswith("apps/backend/"):
        path = path[len("apps/backend/") :]
    return path.replace("/", ".")


def _junit_outcomes(paths: list[Path]) -> dict[tuple[str, str], str]:
    outcomes: dict[tuple[str, str], str] = {}
    for path in paths:
        try:
            tree = ElementTree.parse(path)
        except (OSError, ElementTree.ParseError) as exc:
            raise ObservationInputError(f"invalid JUnit evidence {path}: {exc}") from exc
        for case in tree.iter("testcase"):
            key = (
                case.get("classname") or "",
                (case.get("name") or "").split("[", 1)[0],
            )
            if case.find("failure") is not None or case.find("error") is not None:
                outcome = "failed"
            elif case.find("skipped") is not None:
                outcome = "skipped"
            else:
                outcome = "passed"
            previous = outcomes.get(key)
            if previous is None or previous == "skipped" or outcome == "failed":
                outcomes[key] = outcome
    return outcomes


def junit_proof_payload(
    *,
    contracts: list[PackageContract],
    open_issue_urls: set[str],
    junit_paths: list[Path],
    target_sha: str,
    observed_at: datetime,
    evidence_url: str,
) -> dict[str, Any]:
    """Bind open-initiative guarantee proofs to actual JUnit testcase outcomes."""
    target_sha = _exact_sha(target_sha, label="proof target SHA")
    outcomes = _junit_outcomes(junit_paths)
    proofs: list[dict[str, Any]] = []
    for contract in contracts:
        roadmap = {ac.id: ac for ac in contract.roadmap}
        for initiative in contract.governance:
            if initiative.issue not in open_issue_urls:
                continue
            for guarantee in initiative.guarantees:
                if guarantee.required_proof_strength != "exact":
                    raise ObservationInputError(
                        f"{contract.name}/{guarantee.id}: {guarantee.required_proof_strength} "
                        "proof requires canonical strength-specific execution evidence"
                    )
                matched: list[str] = []
                for ac_id in guarantee.affected_acs:
                    test_ref = roadmap[ac_id].test
                    file_name, separator, test_name = test_ref.partition("::")
                    if not separator or not test_name:
                        raise ObservationInputError(f"{ac_id}: test reference is not executable")
                    module = _module_for(file_name)
                    hits = [
                        outcome
                        for (classname, name), outcome in outcomes.items()
                        if (classname == module or classname.startswith(module + "."))
                        and name == test_name
                    ]
                    if not hits:
                        raise ObservationInputError(f"{ac_id}: current JUnit proof is missing")
                    matched.extend(hits)
                result = "failed" if any(item != "passed" for item in matched) else "passed"
                proofs.append(
                    {
                        "guarantee_id": f"{contract.name}/{guarantee.id}",
                        "proof_id": guarantee.proof,
                        "result": result,
                        "strength": "exact",
                        "target_sha": target_sha,
                        "occurred_at": observed_at.isoformat(),
                        "evidence_url": evidence_url,
                        "gate_id": guarantee.enforcing_gate,
                    }
                )
    return {
        "source": "junit-executed-proof",
        "target_sha": target_sha,
        "proofs": proofs,
    }


def collect_github_snapshot(
    *, repository: str, issue_urls: set[str]
) -> dict[str, Any]:
    """Collect current issue and detailed ruleset facts through authenticated gh."""

    def request(endpoint: str) -> Any:
        try:
            completed = subprocess.run(
                ["gh", "api", endpoint],
                check=True,
                capture_output=True,
                text=True,
            )
            return json.loads(completed.stdout)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            raise ObservationInputError(f"GitHub observation failed for {endpoint}") from exc

    listed = request(f"repos/{repository}/rulesets")
    if not isinstance(listed, list):
        raise ObservationInputError("GitHub ruleset list is not a JSON array")
    rulesets = []
    for item in listed:
        detail = request(f"repos/{repository}/rulesets/{item['id']}")
        rulesets.append(
            {
                "id": detail.get("id"),
                "name": detail.get("name"),
                "enforcement": detail.get("enforcement"),
                "updated_at": detail.get("updated_at"),
                "rules": detail.get("rules", []),
            }
        )
    issues = []
    prefix = f"https://github.com/{repository}/issues/"
    for issue_url in sorted(issue_urls):
        if not issue_url.startswith(prefix):
            raise ObservationInputError(f"initiative issue is outside {repository}")
        number = issue_url.removeprefix(prefix)
        if not number.isdigit():
            raise ObservationInputError(f"initiative issue URL is malformed: {issue_url}")
        issue = request(f"repos/{repository}/issues/{number}")
        issues.append(
            {
                "html_url": issue.get("html_url"),
                "state": issue.get("state"),
                "updated_at": issue.get("updated_at"),
            }
        )
    return {"rulesets": rulesets, "issues": issues}


def _exact_sha(value: object, *, label: str) -> str:
    sha = str(value or "")
    if not _SHA_RE.fullmatch(sha):
        raise ObservationInputError(f"{label} must identify one exact target SHA")
    return sha


def _required_contexts(rulesets: list[dict[str, Any]]) -> set[str]:
    contexts: set[str] = set()
    for ruleset in rulesets:
        if ruleset.get("enforcement") != "active":
            continue
        for rule in ruleset.get("rules", []):
            if rule.get("type") != "required_status_checks":
                continue
            parameters = rule.get("parameters", {})
            for check in parameters.get("required_status_checks", []):
                context = str(check.get("context") or "").strip()
                if context:
                    contexts.add(context)
    return contexts


def _reject_duplicate_coordinates(
    items: Sequence[dict[str, Any]], *, coordinate: str, label: str
) -> None:
    seen: set[str] = set()
    for item in items:
        value = str(item.get(coordinate) or "")
        if value in seen:
            raise ObservationInputError(f"duplicate {label} observation: {value}")
        seen.add(value)


def build_observation_bundle(
    *,
    contracts: list[PackageContract],
    target_sha: str,
    observed_at: datetime,
    detector_payloads: list[dict[str, Any]],
    proof_payloads: list[dict[str, Any]],
    gate_inventory: dict[str, Any],
    workflow: dict[str, Any],
    rulesets: list[dict[str, Any]],
    issue_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate independent inputs and derive one target-SHA observation bundle."""
    target_sha = _exact_sha(target_sha, label="bundle target SHA")
    declared_guarantees = {
        f"{contract.name}/{guarantee.id}"
        for contract in contracts
        for initiative in contract.governance
        for guarantee in initiative.guarantees
    }

    detectors: list[dict[str, Any]] = []
    for payload in detector_payloads:
        if "proofs" in payload:
            raise ObservationInputError(
                "detector payload cannot contain or manufacture proof observations"
            )
        if payload.get("source") != "package-detector":
            raise ObservationInputError("detector payload has an untrusted source")
        if _exact_sha(payload.get("target_sha"), label="detector target SHA") != target_sha:
            raise ObservationInputError("detector payload target SHA does not match bundle")
        for item in payload.get("detectors", []):
            if item.get("guarantee_id") not in declared_guarantees:
                raise ObservationInputError("detector payload references an unknown guarantee")
            detectors.append(dict(item))
    _reject_duplicate_coordinates(
        detectors, coordinate="guarantee_id", label="detector"
    )

    proofs: list[dict[str, Any]] = []
    for payload in proof_payloads:
        if payload.get("source") != "junit-executed-proof":
            raise ObservationInputError("proof payload is not independent executed evidence")
        if _exact_sha(payload.get("target_sha"), label="proof target SHA") != target_sha:
            raise ObservationInputError("proof payload target SHA does not match bundle")
        for item in payload.get("proofs", []):
            if item.get("guarantee_id") not in declared_guarantees:
                raise ObservationInputError("proof payload references an unknown guarantee")
            if _exact_sha(item.get("target_sha"), label="proof target SHA") != target_sha:
                raise ObservationInputError("proof observation target SHA does not match bundle")
            proofs.append(dict(item) | {"source": "junit-executed-proof"})
    _reject_duplicate_coordinates(proofs, coordinate="guarantee_id", label="proof")

    inventory_contexts = {
        str(context) for context in gate_inventory.get("branch_required_status_contexts", [])
    }
    live_contexts = _required_contexts(rulesets)
    if not inventory_contexts or inventory_contexts != live_contexts:
        raise ObservationInputError(
            "declared and live required status contexts do not reconcile"
        )
    live_context = next(iter(sorted(live_contexts)))
    jobs = workflow.get("jobs", {})
    finish = jobs.get(live_context, {}) if isinstance(jobs, dict) else {}
    finish_needs = finish.get("needs", []) if isinstance(finish, dict) else []
    if isinstance(finish_needs, str):
        finish_needs = [finish_needs]
    workflow_jobs = {str(item) for item in finish_needs}
    gates_by_id = {
        str(gate.get("id")): gate for gate in gate_inventory.get("gates", [])
    }
    declared_gate_ids = sorted(
        {
            guarantee.enforcing_gate
            for contract in contracts
            for initiative in contract.governance
            for guarantee in initiative.guarantees
        }
    )
    enforcement = []
    for gate_id in declared_gate_ids:
        gate = gates_by_id.get(gate_id, {})
        gate_job = str(gate.get("job") or "")
        reaches_finish = gate_job in workflow_jobs
        if bool(gate.get("required_by_finish")) != reaches_finish:
            raise ObservationInputError(
                f"{gate_id}: inventory and workflow finish reachability disagree"
            )
        enforcement.append(
            {
                "gate_id": gate_id,
                "declared_blocking": bool(gate.get("blocks_workflow")),
                "workflow_required": reaches_finish,
                "live_required": bool(live_context),
                "required_context": live_context,
                "observed_at": observed_at.isoformat(),
            }
        )

    declared_issues = {
        initiative.issue
        for contract in contracts
        for initiative in contract.governance
    }
    issues = []
    for payload in issue_payloads:
        issue = str(payload.get("html_url") or "")
        if issue not in declared_issues:
            raise ObservationInputError("issue payload references an unknown initiative")
        state = str(payload.get("state") or "").upper()
        if state not in {"OPEN", "CLOSED"}:
            raise ObservationInputError("issue payload has an unknown state")
        issues.append(
            {
                "issue": issue,
                "state": state,
                "observed_at": observed_at.isoformat(),
            }
        )
    _reject_duplicate_coordinates(issues, coordinate="issue", label="issue")

    return {
        "schema_version": 1,
        "target_sha": target_sha,
        "observed_at": observed_at.isoformat(),
        "detectors": detectors,
        "proofs": proofs,
        "enforcement": enforcement,
        "issues": issues,
    }


def validate_observation_bundle_payload(
    payload: dict[str, Any],
    *,
    expected_target_sha: str,
    now: datetime,
    max_age_seconds: int = 3600,
) -> None:
    """Reject forged-shape, stale, or mixed-coordinate observation bundles."""
    if payload.get("schema_version") != 1:
        raise ObservationInputError("observation bundle schema_version must be 1")
    expected = _exact_sha(expected_target_sha, label="expected target SHA")
    if _exact_sha(payload.get("target_sha"), label="bundle target SHA") != expected:
        raise ObservationInputError("observation bundle target SHA does not match expected")
    try:
        observed_at = datetime.fromisoformat(str(payload["observed_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise ObservationInputError("observation bundle has an invalid observed_at") from exc
    if observed_at.tzinfo is None:
        raise ObservationInputError("observation bundle observed_at must be timezone-aware")
    age = (now - observed_at).total_seconds()
    if age < -60 or age > max_age_seconds:
        raise ObservationInputError("observation bundle is stale or from the future")
    for proof in payload.get("proofs", []):
        if proof.get("source") != "junit-executed-proof":
            raise ObservationInputError("proof observation lacks independent JUnit provenance")
        if _exact_sha(proof.get("target_sha"), label="proof target SHA") != expected:
            raise ObservationInputError("proof observation target SHA does not match expected")
    _reject_duplicate_coordinates(
        payload.get("detectors", []), coordinate="guarantee_id", label="detector"
    )
    _reject_duplicate_coordinates(
        payload.get("proofs", []), coordinate="guarantee_id", label="proof"
    )
    _reject_duplicate_coordinates(
        payload.get("issues", []), coordinate="issue", label="issue"
    )


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObservationInputError(f"invalid observation payload {path}") from exc
    if not isinstance(payload, dict):
        raise ObservationInputError(f"observation payload {path} is not an object")
    return payload


def _control_detector_payload(
    *,
    contracts: list[PackageContract],
    open_issue_urls: set[str],
    existing_payloads: list[dict[str, Any]],
    target_sha: str,
) -> dict[str, Any]:
    observed_ids = {
        str(item.get("guarantee_id"))
        for payload in existing_payloads
        for item in payload.get("detectors", [])
    }
    detectors = []
    for contract in contracts:
        if contract.name not in {"meta", "testing"}:
            continue
        for initiative in contract.governance:
            if initiative.issue not in open_issue_urls:
                continue
            for guarantee in initiative.guarantees:
                guarantee_id = f"{contract.name}/{guarantee.id}"
                if guarantee_id not in observed_ids:
                    detectors.append(
                        {
                            "guarantee_id": guarantee_id,
                            "current": 0,
                            "target": 0,
                            "findings": [],
                        }
                    )
    return {
        "source": "package-detector",
        "target_sha": target_sha,
        "detectors": detectors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Collect live inputs and write one package-governance observation bundle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--repository", required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--junit-root", type=Path, required=True)
    parser.add_argument("--detector-payload", type=Path, action="append", default=[])
    parser.add_argument("--gate-inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-github-out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        repo_root = args.repo_root.resolve()
        target_sha = _exact_sha(args.target_sha, label="bundle target SHA")
        contracts = [item.contract for item in discover_packages(repo_root)]
        issue_urls = {
            initiative.issue
            for contract in contracts
            for initiative in contract.governance
        }
        github = collect_github_snapshot(
            repository=args.repository,
            issue_urls=issue_urls,
        )
        observed_at = datetime.now(UTC)
        open_issue_urls = {
            str(item.get("html_url"))
            for item in github["issues"]
            if str(item.get("state")).lower() == "open"
        }
        detector_payloads = [_read_payload(path) for path in args.detector_payload]
        detector_payloads.append(
            _control_detector_payload(
                contracts=contracts,
                open_issue_urls=open_issue_urls,
                existing_payloads=detector_payloads,
                target_sha=target_sha,
            )
        )
        proof_payloads: list[dict[str, Any]] = []
        junit_paths = sorted(args.junit_root.rglob("*.xml"))
        if not junit_paths:
            raise ObservationInputError("no JUnit evidence was supplied")
        evidence_url = (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{args.repository}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'unknown')}"
        )
        proof_payloads.append(
            junit_proof_payload(
                contracts=contracts,
                open_issue_urls=open_issue_urls,
                junit_paths=junit_paths,
                target_sha=target_sha,
                observed_at=observed_at,
                evidence_url=evidence_url,
            )
        )
        inventory_path = args.gate_inventory or (
            repo_root / "common/meta/data/ci-gate-inventory.yaml"
        )
        gate_inventory = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
        if not isinstance(gate_inventory, dict):
            raise ObservationInputError("gate inventory is not a mapping")
        workflow = yaml.safe_load(
            (repo_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        )
        if not isinstance(workflow, dict):
            raise ObservationInputError("CI workflow is not a mapping")
        bundle = build_observation_bundle(
            contracts=contracts,
            target_sha=target_sha,
            observed_at=observed_at,
            detector_payloads=detector_payloads,
            proof_payloads=proof_payloads,
            gate_inventory=gate_inventory,
            workflow=workflow,
            rulesets=github["rulesets"],
            issue_payloads=github["issues"],
        )
        args.output.write_text(
            json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        args.raw_github_out.write_text(
            json.dumps(github, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (ObservationInputError, OSError, yaml.YAMLError) as exc:
        print(f"package governance observations: FAIL: {exc}")
        return 1
    print("package governance observations: PASS")
    return 0


__all__ = [
    "ObservationInputError",
    "build_observation_bundle",
    "collect_github_snapshot",
    "junit_proof_payload",
    "main",
    "validate_observation_bundle_payload",
]
