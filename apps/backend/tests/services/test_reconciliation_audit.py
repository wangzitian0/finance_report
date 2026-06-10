"""Backend-shard coverage for the reconciliation audit harness."""

from __future__ import annotations

from datetime import date

import pytest

from src.models import AccountType
from src.services import reconciliation_audit as audit


def test_AC4_10_1_backend_reconciliation_audit_writes_reports(tmp_path) -> None:
    """AC4.10.1: Backend coverage owns the reconciliation audit implementation."""
    report = audit.build_report(benchmark_size=3)

    json_path, markdown_path = audit.write_report(report, tmp_path)

    assert json_path.exists()
    assert markdown_path.exists()
    assert report["metadata"]["epic"] == "EPIC-004"
    assert report["targets"]["passed"] is True
    assert report["summary"]["failed"] == 0
    assert "Target gate passed" in markdown_path.read_text(encoding="utf-8")


def test_AC4_10_2_backend_reconciliation_audit_classifies_failure_modes() -> None:
    """AC4.10.2: Audit diagnostics classify false negatives and wrong entries."""
    user_id = audit._stable_uuid("user:backend-failure-modes")
    bank = audit._account(user_id, "Backend Audit Bank", AccountType.ASSET)
    expense = audit._account(user_id, "Backend Audit Expense", AccountType.EXPENSE)
    expected_entry = audit._entry(
        user_id,
        "expected-entry",
        date(2024, 7, 1),
        "Expected vendor payment",
        "25.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    actual_entry = audit._entry(
        user_id,
        "actual-entry",
        date(2024, 7, 1),
        "Expected vendor payment",
        "25.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    matching_txn = audit._txn(
        "wrong_entry_txn",
        date(2024, 7, 1),
        "Expected vendor payment",
        "25.00",
        "OUT",
    )
    missing_txn = audit._txn(
        "missing_txn",
        date(2024, 7, 2),
        "Missing journal entry",
        "35.00",
        "OUT",
    )

    report = audit.build_report(
        scenarios=[
            audit.AuditScenario(
                scenario_id="backend-wrong-entry",
                title="Matching route with unexpected entry id",
                transactions=(matching_txn,),
                entries=(actual_entry,),
                expectations=(
                    audit.AuditExpectation(
                        "wrong_entry_txn",
                        audit.AUTO_ACCEPT,
                        (str(expected_entry.id),),
                    ),
                ),
            ),
            audit.AuditScenario(
                scenario_id="backend-false-negative",
                title="Expected match is absent from journal candidates",
                transactions=(missing_txn,),
                entries=(),
                expectations=(
                    audit.AuditExpectation(
                        "missing_txn",
                        audit.AUTO_ACCEPT,
                        (str(expected_entry.id),),
                    ),
                ),
            ),
        ],
        benchmark_size=1,
    )

    failure_types = {row["failure_type"] for row in report["failures"]}
    assert failure_types == {"wrong_entry", "false_negative"}
    assert report["summary"]["failed"] == 2
    assert report["targets"]["passed"] is False


def test_AC4_10_2_backend_reconciliation_audit_covers_false_positive_and_routing_miss() -> None:
    """AC4.10.2: Audit failures include false-positive and routing-miss diagnostics."""
    user_id = audit._stable_uuid("user:backend-diagnostic-modes")
    bank = audit._account(user_id, "Backend Diagnostic Bank", AccountType.ASSET)
    expense = audit._account(
        user_id,
        "Backend Diagnostic Expense",
        AccountType.EXPENSE,
    )
    entry = audit._entry(
        user_id,
        "diagnostic-entry",
        date(2024, 8, 1),
        "Diagnostic vendor",
        "42.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    txn = audit._txn(
        "diagnostic_txn",
        date(2024, 8, 1),
        "Diagnostic vendor",
        "42.00",
        "OUT",
    )

    report = audit.build_report(
        scenarios=[
            audit.AuditScenario(
                scenario_id="backend-false-positive",
                title="Unexpected auto-accept",
                transactions=(txn,),
                entries=(entry,),
                expectations=(audit.AuditExpectation("diagnostic_txn", audit.UNMATCHED),),
            ),
            audit.AuditScenario(
                scenario_id="backend-routing-miss",
                title="Auto-accept when review was expected",
                transactions=(txn,),
                entries=(entry,),
                expectations=(audit.AuditExpectation("diagnostic_txn", audit.REVIEW),),
            ),
        ],
        benchmark_size=1,
    )

    markdown = audit.render_markdown(report)
    failure_types = {row["failure_type"] for row in report["failures"]}
    assert failure_types == {"false_positive", "routing_miss"}
    assert "## Failures" in markdown
    assert "backend-false-positive" in markdown


