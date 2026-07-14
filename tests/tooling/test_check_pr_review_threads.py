"""Tests for the PR review-thread merge gate (common.testing.check_pr_review_threads).

This gate blocks a PR at merge time when an unresolved P0/P1 (or unresolved
Copilot-authored) review thread exists, while resolved/outdated threads and
lower-severity (P2/P3/nit) unresolved threads never block.

Acceptance criteria (EPIC-008, AC group AC8.20):
  AC8.20.1 — the checker blocks (exit 1) when an unresolved P0/P1 (or unresolved
             Copilot) review thread exists.
  AC8.20.2 — resolved/outdated threads and lower-severity (P2/P3/nit) unresolved
             threads do NOT block; they are reported.
  AC8.20.3 — the severity classification rule is documented in the CI/CD SSOT.

All cases feed canned GraphQL JSON to the injectable ``fetch_threads`` seam so
no network call is made. Mirrors the pytest + ``common.*`` import convention of
``tests/tooling/test_check_manifest.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from common.testing import check_pr_review_threads as gate

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers: build canned GraphQL review-thread payloads.
# ---------------------------------------------------------------------------


def _thread(
    *,
    is_resolved: bool = False,
    is_outdated: bool = False,
    author: str = "some-human",
    body: str = "please fix this",
    url: str = "https://github.com/o/r/pull/1#discussion_r1",
) -> dict[str, Any]:
    """Build one reviewThreads node mirroring the GraphQL response shape."""
    return {
        "isResolved": is_resolved,
        "isOutdated": is_outdated,
        "comments": {
            "nodes": [
                {"author": {"login": author}, "body": body, "url": url},
            ]
        },
    }


def _payload(*threads: dict[str, Any]) -> dict[str, Any]:
    """Wrap thread nodes in the full `gh api graphql` envelope."""
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {"nodes": list(threads)},
                }
            }
        }
    }


def _run(payload: dict[str, Any]) -> int:
    """Run the gate with an injected fetcher returning the canned payload."""
    return gate.run(
        pr_number=1,
        repo="o/r",
        fetch_threads=lambda pr_number, repo: payload,
    )


# ---------------------------------------------------------------------------
# Severity classification (the documented rule).
# ---------------------------------------------------------------------------


class TestClassifyThread:
    def test_explicit_p0_marker_is_blocking(self) -> None:
        thread = _thread(body="P0: this corrupts balances")
        assert gate.classify_thread(thread) == gate.Severity.BLOCKING

    def test_explicit_p1_marker_is_blocking(self) -> None:
        thread = _thread(body="this is a P1 problem")
        assert gate.classify_thread(thread) == gate.Severity.BLOCKING

    def test_marker_is_case_insensitive(self) -> None:
        thread = _thread(body="p1 regression")
        assert gate.classify_thread(thread) == gate.Severity.BLOCKING

    def test_copilot_thread_is_blocking_by_default(self) -> None:
        thread = _thread(author="copilot-pull-request-reviewer[bot]", body="suggestion")
        assert gate.classify_thread(thread) == gate.Severity.BLOCKING

    def test_copilot_thread_real_login_without_bot_suffix_is_blocking(self) -> None:
        """AC-testing.review-threads.4: regression (2026-07-12) -- the GraphQL
        reviewThreads API returns author.login as
        "copilot-pull-request-reviewer" with NO "[bot]" suffix, confirmed
        against real threads on #1776/#1782/#1786. The allowlist only had the
        "[bot]"-suffixed form, so every real Copilot thread silently
        classified as non-blocking and this gate never actually blocked a
        Copilot-flagged issue in practice."""
        thread = _thread(author="copilot-pull-request-reviewer", body="suggestion")
        assert gate.classify_thread(thread) == gate.Severity.BLOCKING

    def test_copilot_alias_github_copilot_bot_is_blocking(self) -> None:
        thread = _thread(author="github-copilot[bot]", body="consider this")
        assert gate.classify_thread(thread) == gate.Severity.BLOCKING

    def test_copilot_thread_marked_nit_is_not_blocking(self) -> None:
        thread = _thread(
            author="copilot-pull-request-reviewer[bot]", body="nit: rename var"
        )
        assert gate.classify_thread(thread) == gate.Severity.LOWER

    def test_copilot_thread_marked_p2_is_not_blocking(self) -> None:
        thread = _thread(
            author="copilot-pull-request-reviewer[bot]", body="P2: minor style"
        )
        assert gate.classify_thread(thread) == gate.Severity.LOWER

    def test_plain_human_nit_is_lower(self) -> None:
        thread = _thread(body="nit: tiny wording")
        assert gate.classify_thread(thread) == gate.Severity.LOWER

    def test_plain_human_comment_is_lower(self) -> None:
        thread = _thread(body="what do you think about this?")
        assert gate.classify_thread(thread) == gate.Severity.LOWER


# ---------------------------------------------------------------------------
# Decision: AC8.20.1 — blocking cases exit 1.
# ---------------------------------------------------------------------------


class TestBlocking:
    def test_AC8_20_1_unresolved_p0_blocks(self) -> None:
        """AC-testing.review-threads.1: AC8.20.1: an unresolved P0 review thread exits 1."""
        payload = _payload(_thread(body="P0: must fix", is_resolved=False))
        assert _run(payload) == 1

    def test_AC8_20_1_unresolved_copilot_blocks(self) -> None:
        """AC8.20.1: an unresolved Copilot review thread exits 1."""
        payload = _payload(
            _thread(author="copilot-pull-request-reviewer[bot]", is_resolved=False)
        )
        assert _run(payload) == 1

    def test_AC8_20_1_blocking_thread_url_is_printed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AC8.20.1: the blocking thread's url is named in the summary."""
        url = "https://github.com/o/r/pull/1#discussion_r999"
        payload = _payload(_thread(body="P1: bug", url=url, is_resolved=False))
        assert _run(payload) == 1
        captured = capsys.readouterr()
        assert url in (captured.out + captured.err)


