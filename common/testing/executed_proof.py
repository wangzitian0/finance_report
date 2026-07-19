"""Bind a scenario proof to the pytest outcome and exact CI coordinates."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Protocol

from common.audit.base import (
    TraceAuthorityProfile,
    TraceRecord,
    TraceRecordType,
    TraceResult,
    TraceScope,
    TraceScopeKind,
    TraceTargetClass,
    VersionedTraceRef,
)
from common.audit.extension import TraceJUnitAdapter
from common.testing.ac_proof import PROOF_ATTR, AcProof

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_CONSUMER_ATTR = "__executed_proof_consumer__"

ExecutedProofConsumer = Callable[[TraceRecord], TraceRecord]


class ExecutedProofError(ValueError):
    """A CI proof cannot be bound to exact execution coordinates."""


class _PytestItem(Protocol):
    obj: Any
    nodeid: str
    user_properties: list[tuple[str, str]]


class _PytestReport(Protocol):
    when: str
    passed: bool
    user_properties: list[tuple[str, str]]


def register_executed_proof_consumer(
    item: _PytestItem,
    consumer: ExecutedProofConsumer,
) -> None:
    """Register the sole post-call consumer for one pytest item."""
    if not callable(consumer):
        raise ExecutedProofError("executed-proof consumer must be callable")
    if getattr(item, _CONSUMER_ATTR, None) is not None:
        raise ExecutedProofError("an executed-proof consumer is already registered")
    setattr(item, _CONSUMER_ATTR, consumer)


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def executed_proof_assertion_version(
    *,
    proof_id: str,
    scenario_id: str,
    oracle_kind: str,
    ac_ids: tuple[str, ...] | list[str],
    stage: str,
    task_category: str,
    required_observation_kind: str = "",
) -> str:
    """Hash the declaration fields that define one semantic proof contract."""
    declaration = {
        "ac_ids": list(ac_ids),
        "oracle_kind": oracle_kind,
        "proof_id": proof_id,
        "scenario_id": scenario_id,
        "stage": stage,
        "task_category": task_category,
    }
    if required_observation_kind:
        declaration["required_observation_kind"] = required_observation_kind
    return _digest(declaration)


def _ci_coordinates(environ: Mapping[str, str]) -> tuple[str, str, str, str]:
    repository_id = environ.get("GITHUB_REPOSITORY", "")
    commit_sha = environ.get("GITHUB_SHA", "")
    execution_id = github_execution_id(environ)
    if not repository_id or "/" not in repository_id:
        raise ExecutedProofError("GITHUB_REPOSITORY must identify owner/repository")
    if not _COMMIT_RE.fullmatch(commit_sha):
        raise ExecutedProofError("GITHUB_SHA must be one exact lowercase commit SHA")
    return (
        repository_id,
        commit_sha,
        execution_id,
        "github_ci.merge_authority",
    )


def github_execution_id(environ: Mapping[str, str]) -> str:
    """Return an attempt-specific GitHub execution id or fail closed."""
    run_id = environ.get("GITHUB_RUN_ID", "")
    run_attempt = environ.get("GITHUB_RUN_ATTEMPT", "")
    if not run_id.isdigit() or not run_attempt.isdigit():
        raise ExecutedProofError("GITHUB_RUN_ID and GITHUB_RUN_ATTEMPT must be numeric")
    execution_id = f"{run_id}.{run_attempt}"
    if len(execution_id) > 200:
        raise ExecutedProofError("GitHub execution id must not exceed 200 characters")
    return execution_id


def _local_coordinates(
    item: _PytestItem,
    environ: Mapping[str, str],
) -> tuple[str, str, str, str]:
    execution_id = environ.get("PYTEST_CURRENT_TEST", item.nodeid)
    if len(execution_id) > 200:
        execution_id = f"pytest@{sha256(execution_id.encode('utf-8')).hexdigest()}"
    return (
        environ.get("GITHUB_REPOSITORY", "finance_report"),
        environ.get("GITHUB_SHA", "local-unpinned"),
        execution_id,
        "local.advisory",
    )


def _build_executed_proof(
    proof: AcProof,
    item: _PytestItem,
    *,
    environ: Mapping[str, str],
    occurred_at: datetime,
) -> TraceRecord:
    if environ.get("GITHUB_ACTIONS") == "true":
        repository_id, commit_sha, execution_id, stage = _ci_coordinates(environ)
    else:
        repository_id, commit_sha, execution_id, stage = _local_coordinates(
            item, environ
        )

    contract_path = Path(__file__).with_name("contract.py")
    owner_digest = sha256(contract_path.read_bytes()).hexdigest()
    assertion_version = executed_proof_assertion_version(
        proof_id=proof.proof_id,
        scenario_id=proof.scenario_id,
        oracle_kind=proof.oracle_kind,
        ac_ids=proof.ac_ids,
        stage=proof.stage,
        task_category=proof.task_category,
        required_observation_kind=proof.required_observation_kind,
    )
    evidence_digest = _digest(
        {
            "commit_sha": commit_sha,
            "execution_id": execution_id,
            "node_id_digest": sha256(item.nodeid.encode("utf-8")).hexdigest(),
            "proof": asdict(proof),
            "repository_id": repository_id,
            "result": "pass",
        }
    )
    return TraceRecord.observation(
        scope=TraceScope(TraceScopeKind.REPOSITORY, repository_id),
        target=VersionedTraceRef(
            "terminal_scenario",
            proof.scenario_id,
            commit_sha,
        ),
        target_class=TraceTargetClass.GENERAL,
        assertion=VersionedTraceRef(
            "executed_proof",
            proof.proof_id,
            assertion_version,
        ),
        authority=TraceAuthorityProfile(
            package="testing",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage=stage,
            assertion_owner_digest=owner_digest,
            producer_version=f"pytest@{metadata.version('pytest')}",
        ),
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=evidence_digest,
        occurred_at=occurred_at,
        score=None,
        reason_code="executed_proof_passed",
    )


def record_executed_proof(
    item: _PytestItem,
    report: _PytestReport,
    *,
    environ: Mapping[str, str] | None = None,
    occurred_at: datetime | None = None,
) -> TraceRecord | None:
    """Attach PASS only after a scenario-bound test's call phase passed."""
    if (
        report.when != "call"
        or not report.passed
        or getattr(report, "wasxfail", None) is not None
    ):
        return None
    proof = getattr(item.obj, PROOF_ATTR, None)
    if not isinstance(proof, AcProof) or not proof.scenario_id:
        return None
    if not proof.oracle_kind:
        raise ExecutedProofError("a scenario-bound proof requires oracle_kind")
    if proof.ci_tier != "pr_ci":
        return None
    consumer = getattr(item, _CONSUMER_ATTR, None)
    if proof.required_observation_kind and consumer is None:
        raise ExecutedProofError(
            f"scenario proof requires a {proof.required_observation_kind!r} observation consumer"
        )

    record = _build_executed_proof(
        proof,
        item,
        environ=environ if environ is not None else os.environ,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    TraceJUnitAdapter.emit(
        lambda name, value: item.user_properties.append((name, value)),
        record,
    )
    if consumer is not None:
        output = consumer(record)
        if (
            not isinstance(output, TraceRecord)
            or output.record_type is not TraceRecordType.OBSERVATION
        ):
            raise ExecutedProofError(
                "executed-proof consumer must return one TraceRecord OBSERVATION"
            )
        if (
            proof.required_observation_kind
            and output.assertion.kind != proof.required_observation_kind
        ):
            raise ExecutedProofError(
                "executed-proof consumer returned the wrong observation assertion kind"
            )
        TraceJUnitAdapter.emit(
            lambda name, value: item.user_properties.append((name, value)),
            output,
        )
    return record


def executed_proof_matches(
    record: TraceRecord,
    *,
    proof_id: str,
    scenario_id: str,
    repository_id: str,
    commit_sha: str,
    execution_id: str,
    assertion_version: str | None = None,
) -> bool:
    """Validate one emitted record without inferring success from JUnit shape."""
    return (
        record.record_type is TraceRecordType.OBSERVATION
        and record.result is TraceResult.PASS
        and record.scope.kind is TraceScopeKind.REPOSITORY
        and record.scope.id == repository_id
        and record.target
        == VersionedTraceRef("terminal_scenario", scenario_id, commit_sha)
        and record.assertion.kind == "executed_proof"
        and record.assertion.id == proof_id
        and (assertion_version is None or record.assertion.version == assertion_version)
        and record.execution_id == execution_id
        and record.authority.package == "testing"
        and record.authority.tier == "CODE-ONLY"
        and record.authority.proof_kind == "exact"
        and record.authority.provenance == "deterministic"
        and record.authority.execution_stage == "github_ci.merge_authority"
        and record.reason_code == "executed_proof_passed"
    )
