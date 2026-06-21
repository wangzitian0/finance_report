"""AC8.13.150: AC-keyed proof execution placement metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.ssot import generate_critical_proof_matrix as matrix
from common.ssot.ac_graph import _proof_edges
from common.ssot.ac_proof_execution import (
    PROOF_EXECUTION_STAGES,
    PROOF_TASK_CATEGORIES,
    normalize_proof_execution,
)
from common.testing.ac_proof import ac_proof

ROOT = Path(__file__).resolve().parents[2]


def test_AC8_13_150_ac_proof_execution_model_is_ac_keyed_and_backward_compatible(
    tmp_path: Path,
) -> None:
    """AC8.13.150: proof placement is metadata on the AC proof edge."""
    ci_cd = (ROOT / "docs" / "ssot" / "ci-cd.md").read_text(encoding="utf-8")

    assert "AC -> proof(name, stage, task_category)" in ci_cd
    assert "The AC id remains the only coverage key" in ci_cd
    assert "does not replace authority tier or proof_kind" in ci_cd
    for stage in PROOF_EXECUTION_STAGES:
        assert f"`{stage}`" in ci_cd
    for task_category in PROOF_TASK_CATEGORIES:
        assert f"`{task_category}`" in ci_cd

    @ac_proof("legacy-proof", ac_ids=["AC8.13.150"], ci_tier="pr_ci")
    def legacy_test() -> None:
        """AC8.13.150: legacy ci_tier still implies execution placement."""

    runtime_proof = getattr(legacy_test, "__ac_proof__")
    assert runtime_proof.stage == "github_ci.merge_authority"
    assert runtime_proof.task_category == "critical_behavioral"

    assert normalize_proof_execution({"ci_tier": "manual", "scope": "manual_gate"}) == (
        "manual.adjudication",
        "manual_evidence",
    )
    assert normalize_proof_execution(
        {
            "ci_tier": "pr_ci",
            "scope": "behavioral",
            "stage": "staging.provider_regression",
            "task_category": "provider_gate",
        }
    ) == ("staging.provider_regression", "provider_gate")

    test_dir = tmp_path / "tests" / "e2e"
    test_dir.mkdir(parents=True)
    (test_dir / "test_stage_metadata.py").write_text(
        "\n".join(
            [
                "from common.testing.ac_proof import ac_proof",
                "",
                "@ac_proof(",
                "    'explicit-stage-proof',",
                "    ac_ids=['AC8.13.150'],",
                "    stage='staging.provider_regression',",
                "    task_category='provider_gate',",
                "    ci_tier='post_merge_environment',",
                ")",
                "def test_AC8_13_150_explicit_stage_metadata():",
                '    """AC8.13.150: explicit stage metadata is static."""',
                "    assert True",
                "",
            ]
        ),
        encoding="utf-8",
    )

    [collected] = matrix.collect_proofs(tmp_path)
    assert collected.fields["stage"] == "staging.provider_regression"
    assert collected.fields["task_category"] == "provider_gate"

    [edge] = _proof_edges([collected])
    assert edge.stage == "staging.provider_regression"
    assert edge.task_category == "provider_gate"


def test_AC8_13_150_ac_proof_execution_model_rejects_unknown_metadata() -> None:
    """AC8.13.150: proof placement values fail fast on typos."""
    with pytest.raises(ValueError, match="unknown AC proof stage"):
        normalize_proof_execution(
            {
                "ci_tier": "pr_ci",
                "stage": "staging.provider_regresion",
                "task_category": "provider_gate",
            }
        )

    with pytest.raises(ValueError, match="unknown AC proof task_category"):
        normalize_proof_execution(
            {
                "ci_tier": "pr_ci",
                "stage": "staging.provider_regression",
                "task_category": "provider_gat",
            }
        )