# ---------------------------------------------------------------------------
# Decision: AC8.20.2 — resolved/outdated/lower-severity never block.
# ---------------------------------------------------------------------------


class TestNonBlocking:
    def test_AC8_20_2_resolved_p0_passes(self) -> None:
        """AC-testing.review-threads.2: AC8.20.2: a resolved P0 thread does not block."""
        payload = _payload(_thread(body="P0: was fixed", is_resolved=True))
        assert _run(payload) == 0

    def test_AC8_20_2_outdated_p0_passes(self) -> None:
        """AC8.20.2: an outdated (unresolved) P0 thread does not block."""
        payload = _payload(
            _thread(body="P0: stale", is_resolved=False, is_outdated=True)
        )
        assert _run(payload) == 0

    def test_AC8_20_2_unresolved_nit_passes_but_reported(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AC8.20.2: an unresolved nit does not block but is reported."""
        payload = _payload(_thread(body="nit: rename", is_resolved=False))
        assert _run(payload) == 0
        captured = capsys.readouterr()
        # Lower-severity unresolved threads are surfaced, not silently dropped.
        assert "nit" in (captured.out + captured.err).lower()

    def test_AC8_20_2_empty_passes(self) -> None:
        """AC8.20.2: a PR with no review threads passes (bootstrap-safe)."""
        assert _run(_payload()) == 0

    def test_AC8_20_2_mixed_blocks_only_on_active_p0(self) -> None:
        """A resolved P0 plus an unresolved nit still passes."""
        payload = _payload(
            _thread(body="P0: fixed", is_resolved=True),
            _thread(body="nit: trivial", is_resolved=False),
        )
        assert _run(payload) == 0


# ---------------------------------------------------------------------------
# Injectability + non-PR / bootstrap safety.
# ---------------------------------------------------------------------------


class TestSeamAndSafety:
    def test_run_uses_injected_fetcher_without_network(self) -> None:
        """The fetch seam is honored; no real `gh` call happens in tests."""
        calls: list[tuple[int, str]] = []

        def fake_fetch(pr_number: int, repo: str) -> dict[str, Any]:
            calls.append((pr_number, repo))
            return _payload()

        assert gate.run(pr_number=7, repo="o/r", fetch_threads=fake_fetch) == 0
        assert calls == [(7, "o/r")]

    def test_run_skips_cleanly_when_pr_number_missing(self) -> None:
        """Non-PR events (no PR number) skip the gate without blocking."""
        sentinel_called = False

        def fetch(pr_number: int, repo: str) -> dict[str, Any]:
            nonlocal sentinel_called
            sentinel_called = True
            return _payload()

        assert gate.run(pr_number=None, repo="o/r", fetch_threads=fetch) == 0
        assert sentinel_called is False


# ---------------------------------------------------------------------------
# main(): CLI entrypoint wiring.
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_skips_without_pr_number(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PR_NUMBER", raising=False)
        assert gate.main(["--repo", "o/r"]) == 0

    def test_main_blocks_with_injected_blocking_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _payload(_thread(body="P0: bug", is_resolved=False))
        monkeypatch.setattr(gate, "fetch_threads", lambda pr_number, repo: payload)
        assert gate.main(["--repo", "o/r", "--pr-number", "1"]) == 1

    def test_main_fails_closed_when_pr_present_but_repo_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A PR number with no resolvable repo is a misconfig — fail closed (1)."""
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        called = False

        def fetch(pr_number: int, repo: str) -> dict[str, Any]:
            nonlocal called
            called = True
            return _payload()

        monkeypatch.setattr(gate, "fetch_threads", fetch)
        assert gate.main(["--pr-number", "1"]) == 1
        # The gate must not silently pass: it fails before fetching.
        assert called is False


# ---------------------------------------------------------------------------
# fetch_threads pagination — a PR with >100 review threads must not truncate.
# ---------------------------------------------------------------------------


def _page(nodes: list[dict[str, Any]], *, has_next: bool, cursor: str | None) -> Any:
    """Build a subprocess.run result whose stdout is one GraphQL page."""

    class _Result:
        stdout = json.dumps(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {
                                    "hasNextPage": has_next,
                                    "endCursor": cursor,
                                },
                                "nodes": nodes,
                            }
                        }
                    }
                }
            }
        )

    return _Result()


