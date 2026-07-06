"""Lock: the real-statement corpus stays a reconciled pr_ci proof (#1623).

#1614 was a class of cassette-backed extraction tests that silently skipped in
CI. The durable guard is behavioral, not a text mirror: the real-statement
corpus journey must stay a ``ci_tier="pr_ci"`` @ac_proof whose file classifies
into a PR-evidence stage — because then the ci_tier<->JUnit reconciliation
(check_pr_ci_evidence, where skipped-only is a hard fail) forces it to actually
RUN pre-merge. If it stopped running or lost its pr_ci tier, that gate goes red.
"""

from __future__ import annotations

from common.testing.matrix import PR_EVIDENCE_STAGES, classify_stage

CORPUS_FILE_HINT = "test_statement_corpus_journeys.py"


def _corpus_proofs() -> list[dict]:
    from common.testing.ac_graph import build_proofs_only
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    proofs = build_matrix_from_graph(build_proofs_only()).get("proofs", [])
    return [p for p in proofs if CORPUS_FILE_HINT in p.get("file", "")]


def test_corpus_is_a_reconciled_pr_ci_proof() -> None:
    corpus = _corpus_proofs()
    assert corpus, (
        "no @ac_proof found for the real-statement corpus journey "
        f"({CORPUS_FILE_HINT}) — the cassette-replay safety net is unanchored."
    )
    pr_ci = [p for p in corpus if p.get("ci_tier") == "pr_ci"]
    assert pr_ci, "the corpus journey must stay a pr_ci proof so it runs pre-merge."
    for proof in pr_ci:
        stage = classify_stage(proof["file"])
        assert stage in PR_EVIDENCE_STAGES, (
            f"corpus proof {proof['id']} is pr_ci but its file classifies to "
            f"{stage!r}, which the ci_tier<->JUnit reconciliation does not cover — "
            "it could silently stop running. Map its path into a PR-evidence stage."
        )
