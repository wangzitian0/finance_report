from __future__ import annotations

import json
import shlex
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from tests.benchmarks import pdf_corpus_oracle as oracle_mod


def test_pdf_corpus_oracle_offline_and_invalid_cli_args(tmp_path: Path) -> None:
    assert oracle_mod.main(["--max-workers", "0"]) == 2
    assert oracle_mod.main(["--fixture", "does_not_exist"]) == 2
    assert oracle_mod.main(["--app-url", "  "]) == 2

    report_path = tmp_path / "pdf_corpus_oracle.json"
    summary_path = tmp_path / "pdf_corpus_oracle_summary.json"
    rc = oracle_mod.main(
        [
            "--fixture",
            "bsb_001_straits_capital",
            "--json-report",
            str(report_path),
            "--output-summary",
            str(summary_path),
        ]
    )
    assert rc == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert report["suite"] == "pdf_corpus_oracle"
    assert report["mode"] == "offline"
    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1
    assert report["summary"]["failed"] == 0
    assert report["summary"]["success"] is True
    assert summary["status"] == "PASS"
    assert summary["fixtures_total"] == 1
    assert summary["fixtures_passed"] == 1
    assert summary["fixtures_failed"] == 0
    assert summary["failures_by_fixture"] == {}


def test_pdf_corpus_oracle_live_does_not_short_circuit_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
    seen_specs: list[str] = []

    class _FakeClient:
        def __init__(self, **_kw: Any) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self) -> _FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, path: str, *, json: dict[str, Any]) -> Any:
            if path == "/api/auth/register" and "bsb_001_straits_capital" in json["display_name"]:
                return SimpleNamespace(status_code=500, text="register boom")
            return SimpleNamespace(status_code=201, json=lambda: {"access_token": "tok"})

    def _fake_verify(client: Any, spec: oracle_mod.CorpusStatementSpec, **_kw: Any) -> dict[str, Any]:
        assert client.headers["Authorization"] == "Bearer tok"
        seen_specs.append(spec.fixture_id)
        return {
            "fixture_id": spec.fixture_id,
            "statement_id": "stmt-2",
            "delete_status": 204,
            "comparison": {
                "passed": True,
                "invariants": [],
                "failures": [],
            },
        }

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    monkeypatch.setattr(oracle_mod, "run_live_pdf_statement_verification", _fake_verify)

    report_path = tmp_path / "live_report.json"
    summary_path = tmp_path / "live_summary.json"
    rc = oracle_mod.main(
        [
            "--app-url",
            "http://127.0.0.1:8000",
            "--fixture",
            "bsb_001_straits_capital",
            "--fixture",
            "dbs_statement_fixture",
            "--max-workers",
            "1",
            "--json-report",
            str(report_path),
            "--output-summary",
            str(summary_path),
        ]
    )
    assert rc == 1
    assert seen_specs == ["dbs_statement_fixture"]

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert [r["fixture_id"] for r in report["results"]] == [
        "bsb_001_straits_capital",
        "dbs_statement_fixture",
    ]
    assert report["results"][0]["status"] == "FAIL"
    assert "500" in (report["results"][0]["error_message"] or "")
    assert report["results"][1]["status"] == "PASS"
    assert summary["status"] == "FAIL"
    assert summary["fixtures_total"] == 2
    assert summary["fixtures_passed"] == 1
    assert summary["fixtures_failed"] == 1
    assert list(summary["failures_by_fixture"]) == ["bsb_001_straits_capital"]


def test_pdf_corpus_oracle_max_workers_runs_concurrently_with_isolated_clients(
    tmp_path: Path, monkeypatch
) -> None:
    barrier = threading.Barrier(2, timeout=2.0)
    client_ids: dict[str, int] = {}
    auth_headers: dict[str, str] = {}

    class _ConcurrentClient:
        def __init__(self, **_kw: Any) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self) -> _ConcurrentClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, path: str, *, json: dict[str, Any]) -> Any:
            return SimpleNamespace(
                status_code=201,
                json=lambda: {"access_token": f"tok-{json['display_name']}"},
            )

    def _concurrent_verify(
        client: Any, spec: oracle_mod.CorpusStatementSpec, **_kw: Any
    ) -> dict[str, Any]:
        client_ids[spec.fixture_id] = id(client)
        auth_headers[spec.fixture_id] = client.headers["Authorization"]
        barrier.wait()
        return {
            "fixture_id": spec.fixture_id,
            "statement_id": f"stmt-{spec.fixture_id}",
            "delete_status": 204,
            "comparison": {"passed": True, "invariants": [], "failures": []},
        }

    monkeypatch.setattr(httpx, "Client", _ConcurrentClient)
    monkeypatch.setattr(oracle_mod, "run_live_pdf_statement_verification", _concurrent_verify)

    report_path = tmp_path / "parallel.json"
    rc = oracle_mod.main(
        [
            "--app-url",
            "http://127.0.0.1:8000",
            "--fixture",
            "dbs_statement_fixture",
            "--fixture",
            "bsb_001_straits_capital",
            "--max-workers",
            "2",
            "--json-report",
            str(report_path),
        ]
    )
    assert rc == 0
    assert len(set(client_ids.values())) == 2
    assert len(set(auth_headers.values())) == 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # Preserves manifest selection order even when executing concurrently
    assert [r["fixture_id"] for r in report["results"]] == [
        "bsb_001_straits_capital",
        "dbs_statement_fixture",
    ]


def test_scheduled_audit_json_report_args_parse_cleanly() -> None:
    manifest = oracle_mod.yaml.safe_load(
        (oracle_mod.REPO_ROOT / "runtime-hooks.manifest.json").read_text(encoding="utf-8")
    )
    by_id = {c["id"]: c for c in manifest["checks"]}
    cmd_str = by_id["pdf_corpus_oracle"]["argv"][2]
    oracle_cmd = cmd_str.split("&&", 1)[1]
    tokens = shlex.split(oracle_cmd)
    assert tokens[:3] == ["python", "-m", "tests.benchmarks.pdf_corpus_oracle"]
    json_idx = tokens.index("--json-report")
    sum_idx = tokens.index("--output-summary")
    assert tokens[json_idx + 1].endswith("pdf_corpus_oracle.json")
    assert tokens[sum_idx + 1].endswith("pdf_corpus_oracle_summary.json")
