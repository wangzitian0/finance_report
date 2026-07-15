"""Behavioral locks for the first shared-infrastructure slice of #1867."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

import pytest

from common.meta.extension.ac_registry_format import sort_key
from common.runtime import (
    github_api,
    release_coordinate,
    release_evidence,
    release_images,
)
from common.runtime import wait_post_merge_train_turn as train_wait
from common.testing import (
    ac_scan,
    ac_score_baseline_format,
    cassette_eval_baseline,
    jsonl_baseline,
)
from common.testing import analyze_test_ac_coverage as coverage_analysis
from common.testing import build_ac_traceability, check_ac_traceability
from common.testing import wait_for_cheap_ci


def test_AC_testing_governance_14_jsonl_baseline_bindings_share_parameterized_behavior(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.14: both legacy bindings retain canonical JSONL and floors."""

    ac_payload = {
        "version": 1,
        "acs": {"AC-testing.governance.14": {"score": 0.8, "metric": "m"}},
    }
    case_payload = {
        "version": 1,
        "cases": {"synthetic-case": {"score": 0.7, "metric": "field-accuracy"}},
    }

    for module, payload, key in (
        (ac_score_baseline_format, ac_payload, "acs"),
        (cassette_eval_baseline, case_payload, "cases"),
    ):
        path = tmp_path / f"{key}.jsonl"
        module.write_jsonl(path, payload)
        loaded = module.load_jsonl(path)
        record = next(iter(loaded[key].values()))
        assert record["score"] == next(iter(payload[key].values()))["score"]
        assert record["metric"] == next(iter(payload[key].values()))["metric"]
        assert record["provenance"] == ""

    lowered = jsonl_baseline.ratcheted_raise_only_merge(
        ac_payload,
        {"version": 1, "acs": {"AC-testing.governance.14": {"score": 0.5}}},
        collection_key="acs",
    )
    assert lowered["acs"]["AC-testing.governance.14"]["score"] == 0.8

    raised = jsonl_baseline.ratcheted_raise_only_merge(
        case_payload,
        {"version": 1, "cases": {"synthetic-case": {"score": 0.9}}},
        collection_key="cases",
        default_metric="field-accuracy",
    )
    assert raised["cases"]["synthetic-case"] == {
        "score": 0.9,
        "metric": "field-accuracy",
        "provenance": "",
    }

    assert (
        jsonl_baseline.render_jsonl(
            {"acs": []}, identifier_key="ac_id", collection_key="acs"
        )
        == ""
    )
    path = tmp_path / "nested" / "normalize.jsonl"
    path.parent.mkdir()
    path.write_text('{"ac_id":"z"}\n\n{"ac_id":"a"}\n', encoding="utf-8")
    normalized = jsonl_baseline.normalize_file(
        path, identifier_key="ac_id", collection_key="acs"
    )
    assert list(normalized["acs"]) == ["z", "a"]
    assert path.read_text(encoding="utf-8").startswith('{"ac_id": "a"')

    for invalid, message in (
        ("not-json\n", "invalid JSONL"),
        ('{"other":"x"}\n', "'ac_id'"),
        ('{"ac_id":"x"}\n{"ac_id":"x"}\n', "duplicate ac_id"),
    ):
        path.write_text(invalid, encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            jsonl_baseline.load_jsonl(
                path, identifier_key="ac_id", collection_key="acs"
            )

    assert jsonl_baseline.ratcheted_raise_only_merge(
        {"acs": []}, {"acs": {"ignored": "not-a-record"}}, collection_key="acs"
    ) == {"version": 1, "acs": {}}


def test_AC_testing_governance_15_traceability_tools_share_scanner_and_canonical_sort(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.15: all tools share discovery and preserve package IDs."""

    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    source = test_dir / "test_references.py"
    source.write_text(
        "def test_reference():\n    assert 'AC-audit.36.1' != 'AC-ledger.36.1'\n",
        encoding="utf-8",
    )

    discovered = ac_scan.find_test_files([test_dir])
    assert discovered == [source]
    assert build_ac_traceability.find_test_files is ac_scan.find_test_files
    assert check_ac_traceability.find_test_files is ac_scan.find_test_files

    references = ac_scan.collect_references(discovered)
    assert set(references) == {"AC-audit.36.1", "AC-ledger.36.1"}
    assert sort_key("AC-audit.36.1") != sort_key("AC-ledger.36.1")
    assert coverage_analysis.ac_scan is ac_scan


def test_AC_runtime_github_api_1_runtime_and_testing_share_github_helpers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-runtime.github-api.1: clients, UTC parsing, and output writing remain shared."""

    assert train_wait.GitHubActionsClient is github_api.GitHubActionsClient
    assert wait_for_cheap_ci.GitHubActionsClient is github_api.GitHubActionsClient
    assert train_wait.parse_github_time is github_api.parse_github_time
    assert release_evidence._write_github_output is github_api.write_github_output
    assert release_images._write_github_output is github_api.write_github_output
    assert release_coordinate.write_github_output is github_api.write_github_output

    assert github_api.parse_github_time("2026-07-15T12:00:00Z") == datetime(
        2026, 7, 15, 12, tzinfo=UTC
    )
    assert github_api.parse_github_time(None) is None

    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    github_api.write_github_output({"run_id": "123", "status": "success"})
    assert output.read_text(encoding="utf-8") == "run_id=123\nstatus=success\n"

    requests: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
        assert timeout == 20
        url = request.full_url  # type: ignore[attr-defined]
        requests.append(url)
        if "/jobs" in url:
            return FakeResponse({"jobs": [{"id": 2}]})
        if "/actions/runs/42" in url:
            return FakeResponse({"id": 42})
        if "workflows/5/runs" in url and "&page=1" in url:
            return FakeResponse(
                {"workflow_runs": [{"id": number} for number in range(100)]}
            )
        if "workflows/5/runs" in url:
            return FakeResponse({"workflow_runs": []})
        return FakeResponse({"workflow_runs": [{"id": 1}]})

    monkeypatch.setattr(github_api.urllib.request, "urlopen", fake_urlopen)
    client = github_api.GitHubActionsClient(repository="owner/repo", token="secret")
    assert client.get_workflow_runs("abc") == [{"id": 1}]
    assert client.get_run_jobs(42) == [{"id": 2}]
    assert client.get_run_payload(42) == {"id": 42}
    assert len(client.list_workflow_runs(5)) == 100
    assert any("head_sha=abc" in url for url in requests)

    def raise_http_error(_request: object, *, timeout: int) -> FakeResponse:
        raise urllib.error.HTTPError(
            "https://api.github.com/example",
            401,
            "unauthorized",
            {},
            io.BytesIO(b"denied"),
        )

    monkeypatch.setattr(github_api.urllib.request, "urlopen", raise_http_error)
    with pytest.raises(RuntimeError, match="GitHub API HTTP 401"):
        client.get_workflow_runs("abc")
