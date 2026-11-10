'AC8.20.1 AC8.20.2 AC8.20.3 EPIC-008'; from __future__ import annotations; import json; from pathlib import Path; from typing import Any; import pytest; from common.testing import check_pr_review_threads as gate; _REPO_ROOT = Path(__file__).resolve().parents[2]; _thread = lambda *, is_resolved=False, is_outdated=False, author='some-human', body='please fix this', url='https://github.com/o/r/pull/1#discussion_r1': {'isResolved': is_resolved, 'isOutdated': is_outdated, 'comments': {'nodes': [{'author': {'login': author}, 'body': body, 'url': url}]}}; _payload = lambda *threads: {'data': {'repository': {'pullRequest': {'reviewThreads': {'nodes': list(threads)}}}}}; _run = lambda payload: gate.run(pr_number=1, repo='o/r', fetch_threads=lambda pr_number, repo: payload)
class TestClassifyThread:
    def test_explicit_p0_marker_is_blocking(self) -> None: thread = _thread(body='P0: this corrupts balances'); assert gate.classify_thread(thread) == gate.Severity.BLOCKING; _m1_thread = _thread(body='this is a P1 problem'); assert gate.classify_thread(_m1_thread) == gate.Severity.BLOCKING; _m2_thread = _thread(body='p1 regression'); assert gate.classify_thread(_m2_thread) == gate.Severity.BLOCKING; _m3_thread = _thread(author='copilot-pull-request-reviewer[bot]', body='suggestion'); assert gate.classify_thread(_m3_thread) == gate.Severity.BLOCKING
    def test_copilot_thread_real_login_without_bot_suffix_is_blocking(self) -> None: 'AC-testing.review-threads.4'; thread = _thread(author='copilot-pull-request-reviewer', body='suggestion'); assert gate.classify_thread(thread) == gate.Severity.BLOCKING; _m4_thread = _thread(author='github-copilot[bot]', body='consider this'); assert gate.classify_thread(_m4_thread) == gate.Severity.BLOCKING; _m5_thread = _thread(author='copilot-pull-request-reviewer[bot]', body='nit: rename var'); assert gate.classify_thread(_m5_thread) == gate.Severity.LOWER; _m6_thread = _thread(author='copilot-pull-request-reviewer[bot]', body='P2: minor style'); assert gate.classify_thread(_m6_thread) == gate.Severity.LOWER; _m7_thread = _thread(body='nit: tiny wording'); assert gate.classify_thread(_m7_thread) == gate.Severity.LOWER; _m8_thread = _thread(body='what do you think about this?'); assert gate.classify_thread(_m8_thread) == gate.Severity.LOWER
class TestBlocking:
    def test_AC8_20_1_unresolved_p0_blocks(self) -> None: 'AC-testing.review-threads.1 AC8.20.1'; payload = _payload(_thread(body='P0: must fix', is_resolved=False)); assert _run(payload) == 1; 'AC8.20.1'; 'AC8.20.1'; _m1_payload = _payload(_thread(author='copilot-pull-request-reviewer[bot]', is_resolved=False)); assert _run(_m1_payload) == 1
    def test_AC8_20_1_blocking_thread_url_is_printed(self, capsys: pytest.CaptureFixture[str]) -> None: 'AC8.20.1'; url = 'https://github.com/o/r/pull/1#discussion_r999'; payload = _payload(_thread(body='P1: bug', url=url, is_resolved=False)); assert _run(payload) == 1; captured = capsys.readouterr(); assert url in captured.out + captured.err
class TestNonBlocking:
    def test_AC8_20_2_resolved_p0_passes(self) -> None: 'AC-testing.review-threads.2 AC8.20.2'; payload = _payload(_thread(body='P0: was fixed', is_resolved=True)); assert _run(payload) == 0; 'AC8.20.2'; 'AC8.20.2'; _m1_payload = _payload(_thread(body='P0: stale', is_resolved=False, is_outdated=True)); assert _run(_m1_payload) == 0; 'AC8.20.2'; 'AC8.20.2'; assert _run(_payload()) == 0; _m3_payload = _payload(_thread(body='P0: fixed', is_resolved=True), _thread(body='nit: trivial', is_resolved=False)); assert _run(_m3_payload) == 0
    def test_AC8_20_2_unresolved_nit_passes_but_reported(self, capsys: pytest.CaptureFixture[str]) -> None: 'AC8.20.2'; payload = _payload(_thread(body='nit: rename', is_resolved=False)); assert _run(payload) == 0; captured = capsys.readouterr(); assert 'nit' in (captured.out + captured.err).lower()
