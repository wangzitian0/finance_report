from __future__ import annotations

from datetime import date

import pytest

from src.ledger import AccountType
from src.reconciliation.extension import reconciliation_audit as audit


def test_AC4_10_1_backend_reconciliation_audit_writes_reports(tmp_path) -> None:
    report = audit.build_report(benchmark_size=3)
    json_path, markdown_path = audit.write_report(report, tmp_path)
    assert json_path.exists() and markdown_path.exists()
    assert (report["metadata"]["epic"], report["targets"]["passed"], report["summary"]["failed"]) == (
        "EPIC-004",
        True,
        0,
    )
    assert "Target gate passed" in markdown_path.read_text(encoding="utf-8")


def test_AC4_10_2_backend_reconciliation_audit_classifies_failure_modes() -> None:
    uid = audit._stable_uuid("user:backend-failure-modes")
    bank = audit._account(uid, "Backend Audit Bank", AccountType.ASSET)
    expense = audit._account(uid, "Backend Audit Expense", AccountType.EXPENSE)
    exp_entry = audit._entry(
        uid,
        "expected-entry",
        date(2024, 7, 1),
        "Expected vendor payment",
        "25.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    act_entry = audit._entry(
        uid,
        "actual-entry",
        date(2024, 7, 1),
        "Expected vendor payment",
        "25.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    matching_txn = audit._txn("wrong_entry_txn", date(2024, 7, 1), "Expected vendor payment", "25.00", "OUT")
    missing_txn = audit._txn("missing_txn", date(2024, 7, 2), "Missing journal entry", "35.00", "OUT")
    r1 = audit.build_report(
        scenarios=[
            audit.AuditScenario(
                "backend-wrong-entry",
                "Unexpected entry id",
                (matching_txn,),
                (act_entry,),
                (audit.AuditExpectation("wrong_entry_txn", audit.AUTO_ACCEPT, (str(exp_entry.id),)),),
            ),
            audit.AuditScenario(
                "backend-false-negative",
                "Absent candidate",
                (missing_txn,),
                (),
                (audit.AuditExpectation("missing_txn", audit.AUTO_ACCEPT, (str(exp_entry.id),)),),
            ),
        ],
        benchmark_size=1,
    )
    assert (
        {r["failure_type"] for r in r1["failures"]} == {"wrong_entry", "false_negative"}
        and r1["summary"]["failed"] == 2
        and not r1["targets"]["passed"]
    )

    diag_entry = audit._entry(
        uid,
        "diagnostic-entry",
        date(2024, 8, 1),
        "Diagnostic vendor",
        "42.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    diag_txn = audit._txn("diagnostic_txn", date(2024, 8, 1), "Diagnostic vendor", "42.00", "OUT")
    r2 = audit.build_report(
        scenarios=[
            audit.AuditScenario(
                "backend-false-positive",
                "Unexpected auto-accept",
                (diag_txn,),
                (diag_entry,),
                (audit.AuditExpectation("diagnostic_txn", audit.UNMATCHED),),
            ),
            audit.AuditScenario(
                "backend-routing-miss",
                "Expected review",
                (diag_txn,),
                (diag_entry,),
                (audit.AuditExpectation("diagnostic_txn", audit.REVIEW),),
            ),
        ],
        benchmark_size=1,
    )
    md = audit.render_markdown(r2)
    assert {r["failure_type"] for r in r2["failures"]} == {"false_positive", "routing_miss"}
    assert "## Failures" in md and "backend-false-positive" in md
    assert audit._entry_refs((diag_entry,)) == {str(diag_entry.id): str(diag_entry.id)}


@pytest.mark.parametrize(
    ("score", "expected_route"),
    [
        (audit.DEFAULT_CONFIG.auto_accept, audit.AUTO_ACCEPT),
        (audit.DEFAULT_CONFIG.pending_review, audit.REVIEW),
        (audit.DEFAULT_CONFIG.pending_review - 1, audit.UNMATCHED),
    ],
)
def test_AC4_10_3_backend_reconciliation_audit_score_route_boundaries(score: int, expected_route: str) -> None:
    assert audit._route_for_score(score, audit.DEFAULT_CONFIG) == expected_route


def test_AC4_10_1_and_3_cli_and_runtime_target_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "audit"
    assert audit.main(["--output-dir", str(out_dir), "--benchmark-size", "2", "--stdout"]) == 0
    assert (
        "# Reconciliation Accuracy Audit" in capsys.readouterr().out
        and (out_dir / "reconciliation-audit.json").exists()
    )

    monkeypatch.setattr(
        audit,
        "_run_benchmark",
        lambda cfg, sz: {
            "benchmark_size": sz,
            "runtime_seconds": 11.0,
            "transactions_per_second": 1.0,
            "target_runtime_seconds": 10.0,
            "target_met": False,
            "mode": "deterministic_pair_scoring",
        },
    )
    report = audit.build_report(benchmark_size=1)
    assert report["targets"]["passed"] is False and "runtime" in report["targets"]["failures"]
    assert audit.main(["--output-dir", str(out_dir), "--benchmark-size", "1"]) == 1
