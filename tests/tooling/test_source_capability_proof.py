"""Derived SourceCapability-to-proof join contract."""

from pathlib import Path

import pytest

from common.extraction.source_capability import (
    SOURCE_CAPABILITIES,
    SourceCapability,
    SourceCapabilityStatus,
)
from common.testing.ac_graph import ProofEdge, build_ac_graph
from common.testing.source_capability_proof import validate_source_capability_proofs
from tools import check_ac_index as ac_index_wrapper

ROOT = Path(__file__).resolve().parents[2]


def _capability(
    capability_id: str,
    status: SourceCapabilityStatus,
) -> SourceCapability:
    return SourceCapability(
        capability_id=capability_id,
        status=status,
        intake_modes=("fixture",),
        evidence_kinds=("fixture",),
        produced_facts=("fixture",),
        review_semantics="fixture review",
        traceability_target="fixture-target",
    )


def _proof(
    proof_id: str,
    source_classes: tuple[str, ...],
    *,
    stage: str = "github_ci.merge_authority",
    ci_tier: str = "pr_ci",
) -> ProofEdge:
    return ProofEdge(
        proof_id=proof_id,
        file="tests/e2e/test_fixture.py",
        test="test_fixture",
        ac_ids=("AC-testing.source-capability-proof.1",),
        stage=stage,
        task_category="test",
        ci_tier=ci_tier,
        scope="behavioral",
        required_markers=(),
        fields={"source_classes": list(source_classes)},
    )


def test_AC_testing_source_capability_proof_1_real_registry_resolves_to_required_proofs() -> (
    None
):
    """AC-testing.source-capability-proof.1: owner claims join the real proof graph."""
    graph = build_ac_graph(ROOT)

    assert validate_source_capability_proofs(SOURCE_CAPABILITIES, graph.proofs) == []

    duplicate = (*SOURCE_CAPABILITIES, SOURCE_CAPABILITIES[0])
    errors = validate_source_capability_proofs(duplicate, graph.proofs)
    assert "duplicate SourceCapability ids: bank_statement" in errors

    errors = validate_source_capability_proofs(
        (_capability("bank_statement", SourceCapabilityStatus.SUPPORTED),),
        (_proof("unknown-source", ("not_registered",)),),
    )
    assert (
        "proof unknown-source claims unknown source capability not_registered" in errors
    )

    malformed = _proof("malformed", ())
    malformed.fields["source_classes"] = "bank_statement"
    errors = validate_source_capability_proofs(SOURCE_CAPABILITIES, (malformed,))
    assert "proof malformed source_classes must be a list" in errors


def test_AC_extraction_112_2_supported_capabilities_require_release_proof() -> None:
    """AC-extraction.112.2: automated support needs PR and release proof."""
    capability = _capability("bank_statement", SourceCapabilityStatus.SUPPORTED)

    errors = validate_source_capability_proofs(
        (capability,),
        (_proof("bank-pr", ("bank_statement",)),),
    )

    assert (
        "bank_statement: supported capability lacks release-validation proof" in errors
    )


def test_AC_extraction_112_3_gap_capabilities_cannot_claim_proof() -> None:
    """AC-extraction.112.3: positive proof cannot turn an owner gap into support."""
    capability = _capability("settlement_note", SourceCapabilityStatus.GAP)

    errors = validate_source_capability_proofs(
        (capability,),
        (_proof("settlement-positive", ("settlement_note",)),),
    )

    assert (
        "settlement_note: gap capability is claimed by proof settlement-positive"
        in errors
    )


def test_AC_testing_source_capability_proof_2_static_matrix_is_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.source-capability-proof.2: no duplicate support registry survives."""
    retired = (
        "common/testing/data/source-coverage-matrix.yaml",
        "common/testing/coverage/check_source_coverage_matrix.py",
        "tools/check_source_coverage_matrix.py",
        "tests/tooling/test_source_coverage_matrix.py",
    )
    assert not [path for path in retired if (ROOT / path).exists()]

    stale_routes = (
        "vision.md",
        "common/extraction/readme.md",
        "common/testing/tdd.md",
        "common/testing/ci-cd.md",
        "common/testing/contract.py",
        "common/advisor/contract.py",
        "common/advisor/readme.md",
        "docs/project/EPIC-013.statement-parsing-v2.md",
        "docs/project/EPIC-019.event-driven-upload-to-report-ux.md",
        "docs/project/EPIC-021.application-ai-advisor.md",
    )
    for path in stale_routes:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "source-coverage-matrix" not in text, path
        assert "source_coverage_matrix" not in text, path

    graph = build_ac_graph(ROOT)
    observed: dict[str, object] = {}

    def fake_run_ac_index(argv, *, repo_integrity_checks):
        observed["argv"] = argv
        observed["checks"] = len(repo_integrity_checks)
        assert repo_integrity_checks[0](ROOT, graph) == []
        return 0

    monkeypatch.setattr(ac_index_wrapper, "run_ac_index", fake_run_ac_index)

    assert ac_index_wrapper.main(["--repo-root", str(ROOT)]) == 0
    assert observed == {
        "argv": ["--repo-root", str(ROOT)],
        "checks": 1,
    }
