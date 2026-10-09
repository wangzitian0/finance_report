"""AC-testing.benchmarks.1, AC-testing.benchmarks.2, AC-testing.benchmarks.5: Bench V2 CLI selection, SKIPPED handling, and the case 1 replay switch (#2318)."""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools._lib.benchmarks import run_financial_scenario_benchmark as rb
from tools._lib.benchmarks.case_types import (
    DOMAIN_TO_CASES,
    FLOW_TO_CASES,
    CaseResult,
)


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace every case executor with a recorder.

    `ran` lists the executed case ids in order. `statuses` maps a case id to the
    status its fake executor returns (default PASS).
    """
    ran: list[str] = []
    statuses: dict[str, str] = {}

    def make(case_id: str):
        def _fake(runner: object) -> CaseResult:
            ran.append(case_id)
            return CaseResult(
                case_id=f"case_{case_id}",
                case_name=case_id,
                status=statuses.get(case_id, "PASS"),
                duration_seconds=0.0,
            )

        return _fake

    for number in "123456":
        monkeypatch.setattr(rb, f"execute_case_{number}", make(number))
    monkeypatch.setattr(rb, "execute_case_ui", make("ui"))
    return SimpleNamespace(ran=ran, statuses=statuses)


def _main(tmp_path: Path, *argv: str) -> int:
    return rb.main(
        [
            *argv,
            "--app-url",
            "http://localhost:1",
            "--json-report",
            str(tmp_path / "r.json"),
        ]
    )


def test_default_runs_every_case_and_the_ui_case(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    assert _main(tmp_path) == 0
    assert dispatched.ran == ["1", "2", "3", "4", "5", "6", "ui"]


def test_domain_alone_selects_only_the_cases_of_that_domain(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    assert _main(tmp_path, "--domain", "2") == 0
    assert dispatched.ran == DOMAIN_TO_CASES[2]
    assert dispatched.ran != ["1", "2", "3", "4", "5", "6", "ui"]


def test_flow_alone_selects_the_cases_of_those_flows(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    assert _main(tmp_path, "--flow", "14,23") == 0
    assert dispatched.ran == sorted(set(FLOW_TO_CASES[14]) | set(FLOW_TO_CASES[23]))


def test_explicit_case_and_domain_add_up(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    assert _main(tmp_path, "--case", "1", "--domain", "4") == 0
    assert dispatched.ran == sorted({"1"} | set(DOMAIN_TO_CASES[4]))


def test_case_aliases_select_the_same_cases(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    assert _main(tmp_path, "--case", "case_3,CASE4") == 0
    assert dispatched.ran == ["3", "4"]


def test_verify_ui_adds_the_ui_case_exactly_once(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    assert _main(tmp_path, "--domain", "1", "--verify-ui") == 0
    assert dispatched.ran.count("ui") == 1


@pytest.mark.parametrize(
    "argv",
    [
        ["--case", "1,9"],
        ["--case", "invalid_case_99"],
        ["--domain", "99"],
        ["--domain", "2,x"],
        ["--flow", "31"],
    ],
    ids=[
        "unknown-case-with-valid",
        "unknown-case",
        "unknown-domain",
        "mixed-domain",
        "unknown-flow",
    ],
)
def test_unknown_ids_exit_2_and_run_nothing(
    dispatched: SimpleNamespace,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    assert _main(tmp_path, *argv) == 2
    assert dispatched.ran == []
    assert "Error" in capsys.readouterr().err


def test_a_skipped_case_fails_the_run_unless_allowed(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    dispatched.statuses["ui"] = "SKIPPED"
    assert _main(tmp_path) == 1
    assert _main(tmp_path, "--allow-skip") == 0


def test_a_run_with_only_skipped_cases_never_succeeds(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    dispatched.statuses["ui"] = "SKIPPED"
    assert _main(tmp_path, "--case", "ui", "--allow-skip") == 1


def test_a_failed_case_fails_the_run_even_with_allow_skip(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    dispatched.statuses["3"] = "FAIL"
    assert _main(tmp_path, "--allow-skip") == 1


def test_report_counts_skipped_cases_apart_from_failed_ones(
    dispatched: SimpleNamespace, tmp_path: Path
) -> None:
    dispatched.statuses["ui"] = "SKIPPED"
    _main(tmp_path, "--allow-skip")
    summary = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["summary"]
    assert summary == {
        "total": 7,
        "passed": 6,
        "skipped": 1,
        "failed": 0,
        "success": True,
    }


# ---------------------------------------------------------------- execute_case_ui


def _ui_runner(result: dict | None = None, error: Exception | None = None):
    def verify(**kwargs: object) -> dict:
        if error is not None:
            raise error
        assert result is not None
        return result

    return SimpleNamespace(
        last_auth_context={
            "user_email": "qa@test.example.com",
            "user_data": {"access_token": "tok", "id": "1"},
        },
        verify_browser_ui_hygiene=verify,
    )


def test_case_ui_reports_skipped_and_not_pass() -> None:
    skipped = {"status": "SKIPPED", "reason": "playwright_not_installed"}
    result = rb.execute_case_ui(_ui_runner(skipped))
    assert result.status == "SKIPPED"
    assert result.details["reason"] == "playwright_not_installed"


def test_case_ui_reports_pass_when_the_oracle_passes() -> None:
    result = rb.execute_case_ui(
        _ui_runner({"status": "PASS", "visited_routes": ["/a"]})
    )
    assert result.status == "PASS"


def test_case_ui_reports_fail_when_the_oracle_raises() -> None:
    result = rb.execute_case_ui(_ui_runner(error=AssertionError("boom")))
    assert result.status == "FAIL"
    assert result.error_message == "boom"


# ------------------------------------------------------- case 1 replay switch


class _FakeClient:
    def get(self, url: str) -> SimpleNamespace:
        return SimpleNamespace(
            json=lambda: {
                "account_id": "acc-1",
                "institution": "Standard Chartered Bank",
            }
        )


class _FakeRunner:
    """Records uploads. Parses the statement figures back out of the uploaded CSV."""

    def __init__(self, replay_mode: str) -> None:
        self.replay_mode = replay_mode
        self.uploads: list[str] = []
        self._last = b""

    def upload_statement(
        self,
        client,  # noqa: ANN001
        data,  # noqa: ANN001
        filename,  # noqa: ANN001
        account_id=None,  # noqa: ANN001
        institution=None,  # noqa: ANN001
        currency="SGD",  # noqa: ANN001
    ):
        self.uploads.append(filename)
        self._last = data
        return f"id-{len(self.uploads)}"

    def wait_for_statement_parsed(self, client, statement_id):  # noqa: ANN001
        if self._last.startswith(b"%PDF"):
            return {
                "opening_balance": "15450.75",
                "closing_balance": "15271.23",
                "balance_validated": True,
                "transactions": [],
            }
        rows = list(csv.DictReader(io.StringIO(self._last.decode("utf-8"))))
        return {
            "opening_balance": rows[0]["Statement Opening Balance"],
            "closing_balance": rows[0]["Statement Closing Balance"],
            "balance_validated": True,
            "transactions": rows,
        }

    def adjudicate_unmatched_items(self, client, statement_id):  # noqa: ANN001
        return 0

    def approve_statement(self, client, statement_id):  # noqa: ANN001
        return {"status": "approved"}


def test_case_1_replay_mode_uploads_generated_csv_for_all_four_months(
    tmp_path: Path,
) -> None:
    from tools._lib.benchmarks.cases import case_1

    runner, client = _FakeRunner("replay"), _FakeClient()
    _, m1, account_id, institution = case_1._upload_month1_statement(runner, client)
    case_1._ingest_chained_months(
        runner,
        client,
        tmp_path,
        Decimal(m1["closing_balance"]),
        account_id,
        institution,
    )
    assert runner.uploads == [
        "scb_month1_replay.csv",
        "scb_month2_replay.csv",
        "scb_month3_replay.csv",
        "scb_month4_replay.csv",
    ]


def test_case_1_off_mode_uses_the_pdf_fixture_and_fails_when_it_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tools._lib.benchmarks.cases import case_1

    monkeypatch.setattr(case_1, "REPO_ROOT", tmp_path)
    runner, client = _FakeRunner("off"), _FakeClient()
    with pytest.raises(FileNotFoundError, match="sync_benchmark_fixtures"):
        case_1._upload_month1_statement(runner, client)
    assert runner.uploads == []

    fixture = (
        tmp_path
        / "common/testing/fixtures/benchmarks/bankstatemently/bsb_001_straits_capital.pdf"
    )
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"%PDF-1.4 fake")
    case_1._upload_month1_statement(runner, client)
    assert runner.uploads == ["bsb_001_straits_capital.pdf"]