def test_AC4_10_3_backend_reconciliation_audit_runtime_target_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4.10.3: Runtime target failures are reported as hard-gate failures."""
    monkeypatch.setattr(
        audit,
        "_run_benchmark",
        lambda config, benchmark_size: {
            "benchmark_size": benchmark_size,
            "runtime_seconds": 11.0,
            "transactions_per_second": 1.0,
            "target_runtime_seconds": 10.0,
            "target_met": False,
            "mode": "deterministic_pair_scoring",
        },
    )

    report = audit.build_report(benchmark_size=1)

    assert report["targets"]["passed"] is False
    assert "runtime" in report["targets"]["failures"]


@pytest.mark.parametrize(
    ("score", "expected_route"),
    [
        (audit.DEFAULT_CONFIG.auto_accept, audit.AUTO_ACCEPT),
        (audit.DEFAULT_CONFIG.pending_review, audit.REVIEW),
        (audit.DEFAULT_CONFIG.pending_review - 1, audit.UNMATCHED),
    ],
)
def test_AC4_10_3_backend_reconciliation_audit_score_route_boundaries(
    score: int,
    expected_route: str,
) -> None:
    """AC4.10.3: Audit scoring boundaries match reconciliation config gates."""
    assert audit._route_for_score(score, audit.DEFAULT_CONFIG) == expected_route


def test_AC4_10_1_backend_reconciliation_audit_cli_stdout_and_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC4.10.1: CLI writes artifacts, prints markdown, and exits from targets."""
    monkeypatch.chdir(tmp_path)

    exit_code = audit.main(
        [
            "--output-dir",
            str(tmp_path / "audit"),
            "--benchmark-size",
            "2",
            "--stdout",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "# Reconciliation Accuracy Audit" in out
    assert (tmp_path / "audit" / "reconciliation-audit.json").exists()


def test_AC4_10_1_backend_reconciliation_audit_cli_returns_nonzero_when_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """AC4.10.1: CLI exit code follows the audit target gate."""
    monkeypatch.setattr(
        audit,
        "_run_benchmark",
        lambda config, benchmark_size: {
            "benchmark_size": benchmark_size,
            "runtime_seconds": 11.0,
            "transactions_per_second": 1.0,
            "target_runtime_seconds": 10.0,
            "target_met": False,
            "mode": "deterministic_pair_scoring",
        },
    )

    assert (
        audit.main(
            [
                "--output-dir",
                str(tmp_path / "audit"),
                "--benchmark-size",
                "1",
            ]
        )
        == 1
    )


def test_AC4_10_1_backend_reconciliation_audit_entry_refs_are_stable() -> None:
    """AC4.10.1: Audit entry refs stay deterministic for stable report diffs."""
    user_id = audit._stable_uuid("user:entry-refs")
    bank = audit._account(user_id, "Entry Ref Bank", AccountType.ASSET)
    expense = audit._account(user_id, "Entry Ref Expense", AccountType.EXPENSE)
    entry = audit._entry(
        user_id,
        "entry-ref",
        date(2024, 9, 1),
        "Entry ref memo",
        "9.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )

    assert audit._entry_refs((entry,)) == {str(entry.id): str(entry.id)}
