"""Tests for the EPIC-004 reconciliation audit harness."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import src.models._registry  # noqa: E402, F401  -- register all ORM mappers before relationship config
from src.models.account import AccountType  # noqa: E402
from src.services.reconciliation_audit import (  # noqa: E402
    AUTO_ACCEPT,
    UNMATCHED,
    AuditExpectation,
    AuditScenario,
    _account,
    _entry,
    _txn,
    build_report,
    render_markdown,
    write_report,
)


def test_AC4_10_1_reconciliation_audit_report_schema_and_outputs(tmp_path: Path) -> None:
    """AC4.10.1: Reconciliation audit harness emits JSON and Markdown reports."""
    report = build_report(benchmark_size=100)
    json_path, md_path = write_report(report, tmp_path)

    payload = json.loads(json_path.read_text())
    markdown = md_path.read_text()

    assert payload["metadata"]["issue"] == "#665"
    assert payload["metadata"]["epic"] == "EPIC-004"
    assert payload["metadata"]["macro_outcome"] == "source-ledger-report-traceability"
    assert payload["summary"]["total_expectations"] >= 100
    assert "accuracy_pct" in payload["summary"]
    assert "false_positive_rate_pct" in payload["summary"]
    assert payload["targets"]["passed"] is True
    assert payload["targets"]["failures"] == []
    assert payload["benchmark"]["benchmark_size"] == 100
    assert payload["benchmark"]["mode"] == "deterministic_pair_scoring"
    assert "# Reconciliation Accuracy Audit" in markdown
    assert "Target gate passed" in markdown


def test_AC4_10_2_reconciliation_audit_reports_intentional_false_positive() -> None:
    """AC4.10.2: Audit diagnostics identify false positives and wrong auto-accepts."""
    user_id = _txn("diagnostic_seed", date(2024, 1, 1), "seed", "1.00", "OUT").id
    bank = _account(user_id, "Diagnostic Bank", AccountType.ASSET)
    expense = _account(user_id, "Diagnostic Expense", AccountType.EXPENSE)
    entry = _entry(
        user_id,
        "diagnostic",
        date(2024, 1, 1),
        "Diagnostic merchant",
        "42.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    txn = _txn("diagnostic", date(2024, 1, 1), "Diagnostic merchant", "42.00", "OUT")

    report = build_report(
        scenarios=[
            AuditScenario(
                scenario_id="intentional-false-positive",
                title="Intentional false-positive diagnostic",
                transactions=(txn,),
                entries=(entry,),
                expectations=(AuditExpectation("diagnostic", UNMATCHED),),
            )
        ],
        benchmark_size=10,
    )

    assert report["summary"]["failed"] == 1
    assert report["summary"]["false_positive_count"] == 1
    assert report["targets"]["passed"] is False
    assert "false_positive_rate" in report["targets"]["failures"]
    assert report["failures"][0]["failure_type"] == "false_positive"
    assert report["failures"][0]["actual_route"] == AUTO_ACCEPT
    assert "false_positive expected" in render_markdown(report)


def test_AC4_10_3_ci_gates_reconciliation_audit_thresholds() -> None:
    """AC4.10.3: CI gates reconciliation audit target thresholds."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    ci_cd = (ROOT / "docs/ssot/ci-cd.md").read_text()
    epic = (ROOT / "docs/project/EPIC-004.reconciliation-engine.md").read_text()

    assert "tools/reconciliation_audit.py" in workflow
    assert "reconciliation_audit_status=$?" in workflow
    assert "reconciliation_audit_gate=$reconciliation_audit_status" in workflow
    assert "${{ runner.temp }}/reconciliation-audit/reconciliation-audit.json" in workflow
    assert "${{ runner.temp }}/reconciliation-audit/reconciliation-audit.md" in workflow
    fail_condition = workflow.split('if [ "$registry_status"', 1)[1].split("exit 1", 1)[0]
    assert "reconciliation_audit_status" in fail_condition
    assert "non-gating EPIC-004 accuracy evidence" not in ci_cd
    assert "hard gate" in ci_cd
    assert "10,000-transaction runtime targets" in epic


def test_AC4_10_1_reconciliation_audit_tool_wrapper_delegates_to_backend_service() -> None:
    """AC4.10.1: The root tool delegates to the backend audit implementation."""
    from src.services import reconciliation_audit as implementation

    import tools.reconciliation_audit as tool

    assert tool.main is implementation.main