class TestFetchPagination:
    def test_fetch_threads_follows_all_pages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fetch_threads concatenates every page until hasNextPage is false."""
        pages = [
            _page([_thread(body="t1")], has_next=True, cursor="c1"),
            _page([_thread(body="t2")], has_next=True, cursor="c2"),
            _page([_thread(body="t3")], has_next=False, cursor=None),
        ]
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> Any:
            calls.append(cmd)
            return pages[len(calls) - 1]

        monkeypatch.setattr(gate.subprocess, "run", fake_run)
        merged = gate.fetch_threads(1, "o/r")
        nodes = gate._thread_nodes(merged)
        assert len(nodes) == 3
        # Three page requests; pages 2 and 3 pass the prior endCursor.
        assert len(calls) == 3
        assert any("after=c1" in part for part in calls[1])
        assert any("after=c2" in part for part in calls[2])

    def test_fetch_threads_fails_closed_when_cursor_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """hasNextPage true but no endCursor must raise (never silently drop)."""
        page = _page([_thread(body="t1")], has_next=True, cursor=None)
        monkeypatch.setattr(gate.subprocess, "run", lambda cmd, **kw: page)
        with pytest.raises(RuntimeError):
            gate.fetch_threads(1, "o/r")


# ---------------------------------------------------------------------------
# AC8.20.3 — the classification rule is documented in the CI/CD SSOT.
# ---------------------------------------------------------------------------


def test_AC8_20_3_severity_rule_documented_in_ssot() -> None:
    """AC-testing.review-threads.3: AC8.20.3: common/testing/ci-cd.md documents the gate and its severity rule."""
    ci_cd = (_REPO_ROOT / "common" / "testing" / "ci-cd.md").read_text(encoding="utf-8")
    assert "PR Review Thread Merge Gate" in ci_cd
    # The exact marker rule and the Copilot-author list must be documented.
    assert r"\b(P0|P1)\b" in ci_cd
    assert "copilot-pull-request-reviewer[bot]" in ci_cd
    # Resolved/outdated and lower-severity non-blocking semantics are documented.
    assert "outdated" in ci_cd.lower()
    assert "do **not** block" in ci_cd or "do not block" in ci_cd
