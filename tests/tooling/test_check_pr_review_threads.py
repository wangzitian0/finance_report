"""AC8.20.1 AC8.20.2 AC8.20.3 EPIC-008"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from common.testing import check_pr_review_threads as gate

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _thread(
    *,
    is_resolved: bool = False,
    is_outdated: bool = False,
    author: str = "some-human",
    body: str = "please fix this",
    url: str = "https://github.com/o/r/pull/1#discussion_r1",
) -> dict[str, Any]:
    return {
        "isResolved": is_resolved,
        "isOutdated": is_outdated,
        "comments": {
            "nodes": [{"author": {"login": author}, "body": body, "url": url}]
        },
    }


def _payload(*threads: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": {
            "repository": {"pullRequest": {"reviewThreads": {"nodes": list(threads)}}}
        }
    }


def _run(payload: dict[str, Any]) -> int:
    return gate.run(pr_number=1, repo="o/r", fetch_threads=lambda _pr, _repo: payload)


class TestThreadWeight:
    def test_literal_severity_weights_and_unlabelled_default(self) -> None:
        assert gate.thread_weight(_thread(body="severity: high\nbug")) == ("High", 1.0)
        assert gate.thread_weight(_thread(body="Severity: MIDDLE")) == ("Medium", 0.5)
        assert gate.thread_weight(_thread(body="severity: medium")) == ("Medium", 0.5)
        assert gate.thread_weight(_thread(body="severity: low\nnit")) == ("Low", 0.25)
        assert gate.thread_weight(_thread(body="plain comment")) == (
            "Medium (default)",
            0.5,
        )

    def test_copilot_has_no_special_author_weight(self) -> None:
        assert gate.thread_weight(
            _thread(author="copilot-pull-request-reviewer[bot]", body="suggestion")
        ) == ("Medium (default)", 0.5)
        assert gate.thread_weight(
            _thread(author="github-copilot[bot]", body="severity: low")
        ) == ("Low", 0.25)

    def test_legacy_markers_without_severity_use_unlabelled_weight(self) -> None:
        for body in ("P0 blocker", "P1 regression", "nit: rename var", "P2/P3 polish"):
            assert gate.thread_weight(_thread(body=body)) == ("Medium (default)", 0.5)
        assert _run(_payload(_thread(body="P0 blocker without severity tag"))) == 0


class TestBlocking:
    def test_single_high_blocks_at_one_point_zero(self) -> None:
        assert _run(_payload(_thread(body="severity: high: corrupts ledger"))) == 1

    def test_two_middle_or_unlabelled_threads_block(self) -> None:
        assert (
            _run(
                _payload(
                    _thread(body="severity: middle: one"),
                    _thread(body="severity: medium: two"),
                )
            )
            == 1
        )
        assert _run(_payload(_thread(body="first"), _thread(body="second"))) == 1

    def test_four_low_threads_block(self) -> None:
        assert _run(_payload(*[_thread(body="severity: low") for _ in range(4)])) == 1

    def test_blocking_thread_url_and_score_printed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        url = "https://github.com/o/r/pull/1#discussion_r999"
        assert (
            _run(
                _payload(
                    _thread(body="severity: high", url=url),
                    _thread(body="severity: low"),
                )
            )
            == 1
        )
        captured = capsys.readouterr()
        assert url in captured.err
        assert "weighted score 1.25" in captured.out
        assert "unresolved review score 1.25 >= 1.00" in captured.err


class TestNonBlocking:
    def test_single_unlabelled_copilot_or_middle_passes(self) -> None:
        assert (
            _run(
                _payload(
                    _thread(
                        author="copilot-pull-request-reviewer[bot]",
                        body="consider renaming",
                    )
                )
            )
            == 0
        )
        assert _run(_payload(_thread(body="severity: middle"))) == 0

    def test_three_low_threads_pass(self) -> None:
        assert _run(_payload(*[_thread(body="severity: low") for _ in range(3)])) == 0

    def test_resolved_and_outdated_high_threads_ignored(self) -> None:
        assert _run(_payload(_thread(body="severity: high", is_resolved=True))) == 0
        assert _run(_payload(_thread(body="severity: high", is_outdated=True))) == 0
        assert _run(_payload()) == 0
        assert (
            _run(
                _payload(
                    _thread(body="severity: high", is_resolved=True),
                    _thread(body="severity: low"),
                )
            )
            == 0
        )

    def test_unresolved_below_threshold_is_reported(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(_payload(_thread(body="severity: low: rename var"))) == 0
        captured = capsys.readouterr()
        assert "rename var" in (captured.out + captured.err).lower()


class TestSeamAndSafety:
    def test_run_uses_injected_fetcher_without_network(self) -> None:
        calls: list[tuple[int, str]] = []

        def fake_fetch(pr_number: int, repo: str) -> dict[str, Any]:
            calls.append((pr_number, repo))
            return _payload()

        assert gate.run(pr_number=7, repo="o/r", fetch_threads=fake_fetch) == 0
        assert calls == [(7, "o/r")]

    def test_run_skips_cleanly_when_pr_number_missing(self) -> None:
        sentinel_called = False

        def fetch(_pr_number: int, _repo: str) -> dict[str, Any]:
            nonlocal sentinel_called
            sentinel_called = True
            return _payload()

        assert gate.run(pr_number=None, repo="o/r", fetch_threads=fetch) == 0
        assert sentinel_called is False


class TestMain:
    def test_main_skips_without_pr_number(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PR_NUMBER", raising=False)
        assert gate.main(["--repo", "o/r"]) == 0

    def test_main_blocks_with_injected_blocking_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _payload(_thread(body="severity: high", is_resolved=False))
        monkeypatch.setattr(gate, "fetch_threads", lambda _pr, _repo: payload)
        assert gate.main(["--repo", "o/r", "--pr-number", "1"]) == 1

    def test_main_fails_closed_when_pr_present_but_repo_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        called = False

        def fetch(_pr_number: int, _repo: str) -> dict[str, Any]:
            nonlocal called
            called = True
            return _payload()

        monkeypatch.setattr(gate, "fetch_threads", fetch)
        assert gate.main(["--pr-number", "1"]) == 1
        assert called is False


def _page(nodes: list[dict[str, Any]], *, has_next: bool, cursor: str | None) -> Any:
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
        pages = [
            _page([_thread(body="t1")], has_next=True, cursor="c1"),
            _page([_thread(body="t2")], has_next=True, cursor="c2"),
            _page([_thread(body="t3")], has_next=False, cursor=None),
        ]
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: Any) -> Any:
            calls.append(cmd)
            return pages[len(calls) - 1]

        monkeypatch.setattr(gate.subprocess, "run", fake_run)
        merged = gate.fetch_threads(1, "o/r")
        nodes = gate._thread_nodes(merged)
        assert len(nodes) == 3
        assert len(calls) == 3
        assert any("after=c1" in part for part in calls[1])
        assert any("after=c2" in part for part in calls[2])

    def test_fetch_threads_fails_closed_when_cursor_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        page = _page([_thread(body="t1")], has_next=True, cursor=None)
        monkeypatch.setattr(gate.subprocess, "run", lambda _cmd, **_kw: page)
        with pytest.raises(RuntimeError):
            gate.fetch_threads(1, "o/r")


def test_AC8_20_3_severity_rule_documented_in_ssot() -> None:
    "AC-testing.review-threads.3 AC8.20.3"
    ci_cd = (_REPO_ROOT / "common" / "testing" / "ci-cd.md").read_text(encoding="utf-8")
    section = ci_cd.split("## PR Review Thread Merge Gate", 1)[1].split("\n## ", 1)[0]
    lower = " ".join(section.lower().replace("`", "").split())
    assert f"high = {gate.SEVERITY_WEIGHTS['high'][1]}" in lower
    assert f"middle/medium = {gate.SEVERITY_WEIGHTS['middle'][1]}" in lower
    assert f"low = {gate.SEVERITY_WEIGHTS['low'][1]}" in lower
    assert f"unlabelled = {gate.UNLABELLED_WEIGHT[1]}" in lower
    assert f">= {gate.REVIEW_BLOCK_SCORE}" in lower
    assert "resolved and outdated threads do not count" in lower
    assert "copilot review is optional and non-blocking" in lower