class TestSeamAndSafety:
    def test_run_uses_injected_fetcher_without_network(self) -> None:
        calls: list[tuple[int, str]] = []
        def fake_fetch(pr_number: int, repo: str) -> dict[str, Any]: calls.append((pr_number, repo)); return _payload()
        assert gate.run(pr_number=7, repo='o/r', fetch_threads=fake_fetch) == 0; assert calls == [(7, 'o/r')]
    def test_run_skips_cleanly_when_pr_number_missing(self) -> None:
        sentinel_called = False
        def fetch(pr_number: int, repo: str) -> dict[str, Any]: nonlocal sentinel_called; sentinel_called = True; return _payload()
        assert gate.run(pr_number=None, repo='o/r', fetch_threads=fetch) == 0; assert sentinel_called is False
class TestMain:
    def test_main_skips_without_pr_number(self, monkeypatch: pytest.MonkeyPatch) -> None: monkeypatch.delenv('PR_NUMBER', raising=False); assert gate.main(['--repo', 'o/r']) == 0
    def test_main_blocks_with_injected_blocking_thread(self, monkeypatch: pytest.MonkeyPatch) -> None: payload = _payload(_thread(body='P0: bug', is_resolved=False)); monkeypatch.setattr(gate, 'fetch_threads', lambda pr_number, repo: payload); assert gate.main(['--repo', 'o/r', '--pr-number', '1']) == 1
    def test_main_fails_closed_when_pr_present_but_repo_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv('GITHUB_REPOSITORY', raising=False); called = False
        def fetch(pr_number: int, repo: str) -> dict[str, Any]: nonlocal called; called = True; return _payload()
        monkeypatch.setattr(gate, 'fetch_threads', fetch); assert gate.main(['--pr-number', '1']) == 1; assert called is False
def _page(nodes: list[dict[str, Any]], *, has_next: bool, cursor: str | None) -> Any:
    class _Result: stdout = json.dumps({'data': {'repository': {'pullRequest': {'reviewThreads': {'pageInfo': {'hasNextPage': has_next, 'endCursor': cursor}, 'nodes': nodes}}}}})
    return _Result()
class TestFetchPagination:
    def test_fetch_threads_follows_all_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pages = [_page([_thread(body='t1')], has_next=True, cursor='c1'), _page([_thread(body='t2')], has_next=True, cursor='c2'), _page([_thread(body='t3')], has_next=False, cursor=None)]; calls: list[list[str]] = []
        def fake_run(cmd: list[str], **kwargs: Any) -> Any: calls.append(cmd); return pages[len(calls) - 1]
        monkeypatch.setattr(gate.subprocess, 'run', fake_run); merged = gate.fetch_threads(1, 'o/r'); nodes = gate._thread_nodes(merged); assert len(nodes) == 3; assert len(calls) == 3; assert any(('after=c1' in part for part in calls[1])); assert any(('after=c2' in part for part in calls[2]))
    def test_fetch_threads_fails_closed_when_cursor_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _page([_thread(body='t1')], has_next=True, cursor=None); monkeypatch.setattr(gate.subprocess, 'run', lambda cmd, **kw: page)
        with pytest.raises(RuntimeError): gate.fetch_threads(1, 'o/r')
def test_AC8_20_3_severity_rule_documented_in_ssot() -> None: 'AC-testing.review-threads.3 AC8.20.3'; ci_cd = (_REPO_ROOT / 'common' / 'testing' / 'ci-cd.md').read_text(encoding='utf-8'); assert 'PR Review Thread Merge Gate' in ci_cd; assert '\\b(P0|P1)\\b' in ci_cd; assert 'copilot-pull-request-reviewer[bot]' in ci_cd; assert 'outdated' in ci_cd.lower(); assert 'do **not** block' in ci_cd or 'do not block' in ci_cd
