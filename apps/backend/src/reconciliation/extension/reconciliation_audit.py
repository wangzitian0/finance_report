"""Deterministic reconciliation audit harness.

This module exercises the same pure scoring helpers used by the reconciliation
engine and emits audit-grade diagnostics for expected-vs-actual matching.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from src.audit import JournalEntrySourceType
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    detect_transfer_pattern,
)
from src.reconciliation.base.config import DEFAULT_CONFIG, ReconciliationConfig
from src.reconciliation.extension.matching import _find_many_to_one_candidates, _find_normal_candidates
from src.reconciliation.extension.scoring import (
    score_amount,
    score_business_logic,
    score_date,
    score_description,
    weighted_total,
)

AUTO_ACCEPT = "auto_accept"
REVIEW = "review"
UNMATCHED = "unmatched"


@dataclass(frozen=True)
class AuditExpectation:
    """Expected reconciliation outcome for one bank transaction."""

    transaction_ref: str
    route: str
    journal_entry_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditScenario:
    """A deterministic scenario with labeled ground truth."""

    scenario_id: str
    title: str
    transactions: tuple[AtomicTransaction, ...]
    entries: tuple[JournalEntry, ...]
    expectations: tuple[AuditExpectation, ...]
    pattern_scores: dict[str, float] | None = None


def _stable_uuid(name: str) -> UUID:
    """Return a deterministic UUID for stable report diffs."""
    from uuid import NAMESPACE_URL, uuid5

    return uuid5(NAMESPACE_URL, f"finance-report-reconciliation-audit:{name}")


def _account(user_id: UUID, name: str, account_type: AccountType) -> Account:
    account = Account(
        id=_stable_uuid(f"account:{name}"),
        user_id=user_id,
        name=name,
        type=account_type,
        currency="SGD",
        is_active=True,
    )
    return account


def _entry(
    user_id: UUID,
    ref: str,
    entry_date: date,
    memo: str,
    amount: str,
    *,
    bank_account: Account,
    other_account: Account,
    direction: str,
) -> JournalEntry:
    entry = JournalEntry(
        id=_stable_uuid(f"entry:{ref}"),
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    amount_decimal = Decimal(amount)
    if direction == "IN":
        bank_direction = Direction.DEBIT
        other_direction = Direction.CREDIT
    else:
        bank_direction = Direction.CREDIT
        other_direction = Direction.DEBIT

    entry.lines = [
        JournalLine(
            id=_stable_uuid(f"line:{ref}:bank"),
            journal_entry_id=entry.id,
            account_id=bank_account.id,
            account=bank_account,
            direction=bank_direction,
            amount=amount_decimal,
            currency="SGD",
        ),
        JournalLine(
            id=_stable_uuid(f"line:{ref}:other"),
            journal_entry_id=entry.id,
            account_id=other_account.id,
            account=other_account,
            direction=other_direction,
            amount=amount_decimal,
            currency="SGD",
        ),
    ]
    return entry


def _txn(ref: str, txn_date: date, description: str, amount: str, direction: str) -> AtomicTransaction:
    return AtomicTransaction(
        id=_stable_uuid(f"txn:{ref}"),
        user_id=_stable_uuid("user:golden"),
        txn_date=txn_date,
        description=description,
        amount=Decimal(amount),
        direction=TransactionDirection(direction),
        reference=ref,
        currency="SGD",
        dedup_hash=str(_stable_uuid(f"dedup:{ref}")),
        source_documents=[],
    )


def _entry_refs(entries: tuple[JournalEntry, ...]) -> dict[str, str]:
    return {str(entry.id): str(entry.id) for entry in entries}


def _scenario_accounts(user_id: UUID) -> dict[str, Account]:
    return {
        "bank": _account(user_id, "Audit Bank", AccountType.ASSET),
        "income": _account(user_id, "Audit Income", AccountType.INCOME),
        "expense": _account(user_id, "Audit Expense", AccountType.EXPENSE),
    }


def build_golden_scenarios() -> list[AuditScenario]:
    """Build the deterministic golden reconciliation dataset."""
    user_id = _stable_uuid("user:golden")
    accounts = _scenario_accounts(user_id)
    bank = accounts["bank"]
    income = accounts["income"]
    expense = accounts["expense"]

    exact_entry = _entry(
        user_id,
        "exact_salary",
        date(2024, 1, 25),
        "January salary employer inc",
        "5000.00",
        bank_account=bank,
        other_account=income,
        direction="IN",
    )
    similar_entry = _entry(
        user_id,
        "similar_salary",
        date(2024, 2, 25),
        "February salary employer inc",
        "5000.00",
        bank_account=bank,
        other_account=income,
        direction="IN",
    )
    review_entry = _entry(
        user_id,
        "review_subscription",
        date(2024, 3, 4),
        "Annual software subscription",
        "120.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    unrelated_entry = _entry(
        user_id,
        "monthly_rent",
        date(2024, 1, 5),
        "Monthly rent landlord",
        "2000.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    batch_entry = _entry(
        user_id,
        "batch_settlement",
        date(2024, 4, 5),
        "Batch settlement ACME",
        "30.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    split_purchase = _entry(
        user_id,
        "vendor_purchase",
        date(2024, 5, 6),
        "Vendor equipment purchase",
        "100.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    split_fee = _entry(
        user_id,
        "vendor_fee",
        date(2024, 5, 6),
        "Vendor wire fee",
        "5.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )
    cross_period = _entry(
        user_id,
        "cross_period_bill",
        date(2024, 2, 2),
        "Month end utility bill",
        "88.00",
        bank_account=bank,
        other_account=expense,
        direction="OUT",
    )

    core_scenarios = [
        AuditScenario(
            scenario_id="exact-auto-accept",
            title="Exact salary match auto-accepts",
            transactions=(_txn("exact_salary", date(2024, 1, 25), "January salary employer inc", "5000.00", "IN"),),
            entries=(exact_entry,),
            expectations=(AuditExpectation("exact_salary", AUTO_ACCEPT, (str(exact_entry.id),)),),
        ),
        AuditScenario(
            scenario_id="similar-auto-accept",
            title="Similar payroll description still matches",
            transactions=(
                _txn("similar_salary", date(2024, 2, 25), "February salary from employer inc", "5000.00", "IN"),
            ),
            entries=(similar_entry,),
            expectations=(AuditExpectation("similar_salary", AUTO_ACCEPT, (str(similar_entry.id),)),),
        ),
        AuditScenario(
            scenario_id="review-band",
            title="Ambiguous subscription routes to review",
            transactions=(
                _txn("review_subscription", date(2024, 3, 8), "Software renewal card charge", "120.00", "OUT"),
            ),
            entries=(review_entry,),
            expectations=(AuditExpectation("review_subscription", REVIEW, (str(review_entry.id),)),),
        ),
        AuditScenario(
            scenario_id="unrelated-unmatched",
            title="Unrelated small purchase remains unmatched",
            transactions=(_txn("unrelated_coffee", date(2024, 1, 20), "Coffee shop purchase", "5.50", "OUT"),),
            entries=(unrelated_entry,),
            expectations=(AuditExpectation("unrelated_coffee", UNMATCHED),),
        ),
        AuditScenario(
            scenario_id="transfer-detection",
            title="Transfer-shaped transaction is routed as auto-accepted transfer",
            transactions=(_txn("transfer_out", date(2024, 3, 10), "FAST transfer to savings", "500.00", "OUT"),),
            entries=(),
            expectations=(AuditExpectation("transfer_out", AUTO_ACCEPT),),
        ),
        AuditScenario(
            scenario_id="many-to-one-batch",
            title="Two batch rows reconcile to one settlement entry",
            transactions=(
                _txn("batch_a", date(2024, 4, 5), "Batch settlement ACME", "12.00", "OUT"),
                _txn("batch_b", date(2024, 4, 5), "Batch settlement ACME", "18.00", "OUT"),
            ),
            entries=(batch_entry,),
            expectations=(
                AuditExpectation("batch_a", AUTO_ACCEPT, (str(batch_entry.id),)),
                AuditExpectation("batch_b", AUTO_ACCEPT, (str(batch_entry.id),)),
            ),
        ),
        AuditScenario(
            scenario_id="one-to-many-fee-split",
            title="One bank row reconciles to purchase plus fee entries",
            transactions=(
                _txn("vendor_total", date(2024, 5, 6), "Vendor equipment purchase wire fee", "105.00", "OUT"),
            ),
            entries=(split_purchase, split_fee),
            expectations=(AuditExpectation("vendor_total", AUTO_ACCEPT, (str(split_purchase.id), str(split_fee.id))),),
        ),
        AuditScenario(
            scenario_id="cross-period",
            title="Month-end transaction matches adjacent-period entry",
            transactions=(_txn("cross_period_bill", date(2024, 1, 31), "Month end utility bill", "88.00", "OUT"),),
            entries=(cross_period,),
            expectations=(AuditExpectation("cross_period_bill", AUTO_ACCEPT, (str(cross_period.id),)),),
        ),
    ]

    return core_scenarios + _build_false_positive_audit_scenarios(user_id, bank, expense)


def _build_false_positive_audit_scenarios(
    user_id: UUID,
    bank: Account,
    expense: Account,
    count: int = 100,
) -> list[AuditScenario]:
    """Build unmatched decoy scenarios for the manual false-positive audit."""
    scenarios: list[AuditScenario] = []
    for index in range(count):
        txn_ref = f"false_positive_decoy_{index:03d}"
        entry_ref = f"false_positive_decoy_entry_{index:03d}"
        txn_amount = Decimal("37.11") + Decimal(index % 13)
        entry_amount = txn_amount + Decimal("900.00")
        txn_date = date(2024, 6, 1) + timedelta(days=index % 28)
        decoy_entry = _entry(
            user_id,
            entry_ref,
            txn_date,
            f"Different vendor invoice {index:03d}",
            str(entry_amount),
            bank_account=bank,
            other_account=expense,
            direction="OUT",
        )
        scenarios.append(
            AuditScenario(
                scenario_id=f"manual-false-positive-audit-{index:03d}",
                title="Decoy transaction must remain unmatched",
                transactions=(
                    _txn(
                        txn_ref,
                        txn_date,
                        f"Coffee shop card purchase {index:03d}",
                        str(txn_amount),
                        "OUT",
                    ),
                ),
                entries=(decoy_entry,),
                expectations=(AuditExpectation(txn_ref, UNMATCHED),),
            )
        )
    return scenarios


def _route_for_score(score: int, config: ReconciliationConfig) -> str:
    if score >= config.auto_accept:
        return AUTO_ACCEPT
    if score >= config.pending_review:
        return REVIEW
    return UNMATCHED


def _transaction_ref(transaction: AtomicTransaction) -> str:
    return str(transaction.reference or transaction.id)


def _evaluate_scenario(scenario: AuditScenario, config: ReconciliationConfig) -> list[dict]:
    actual_by_txn: dict[str, dict] = {}

    for txn in scenario.transactions:
        ref = _transaction_ref(txn)
        if detect_transfer_pattern(txn.description):
            actual_by_txn[ref] = {
                "route": AUTO_ACCEPT,
                "score": 100,
                "journal_entry_ids": [],
                "score_breakdown": {"transfer": 100.0},
            }

    many_to_one = _find_many_to_one_candidates(
        list(scenario.transactions),
        list(scenario.entries),
        scenario.pattern_scores or {},
        config,
        base_currency="SGD",
    )
    for group_txn, candidate in many_to_one:
        group_key = f"{group_txn.description}:{group_txn.txn_date.isoformat()}"
        for txn in scenario.transactions:
            if f"{txn.description}:{txn.txn_date.isoformat()}" != group_key:
                continue
            actual_by_txn[_transaction_ref(txn)] = {
                "route": _route_for_score(candidate.score, config),
                "score": candidate.score,
                "journal_entry_ids": sorted(candidate.journal_entry_ids),
                "score_breakdown": candidate.breakdown,
            }

    normal = _find_normal_candidates(
        [txn for txn in scenario.transactions if _transaction_ref(txn) not in actual_by_txn],
        list(scenario.entries),
        scenario.pattern_scores or {},
        config,
        base_currency="SGD",
    )
    for txn, candidate in normal:
        actual_by_txn[_transaction_ref(txn)] = {
            "route": _route_for_score(candidate.score, config),
            "score": candidate.score,
            "journal_entry_ids": sorted(candidate.journal_entry_ids),
            "score_breakdown": candidate.breakdown,
        }

    rows: list[dict] = []
    for expectation in scenario.expectations:
        actual = actual_by_txn.get(
            expectation.transaction_ref,
            {
                "route": UNMATCHED,
                "score": 0,
                "journal_entry_ids": [],
                "score_breakdown": {},
            },
        )
        expected_ids = sorted(expectation.journal_entry_refs)
        actual_ids = sorted(actual["journal_entry_ids"])
        route_ok = actual["route"] == expectation.route
        entries_ok = not expected_ids or actual_ids == expected_ids
        passed = route_ok and entries_ok
        failure_type = None
        if not passed:
            if actual["route"] == AUTO_ACCEPT and expectation.route == UNMATCHED:
                failure_type = "false_positive"
            elif expectation.route in {AUTO_ACCEPT, REVIEW} and actual["route"] == UNMATCHED:
                failure_type = "false_negative"
            elif expected_ids and actual_ids != expected_ids:
                failure_type = "wrong_entry"
            else:
                failure_type = "routing_miss"

        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "title": scenario.title,
                "transaction_ref": expectation.transaction_ref,
                "expected_route": expectation.route,
                "actual_route": actual["route"],
                "expected_journal_entry_ids": expected_ids,
                "actual_journal_entry_ids": actual_ids,
                "score": actual["score"],
                "score_breakdown": actual["score_breakdown"],
                "passed": passed,
                "failure_type": failure_type,
            }
        )
    return rows


def _run_benchmark(config: ReconciliationConfig, benchmark_size: int) -> dict:
    user_id = _stable_uuid("user:benchmark")
    accounts = _scenario_accounts(user_id)
    bank = accounts["bank"]
    income = accounts["income"]
    start = time.perf_counter()

    for index in range(benchmark_size):
        txn_date = date(2024, 1, 1) + timedelta(days=index % 28)
        amount = Decimal("1000.00") + Decimal(index % 97)
        txn = _txn(f"benchmark_{index}", txn_date, f"Benchmark payroll {index}", str(amount), "IN")
        entry = _entry(
            user_id,
            f"benchmark_{index}",
            txn_date,
            f"Benchmark payroll {index}",
            str(amount),
            bank_account=bank,
            other_account=income,
            direction="IN",
        )
        scores = {
            "amount": score_amount(txn.amount, amount, config),
            "date": score_date(txn.txn_date, entry.entry_date, config),
            "description": score_description(txn.description, entry.memo),
            "business": score_business_logic(txn, entry),
            "history": 0.0,
        }
        weighted_total(scores, config)

    elapsed = time.perf_counter() - start
    return {
        "benchmark_size": benchmark_size,
        "runtime_seconds": round(elapsed, 6),
        "transactions_per_second": round(benchmark_size / elapsed, 2) if elapsed else benchmark_size,
        "target_runtime_seconds": 10.0,
        "target_met": elapsed <= 10.0,
        "mode": "deterministic_pair_scoring",
    }


def build_report(
    *,
    scenarios: list[AuditScenario] | None = None,
    config: ReconciliationConfig = DEFAULT_CONFIG,
    benchmark_size: int = 10_000,
) -> dict:
    """Build a reconciliation audit report."""
    scenario_rows: list[dict] = []
    for scenario in scenarios or build_golden_scenarios():
        scenario_rows.extend(_evaluate_scenario(scenario, config))

    total = len(scenario_rows)
    passed = sum(1 for row in scenario_rows if row["passed"])
    failures = [row for row in scenario_rows if not row["passed"]]
    actual_auto = [row for row in scenario_rows if row["actual_route"] == AUTO_ACCEPT]
    expected_matchable = [row for row in scenario_rows if row["expected_route"] in {AUTO_ACCEPT, REVIEW}]
    false_positives = [row for row in failures if row["failure_type"] in {"false_positive", "wrong_entry"}]
    false_negatives = [row for row in failures if row["failure_type"] == "false_negative"]
    accuracy_pct = round((passed / total) * 100, 2) if total else 100.0
    false_positive_rate_pct = round((len(false_positives) / max(len(actual_auto), 1)) * 100, 2)
    false_negative_rate_pct = round((len(false_negatives) / max(len(expected_matchable), 1)) * 100, 2)
    benchmark = _run_benchmark(config, benchmark_size)
    target_accuracy_pct = 95.0
    target_false_positive_rate_pct = 0.5
    target_false_negative_rate_pct = 2.0
    target_failures = []
    if accuracy_pct < target_accuracy_pct:
        target_failures.append("accuracy")
    if false_positive_rate_pct > target_false_positive_rate_pct:
        target_failures.append("false_positive_rate")
    if false_negative_rate_pct > target_false_negative_rate_pct:
        target_failures.append("false_negative_rate")
    if not benchmark["target_met"]:
        target_failures.append("runtime")

    return {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "issue": "#665",
            "epic": "EPIC-004",
            "macro_outcome": "source-ledger-report-traceability",
        },
        "thresholds": {
            "auto_accept": config.auto_accept,
            "pending_review": config.pending_review,
            "target_accuracy_pct": target_accuracy_pct,
            "target_false_positive_rate_pct": target_false_positive_rate_pct,
            "target_false_negative_rate_pct": target_false_negative_rate_pct,
        },
        "summary": {
            "total_expectations": total,
            "passed": passed,
            "failed": len(failures),
            "accuracy_pct": accuracy_pct,
            "false_positive_count": len(false_positives),
            "false_positive_rate_pct": false_positive_rate_pct,
            "false_negative_count": len(false_negatives),
            "false_negative_rate_pct": false_negative_rate_pct,
            "review_routing_miss_count": sum(
                1 for row in failures if row["expected_route"] == REVIEW and row["failure_type"] == "routing_miss"
            ),
        },
        "targets": {
            "passed": not target_failures,
            "failures": target_failures,
        },
        "benchmark": benchmark,
        "scenarios": scenario_rows,
        "failures": failures,
    }


def render_markdown(report: dict) -> str:
    """Render a human-readable audit report."""
    summary = report["summary"]
    benchmark = report["benchmark"]
    lines = [
        "# Reconciliation Accuracy Audit",
        "",
        f"- EPIC: {report['metadata']['epic']}",
        f"- Issue: {report['metadata']['issue']}",
        f"- Macro outcome: `{report['metadata']['macro_outcome']}`",
        f"- Generated at: {report['metadata']['generated_at']}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Total expectations | {summary['total_expectations']} |",
        f"| Passed | {summary['passed']} |",
        f"| Failed | {summary['failed']} |",
        f"| Accuracy | {summary['accuracy_pct']}% |",
        f"| False positives | {summary['false_positive_count']} |",
        f"| False positive rate | {summary['false_positive_rate_pct']}% |",
        f"| False negatives | {summary['false_negative_count']} |",
        f"| False negative rate | {summary['false_negative_rate_pct']}% |",
        f"| Target gate passed | {report['targets']['passed']} |",
        "",
        "## Benchmark",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Mode | {benchmark['mode']} |",
        f"| Benchmark size | {benchmark['benchmark_size']} |",
        f"| Runtime seconds | {benchmark['runtime_seconds']} |",
        f"| Transactions / second | {benchmark['transactions_per_second']} |",
        f"| Target met | {benchmark['target_met']} |",
        "",
        "## Scenario Results",
        "",
        "| Scenario | Txn | Expected | Actual | Score | Passed |",
        "|---|---|---|---|---:|---|",
    ]
    for row in report["scenarios"]:
        lines.append(
            f"| {row['scenario_id']} | {row['transaction_ref']} | {row['expected_route']} | "
            f"{row['actual_route']} | {row['score']} | {row['passed']} |"
        )

    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        for row in report["failures"]:
            lines.append(
                f"- `{row['scenario_id']}` / `{row['transaction_ref']}`: "
                f"{row['failure_type']} expected `{row['expected_route']}` got `{row['actual_route']}` "
                f"at score {row['score']}"
            )
    return "\n".join(lines) + "\n"


def write_report(report: dict, output_dir: Path) -> tuple[Path, Path]:
    """Write JSON and Markdown audit outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "reconciliation-audit.json"
    md_path = output_dir / "reconciliation-audit.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run the EPIC-004 reconciliation audit harness.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/reconciliation-audit"),
        help="Directory for JSON and Markdown audit outputs.",
    )
    parser.add_argument(
        "--benchmark-size",
        type=int,
        default=10_000,
        help="Deterministic benchmark transaction count.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print Markdown report to stdout.")
    args = parser.parse_args(argv)

    report = build_report(benchmark_size=args.benchmark_size)
    write_report(report, args.output_dir)
    if args.stdout:
        print(render_markdown(report), end="")
    return 0 if report["targets"]["passed"] else 1
