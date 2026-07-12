"""Real-corpus-eval release-evidence check (AC-runtime.real-corpus-eval.*, #1764).

Behavioral tests only — no source-text mirroring (see #1435): each test calls
``verify_real_corpus_eval`` directly with an injected ``gh_json``/``now``, the
same DI pattern the pre-existing verify_source_ci/verify_staging tests in
tests/tooling/test_post_merge_e2e_gates.py use, kept in its own small file
rather than added to that already-3900-line one.
"""

from __future__ import annotations

import datetime as dt

import pytest

from common.runtime import release_evidence

_NOW = dt.datetime(2026, 7, 12, 12, 0, tzinfo=dt.timezone.utc)


def test_AC_runtime_real_corpus_eval_1_fresh_success_run_passes() -> None:
    """AC-runtime.real-corpus-eval.1: a completed, successful, fresh run passes."""

    def fake_gh_json(_args: list[str]) -> object:
        return [
            {
                "databaseId": 100,
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-07-12T00:00:00Z",  # 12h before _NOW
            }
        ]

    run_id = release_evidence.verify_real_corpus_eval(
        repository="owner/repo",
        gh_json=fake_gh_json,
        now=_NOW,
    )
    assert run_id == "100"


def test_AC_runtime_real_corpus_eval_2_no_completed_run_fails_closed() -> None:
    """AC-runtime.real-corpus-eval.2: no completed run at all is a hard failure,
    never a silent pass — an eval that has never run proves nothing (Axiom E)."""

    def fake_gh_json(_args: list[str]) -> object:
        return []

    with pytest.raises(RuntimeError, match="No completed real-corpus-eval run"):
        release_evidence.verify_real_corpus_eval(
            repository="owner/repo", gh_json=fake_gh_json, now=_NOW
        )


def test_AC_runtime_real_corpus_eval_3_failed_run_fails_closed() -> None:
    """AC-runtime.real-corpus-eval.3: a completed-but-failed run (a real accuracy
    or calibration regression) fails closed, not silently passed over."""

    def fake_gh_json(_args: list[str]) -> object:
        return [
            {
                "databaseId": 101,
                "status": "completed",
                "conclusion": "failure",
                "createdAt": "2026-07-12T00:00:00Z",
            }
        ]

    with pytest.raises(RuntimeError, match="did not succeed"):
        release_evidence.verify_real_corpus_eval(
            repository="owner/repo", gh_json=fake_gh_json, now=_NOW
        )


def test_AC_runtime_real_corpus_eval_4_stale_run_fails_closed() -> None:
    """AC-runtime.real-corpus-eval.4: a successful run older than max_age_hours
    fails closed — staleness is exactly as untrustworthy as never having run."""

    def fake_gh_json(_args: list[str]) -> object:
        return [
            {
                "databaseId": 102,
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-07-01T00:00:00Z",  # far more than 48h before _NOW
            }
        ]

    with pytest.raises(RuntimeError, match="stale"):
        release_evidence.verify_real_corpus_eval(
            repository="owner/repo",
            gh_json=fake_gh_json,
            now=_NOW,
            max_age_hours=48.0,
        )


def test_AC_runtime_real_corpus_eval_5_picks_the_most_recent_completed_run() -> None:
    """AC-runtime.real-corpus-eval.5: with multiple runs, the newest completed one
    governs the verdict — a fixed-then-passing re-run supersedes an old failure."""

    def fake_gh_json(_args: list[str]) -> object:
        return [
            {
                "databaseId": 200,
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-07-12T06:00:00Z",
            },
            {
                "databaseId": 199,
                "status": "completed",
                "conclusion": "failure",
                "createdAt": "2026-07-10T00:00:00Z",
            },
        ]

    run_id = release_evidence.verify_real_corpus_eval(
        repository="owner/repo", gh_json=fake_gh_json, now=_NOW
    )
    assert run_id == "200"


def test_AC_runtime_real_corpus_eval_6_missing_created_at_fails_closed() -> None:
    """AC-runtime.real-corpus-eval.6: a completed/successful run with no (or
    blank) createdAt fails closed with a clear error, not an unhandled
    KeyError/TypeError and not a silent freshness pass."""

    def fake_gh_json(_args: list[str]) -> object:
        return [
            {
                "databaseId": 300,
                "status": "completed",
                "conclusion": "success",
                "createdAt": None,
            }
        ]

    with pytest.raises(RuntimeError, match="missing createdAt"):
        release_evidence.verify_real_corpus_eval(
            repository="owner/repo", gh_json=fake_gh_json, now=_NOW
        )
