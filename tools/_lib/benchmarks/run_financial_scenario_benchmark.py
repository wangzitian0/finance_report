#!/usr/bin/env python3
"""
Financial Reporting Temporal Scenario Benchmark Suite.

Executes end-to-end multi-period accounting scenarios against the live application
(e.g., Staging: https://report-staging.zitian.party) and validates fundamental
3-statement financial reconciliation identities:
  1. Balance Sheet: Assets == Liabilities + Equity + Net Income (delta == 0.00)
  2. Multi-period Rollforward: Month 2 Opening Balance == Month 1 Closing Balance
  3. Income Statement: Net Income accumulates into Retained Earnings
  4. Cash Flow: Beginning Cash + Net Cash Flow == Ending Cash
  5. Asset Reallocation / Transfer: Zero P&L contamination on internal swaps

Usage:
  python tools/run_financial_scenario_benchmark.py --app-url https://report-staging.zitian.party --case 1,3
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Any, Sequence

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools._lib.benchmarks.benchmark_html_reporter import (  # noqa: E402
    extract_summary_data,
    generate_html_report,
)
from tools._lib.benchmarks.case_types import CaseResult  # noqa: E402
from tools._lib.benchmarks.cases import (  # noqa: E402
    execute_case_1,
    execute_case_2,
    execute_case_3,
    execute_case_4,
    execute_case_5,
    execute_case_6,
)
from tools._lib.benchmarks.statement_generators import (  # noqa: E402
    generate_bank_asset_transfer_pdf,
    generate_consecutive_month2_pdf,
    generate_consecutive_month3_pdf,
    generate_consecutive_month4_pdf,
    generate_credit_card_repayment_bank_pdf,
    generate_household_wife_operations_csv,
    generate_multicurrency_hkd_csv,
    generate_multicurrency_usd_csv,
    generate_standard_operations_csv,
)


class ScenarioBenchmarkRunner:
    """Benchmark scenario runner connecting to the target API."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 180.0,
        verify: bool = True,
        replay_mode: str = "off",
        cassette_mode: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify = verify
        self.replay_mode = cassette_mode or replay_mode
        self.cassette_mode = self.replay_mode
        self.last_auth_context: dict[str, Any] | None = None

    def create_ephemeral_client(
        self, prefix: str = "qa_bench"
    ) -> tuple[httpx.Client, str, dict[str, Any]]:
        """Register an ephemeral test user and return an authenticated HTTP client."""
        client = httpx.Client(
            base_url=self.base_url, verify=self.verify, timeout=self.timeout
        )
        user_email = f"{prefix}_{uuid.uuid4().hex[:8]}@test.example.com"
        reg_resp = client.post(
            "/api/auth/register",
            json={
                "email": user_email,
                "password": "Password123!",
                "display_name": f"Benchmark Runner {prefix}",
            },
        )
        if reg_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"User registration failed: {reg_resp.status_code} {reg_resp.text}"
            )

        user_data = reg_resp.json()
        token = user_data.get("access_token")
        if not token:
            raise RuntimeError(f"No access token returned: {user_data}")

        client.headers.update({"Authorization": f"Bearer {token}"})
        self.last_auth_context = {
            "client": client,
            "user_email": user_email,
            "user_data": user_data,
        }
        return client, user_email, user_data

    def upload_statement(
        self,
        client: httpx.Client,
        file_bytes: bytes,
        filename: str,
        account_id: str | None = None,
        institution: str | None = None,
        currency: str = "SGD",
    ) -> str:
        """Upload a statement PDF or CSV and return statement ID."""
        if filename.endswith(".csv") and not account_id:
            account_name = f"{institution or 'Operating'} Cash Account"
            acc = self.create_account(
                client, name=account_name, type="ASSET", currency=currency
            )
            account_id = acc["id"]

        content_type = "text/csv" if filename.endswith(".csv") else "application/pdf"
        files = {"file": (filename, file_bytes, content_type)}
        data: dict[str, str] = {}
        if account_id:
            data["account_id"] = str(account_id)
        if institution:
            data["institution"] = institution

        resp = client.post("/api/statements/upload", files=files, data=data)
        if resp.status_code not in (200, 201, 202):
            raise RuntimeError(
                f"Statement upload failed: {resp.status_code} {resp.text}"
            )
        statement_id = resp.json().get("id")
        if not statement_id:
            raise RuntimeError(f"Upload response missing statement ID: {resp.json()}")
        return str(statement_id)

    def wait_for_statement_parsed(
        self,
        client: httpx.Client,
        statement_id: str,
        max_wait_seconds: int = 150,
        poll_interval: int = 3,
    ) -> dict[str, Any]:
        """Poll statement status until terminal state ('parsed', 'rejected', 'failed')."""
        start = time.time()
        while time.time() - start < max_wait_seconds:
            resp = client.get(f"/api/statements/{statement_id}")
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Polling statement {statement_id} failed: {resp.status_code} {resp.text}"
                )
            data = resp.json()
            status = data.get("status")
            if status == "parsed":
                return data
            if status in ("rejected", "failed"):
                err = data.get("validation_error") or "Unknown validation error"
                raise RuntimeError(
                    f"Statement {statement_id} entered terminal failure state '{status}': {err}"
                )
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Statement {statement_id} did not reach parsed status within {max_wait_seconds}s"
        )

    def adjudicate_unmatched_items(
        self,
        client: httpx.Client,
        statement_id: str,
        default_income_category: str = "OTHER_INCOME",
        default_expense_category: str = "OTHER_EXPENSE",
        non_pnl_intent: str | None = None,
        non_pnl_counter_account_id: str | None = None,
        currency: str | None = None,
    ) -> int:
        """Resolve any Stage 1 unmatched transactions with explicit economic intent."""
        unmatched_resp = client.get(
            f"/api/reconciliation/unmatched?statement_id={statement_id}"
        )
        if unmatched_resp.status_code != 200:
            raise RuntimeError(
                f"Failed to fetch unmatched items: {unmatched_resp.status_code} {unmatched_resp.text}"
            )

        items = unmatched_resp.json().get("items", [])
        if not items:
            return 0

        if not currency:
            stmt_resp = client.get(f"/api/statements/{statement_id}")
            if stmt_resp.status_code == 200:
                currency = stmt_resp.json().get("currency", "SGD")
            else:
                currency = "SGD"

        accounts_cache: dict[tuple[str, str], str] = {}

        def get_or_create_counter_account(acc_type: str, curr: str) -> str:
            key = (acc_type, curr)
            if key not in accounts_cache:
                acc = self.create_account(
                    client,
                    name=f"{acc_type.capitalize()} - Other {curr}",
                    type=acc_type,
                    currency=curr,
                )
                accounts_cache[key] = acc["id"]
            return accounts_cache[key]

        count = 0
        for item in items:
            txn_id = item["id"]
            direction = item.get("direction", "OUT")
            desc = item.get("description", "")
            txn_curr = item.get("currency") or currency

            if non_pnl_intent and non_pnl_counter_account_id:
                payload = {
                    "intent": non_pnl_intent,
                    "counter_account_id": non_pnl_counter_account_id,
                    "rationale": f"Benchmark non-P&L disposition for {desc}",
                }
            else:
                is_in = direction == "IN"
                intent = "income" if is_in else "expense"
                acc_type = "INCOME" if is_in else "EXPENSE"
                category = (
                    default_income_category if is_in else default_expense_category
                )
                acc_id = get_or_create_counter_account(acc_type, txn_curr)
                payload = {
                    "intent": intent,
                    "counter_account_id": acc_id,
                    "category": category,
                    "rationale": f"Benchmark disposition for {desc}",
                }

            disp_resp = client.post(
                f"/api/reconciliation/unmatched/{txn_id}/reviewed-disposition",
                json=payload,
            )
            if disp_resp.status_code != 200:
                raise RuntimeError(
                    f"Adjudication failed for txn {txn_id}: {disp_resp.status_code} {disp_resp.text}"
                )
            count += 1

        return count

    def approve_statement(
        self, client: httpx.Client, statement_id: str
    ) -> dict[str, Any]:
        """Approve statement to post ledger entries."""
        resp = client.post(
            f"/api/statements/{statement_id}/review/approve",
            json={"create_account_if_missing": True},
        )
        if (
            resp.status_code == 400
            and "requires explicit human confirmation before posting" in resp.text
        ):
            review_resp = client.get(f"/api/statements/{statement_id}/review")
            if review_resp.status_code == 200:
                rev = review_resp.json()
                digest = rev.get("source_result_digest")
                account_id = rev.get("account_id")
                stmt_resp = client.get(f"/api/statements/{statement_id}")
                if stmt_resp.status_code != 200:
                    raise RuntimeError(
                        f"Failed to fetch statement {statement_id}: {stmt_resp.status_code} {stmt_resp.text}"
                    )
                stmt = stmt_resp.json()
                env_payload = {
                    "source_result_digest": digest,
                    "account_id": account_id or stmt.get("account_id"),
                    "currency": stmt.get("currency", "SGD"),
                    "period_start": stmt.get("period_start") or "2025-04-01",
                    "period_end": stmt.get("period_end") or "2025-04-30",
                    "opening_balance": str(stmt.get("opening_balance", "0.00")),
                    "closing_balance": str(stmt.get("closing_balance", "0.00")),
                    "rationale": "Benchmark automated review envelope confirmation",
                }
                conf_resp = client.post(
                    f"/api/statements/{statement_id}/review/envelope",
                    json=env_payload,
                )
                if conf_resp.status_code in (200, 201):
                    resp = client.post(
                        f"/api/statements/{statement_id}/review/approve",
                        json={"create_account_if_missing": True},
                    )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Approval failed for statement {statement_id}: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_balance_sheet(
        self,
        client: httpx.Client,
        as_of_date: str | None = None,
        currency: str | None = None,
        include_restricted: bool | None = None,
    ) -> dict[str, Any]:
        params: list[str] = []
        if as_of_date:
            params.append(f"as_of_date={as_of_date}")
        if currency:
            params.append(f"currency={currency}")
        if include_restricted is not None:
            params.append(
                f"include_restricted={'true' if include_restricted else 'false'}"
            )
        query = f"?{'&'.join(params)}" if params else ""
        resp = client.get(f"/api/reports/balance-sheet{query}")
        if resp.status_code != 200:
            raise RuntimeError(
                f"Balance sheet request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_income_statement(
        self, client: httpx.Client, start_date: str, end_date: str
    ) -> dict[str, Any]:
        resp = client.get(
            f"/api/reports/income-statement?start_date={start_date}&end_date={end_date}"
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Income statement request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_cash_flow(
        self, client: httpx.Client, start_date: str, end_date: str
    ) -> dict[str, Any]:
        resp = client.get(
            f"/api/reports/cash-flow?start_date={start_date}&end_date={end_date}"
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Cash flow request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def import_brokerage_positions(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
        filename: str = "brokerage_statement.csv",
    ) -> dict[str, Any]:
        resp = client.post(
            "/api/portfolio/brokerage/import",
            json={"filename": filename, "payload": payload},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Brokerage import request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_holdings(
        self, client: httpx.Client, as_of_date: str | None = None
    ) -> dict[str, Any]:
        params = f"?as_of_date={as_of_date}" if as_of_date else ""
        resp = client.get(f"/api/portfolio/holdings{params}")
        if resp.status_code != 200:
            raise RuntimeError(
                f"Holdings request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def update_market_prices(
        self,
        client: httpx.Client,
        updates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Update market prices manually for portfolio securities."""
        resp = client.post("/api/portfolio/prices/update", json={"updates": updates})
        if resp.status_code != 200:
            raise RuntimeError(f"Price update failed: {resp.status_code} {resp.text}")
        return resp.json()

    def create_account(
        self,
        client: httpx.Client,
        name: str,
        type: str,
        currency: str = "SGD",
    ) -> dict[str, Any]:
        """Create a ledger account (e.g., ASSET, LIABILITY, EXPENSE, INCOME)."""
        resp = client.post(
            "/api/accounts",
            json={"name": name, "type": type, "currency": currency},
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create account '{name}': {resp.status_code} {resp.text}"
            )
        return resp.json()

    def post_manual_journal_entry(
        self,
        client: httpx.Client,
        memo: str,
        lines: list[dict[str, Any]],
        entry_date: str = "2025-04-10",
        rationale: str = "Benchmark manual journal entry",
    ) -> dict[str, Any]:
        """Create and post a balanced double-entry manual journal entry."""
        create_resp = client.post(
            "/api/journal-entries",
            json={
                "entry_date": entry_date,
                "memo": memo,
                "lines": lines,
                "rationale": rationale,
            },
        )
        if create_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create draft journal entry: {create_resp.status_code} {create_resp.text}"
            )
        entry_id = create_resp.json()["id"]
        post_resp = client.post(f"/api/journal-entries/{entry_id}/postings")
        if post_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to post journal entry {entry_id}: {post_resp.status_code} {post_resp.text}"
            )
        return post_resp.json()

    def create_valuation_snapshot(
        self,
        client: httpx.Client,
        component_type: str,
        as_of_date: str,
        value: str,
        currency: str,
        source: str,
        valuation_basis: str = "market_appraisal",
        liquidity_class: str = "illiquid",
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Register a manual asset valuation snapshot (e.g. real estate appraisal)."""
        payload: dict[str, Any] = {
            "component_type": component_type,
            "as_of_date": as_of_date,
            "value": value,
            "currency": currency,
            "source": source,
            "valuation_basis": valuation_basis,
            "liquidity_class": liquidity_class,
        }
        if notes:
            payload["notes"] = notes
        resp = client.post("/api/assets/valuation-snapshots", json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Valuation snapshot failed: {resp.status_code} {resp.text}"
            )
        return resp.json()

    def get_valuation_components(
        self,
        client: httpx.Client,
        as_of_date: str | None = None,
    ) -> dict[str, Any]:
        """Fetch manual valuation components summary."""
        params = f"?as_of_date={as_of_date}" if as_of_date else ""
        resp = client.get(f"/api/assets/valuation-components{params}")
        if resp.status_code != 200:
            raise RuntimeError(
                f"Valuation components request failed: {resp.status_code} {resp.text}"
            )
        return resp.json()


# =====================================================================
# Re-exported Benchmark Case Executors & Statement Generators
# =====================================================================

__all__ = [
    "CaseResult",
    "ScenarioBenchmarkRunner",
    "execute_case_1",
    "execute_case_2",
    "execute_case_3",
    "execute_case_4",
    "execute_case_5",
    "generate_bank_asset_transfer_pdf",
    "generate_consecutive_month2_pdf",
    "generate_consecutive_month3_pdf",
    "generate_consecutive_month4_pdf",
    "generate_credit_card_repayment_bank_pdf",
    "generate_household_wife_operations_csv",
    "generate_multicurrency_hkd_csv",
    "generate_multicurrency_usd_csv",
    "generate_standard_operations_csv",
    "main",
]


# =====================================================================
# Main Orchestrator & CLI Entrypoint
# =====================================================================


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Financial Reporting Multi-Scenario Benchmark Suite."
    )
    parser.add_argument(
        "--app-url",
        default="https://report-staging.zitian.party",
        help="Target base URL (default: https://report-staging.zitian.party)",
    )
    parser.add_argument(
        "--case",
        default="all",
        help="Comma-separated case IDs to run (1, 2, 3, 4, 5, 6, or all)",
    )
    parser.add_argument(
        "--version-ref",
        default="v0.1.52",
        help="Release tag or version identifier (default: v0.1.52)",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=REPO_ROOT / "benchmark_run_report.json",
        help="Path to output JSON benchmark report",
    )
    parser.add_argument(
        "--output-html",
        type=Path,
        default=None,
        help="Path to output standalone single-file HTML report",
    )
    parser.add_argument(
        "--output-summary",
        type=Path,
        default=None,
        help="Path to output summary JSON for dashboard aggregation",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Path to previous benchmark report/summary JSON for baseline diff",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="HTTP timeout per request in seconds",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        default=False,
        help="Disable TLS certificate verification for local development/testing",
    )
    parser.add_argument(
        "--cassette",
        choices=["replay", "off"],
        default="off",
        help="Enable cassette replay mode for fast execution without live OCR latency",
    )
    return parser.parse_args(argv)


def _dispatch_cases(runner: ScenarioBenchmarkRunner, case_arg: str) -> list[CaseResult]:
    requested = [c.strip().lower() for c in case_arg.split(",") if c.strip()]
    run_all = "all" in requested

    def _should_run(case_num: str) -> bool:
        return (
            run_all
            or case_num in requested
            or f"case_{case_num}" in requested
            or f"case{case_num}" in requested
        )

    results: list[CaseResult] = []
    if _should_run("1"):
        results.append(execute_case_1(runner))
    if _should_run("2"):
        results.append(execute_case_2(runner))
    if _should_run("3"):
        results.append(execute_case_3(runner))
    if _should_run("4"):
        results.append(execute_case_4(runner))
    if _should_run("5"):
        results.append(execute_case_5(runner))
    if _should_run("6"):
        results.append(execute_case_6(runner))
    return results


def _build_report_data(
    args: argparse.Namespace, results: list[CaseResult], all_passed: bool
) -> dict[str, Any]:
    return {
        "suite": "financial_reporting_temporal_scenarios",
        "version_ref": args.version_ref,
        "app_url": args.app_url,
        "run_at": datetime.now(UTC).isoformat(),
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == "PASS"),
            "failed": sum(1 for r in results if r.status != "PASS"),
            "success": all_passed,
        },
        "results": [asdict(r) for r in results],
    }


def _save_reports(
    args: argparse.Namespace,
    report_data: dict[str, Any],
) -> None:
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_report, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

    baseline_data = None
    if args.baseline and args.baseline.exists():
        try:
            with open(args.baseline, "r", encoding="utf-8") as f:
                baseline_data = json.load(f)
        except Exception as exc:
            print(f"⚠️ Failed to read baseline {args.baseline}: {exc}", file=sys.stderr)

    if args.output_html:
        args.output_html.parent.mkdir(parents=True, exist_ok=True)
        html_report = generate_html_report(report_data, baseline_data=baseline_data)
        with open(args.output_html, "w", encoding="utf-8") as f:
            f.write(html_report)
        print(f"HTML report saved to: {args.output_html} ({len(html_report)} bytes)")

    if args.output_summary:
        args.output_summary.parent.mkdir(parents=True, exist_ok=True)
        summary_data = extract_summary_data(report_data)
        with open(args.output_summary, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
        print(f"Summary JSON saved to: {args.output_summary}")


def _print_summary(
    results: list[CaseResult],
    report_data: dict[str, Any],
    json_report_path: Path | None,
) -> None:
    print("======================================================================")
    print("BENCHMARK EXECUTION SUMMARY")
    print("======================================================================")
    for r in results:
        status_icon = "✅ PASS" if r.status == "PASS" else "❌ FAIL"
        print(
            f"{status_icon} | {r.case_id.upper()}: {r.case_name} ({r.duration_seconds:.2f}s)"
        )
        if r.error_message:
            print(f"       Error: {r.error_message}")
    print("----------------------------------------------------------------------")
    print(
        f"Total: {len(results)} | Passed: {report_data['summary']['passed']} | Failed: {report_data['summary']['failed']}"
    )
    if json_report_path:
        print(f"Report saved to: {json_report_path}")
    print("======================================================================")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    print("======================================================================")
    print("FINANCIAL REPORTING TEMPORAL BENCHMARK SUITE")
    print(f"Target Environment: {args.app_url}")
    print(f"Version Ref:        {args.version_ref}")
    print(f"Cases Selected:     {args.case}")
    print(f"Started At:         {datetime.now(UTC).isoformat()}")
    print("======================================================================")

    runner = ScenarioBenchmarkRunner(
        base_url=args.app_url,
        timeout=args.timeout,
        verify=not args.insecure,
        cassette_mode=args.cassette,
    )

    results = _dispatch_cases(runner, args.case)
    if not results:
        print("❌ Error: No valid benchmark cases selected.", file=sys.stderr)
        return 2

    all_passed = bool(results) and all(r.status == "PASS" for r in results)
    report_data = _build_report_data(args, results, all_passed)
    _save_reports(args, report_data)
    _print_summary(results, report_data, args.json_report)

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
