"""Deterministic reconciliation audit harness."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from src.audit import JournalEntrySourceType
from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    detect_transfer_pattern,
    fit_journal_memo,
)
from src.reconciliation.base.config import DEFAULT_CONFIG, ReconciliationConfig
from src.reconciliation.extension.candidate_policy import (
    _find_many_to_one_candidates,
    _find_normal_candidates,
    build_many_to_one_groups,
)
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
    transaction_ref: str
    route: str
    journal_entry_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditScenario:
    scenario_id: str
    title: str
    transactions: tuple[AtomicTransaction, ...]
    entries: tuple[JournalEntry, ...]
    expectations: tuple[AuditExpectation, ...]
    pattern_scores: dict[str, float] | None = None


def _stable_uuid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"finance-report-reconciliation-audit:{name}")


def _account(user_id: UUID, name: str, account_type: AccountType) -> Account:
    return Account(
        id=_stable_uuid(f"account:{name}"),
        user_id=user_id,
        name=name,
        type=account_type,
        currency="SGD",
        is_active=True,
    )


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
    amt = Decimal(amount)
    bank_dir, other_dir = (
        (Direction.DEBIT, Direction.CREDIT) if direction == "IN" else (Direction.CREDIT, Direction.DEBIT)
    )
    entry.lines = [
        JournalLine(
            id=_stable_uuid(f"line:{ref}:{tag}"),
            journal_entry_id=entry.id,
            account_id=acct.id,
            account=acct,
            direction=d,
            amount=amt,
            currency="SGD",
        )
        for tag, acct, d in (("bank", bank_account, bank_dir), ("other", other_account, other_dir))
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


_ENTRY_SPECS = (
    ("exact_salary", date(2024, 1, 25), "January salary employer inc", "5000.00", "income", "IN"),
    ("similar_salary", date(2024, 2, 25), "February salary employer inc", "5000.00", "income", "IN"),
    ("review_subscription", date(2024, 3, 4), "Annual software subscription", "120.00", "expense", "OUT"),
    ("monthly_rent", date(2024, 1, 5), "Monthly rent landlord", "2000.00", "expense", "OUT"),
    ("batch_settlement", date(2024, 4, 5), "Batch settlement ACME", "30.00", "expense", "OUT"),
    ("vendor_purchase", date(2024, 5, 6), "Vendor equipment purchase", "100.00", "expense", "OUT"),
    ("vendor_fee", date(2024, 5, 6), "Vendor wire fee", "5.00", "expense", "OUT"),
    ("cross_period_bill", date(2024, 2, 2), "Month end utility bill", "88.00", "expense", "OUT"),
)

_SCENARIO_SPECS = (
    (
        "exact-auto-accept",
        "Exact salary match auto-accepts",
        (("exact_salary", date(2024, 1, 25), "January salary employer inc", "5000.00", "IN"),),
        ("exact_salary",),
        (("exact_salary", AUTO_ACCEPT, ("exact_salary",)),),
    ),
    (
        "similar-auto-accept",
        "Similar payroll description still matches",
        (("similar_salary", date(2024, 2, 25), "February salary from employer inc", "5000.00", "IN"),),
        ("similar_salary",),
        (("similar_salary", AUTO_ACCEPT, ("similar_salary",)),),
    ),
    (
        "review-band",
        "Ambiguous subscription routes to review",
        (("review_subscription", date(2024, 3, 8), "Software renewal card charge", "120.00", "OUT"),),
        ("review_subscription",),
        (("review_subscription", REVIEW, ("review_subscription",)),),
    ),
    (
        "unrelated-unmatched",
        "Unrelated small purchase remains unmatched",
        (("unrelated_coffee", date(2024, 1, 20), "Coffee shop purchase", "5.50", "OUT"),),
        ("monthly_rent",),
        (("unrelated_coffee", UNMATCHED, ()),),
    ),
    (
        "transfer-detection",
        "Transfer-shaped transaction is routed as auto-accepted transfer",
        (("transfer_out", date(2024, 3, 10), "FAST transfer to savings", "500.00", "OUT"),),
        (),
        (("transfer_out", AUTO_ACCEPT, ()),),
    ),
    (
        "many-to-one-batch",
        "Two batch rows reconcile to one settlement entry",
        (
            ("batch_a", date(2024, 4, 5), "Batch settlement ACME", "12.00", "OUT"),
            ("batch_b", date(2024, 4, 5), "Batch settlement ACME", "18.00", "OUT"),
        ),
        ("batch_settlement",),
        (
            ("batch_a", AUTO_ACCEPT, ("batch_settlement",)),
            ("batch_b", AUTO_ACCEPT, ("batch_settlement",)),
        ),
    ),
    (
        "one-to-many-fee-split",
        "One bank row reconciles to purchase plus fee entries",
        (("vendor_total", date(2024, 5, 6), "Vendor equipment purchase wire fee", "105.00", "OUT"),),
        ("vendor_purchase", "vendor_fee"),
        (("vendor_total", AUTO_ACCEPT, ("vendor_purchase", "vendor_fee")),),
    ),
    (
        "cross-period",
        "Month-end transaction matches adjacent-period entry",
        (("cross_period_bill", date(2024, 1, 31), "Month end utility bill", "88.00", "OUT"),),
        ("cross_period_bill",),
        (("cross_period_bill", AUTO_ACCEPT, ("cross_period_bill",)),),
    ),
)


def build_golden_scenarios() -> list[AuditScenario]:
    user_id = _stable_uuid("user:golden")
    accounts = _scenario_accounts(user_id)
    bank = accounts["bank"]
    entries_by_ref = {
        ref: _entry(user_id, ref, dt, memo, amt, bank_account=bank, other_account=accounts[acct_key], direction=d)
        for ref, dt, memo, amt, acct_key, d in _ENTRY_SPECS
    }
    core = [
        AuditScenario(
            scenario_id=sid,
            title=title,
            transactions=tuple(_txn(*t) for t in txns),
            entries=tuple(entries_by_ref[er] for er in entry_refs),
            expectations=tuple(
                AuditExpectation(tref, route, tuple(str(entries_by_ref[er].id) for er in erefs))
                for tref, route, erefs in exps
            ),
        )
        for sid, title, txns, entry_refs, exps in _SCENARIO_SPECS
    ]
    return core + _build_false_positive_audit_scenarios(user_id, bank, accounts["expense"])


def _build_false_positive_audit_scenarios(
    user_id: UUID, bank: Account, expense: Account, count: int = 100
) -> list[AuditScenario]:
    scenarios: list[AuditScenario] = []
    for i in range(count):
        txn_ref = f"false_positive_decoy_{i:03d}"
        txn_amount = Decimal("37.11") + Decimal(i % 13)
        txn_date = date(2024, 6, 1) + timedelta(days=i % 28)
        decoy_entry = _entry(
            user_id,
            f"false_positive_decoy_entry_{i:03d}",
            txn_date,
            f"Different vendor invoice {i:03d}",
            str(txn_amount + Decimal("900.00")),
            bank_account=bank,
            other_account=expense,
            direction="OUT",
        )
        scenarios.append(
            AuditScenario(
                scenario_id=f"manual-false-positive-audit-{i:03d}",
                title="Decoy transaction must remain unmatched",
                transactions=(_txn(txn_ref, txn_date, f"Coffee shop card purchase {i:03d}", str(txn_amount), "OUT"),),
                entries=(decoy_entry,),
                expectations=(AuditExpectation(txn_ref, UNMATCHED),),
            )
        )
    return scenarios


def _route_for_score(score: int, config: ReconciliationConfig) -> str:
    if score >= config.auto_accept:
        return AUTO_ACCEPT
    return REVIEW if score >= config.pending_review else UNMATCHED


def _transaction_ref(transaction: AtomicTransaction) -> str:
    return str(transaction.reference or transaction.id)


def _candidate_record(candidate, config: ReconciliationConfig) -> dict:
    return {
        "route": _route_for_score(candidate.score, config),
        "score": candidate.score,
        "journal_entry_ids": sorted(candidate.journal_entry_ids),
        "score_breakdown": candidate.breakdown,
    }


def _evaluate_scenario(scenario: AuditScenario, config: ReconciliationConfig) -> list[dict]:
    actual_by_txn: dict[str, dict] = {}
    ps = scenario.pattern_scores or {}

    groups_by_head = {group[0].id: group for group in build_many_to_one_groups(scenario.transactions)}
    for group_txn, candidate in _find_many_to_one_candidates(
        list(scenario.transactions), list(scenario.entries), ps, config, base_currency="SGD"
    ):
        for txn in groups_by_head[group_txn.id]:
            actual_by_txn[_transaction_ref(txn)] = _candidate_record(candidate, config)

    for txn, candidate in _find_normal_candidates(
        [t for t in scenario.transactions if _transaction_ref(t) not in actual_by_txn],
        list(scenario.entries),
        ps,
        config,
        base_currency="SGD",
    ):
        actual_by_txn[_transaction_ref(txn)] = _candidate_record(candidate, config)

    for txn in scenario.transactions:
        ref = _transaction_ref(txn)
        if ref not in actual_by_txn and detect_transfer_pattern(txn.description):
            actual_by_txn[ref] = {
                "route": AUTO_ACCEPT,
                "score": 100,
                "journal_entry_ids": [],
                "score_breakdown": {"transfer": 100.0},
            }

    rows: list[dict] = []
    for exp in scenario.expectations:
        actual = actual_by_txn.get(
            exp.transaction_ref,
            {"route": UNMATCHED, "score": 0, "journal_entry_ids": [], "score_breakdown": {}},
        )
        expected_ids = sorted(exp.journal_entry_refs)
        actual_ids = sorted(actual["journal_entry_ids"])
        passed = actual["route"] == exp.route and (not expected_ids or actual_ids == expected_ids)
        failure_type = None
        if not passed:
            if actual["route"] == AUTO_ACCEPT and exp.route == UNMATCHED:
                failure_type = "false_positive"
            elif exp.route in {AUTO_ACCEPT, REVIEW} and actual["route"] == UNMATCHED:
                failure_type = "false_negative"
            elif expected_ids and actual_ids != expected_ids:
                failure_type = "wrong_entry"
            else:
                failure_type = "routing_miss"
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "title": scenario.title,
                "transaction_ref": exp.transaction_ref,
                "expected_route": exp.route,
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
    bank, income = accounts["bank"], accounts["income"]
    start = time.perf_counter()
    for i in range(benchmark_size):
        txn_date = date(2024, 1, 1) + timedelta(days=i % 28)
        amount = Decimal("1000.00") + Decimal(i % 97)
        label = f"Benchmark payroll {i}"
        txn = _txn(f"benchmark_{i}", txn_date, label, str(amount), "IN")
        entry = _entry(
            user_id,
            f"benchmark_{i}",
            txn_date,
            label,
            str(amount),
            bank_account=bank,
            other_account=income,
            direction="IN",
        )
        weighted_total(
            {
                "amount": score_amount(txn.amount, amount, config),
                "date": score_date(txn.txn_date, entry.entry_date, config),
                "description": score_description(fit_journal_memo(txn.description or ""), entry.memo),
                "business": score_business_logic(txn, entry),
                "history": 0.0,
            },
            config,
        )
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
    scenario_rows = [
        row for scenario in (scenarios or build_golden_scenarios()) for row in _evaluate_scenario(scenario, config)
    ]
    total = len(scenario_rows)
    passed = sum(1 for r in scenario_rows if r["passed"])
    failures = [r for r in scenario_rows if not r["passed"]]
    actual_auto = [r for r in scenario_rows if r["actual_route"] == AUTO_ACCEPT]
    expected_matchable = [r for r in scenario_rows if r["expected_route"] in {AUTO_ACCEPT, REVIEW}]
    false_positives = [r for r in failures if r["failure_type"] in {"false_positive", "wrong_entry"}]
    false_negatives = [r for r in failures if r["failure_type"] == "false_negative"]
    accuracy_pct = round((passed / total) * 100, 2) if total else 100.0
    fp_pct = round((len(false_positives) / max(len(actual_auto), 1)) * 100, 2)
    fn_pct = round((len(false_negatives) / max(len(expected_matchable), 1)) * 100, 2)
    benchmark = _run_benchmark(config, benchmark_size)
    target_failures = [
        name
        for name, bad in (
            ("accuracy", accuracy_pct < 95.0),
            ("false_positive_rate", fp_pct > 0.5),
            ("false_negative_rate", fn_pct > 2.0),
            ("runtime", not benchmark["target_met"]),
        )
        if bad
    ]
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
            "target_accuracy_pct": 95.0,
            "target_false_positive_rate_pct": 0.5,
            "target_false_negative_rate_pct": 2.0,
        },
        "summary": {
            "total_expectations": total,
            "passed": passed,
            "failed": len(failures),
            "accuracy_pct": accuracy_pct,
            "false_positive_count": len(false_positives),
            "false_positive_rate_pct": fp_pct,
            "false_negative_count": len(false_negatives),
            "false_negative_rate_pct": fn_pct,
            "review_routing_miss_count": sum(
                1 for r in failures if r["expected_route"] == REVIEW and r["failure_type"] == "routing_miss"
            ),
        },
        "targets": {"passed": not target_failures, "failures": target_failures},
        "benchmark": benchmark,
        "scenarios": scenario_rows,
        "failures": failures,
    }


def render_markdown(report: dict) -> str:
    s, b, m = report["summary"], report["benchmark"], report["metadata"]
    lines = [
        "# Reconciliation Accuracy Audit",
        "",
        f"- EPIC: {m['epic']}",
        f"- Issue: {m['issue']}",
        f"- Macro outcome: `{m['macro_outcome']}`",
        f"- Generated at: {m['generated_at']}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Total expectations | {s['total_expectations']} |",
        f"| Passed | {s['passed']} |",
        f"| Failed | {s['failed']} |",
        f"| Accuracy | {s['accuracy_pct']}% |",
        f"| False positives | {s['false_positive_count']} |",
        f"| False positive rate | {s['false_positive_rate_pct']}% |",
        f"| False negatives | {s['false_negative_count']} |",
        f"| False negative rate | {s['false_negative_rate_pct']}% |",
        f"| Target gate passed | {report['targets']['passed']} |",
        "",
        "## Benchmark",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Mode | {b['mode']} |",
        f"| Benchmark size | {b['benchmark_size']} |",
        f"| Runtime seconds | {b['runtime_seconds']} |",
        f"| Transactions / second | {b['transactions_per_second']} |",
        f"| Target met | {b['target_met']} |",
        "",
        "## Scenario Results",
        "",
        "| Scenario | Txn | Expected | Actual | Score | Passed |",
        "|---|---|---|---|---:|---|",
        *(
            f"| {r['scenario_id']} | {r['transaction_ref']} | {r['expected_route']} | {r['actual_route']} | {r['score']} | {r['passed']} |"
            for r in report["scenarios"]
        ),
    ]
    if report["failures"]:
        lines.extend(
            [
                "",
                "## Failures",
                "",
                *(
                    f"- `{r['scenario_id']}` / `{r['transaction_ref']}`: {r['failure_type']} expected `{r['expected_route']}` got `{r['actual_route']}` at score {r['score']}"
                    for r in report["failures"]
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def write_report(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "reconciliation-audit.json"
    md_path = output_dir / "reconciliation-audit.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the EPIC-004 reconciliation audit harness.")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/reconciliation-audit"))
    parser.add_argument("--benchmark-size", type=int, default=10_000)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(benchmark_size=args.benchmark_size)
    write_report(report, args.output_dir)
    if args.stdout:
        print(render_markdown(report), end="")
    return 0 if report["targets"]["passed"] else 1
