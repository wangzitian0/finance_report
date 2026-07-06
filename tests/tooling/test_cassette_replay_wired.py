"""Lock: the LLM cassette-replay safety net cannot silently revert to skip (#1623).

#1614 was a whole class of extraction tests that carried a `skipif` on
LLM_CASSETTE_MODE and silently skipped everywhere (no CI lane ever set the
mode), so the "extraction LLM path is exercised in PR CI" gate ran nowhere. The
fix made the tests default THEMSELVES to replay. This locks that fix: if the
default-to-replay fixture is removed, the tests would skip again — so assert it
stays, and assert the corpus journey stays a pr_ci proof (which the
ci_tier<->JUnit reconciliation then forces to actually run).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPLAY_TEST = (
    ROOT
    / "apps"
    / "backend"
    / "tests"
    / "extraction"
    / "test_extraction_cassette_replay.py"
)
CORPUS_TEST = (
    ROOT / "apps" / "backend" / "tests" / "e2e" / "test_statement_corpus_journeys.py"
)


def test_extraction_cassette_tests_default_to_replay_not_skip() -> None:
    src = REPLAY_TEST.read_text(encoding="utf-8")
    assert "autouse=True" in src and "_default_to_replay" in src, (
        "the extraction cassette tests must keep the autouse default-to-replay "
        "fixture, or they silently skip in CI again (#1614)."
    )
    assert "CassetteMode.REPLAY" in src, "replay mode must be the default when unset"


def test_corpus_journey_stays_a_pr_ci_proof() -> None:
    src = CORPUS_TEST.read_text(encoding="utf-8")
    assert "@ac_proof(" in src and 'ci_tier="pr_ci"' in src, (
        "the real-statement corpus journey must stay a pr_ci @ac_proof so the "
        "ci_tier<->JUnit reconciliation forces it to run pre-merge."
    )
