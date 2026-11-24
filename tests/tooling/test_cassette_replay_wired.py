from __future__ import annotations

from pathlib import Path

from common.testing.matrix import PR_EVIDENCE_STAGES, classify_stage

CORPUS_FILE = Path("apps/backend/tests/integration/test_statement_corpus_journeys.py")


def test_corpus_is_a_reconciled_pr_ci_proof() -> None:
    assert CORPUS_FILE.is_file(), (
        f"missing real-statement corpus journey ({CORPUS_FILE}) — the stored-readings safety net is unanchored."
    )
    stage = classify_stage(CORPUS_FILE.as_posix())
    assert stage in PR_EVIDENCE_STAGES, (
        f"corpus file classifies to {stage!r}, which PR_EVIDENCE_STAGES does not cover."
    )
