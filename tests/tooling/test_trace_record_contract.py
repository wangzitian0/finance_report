"""Cross-runtime locks for AC-audit.trace-record.1-.2."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from common.audit.base.trace import (
    _VALID_PROOF_KINDS,
    _VALID_STAGES,
    TraceAuthorityProfile,
    TraceRecord,
    TraceRecordValidationError,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from common.audit.extension import TraceRecordCodec
from common.audit.ratio import Ratio
from common.meta.base.authority_matrix import PACKAGE_TIERS, TIER_VALID_PROOF_KINDS
from common.testing.ac_proof_execution import PROOF_EXECUTION_STAGES
from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]


def _normalized_trace_ast(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module and node.module.startswith("common.audit"):
            node.module = node.module.replace("common.audit", "audit", 1)
        elif node.module and node.module.startswith("src.audit"):
            node.module = node.module.replace("src.audit", "audit", 1)
        elif node.level == 2 and node.module == "ratio":
            node.module = "audit.ratio"
            node.level = 0
    return ast.dump(tree, include_attributes=False)


@pytest.mark.parametrize(
    ("common_path", "backend_path"),
    (
        ("base/trace.py", "base/trace.py"),
        ("base/trace_repository.py", "base/trace_repository.py"),
        ("extension/trace_codec.py", "extension/trace_codec.py"),
        ("extension/trace_adapters.py", "extension/trace_adapters.py"),
    ),
)
def test_trace_record_common_and_backend_mirrors_are_semantically_identical(
    common_path: str,
    backend_path: str,
):
    common = REPO / "common/audit" / common_path
    backend = REPO / "apps/backend/src/audit" / backend_path

    assert _normalized_trace_ast(common) == _normalized_trace_ast(backend)


@ac_proof(
    proof_id="trace_record_common_backend_codec_parity",
    ac_ids=["AC-audit.trace-record.1"],
    ci_tier="pr_ci",
    issue="#1906",
)
def test_trace_record_common_and_backend_codecs_are_wire_identical():
    record = TraceRecord.observation(
        scope=TraceScope.tenant(uuid4()),
        target=VersionedTraceRef(kind="proof", id="proof-1", version="v1"),
        target_class=TraceTargetClass.GENERAL,
        assertion=VersionedTraceRef(kind="invariant", id="invariant-1", version="v1"),
        authority=TraceAuthorityProfile(
            package="audit",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="github_ci.merge_authority",
            assertion_owner_digest="a" * 64,
            producer_version="tooling@1",
        ),
        result=TraceResult.PASS,
        execution_id="execution-1",
        evidence_manifest_digest="b" * 64,
        occurred_at=datetime(2026, 7, 17, tzinfo=UTC),
        score=Ratio(Decimal("0.875")),
        reason_code="parity_fixture",
    )
    encoded = TraceRecordCodec.encode(record)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.audit import TraceRecordCodec; "
            "import sys; print(TraceRecordCodec.encode(TraceRecordCodec.decode(sys.stdin.read())))",
        ],
        cwd=REPO / "apps/backend",
        input=encoded,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == encoded


@ac_proof(
    proof_id="trace_record_authority_matrix_parity",
    ac_ids=["AC-audit.trace-record.2"],
    ci_tier="pr_ci",
    issue="#1906",
)
def test_trace_authority_profile_acceptance_matches_the_canonical_matrix():
    assert _VALID_PROOF_KINDS == {
        tier: TIER_VALID_PROOF_KINDS[tier] for tier in PACKAGE_TIERS
    }
    all_kinds = {kind for kinds in TIER_VALID_PROOF_KINDS.values() for kind in kinds}
    cases: list[dict[str, str]] = []
    expected_results: list[bool] = []
    for tier in PACKAGE_TIERS:
        for proof_kind in all_kinds:
            kwargs = dict(
                package="audit",
                tier=tier,
                proof_kind=proof_kind,
                provenance=(
                    "live_llm" if tier in {"LLM-LED", "LLM-ONLY"} else "deterministic"
                ),
                execution_stage="github_ci.merge_authority",
                assertion_owner_digest="a" * 64,
                producer_version="tooling@1",
            )
            expected = proof_kind in TIER_VALID_PROOF_KINDS[tier]
            if expected:
                TraceAuthorityProfile(**kwargs)
            else:
                with pytest.raises(TraceRecordValidationError):
                    TraceAuthorityProfile(**kwargs)
            cases.append(kwargs)
            expected_results.append(expected)

    manual = dict(
        package="audit",
        tier="CODE-LED",
        proof_kind="exact",
        provenance="manual",
        execution_stage="manual.adjudication",
        assertion_owner_digest="a" * 64,
        producer_version="operator@1",
    )
    TraceAuthorityProfile(**manual)
    cases.append(manual)
    expected_results.append(True)
    cases.append({**manual, "tier": "HU", "proof_kind": "evidence"})
    expected_results.append(False)

    backend_probe = """
import json
import sys

from src.audit import TraceAuthorityProfile

accepted = []
for row in json.load(sys.stdin):
    try:
        TraceAuthorityProfile(**row)
        accepted.append(True)
    except ValueError:
        accepted.append(False)
print(json.dumps(accepted))
"""
    result = subprocess.run(
        [sys.executable, "-c", backend_probe],
        cwd=REPO / "apps/backend",
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected_results


def test_trace_authority_stage_acceptance_matches_execution_ssot():
    assert _VALID_STAGES == frozenset(PROOF_EXECUTION_STAGES)
    for stage in PROOF_EXECUTION_STAGES:
        TraceAuthorityProfile(
            package="audit",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance=(
                "manual" if stage == "manual.adjudication" else "deterministic"
            ),
            execution_stage=stage,
            assertion_owner_digest="a" * 64,
            producer_version="tooling@1",
        )
    with pytest.raises(TraceRecordValidationError, match="not registered"):
        TraceAuthorityProfile(
            package="audit",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="invented.stage",
            assertion_owner_digest="a" * 64,
            producer_version="tooling@1",
        )
