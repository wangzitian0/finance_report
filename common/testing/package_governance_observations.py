"""Build package-governance observations from independent raw inputs."""

from __future__ import annotations

import argparse
import importlib.util
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

from common.audit.base import TraceRecordValidationError
from common.audit.extension import TraceRecordCodec
from common.meta.base.governance_control import DetectorObservation, ProofObservation
from common.meta.base.package_contract import PackageContract
from common.meta.data.projection import contract_index
from common.meta.extension.check_package_contract import discover_packages
from common.testing.check_pr_ci_evidence import collect_executed_proofs
from common.testing.executed_proof import (
    ExecutedProofError,
    executed_proof_assertion_version,
    executed_proof_matches,
    github_execution_id,
)
from common.testing.generate_critical_proof_matrix import (
    GeneratorError,
    collect_proofs_from_file,
)

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
    severity = {"passed": 0, "skipped": 1, "failed": 2}
    for path in paths:
        try:
            tree = ElementTree.parse(path)
        except (OSError, ElementTree.ParseError) as exc:
            raise ObservationInputError(
                f"invalid JUnit evidence {path}: {exc}"
            ) from exc
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
            if previous is None or severity[outcome] > severity[previous]:
                outcomes[key] = outcome
    return outcomes


def junit_proof_payload(
    *,
    contracts: list[PackageContract],
    issue_states: dict[str, str],
    junit_lanes: dict[str, list[Path]],
    target_sha: str,
    observed_at: datetime,
    evidence_url: str,
    repository: str,
    execution_id: str,
    proof_profiles: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind guarantees only to canonical executed-proof JUnit records."""
    target_sha = _exact_sha(target_sha, label="proof target SHA")
    lane_evidence: dict[
        str,
        tuple[
            dict[tuple[str, str], str],
            dict[tuple[str, str], tuple[Any, ...]],
            set[tuple[str, str]],
        ],
    ] = {}
    for gate_id, paths in junit_lanes.items():
        lane_evidence[gate_id] = (
            _junit_outcomes(paths),
            *collect_executed_proofs(paths),
        )
    proofs: list[dict[str, Any]] = []
    for contract in contracts:
        roadmap = {ac.id: ac for ac in contract.roadmap}
        for initiative in contract.governance:
            issue_state = str(issue_states.get(initiative.issue) or "").lower()
            if issue_state not in {"open", "closed"}:
                raise ObservationInputError(
                    f"{initiative.id}: current issue state is missing"
                )
            for guarantee in initiative.guarantees:
                guarantee_id = f"{contract.name}/{guarantee.id}"
                if len(guarantee.affected_acs) != 1:
                    if issue_state == "closed" and guarantee_id not in (
                        proof_profiles or {}
                    ):
                        continue
                    raise ObservationInputError(
                        f"{contract.name}/{guarantee.id}: proof must bind one scenario AC"
                    )
                lane = lane_evidence.get(guarantee.enforcing_gate)
                if lane is None:
                    if issue_state == "closed":
                        continue
                    raise ObservationInputError(
                        f"{contract.name}/{guarantee.id}: declared gate lane "
                        f"{guarantee.enforcing_gate!r} supplied no JUnit evidence"
                    )
                outcomes, records, malformed = lane
                ac_id = guarantee.affected_acs[0]
                profile = (proof_profiles or {}).get(
                    guarantee_id,
                    {
                        "ac_ids": [ac_id],
                        "oracle_kind": "deterministic_contract",
                        "scenario_id": ac_id,
                        "stage": "github_ci.merge_authority",
                        "task_category": "critical_behavioral",
                        "governance_strength": guarantee.required_proof_strength,
                    },
                )
                assertion_version = executed_proof_assertion_version(
                    proof_id=guarantee.proof,
                    scenario_id=str(profile["scenario_id"]),
                    oracle_kind=str(profile["oracle_kind"]),
                    ac_ids=[str(item) for item in profile["ac_ids"]],
                    stage=str(profile["stage"]),
                    task_category=str(profile["task_category"]),
                    governance_strength=str(profile["governance_strength"]),
                )
                matched_records = []
                for ac_id in guarantee.affected_acs:
                    test_ref = roadmap[ac_id].test
                    file_name, separator, test_name = test_ref.partition("::")
                    if not separator or not test_name:
                        raise ObservationInputError(
                            f"{ac_id}: test reference is not executable"
                        )
                    module = _module_for(file_name)
                    keys = [
                        key
                        for key in set(records) | malformed
                        for classname, name in [key]
                        if (classname == module or classname.startswith(module + "."))
                        and name == test_name
                    ]
                    if not keys:
                        if issue_state == "closed":
                            continue
                        raise ObservationInputError(
                            f"{ac_id}: canonical executed proof is missing from current JUnit"
                        )
                    if any(key in malformed for key in keys):
                        raise ObservationInputError(
                            f"{ac_id}: canonical executed proof is malformed"
                        )
                    if any(outcomes.get(key) != "passed" for key in keys):
                        raise ObservationInputError(
                            f"{ac_id}: canonical executed proof testcase did not pass"
                        )
                    matched_records.extend(
                        record for key in keys for record in records.get(key, ())
                    )
                if not matched_records and issue_state == "closed":
                    continue
                exact = next(
                    (
                        record
                        for record in matched_records
                        if executed_proof_matches(
                            record,
                            proof_id=guarantee.proof,
                            scenario_id=guarantee.affected_acs[0],
                            repository_id=repository,
                            commit_sha=target_sha,
                            execution_id=execution_id,
                            assertion_version=assertion_version,
                        )
                    ),
                    None,
                )
                if exact is None:
                    if issue_state == "closed":
                        continue
                    raise ObservationInputError(
                        f"{contract.name}/{guarantee.id}: canonical executed proof "
                        "does not match the declared strength profile and CI coordinates"
                    )
                proofs.append(
                    {
                        "guarantee_id": f"{contract.name}/{guarantee.id}",
                        "proof_id": guarantee.proof,
                        "result": "passed",
                        "strength": guarantee.required_proof_strength,
                        "target_sha": exact.target.version,
                        "occurred_at": exact.occurred_at.isoformat(),
                        "evidence_url": evidence_url,
                        "gate_id": guarantee.enforcing_gate,
                        "scenario_id": str(profile["scenario_id"]),
                        "ac_ids": [str(item) for item in profile["ac_ids"]],
                        "oracle_kind": str(profile["oracle_kind"]),
                        "stage": str(profile["stage"]),
                        "task_category": str(profile["task_category"]),
                        "repository": repository,
                        "execution_id": execution_id,
                        "assertion_version": assertion_version,
                        "trace_record": TraceRecordCodec.encode(exact),
                    }
                )
    return {
        "source": "junit-executed-proof",
        "target_sha": target_sha,
        "proofs": proofs,
    }


def discover_package_detector_payloads(
    *,
    contracts: list[PackageContract],
    repo_root: Path,
    target_sha: str,
) -> list[dict[str, Any]]:
    """Discover optional package-owned detector providers behind one adapter."""
    target_sha = _exact_sha(target_sha, label="detector target SHA")
    payloads: list[dict[str, Any]] = []
    for contract in contracts:
        provider_path = (
            repo_root
            / "common"
            / contract.name
            / "extension"
            / "governance_detector.py"
        )
        if not provider_path.is_file():
            continue
        module_name = f"common.{contract.name}.extension.governance_detector"
        spec = importlib.util.spec_from_file_location(module_name, provider_path)
        if spec is None or spec.loader is None:
            raise ObservationInputError(
                f"{contract.name}: package detector provider cannot be loaded"
            )
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            provider = getattr(module, "detect_governance")
            raw_items = provider(repo_root=repo_root)
        except Exception as exc:
            raise ObservationInputError(
                f"{contract.name}: package detector provider failed"
            ) from exc
        if not isinstance(raw_items, list):
            raise ObservationInputError(
                f"{contract.name}: package detector provider must return a list"
            )
        owned_ids = {
            f"{contract.name}/{guarantee.id}"
            for initiative in contract.governance
            for guarantee in initiative.guarantees
        }
        detectors: list[dict[str, Any]] = []
        for raw_item in raw_items:
            try:
                detector = DetectorObservation.model_validate(raw_item, extra="forbid")
            except Exception as exc:
                raise ObservationInputError(
                    f"{contract.name}: package detector observation is invalid"
                ) from exc
            if detector.guarantee_id not in owned_ids:
                raise ObservationInputError(
                    f"{detector.guarantee_id}: detector is outside its owning package"
                )
            detectors.append(detector.model_dump(mode="json"))
        _reject_duplicate_coordinates(
            detectors, coordinate="guarantee_id", label="package detector"
        )
        if detectors:
            payloads.append(
                {
                    "source": "package-detector",
                    "target_sha": target_sha,
                    "detectors": detectors,
                }
            )
    return payloads


def _governance_proof_profiles(
    *,
    contracts: list[PackageContract],
    repo_root: Path,
    issue_states: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve each guarantee to the decorator on its declared AC testcase."""
    profiles: dict[str, dict[str, Any]] = {}
    file_cache: dict[Path, list[Any]] = {}
    for contract in contracts:
        roadmap = {ac.id: ac for ac in contract.roadmap}
        for initiative in contract.governance:
            issue_state = (issue_states or {}).get(initiative.issue, "open").lower()
            for guarantee in initiative.guarantees:
                if len(guarantee.affected_acs) != 1:
                    if issue_state == "closed":
                        continue
                    raise ObservationInputError(
                        f"{contract.name}/{guarantee.id}: proof must bind one scenario AC"
                    )
                ac_id = guarantee.affected_acs[0]
                test_ref = roadmap[ac_id].test
                file_name, separator, test_name = test_ref.partition("::")
                if not separator or not test_name:
                    raise ObservationInputError(
                        f"{ac_id}: test reference is not executable"
                    )
                path = repo_root / file_name
                if not path.is_file():
                    if issue_state == "closed":
                        continue
                    raise ObservationInputError(f"{ac_id}: proof test file is missing")
                if path not in file_cache:
                    try:
                        file_cache[path] = collect_proofs_from_file(path, repo_root)
                    except (GeneratorError, OSError, SyntaxError) as exc:
                        raise ObservationInputError(
                            f"{ac_id}: proof declaration cannot be collected"
                        ) from exc
                declarations = file_cache[path]
                matches = [
                    item
                    for item in declarations
                    if item.proof_id == guarantee.proof and item.test == test_name
                ]
                guarantee_id = f"{contract.name}/{guarantee.id}"
                if len(matches) != 1:
                    if issue_state == "closed" and not matches:
                        continue
                    raise ObservationInputError(
                        f"{guarantee_id}: declared @ac_proof profile is missing or duplicate"
                    )
                fields = matches[0].fields
                if (
                    fields.get("ac_ids") != [ac_id]
                    or fields.get("scenario_id") != ac_id
                    or fields.get("governance_strength")
                    != guarantee.required_proof_strength
                    or fields.get("ci_tier") != "pr_ci"
                    or fields.get("stage") != "github_ci.merge_authority"
                    or not fields.get("oracle_kind")
                ):
                    raise ObservationInputError(
                        f"{guarantee_id}: @ac_proof profile disagrees with the guarantee"
                    )
                profiles[guarantee_id] = dict(fields)
    return profiles


def _junit_lanes(root: Path) -> dict[str, list[Path]]:
    """Classify downloaded JUnit by its producing CI artifact lane."""
    lanes: dict[str, list[Path]] = {}
    for path in sorted(root.rglob("*.xml")):
        parts = path.relative_to(root).parts
        lane: str | None = None
        if parts and parts[0] == "backend" and len(parts) > 1:
            artifact = parts[1]
            if re.fullmatch(r"backend-shard-[1-5]-test-context", artifact):
                lane = "ci.backend"
            elif artifact == "backend-integration-test-context":
                lane = "ci.backend_integration"
            elif artifact == "backend-tier1-e2e-test-context":
                lane = "ci.backend_e2e_tier1"
        elif parts and parts[0] == "frontend":
            lane = "ci.frontend_vitest"
        elif parts and parts[0] == "tooling":
            lane = "ci.tooling_coverage"
        if lane is None:
            raise ObservationInputError(f"JUnit evidence has no known CI lane: {path}")
        lanes.setdefault(lane, []).append(path)
    if not lanes:
        raise ObservationInputError("no JUnit evidence was supplied")
    return lanes


def collect_github_snapshot(*, repository: str, issue_urls: set[str]) -> dict[str, Any]:
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
            raise ObservationInputError(
                f"GitHub observation failed for {endpoint}"
            ) from exc

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
                "target": detail.get("target"),
                "enforcement": detail.get("enforcement"),
                "conditions": detail.get("conditions"),
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
            raise ObservationInputError(
                f"initiative issue URL is malformed: {issue_url}"
            )
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
        conditions = ruleset.get("conditions")
        ref_name = conditions.get("ref_name") if isinstance(conditions, dict) else None
        includes = ref_name.get("include", []) if isinstance(ref_name, dict) else []
        excludes = ref_name.get("exclude", []) if isinstance(ref_name, dict) else []
        applies_to_default = (
            ruleset.get("target") == "branch"
            and "~DEFAULT_BRANCH" in includes
            and "~DEFAULT_BRANCH" not in excludes
        )
        if ruleset.get("enforcement") != "active" or not applies_to_default:
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


_FINISH_RESULT_CHECK_RE = re.compile(
    r'^\s*if \[\[ "\$\{\{ needs\.(?P<job>[A-Za-z0-9_-]+)\.result \}\}" '
    r'!= "success" \]\]; then\s*$'
)
_NONZERO_EXIT_RE = re.compile(r"^\s*exit\s+[1-9][0-9]*\s*$")


def _finish_blocked_jobs(finish: dict[str, Any]) -> set[str]:
    """Return jobs guarded by one canonical, unconditional nonzero exit block."""
    blocked: set[str] = set()
    for step in finish.get("steps", []):
        if not isinstance(step, dict):
            continue
        lines = str(step.get("run") or "").splitlines()
        for index, line in enumerate(lines):
            match = _FINISH_RESULT_CHECK_RE.fullmatch(line)
            if match is None:
                continue
            body: list[str] = []
            for candidate in lines[index + 1 :]:
                if candidate.strip() == "fi":
                    break
                body.append(candidate)
            else:
                continue
            executable = [
                candidate
                for candidate in body
                if candidate.strip() and not candidate.lstrip().startswith("#")
            ]
            if any(
                candidate.lstrip().startswith(("if ", "elif ", "else"))
                for candidate in executable
            ):
                continue
            if any(_NONZERO_EXIT_RE.fullmatch(candidate) for candidate in executable):
                blocked.add(match.group("job"))
    return blocked


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
        f"{contract.name}/{guarantee.id}": guarantee
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
        if (
            _exact_sha(payload.get("target_sha"), label="detector target SHA")
            != target_sha
        ):
            raise ObservationInputError(
                "detector payload target SHA does not match bundle"
            )
        for item in payload.get("detectors", []):
            if item.get("guarantee_id") not in declared_guarantees:
                raise ObservationInputError(
                    "detector payload references an unknown guarantee"
                )
            try:
                detector = DetectorObservation.model_validate(item, extra="forbid")
            except Exception as exc:
                raise ObservationInputError(
                    "detector payload contains an invalid observation"
                ) from exc
            detectors.append(detector.model_dump(mode="json"))
    _reject_duplicate_coordinates(
        detectors, coordinate="guarantee_id", label="detector"
    )

    proofs: list[dict[str, Any]] = []
    for payload in proof_payloads:
        if payload.get("source") != "junit-executed-proof":
            raise ObservationInputError(
                "proof payload is not independent executed evidence"
            )
        if (
            _exact_sha(payload.get("target_sha"), label="proof target SHA")
            != target_sha
        ):
            raise ObservationInputError(
                "proof payload target SHA does not match bundle"
            )
        for item in payload.get("proofs", []):
            guarantee = declared_guarantees.get(str(item.get("guarantee_id") or ""))
            if guarantee is None:
                raise ObservationInputError(
                    "proof payload references an unknown guarantee"
                )
            try:
                proof = ProofObservation.model_validate(item)
            except Exception as exc:
                raise ObservationInputError(
                    "proof payload contains an invalid observation"
                ) from exc
            if (
                proof.proof_id != guarantee.proof
                or proof.strength != guarantee.required_proof_strength
                or proof.gate_id != guarantee.enforcing_gate
            ):
                raise ObservationInputError(
                    "proof observation disagrees with its guarantee declaration"
                )
            if (
                _exact_sha(item.get("target_sha"), label="proof target SHA")
                != target_sha
            ):
                raise ObservationInputError(
                    "proof observation target SHA does not match bundle"
                )
            proofs.append(dict(item) | {"source": "junit-executed-proof"})
    _reject_duplicate_coordinates(proofs, coordinate="guarantee_id", label="proof")

    inventory_contexts = {
        str(context)
        for context in gate_inventory.get("branch_required_status_contexts", [])
    }
    live_contexts = _required_contexts(rulesets)
    if not inventory_contexts or inventory_contexts != live_contexts:
        raise ObservationInputError(
            "declared and live required status contexts do not reconcile"
        )
    if len(live_contexts) != 1:
        raise ObservationInputError(
            "exactly one live required finish context is required"
        )
    live_context = next(iter(sorted(live_contexts)))
    jobs = workflow.get("jobs", {})
    finish = jobs.get(live_context, {}) if isinstance(jobs, dict) else {}
    finish_needs = finish.get("needs", []) if isinstance(finish, dict) else []
    if isinstance(finish_needs, str):
        finish_needs = [finish_needs]
    workflow_jobs = {str(item) for item in finish_needs}
    blocked_jobs = _finish_blocked_jobs(finish) if isinstance(finish, dict) else set()
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
        blocks_finish = reaches_finish and gate_job in blocked_jobs
        if bool(gate.get("blocks_workflow")) != blocks_finish:
            raise ObservationInputError(
                f"{gate_id}: finish depends on {gate_job!r} but does not block its failure"
            )
        enforcement.append(
            {
                "gate_id": gate_id,
                "declared_blocking": bool(gate.get("blocks_workflow")),
                "workflow_required": blocks_finish,
                "live_required": bool(live_context),
                "required_context": live_context,
                "observed_at": observed_at.isoformat(),
            }
        )

    declared_issues = {
        initiative.issue for contract in contracts for initiative in contract.governance
    }
    issues = []
    for payload in issue_payloads:
        issue = str(payload.get("html_url") or "")
        if issue not in declared_issues:
            raise ObservationInputError(
                "issue payload references an unknown initiative"
            )
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
        "schema_version": 2,
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
    if payload.get("schema_version") != 2:
        raise ObservationInputError("observation bundle schema_version must be 2")
    expected = _exact_sha(expected_target_sha, label="expected target SHA")
    if _exact_sha(payload.get("target_sha"), label="bundle target SHA") != expected:
        raise ObservationInputError(
            "observation bundle target SHA does not match expected"
        )
    try:
        observed_at = datetime.fromisoformat(
            str(payload["observed_at"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise ObservationInputError(
            "observation bundle has an invalid observed_at"
        ) from exc
    if observed_at.tzinfo is None:
        raise ObservationInputError(
            "observation bundle observed_at must be timezone-aware"
        )
    age = (now - observed_at).total_seconds()
    if age < -60 or age > max_age_seconds:
        raise ObservationInputError("observation bundle is stale or from the future")
    for proof in payload.get("proofs", []):
        if proof.get("source") != "junit-executed-proof":
            raise ObservationInputError(
                "proof observation lacks independent JUnit provenance"
            )
        if _exact_sha(proof.get("target_sha"), label="proof target SHA") != expected:
            raise ObservationInputError(
                "proof observation target SHA does not match expected"
            )
        try:
            record = TraceRecordCodec.decode(proof.get("trace_record"))
        except (TraceRecordValidationError, TypeError) as exc:
            raise ObservationInputError(
                "proof observation lacks a canonical TraceRecord"
            ) from exc
        scenario_id = str(proof.get("scenario_id") or "")
        repository = str(proof.get("repository") or "")
        execution_id = str(proof.get("execution_id") or "")
        assertion_version = str(proof.get("assertion_version") or "")
        try:
            declared_assertion_version = executed_proof_assertion_version(
                proof_id=str(proof.get("proof_id") or ""),
                scenario_id=scenario_id,
                oracle_kind=str(proof.get("oracle_kind") or ""),
                ac_ids=[str(item) for item in proof.get("ac_ids", [])],
                stage=str(proof.get("stage") or ""),
                task_category=str(proof.get("task_category") or ""),
                governance_strength=str(proof.get("strength") or ""),
            )
        except (TypeError, ValueError) as exc:
            raise ObservationInputError(
                "proof observation has an invalid strength profile"
            ) from exc
        if assertion_version != declared_assertion_version:
            raise ObservationInputError(
                "proof observation strength profile does not match its assertion version"
            )
        if not executed_proof_matches(
            record,
            proof_id=str(proof.get("proof_id") or ""),
            scenario_id=scenario_id,
            repository_id=repository,
            commit_sha=expected,
            execution_id=execution_id,
            assertion_version=assertion_version,
        ):
            raise ObservationInputError(
                "proof observation canonical TraceRecord does not match its coordinates"
            )
        try:
            occurred_at = datetime.fromisoformat(
                str(proof.get("occurred_at") or "").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ObservationInputError(
                "proof observation has invalid occurred_at"
            ) from exc
        if proof.get("result") != "passed" or occurred_at != record.occurred_at:
            raise ObservationInputError(
                "proof observation does not faithfully project its canonical TraceRecord"
            )
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
    gate_inventory: dict[str, Any],
    workflow: dict[str, Any],
    rulesets: list[dict[str, Any]],
    issue_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    """Detect control integrity only from non-proof authoritative facts."""
    observed_ids = {
        str(item.get("guarantee_id"))
        for payload in existing_payloads
        for item in payload.get("detectors", [])
    }
    detectors = []
    try:
        projection = contract_index(contracts)
        projection_findings: list[str] = []
    except ValueError:
        projection = {"roadmap": {}}
        projection_findings = ["contract-projection-invalid"]
    source_ac_count = sum(len(contract.roadmap) for contract in contracts)
    if len(projection["roadmap"]) != source_ac_count:
        projection_findings.append("contract-projection-lossy")
    package_names = [contract.name for contract in contracts]
    if len(package_names) != len(set(package_names)):
        projection_findings.append("duplicate-package-owner")
    issue_states = {
        str(item.get("html_url")): str(item.get("state") or "").lower()
        for item in issue_payloads
    }
    gates_by_id = {
        str(item.get("id")): item for item in gate_inventory.get("gates", [])
    }
    live_contexts = _required_contexts(rulesets)
    jobs = workflow.get("jobs", {}) if isinstance(workflow, dict) else {}
    finish_context = next(iter(live_contexts), "") if len(live_contexts) == 1 else ""
    finish = jobs.get(finish_context, {}) if isinstance(jobs, dict) else {}
    needs = finish.get("needs", []) if isinstance(finish, dict) else []
    if isinstance(needs, str):
        needs = [needs]
    finish_needs = {str(item) for item in needs}
    blocked_jobs = _finish_blocked_jobs(finish) if isinstance(finish, dict) else set()
    for contract in contracts:
        if contract.name not in {"meta", "testing"}:
            continue
        for initiative in contract.governance:
            if initiative.issue not in open_issue_urls:
                continue
            for guarantee in initiative.guarantees:
                guarantee_id = f"{contract.name}/{guarantee.id}"
                if guarantee_id in observed_ids:
                    raise ObservationInputError(
                        f"{guarantee_id}: control detector observation cannot be overridden"
                    )
                findings = list(projection_findings)
                if any(
                    ac_id not in projection["roadmap"]
                    for ac_id in guarantee.affected_acs
                ):
                    findings.append("governance-ac-not-in-projection")
                if issue_states.get(initiative.issue) != "open":
                    findings.append("missing-open-issue-observation")
                gate = gates_by_id.get(guarantee.enforcing_gate)
                gate_job = str((gate or {}).get("job") or "")
                if not finish_context:
                    findings.append("missing-single-live-finish-context")
                if not gate_job or gate_job not in finish_needs:
                    findings.append("gate-not-in-finish-needs")
                elif gate_job not in blocked_jobs:
                    findings.append("gate-failure-not-blocked-by-finish")
                detectors.append(
                    {
                        "guarantee_id": guarantee_id,
                        "current": len(findings),
                        "target": 0,
                        "findings": findings,
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
        issue_states = {
            str(item.get("html_url")): str(item.get("state") or "").lower()
            for item in github["issues"]
        }
        open_issue_urls = {
            issue for issue, state in issue_states.items() if state == "open"
        }
        detector_payloads = [_read_payload(path) for path in args.detector_payload]
        detector_payloads.extend(
            discover_package_detector_payloads(
                contracts=contracts,
                repo_root=repo_root,
                target_sha=target_sha,
            )
        )
        proof_payloads: list[dict[str, Any]] = []
        junit_lanes = _junit_lanes(args.junit_root)
        evidence_url = (
            f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{args.repository}/actions/runs/{os.environ.get('GITHUB_RUN_ID', 'unknown')}"
        )
        proof_payloads.append(
            junit_proof_payload(
                contracts=contracts,
                issue_states=issue_states,
                junit_lanes=junit_lanes,
                target_sha=target_sha,
                observed_at=observed_at,
                evidence_url=evidence_url,
                repository=args.repository,
                execution_id=github_execution_id(os.environ),
                proof_profiles=_governance_proof_profiles(
                    contracts=contracts,
                    repo_root=repo_root,
                    issue_states=issue_states,
                ),
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
        detector_payloads.append(
            _control_detector_payload(
                contracts=contracts,
                open_issue_urls=open_issue_urls,
                existing_payloads=detector_payloads,
                target_sha=target_sha,
                gate_inventory=gate_inventory,
                workflow=workflow,
                rulesets=github["rulesets"],
                issue_payloads=github["issues"],
            )
        )
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
    except (ExecutedProofError, ObservationInputError, OSError, yaml.YAMLError) as exc:
        print(f"package governance observations: FAIL: {exc}")
        return 1
    print("package governance observations: PASS")
    return 0


__all__ = [
    "ObservationInputError",
    "build_observation_bundle",
    "collect_github_snapshot",
    "discover_package_detector_payloads",
    "junit_proof_payload",
    "main",
    "validate_observation_bundle_payload",
]
