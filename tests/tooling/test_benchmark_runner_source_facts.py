"""AC-testing.benchmarks.11 and AC-testing.benchmarks.12: the Bench V2 runner states only what it read (#2484).

Each test fails on the earlier behavior or guards against fixing it too far:
- The review envelope used an invented period and zero balances when the parsed statement had none.
- A failed review lookup and a rejected envelope ended as a misleading "Approval failed ... 400".
- A manifest entry without a SHA-256 passed the fixture check, and the download step wrote its bytes
  and printed "Verified".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools._lib.benchmarks import sync_benchmark_fixtures as sync
from tools._lib.benchmarks.run_financial_scenario_benchmark import (
    ScenarioBenchmarkRunner,
)

# ------------------------------------------------------------ approve_statement


class _Resp:
    def __init__(self, status_code: int, body: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text

    def json(self) -> Any:
        return self._body


class _ApprovalClient:
    """The first approve asks for a human confirmation. The envelope call unlocks it."""

    def __init__(
        self,
        statement: dict[str, Any],
        review_status: int = 200,
        envelope_status: int = 200,
        needs_confirmation: bool = True,
    ) -> None:
        self.statement = statement
        self.review_status = review_status
        self.envelope_status = envelope_status
        self.needs_confirmation = needs_confirmation
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.confirmed = False

    def get(self, url: str) -> _Resp:
        if url.endswith("/review"):
            return _Resp(
                self.review_status,
                {"source_result_digest": "digest-1", "account_id": "acc-1"},
                "review text",
            )
        return _Resp(200, self.statement)

    def post(self, url: str, json: dict[str, Any]) -> _Resp:
        self.posts.append((url, json))
        if url.endswith("/review/envelope"):
            self.confirmed = self.envelope_status in (200, 201)
            return _Resp(self.envelope_status, {}, "envelope text")
        if self.confirmed or not self.needs_confirmation:
            return _Resp(200, {"status": "approved"})
        return _Resp(
            400, {}, "Statement requires explicit human confirmation before posting"
        )


def _statement(**overrides: Any) -> dict[str, Any]:
    base = {
        "period_start": "2026-02-01",
        "period_end": "2026-02-28",
        "opening_balance": "1000.00",
        "closing_balance": "1250.50",
        "currency": "SGD",
    }
    return {**base, **overrides}


def _runner() -> ScenarioBenchmarkRunner:
    return ScenarioBenchmarkRunner(base_url="http://localhost:1")


def _envelope_posts(client: _ApprovalClient) -> list[dict[str, Any]]:
    return [body for url, body in client.posts if url.endswith("/review/envelope")]


def _approve_posts(client: _ApprovalClient) -> int:
    return sum(url.endswith("/review/approve") for url, _ in client.posts)


def test_AC_testing_benchmarks_11_the_envelope_states_the_facts_of_the_parsed_statement() -> (
    None
):
    client = _ApprovalClient(_statement())

    result = _runner().approve_statement(client, "s-1")  # type: ignore[arg-type]

    assert result == {"status": "approved"}
    assert _envelope_posts(client) == [
        {
            "source_result_digest": "digest-1",
            "account_id": "acc-1",
            "currency": "SGD",
            "period_start": "2026-02-01",
            "period_end": "2026-02-28",
            "opening_balance": "1000.00",
            "closing_balance": "1250.50",
            "rationale": "Benchmark automated review envelope confirmation",
        }
    ]
    assert _approve_posts(client) == 2


def test_AC_testing_benchmarks_11_a_zero_balance_is_a_fact_and_not_a_missing_value() -> (
    None
):
    client = _ApprovalClient(_statement(opening_balance="0.00", closing_balance=0))

    _runner().approve_statement(client, "s-1")  # type: ignore[arg-type]

    envelope = _envelope_posts(client)[0]
    assert envelope["opening_balance"] == "0.00"
    assert envelope["closing_balance"] == "0"


@pytest.mark.parametrize(
    "key",
    ["period_start", "period_end", "opening_balance", "closing_balance", "currency"],
)
@pytest.mark.parametrize("empty", [None, ""], ids=["none", "empty"])
def test_AC_testing_benchmarks_11_a_missing_statement_fact_is_never_replaced_by_a_default(
    key: str, empty: object
) -> None:
    client = _ApprovalClient(_statement(**{key: empty}))

    with pytest.raises(RuntimeError, match=rf"has no .*{key}"):
        _runner().approve_statement(client, "s-1")  # type: ignore[arg-type]

    assert _envelope_posts(client) == []


def test_AC_testing_benchmarks_11_every_missing_fact_is_named() -> None:
    client = _ApprovalClient(_statement(period_start=None, closing_balance=None))

    with pytest.raises(RuntimeError) as error:
        _runner().approve_statement(client, "s-1")  # type: ignore[arg-type]

    assert "period_start" in str(error.value)
    assert "closing_balance" in str(error.value)


def test_AC_testing_benchmarks_11_a_failed_review_lookup_is_reported_with_its_status() -> (
    None
):
    client = _ApprovalClient(_statement(), review_status=500)

    with pytest.raises(RuntimeError, match="Review lookup failed .* 500 review text"):
        _runner().approve_statement(client, "s-1")  # type: ignore[arg-type]

    assert _envelope_posts(client) == []


def test_AC_testing_benchmarks_11_a_rejected_envelope_is_reported_and_not_approved_again() -> (
    None
):
    client = _ApprovalClient(_statement(), envelope_status=422)

    with pytest.raises(
        RuntimeError, match="Review envelope confirmation failed .* 422 envelope text"
    ):
        _runner().approve_statement(client, "s-1")  # type: ignore[arg-type]

    assert _approve_posts(client) == 1


def test_AC_testing_benchmarks_11_a_statement_that_needs_no_confirmation_posts_no_envelope() -> (
    None
):
    client = _ApprovalClient(_statement(), needs_confirmation=False)

    result = _runner().approve_statement(client, "s-1")  # type: ignore[arg-type]

    assert result == {"status": "approved"}
    assert _envelope_posts(client) == []
    assert _approve_posts(client) == 1


# ------------------------------------------------------------------ fixtures


class _Download:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code


class _DownloadClient:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.urls: list[str] = []

    def get(self, url: str) -> _Download:
        self.urls.append(url)
        return _Download(self.content)


def _fixture(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "a",
        "local_path": "a.csv",
        "download_url": "https://example.invalid/a.csv",
        **overrides,
    }


def test_AC_testing_benchmarks_12_a_manifest_entry_without_a_hash_fails_verification(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.csv").write_bytes(b"data")

    ok, message = sync.verify_fixture({"local_path": "a.csv"}, tmp_path)

    assert ok is False
    assert message == "Manifest has no sha256 for a.csv"


def test_AC_testing_benchmarks_12_a_hash_that_matches_the_bytes_passes_and_another_fails(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.csv").write_bytes(b"data")
    good = sync.compute_sha256(b"data")

    assert sync.verify_fixture({"local_path": "a.csv", "sha256": good}, tmp_path)[0]
    ok, message = sync.verify_fixture(
        {"local_path": "a.csv", "sha256": "0" * 64}, tmp_path
    )
    assert ok is False
    assert "SHA-256 mismatch" in message


def test_AC_testing_benchmarks_12_the_download_of_a_fixture_without_a_hash_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _DownloadClient(b"data")

    saved = sync.download_fixture(client, _fixture(), tmp_path)  # type: ignore[arg-type]

    out = capsys.readouterr().out
    assert saved is False
    assert not (tmp_path / "a.csv").exists()
    assert client.urls == []
    assert "Manifest has no sha256 for a.csv" in out
    assert "Verified" not in out


def test_AC_testing_benchmarks_12_the_download_of_a_fixture_with_a_wrong_hash_writes_nothing(
    tmp_path: Path,
) -> None:
    client = _DownloadClient(b"data")

    saved = sync.download_fixture(client, _fixture(sha256="0" * 64), tmp_path)  # type: ignore[arg-type]

    assert saved is False
    assert not (tmp_path / "a.csv").exists()


def test_AC_testing_benchmarks_12_the_download_of_a_fixture_with_the_right_hash_is_written(
    tmp_path: Path,
) -> None:
    client = _DownloadClient(b"data")

    saved = sync.download_fixture(
        client,  # type: ignore[arg-type]
        _fixture(sha256=sync.compute_sha256(b"data")),
        tmp_path,
    )

    assert saved is True
    assert (tmp_path / "a.csv").read_bytes() == b"data"
