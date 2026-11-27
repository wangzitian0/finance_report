#!/usr/bin/env python3
"""Financial Reporting Temporal Scenario Benchmark Suite."""

from __future__ import annotations

import argparse
from collections import Counter
import importlib.metadata
import io
import json
import math
import sys
import time
import uuid
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.runtime.sdk_pin import read_sdk_pin  # noqa: E402
from tests.benchmarks.benchmark_summary import (  # noqa: E402
    extract_summary_data,
    sanitize_for_json,
    write_utf8_atomic,
)
from tests.benchmarks.case_types import (  # noqa: E402
    DOMAIN_TO_CASES,
    FLOW_TO_CASES,
    CaseResult,
)
from tests.benchmarks.cases import (  # noqa: E402
    execute_case_1,
    execute_case_2,
    execute_case_3,
    execute_case_4,
    execute_case_5,
    execute_case_6,
)
from tests.benchmarks.oracles import verify_browser_ui_hygiene  # noqa: E402
from tests.fixtures.provider_review import wait_for_statement_runs_sync  # noqa: E402


def _check_resp(resp: Any, label: str, expected: tuple[int, ...] = (200,)) -> Any:
    if resp.status_code not in expected:
        raise RuntimeError(f"{label}: {resp.status_code} {resp.text}")
    return resp


def _get_json(
    client: httpx.Client,
    url: str,
    label: str,
    expected: tuple[int, ...] = (200,),
    **kwargs: Any,
) -> Any:
    return _check_resp(client.get(url, **kwargs), label, expected).json()


def _post_json(
    client: httpx.Client,
    url: str,
    label: str,
    expected: tuple[int, ...] = (200,),
    **kwargs: Any,
) -> Any:
    return _check_resp(client.post(url, **kwargs), label, expected).json()


def _patch_json(
    client: httpx.Client,
    url: str,
    label: str,
    expected: tuple[int, ...] = (200,),
    **kwargs: Any,
) -> Any:
    return _check_resp(client.patch(url, **kwargs), label, expected).json()


def _qs(*pairs: tuple[str, Any]) -> str:
    parts = [f"{k}={v}" for k, v in pairs if v is not None and v != ""]
    return f"?{'&'.join(parts)}" if parts else ""


class ScenarioBenchmarkRunner:
    """Benchmark scenario runner connecting to the target API."""

    ENVELOPE_FACTS = (
        "currency",
        "period_start",
        "period_end",
        "opening_balance",
        "closing_balance",
    )

    def __init__(
        self,
        base_url: str,
        timeout: float = 180.0,
        verify: bool = True,
        replay_mode: str = "off",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify = verify
        self.replay_mode = replay_mode
        self.last_auth_context: dict[str, Any] | None = None
        self._counter_accounts_cache: dict[tuple[str, str, str], str] = {}

    def create_ephemeral_client(self, prefix: str = "qa_bench") -> tuple[httpx.Client, str, dict[str, Any]]:
        client = httpx.Client(base_url=self.base_url, verify=self.verify, timeout=self.timeout)
        user_email = f"{prefix}_{uuid.uuid4().hex[:8]}@test.example.com"
        user_data = _post_json(
            client,
            "/api/auth/register",
            "User registration failed",
            expected=(200, 201),
            json={
                "email": user_email,
                "password": "Password123!",
                "display_name": f"Benchmark Runner {prefix}",
            },
        )
        token = user_data.get("access_token")
        if not token:
            raise RuntimeError(f"No access token returned: {user_data}")
        client.headers.update({"Authorization": f"Bearer {token}"})
        self.pin_explicit_review_path(client)
        self.last_auth_context = {
            "client": client,
            "user_email": user_email,
            "user_data": user_data,
        }
        return client, user_email, user_data

    def pin_explicit_review_path(self, client: httpx.Client) -> None:
        resp = _check_resp(
            client.patch(
                "/api/users/me/settings",
                json={
                    "enable_ai_classification": False,
                    "auto_accept_ai_suggestions": False,
                },
            ),
            "Pinning explicit review path failed",
        )
        settings = resp.json()
        if (
            settings.get("enable_ai_classification") is not False
            or settings.get("auto_accept_ai_suggestions_active") is not False
        ):
            raise RuntimeError(f"Explicit review path not in effect: {settings}")

    def upload_statement(
        self,
        client: httpx.Client,
        file_bytes: bytes,
        filename: str,
        account_id: str | None = None,
        institution: str | None = None,
        currency: str = "SGD",
    ) -> str:
        if filename.endswith(".csv") and not institution:
            institution = "Operating"
        if filename.endswith(".csv") and not account_id:
            account_name = f"{institution} Cash Account"
            cache: dict[tuple[int, str, str], str] = getattr(self, "_client_account_cache", {})
            self._client_account_cache = cache
            cache_key = (id(client), account_name, currency)
            account_id = cache.get(cache_key)
            if account_id is None:
                account_id = str(self.create_account(client, name=account_name, type="ASSET", currency=currency)["id"])
                cache[cache_key] = account_id

        content_type = "text/csv" if filename.endswith(".csv") else "application/pdf"
        data = {k: str(v) for k, v in (("account_id", account_id), ("institution", institution)) if v}
        body = _post_json(
            client,
            "/api/statements",
            "Statement upload failed",
            expected=(200, 201, 202),
            files={"file": (filename, file_bytes, content_type)},
            data=data,
        )
        if not body.get("id"):
            raise RuntimeError(f"Upload response missing statement ID: {body}")
        return str(body["id"])

    def wait_for_statement_parsed(
        self,
        client: httpx.Client,
        statement_id: str,
        max_wait_seconds: int = 150,
        poll_interval: int = 3,
        max_rate_limit_retries: int = 2,
        retry_backoff_seconds: float = 15.0,
    ) -> dict[str, Any]:
        start = time.time()
        retries_used = 0
        while time.time() - start < max_wait_seconds:
            data = _get_json(
                client,
                f"/api/statements/{statement_id}",
                f"Polling statement {statement_id} failed",
            )
            status = data.get("status")
            if status in ("parsed", "approved"):
                return data
            if status in ("rejected", "failed"):
                err = str(data.get("validation_error") or "Unknown validation error")
                runs_resp = client.get(f"/api/statements/{statement_id}/runs")
                latest_error_code = None
                if runs_resp.status_code == 200:
                    run_items = runs_resp.json().get("items") or []
                    if run_items:
                        latest_error_code = run_items[-1].get("error_code")
                is_rate_limited = latest_error_code == "provider_rate_limited" or "RateLimitError" in err
                if is_rate_limited and retries_used < max_rate_limit_retries:
                    retries_used += 1
                    time.sleep(retry_backoff_seconds)
                    _check_resp(
                        client.post(f"/api/statements/{statement_id}/runs", json={}),
                        f"Retrying statement {statement_id} failed",
                        expected=(200, 202),
                    )
                    start = time.time()
                    continue
                raise RuntimeError(f"Statement {statement_id} entered terminal failure state '{status}': {err}")
            time.sleep(poll_interval)
        raise TimeoutError(
            f"Statement {statement_id} did not reach parsed or approved status within {max_wait_seconds}s"
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
        items = _get_json(
            client,
            f"/api/reconciliation/unmatched?statement_id={statement_id}",
            "Failed to fetch unmatched items",
        ).get("items", [])
        if not items:
            return 0
        if not currency:
            stmt_resp = client.get(f"/api/statements/{statement_id}")
            currency = stmt_resp.json().get("currency", "SGD") if stmt_resp.status_code == 200 else "SGD"

        def counter_account(acc_type: str, curr: str) -> str:
            scope = str(client.headers.get("Authorization") or id(client))
            key = (scope, acc_type, curr)
            if key not in self._counter_accounts_cache:
                target_name = f"{acc_type.capitalize()} - Other {curr}"
                list_resp = client.get("/api/accounts")
                if list_resp.status_code == 200 and isinstance(list_resp.json(), dict):
                    for existing in list_resp.json().get("items", []):
                        if (
                            existing.get("name") == target_name
                            and existing.get("type") == acc_type
                            and existing.get("currency") == curr
                            and existing.get("id")
                        ):
                            self._counter_accounts_cache[key] = str(existing["id"])
                            break
            if key not in self._counter_accounts_cache:
                self._counter_accounts_cache[key] = self.create_account(
                    client,
                    name=f"{acc_type.capitalize()} - Other {curr}",
                    type=acc_type,
                    currency=curr,
                )["id"]
            return self._counter_accounts_cache[key]

        for item in items:
            txn_id = item["id"]
            desc = item.get("description", "")
            txn_curr = item.get("currency") or currency
            if non_pnl_intent and non_pnl_counter_account_id:
                payload = {
                    "intent": non_pnl_intent,
                    "counter_account_id": non_pnl_counter_account_id,
                    "rationale": f"Benchmark non-P&L disposition for {desc}",
                }
            else:
                is_in = item.get("direction", "OUT") == "IN"
                payload = {
                    "intent": "income" if is_in else "expense",
                    "counter_account_id": counter_account("INCOME" if is_in else "EXPENSE", txn_curr),
                    "category": (default_income_category if is_in else default_expense_category),
                    "rationale": f"Benchmark disposition for {desc}",
                }
            _post_json(
                client,
                f"/api/reconciliation/unmatched/{txn_id}/reviewed-dispositions",
                f"Adjudication failed for txn {txn_id}",
                json=payload,
            )
        return len(items)

    def confirm_review_envelope(self, client: httpx.Client, statement_id: str) -> None:
        review = _get_json(
            client,
            f"/api/statements/{statement_id}/review",
            f"Review lookup failed for statement {statement_id}",
        )
        stmt = _get_json(
            client,
            f"/api/statements/{statement_id}",
            f"Failed to fetch statement {statement_id}",
        )
        missing = [k for k in self.ENVELOPE_FACTS if stmt.get(k) in (None, "")]
        if missing:
            raise RuntimeError(
                f"Cannot confirm the review envelope for statement {statement_id}: "
                f"the parsed statement has no {', '.join(missing)}"
            )
        _post_json(
            client,
            f"/api/statements/{statement_id}/review-envelopes",
            f"Review envelope confirmation failed for statement {statement_id}",
            expected=(200, 201),
            json={
                "source_result_digest": review.get("source_result_digest"),
                "account_id": review.get("account_id") or stmt.get("account_id"),
                **{k: str(stmt[k]) for k in self.ENVELOPE_FACTS},
                "rationale": "Benchmark automated review envelope confirmation",
            },
        )

    @staticmethod
    def _approval_body(client: httpx.Client, statement_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Return ``body`` plus the extraction result that the current review shows (#3025)."""
        review = _get_json(
            client, f"/api/statements/{statement_id}/review", f"Review lookup failed for statement {statement_id}"
        )
        digest = review.get("source_result_digest")
        return {**body, "expected_source_result_digest": digest} if digest else body

    def approve_statement(self, client: httpx.Client, statement_id: str) -> dict[str, Any]:
        current = client.get(f"/api/statements/{statement_id}")
        if current.status_code == 200 and current.json().get("status") == "approved":
            return current.json()
        # The approval answers 409 while the classify run of the statement is active (#2994).
        wait_for_statement_runs_sync(client, f"/api/statements/{statement_id}/runs")
        url = f"/api/statements/{statement_id}/approvals"
        resp = client.post(url, json=self._approval_body(client, statement_id, {"create_account_if_missing": True}))
        if resp.status_code == 400:
            err_id = resp.json().get("error_id") if resp.headers.get("content-type", "").startswith("application/json") else None
            if err_id == "envelope_confirmation_required" or "requires explicit human confirmation before posting" in resp.text:
                self.confirm_review_envelope(client, statement_id)
                resp = client.post(url, json=self._approval_body(client, statement_id, {"create_account_if_missing": True}))
        return _check_resp(resp, f"Approval failed for statement {statement_id}").json()

    def reject_statement(
        self,
        client: httpx.Client,
        statement_id: str,
        notes: str = "Low quality corrupted scan rejected in triage",
    ) -> dict[str, Any]:
        """Stage 1 reject triggers immediate reparse (`parsing`) and logs rejection feedback."""
        data = _post_json(
            client,
            f"/api/statements/{statement_id}/rejections",
            f"Rejection failed for statement {statement_id}",
            json={"notes": notes},
        )
        if data.get("status") not in ("parsing", "parsed", "rejected"):
            raise RuntimeError(f"Expected parsing/parsed/rejected status for statement {statement_id}, got: {data}")
        return data

    def retire_statement(self, client: httpx.Client, statement_id: str) -> None:
        """Retire a statement from ledger and review views via DELETE (#3255)."""
        _check_resp(
            client.delete(f"/api/statements/{statement_id}"),
            f"Retirement failed for statement {statement_id}",
            expected=(200, 204),
        )

    def assert_approval_blocked_by_balance_mismatch(self, client: httpx.Client, statement_id: str) -> dict[str, Any]:
        # The body names the reviewed result, so the block below comes from the balance check and not from a missing digest.
        resp = client.post(f"/api/statements/{statement_id}/approvals", json=self._approval_body(client, statement_id, {}))
        if resp.status_code not in (400, 422) or "expected_source_result_digest" in resp.text:
            raise RuntimeError(
                f"Expected balance mismatch approval block (400/422) for {statement_id}, got {resp.status_code}: {resp.text}"
            )
        body = resp.json()
        return {
            "status_code": resp.status_code,
            "detail": body.get("detail", resp.text) if isinstance(body, dict) else resp.text,
        }

    def assert_brokerage_import_requires_snapshot_date(self, client: httpx.Client, statement_id: str) -> dict[str, Any]:
        resp = client.post("/api/portfolio/brokerage-imports", json={"statement_id": statement_id})
        if resp.status_code != 422:
            raise RuntimeError(
                f"Expected undated brokerage CSV import to fail with 422 for {statement_id}, got {resp.status_code}: {resp.text}"
            )
        body = resp.json()
        if not (
            isinstance(body, dict)
            and (body.get("error_id") == "brokerage_snapshot_date_missing" or "snapshot" in str(body).lower())
        ):
            raise RuntimeError(f"Expected brokerage_snapshot_date_missing error for {statement_id}, got: {body}")
        return body

    def get_data_quality_health(
        self,
        client: httpx.Client,
        as_of_date: str | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        params = {k: v for k, v in (("as_of_date", as_of_date), ("currency", currency)) if v}
        return _get_json(
            client,
            "/api/reports/data-quality",
            "Get data quality health failed",
            params=params,
        )

    def run_stage2_consistency_checks(self, client: httpx.Client, statement_id: str) -> dict[str, Any]:
        return _post_json(
            client,
            "/api/reconciliation/consistency-checks/runs",
            f"Stage 2 consistency checks failed for {statement_id}",
            json={"statement_id": statement_id},
        )

    def batch_approve_matches(self, client: httpx.Client, match_ids: list[str] | None = None) -> dict[str, Any]:
        return _post_json(
            client,
            "/api/reconciliation/matches",
            "Batch approve matches failed",
            json={"action": "accept", "match_ids": match_ids or []},
        )

    def run_reconciliation(self, client: httpx.Client, statement_id: str | None = None) -> dict[str, Any]:
        payload = {"statement_id": statement_id} if statement_id else {}
        return _post_json(
            client,
            "/api/reconciliation/runs",
            "Reconciliation run failed",
            json=payload,
        )

    def accept_reconciliation_matches(self, client: httpx.Client) -> int:
        items = _get_json(
            client,
            "/api/reconciliation/matches?status=pending_review",
            "Listing pending reconciliation matches failed",
        ).get("items", [])
        for match in items:
            match_id = match["id"]
            _patch_json(
                client,
                f"/api/reconciliation/matches/{match_id}",
                f"Accepting reconciliation match {match_id} failed",
                json={"action": "accept"},
            )
        return len(items)

    def list_transaction_anomalies(self, client: httpx.Client, txn_id: str) -> list[dict[str, Any]]:
        return _get_json(
            client,
            f"/api/reconciliation/transactions/{txn_id}/anomalies",
            f"Transaction anomalies request failed for {txn_id}",
        )

    def post_reconciliation_adjustment(
        self,
        client: httpx.Client,
        account_id: str,
        bank_balance: str,
        book_balance: str,
        threshold: str = "0.05",
    ) -> dict[str, Any]:
        return _post_json(
            client,
            "/api/reconciliation/adjustments",
            "Reconciliation adjustment failed",
            json={
                "account_id": account_id,
                "bank_balance": bank_balance,
                "book_balance": book_balance,
                "threshold": threshold,
            },
        )

    def get_report_coverage(self, client: httpx.Client, as_of_date: str | None = None) -> dict[str, Any]:
        return _get_json(
            client,
            f"/api/reports/coverage{_qs(('as_of_date', as_of_date))}",
            "Report coverage request failed",
        )

    def get_balance_sheet_diagnostics(
        self,
        client: httpx.Client,
        as_of_date: str | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        q = _qs(("as_of_date", as_of_date), ("currency", currency))
        return _get_json(
            client,
            f"/api/reports/balance-sheet/diagnostics{q}",
            "Balance sheet diagnostics request failed",
        )

    def get_account_lineage(
        self,
        client: httpx.Client,
        account_id: str,
        as_of_date: str | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        q = _qs(
            ("account_id", account_id),
            ("as_of_date", as_of_date),
            ("currency", currency),
        )
        return _get_json(
            client,
            f"/api/reports/account-lineage{q}",
            f"Account lineage request failed for {account_id}",
        )

    def export_annual_tax_archive(
        self,
        client: httpx.Client,
        year: int = 2025,
        currency: str = "SGD",
    ) -> dict[str, Any]:
        snapshot = _post_json(
            client,
            "/api/reports/package/snapshots",
            "Annual tax snapshot creation failed",
            json={
                "framework_id": "personal_us_gaap_like",
                "start_date": f"{year}-01-01",
                "end_date": f"{year}-12-31",
                "as_of_date": f"{year}-12-31",
                "currency": currency,
            },
        )
        snapshot_id = snapshot.get("id")
        if not snapshot_id:
            raise RuntimeError(f"Annual tax snapshot response missing id: {snapshot}")
        resp = _check_resp(
            client.get(
                f"/api/reports/package/snapshots/{snapshot_id}/exports",
                params={"format": "zip"},
            ),
            "Annual tax archive export failed",
        )
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if not manifest.get("files"):
            raise RuntimeError(f"Annual tax archive manifest has no files: {manifest}")
        return manifest

    def get_balance_sheet(
        self,
        client: httpx.Client,
        as_of_date: str | None = None,
        currency: str | None = None,
        include_restricted: bool | None = None,
    ) -> dict[str, Any]:
        inc = None if include_restricted is None else ("true" if include_restricted else "false")
        q = _qs(
            ("as_of_date", as_of_date),
            ("currency", currency),
            ("include_restricted", inc),
        )
        return _get_json(client, f"/api/reports/balance-sheet{q}", "Balance sheet request failed")

    def get_income_statement(self, client: httpx.Client, start_date: str, end_date: str) -> dict[str, Any]:
        return _get_json(
            client,
            f"/api/reports/income-statement?start_date={start_date}&end_date={end_date}",
            "Income statement request failed",
        )

    def get_cash_flow(self, client: httpx.Client, start_date: str, end_date: str) -> dict[str, Any]:
        return _get_json(
            client,
            f"/api/reports/cash-flow?start_date={start_date}&end_date={end_date}",
            "Cash flow request failed",
        )

    def import_brokerage_positions(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
        filename: str = "brokerage_statement.csv",
        source_document_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"filename": filename, "payload": payload}
        if source_document_id is not None:
            body["source_document_id"] = source_document_id
        return _post_json(
            client,
            "/api/portfolio/brokerage-imports",
            "Brokerage import request failed",
            json=body,
        )

    def get_holdings(self, client: httpx.Client, as_of_date: str | None = None) -> dict[str, Any]:
        return _get_json(
            client,
            f"/api/portfolio/holdings{_qs(('as_of_date', as_of_date))}",
            "Holdings request failed",
        )

    def update_market_prices(self, client: httpx.Client, updates: list[dict[str, Any]]) -> dict[str, Any]:
        return _post_json(
            client,
            "/api/pricing/price-overrides",
            "Price update failed",
            json={"updates": updates},
        )

    def create_account(
        self,
        client: httpx.Client,
        name: str,
        type: str,
        currency: str = "SGD",
    ) -> dict[str, Any]:
        return _post_json(
            client,
            "/api/accounts",
            f"Failed to create account '{name}'",
            expected=(200, 201),
            json={"name": name, "type": type, "currency": currency},
        )

    def post_manual_journal_entry(
        self,
        client: httpx.Client,
        memo: str,
        lines: list[dict[str, Any]],
        entry_date: str = "2025-04-10",
        rationale: str = "Benchmark manual journal entry",
    ) -> dict[str, Any]:
        draft = _post_json(
            client,
            "/api/journal-entries",
            "Failed to create draft journal entry",
            expected=(200, 201),
            json={
                "entry_date": entry_date,
                "memo": memo,
                "lines": lines,
                "rationale": rationale,
            },
        )
        entry_id = draft["id"]
        return _post_json(
            client,
            f"/api/journal-entries/{entry_id}/postings",
            f"Failed to post journal entry {entry_id}",
            expected=(200, 201),
        )

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
        return _post_json(
            client,
            "/api/pricing/manual-valuations",
            "Valuation snapshot failed",
            expected=(200, 201),
            json=payload,
        )

    def get_valuation_components(self, client: httpx.Client, as_of_date: str | None = None) -> dict[str, Any]:
        return _get_json(
            client,
            f"/api/pricing/valuation-components{_qs(('as_of_date', as_of_date))}",
            "Valuation components request failed",
        )

    def query_ai_advisor(self, client: httpx.Client, question: str) -> str:
        return _check_resp(
            client.post("/api/chat", json={"message": question}, timeout=self.timeout),
            "AI Advisor request failed",
        ).text

    def verify_browser_ui_hygiene(
        self,
        auth_context: dict[str, Any] | None = None,
        routes: list[str] | None = None,
        allow_skip_if_no_browser: bool = True,
    ) -> dict[str, Any]:
        return verify_browser_ui_hygiene(
            self,
            auth_context=auth_context,
            routes=routes,
            allow_skip_if_no_browser=allow_skip_if_no_browser,
        )


def execute_case_ui(runner: ScenarioBenchmarkRunner) -> CaseResult:
    start_time = time.time()
    case_name = "Case UI: Browser Zero-Console-Error & DOM Hygiene Oracle"
    try:
        if not runner.last_auth_context:
            runner.create_ephemeral_client("case_ui")
        hygiene_res = runner.verify_browser_ui_hygiene(allow_skip_if_no_browser=True)
        status = "SKIPPED" if hygiene_res.get("status") == "SKIPPED" else "PASS"
        return CaseResult(
            case_id="case_ui",
            case_name=case_name,
            status=status,
            duration_seconds=time.time() - start_time,
            details=hygiene_res,
        )
    except Exception as exc:
        return CaseResult(
            case_id="case_ui",
            case_name=case_name,
            status="FAIL",
            duration_seconds=time.time() - start_time,
            error_message=str(exc),
        )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Financial Reporting Multi-Scenario Benchmark Suite.")
    parser.add_argument("--app-url", default="https://report-staging.zitian.party")
    parser.add_argument("--case", default=None)
    parser.add_argument("--version-ref", default="v2.0")
    parser.add_argument("--json-report", type=Path, default=REPO_ROOT / "tmp/benchmark_run_report.json")
    parser.add_argument("--output-summary", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--insecure", action="store_true", default=False)
    parser.add_argument("--cassette", choices=["replay", "off"], default="off")
    parser.add_argument("--domain", type=str, default=None)
    parser.add_argument("--flow", type=str, default=None)
    parser.add_argument("--verify-ui", action="store_true", default=False)
    parser.add_argument("--allow-skip", action="store_true", default=False)
    return parser.parse_args(argv)


def _normalize_case_id(token: str) -> str:
    token = token.strip().lower()
    for prefix in ("case_", "case"):
        if token.startswith(prefix):
            return token[len(prefix) :]
    return token


def _dispatch_cases(
    runner: ScenarioBenchmarkRunner,
    case_arg: str,
    domain_arg: str | None = None,
    flow_arg: str | None = None,
) -> list[CaseResult]:
    executors = {
        "1": execute_case_1,
        "2": execute_case_2,
        "3": execute_case_3,
        "4": execute_case_4,
        "5": execute_case_5,
        "6": execute_case_6,
    }
    requested = {_normalize_case_id(c) for c in case_arg.split(",") if c.strip()}
    unknown_cases = sorted(requested - set(executors) - {"all", "ui"})
    if unknown_cases:
        raise ValueError(f"Unknown benchmark case id(s) {unknown_cases}; valid ids are 1 to 6, ui, all")

    for ids, label, mapping in (
        (domain_arg, "domain", DOMAIN_TO_CASES),
        (flow_arg, "flow", FLOW_TO_CASES),
    ):
        if not ids:
            continue
        unknown_ids: list[str] = []
        for raw in ids.split(","):
            token = raw.strip().lower()
            if not token:
                continue
            if token == "all":
                for cases in mapping.values():
                    requested.update(cases)
            elif token.isdigit() and int(token) in mapping:
                requested.update(mapping[int(token)])
            else:
                unknown_ids.append(raw.strip())
        if unknown_ids:
            raise ValueError(f"Unknown {label} id(s) {unknown_ids}")

    run_all = "all" in requested
    results = [executors[cid](runner) for cid in sorted(executors) if run_all or cid in requested]
    if run_all or "ui" in requested or getattr(runner, "verify_ui", False):
        results.append(execute_case_ui(runner))
    return results


DEFAULT_RATCHET_POLICY_PATH = REPO_ROOT / "tests" / "fixtures" / "benchmarks" / "ratchet_policy.json"


def _load_scenario_ratchet_policy(path: Path = DEFAULT_RATCHET_POLICY_PATH) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    sec = raw.get("financial_scenario_benchmark")
    return dict(sec) if isinstance(sec, Mapping) else None


def _percentile_seconds(values: Sequence[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(ratio * len(ordered)) - 1))
    return round(ordered[idx], 3)


def _classify_case_error(result: CaseResult) -> str:
    msg = str(result.error_message or "")
    if "Timeout" in msg or "Timed out" in msg:
        return "TIMEOUT"
    if "review-envelopes" in msg or "Envelope confirmation" in msg:
        return "ENVELOPE_CONFIRMATION_FAILED"
    if "Rejection failed" in msg or "Expected rejected" in msg:
        return "REJECTION_SEMANTICS_ERROR"
    if "equation" in msg.lower() or "balanced" in msg.lower():
        return "EQUATION_INVARIANT_FAILED"
    return "CASE_ASSERTION_FAILED"


def evaluate_scenario_ratchet(
    results: Sequence[CaseResult],
    policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Check zero equation delta invariant and non-regression ratchet floor."""
    hard_failures: list[str] = []
    max_delta_limit = Decimal(str((policy or {}).get("max_equation_delta", "0.00")))
    for r in results:
        details = r.details if isinstance(r.details, Mapping) else {}
        if details.get("is_balanced") is False:
            hard_failures.append(f"{r.case_id}:is_balanced=False")
        if r.status not in ("PASS", "SKIPPED") and _classify_case_error(r) == "EQUATION_INVARIANT_FAILED":
            hard_failures.append(f"{r.case_id}:EQUATION_INVARIANT_FAILED")
        for key in ("equation_delta", "equation_delta_sgd", "equation_delta_usd"):
            raw = details.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                val = abs(Decimal(str(raw)))
            except InvalidOperation:
                continue
            if val > max_delta_limit:
                hard_failures.append(f"{r.case_id}:{key}={val}")

    passed = sum(1 for r in results if r.status == "PASS")
    total_expected = (
        int(policy["total_expected"])
        if policy and policy.get("total_expected") is not None
        else len(results)
    )
    enforced = bool(policy and len(results) >= total_expected > 0)
    floor_passed = (
        int(policy["floor_passed"])
        if policy and policy.get("floor_passed") is not None
        else len(results)
    )
    hard_invariant_ok = not hard_failures
    all_passed = all(r.status in ("PASS", "SKIPPED") for r in results) and passed >= 1
    gate_passed = hard_invariant_ok and (passed >= floor_passed if enforced else all_passed)
    return {
        "enforced": enforced,
        "floor_passed": floor_passed if enforced else len(results),
        "total_expected": total_expected,
        "passed": passed,
        "hard_invariant_ok": hard_invariant_ok,
        "hard_invariant_failures": hard_failures,
        "gate_passed": gate_passed,
    }


def _build_report_data(
    args: argparse.Namespace,
    results: list[CaseResult],
    all_passed: bool,
    ratchet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    durations = [float(r.duration_seconds) for r in results]
    error_counts = dict(Counter(_classify_case_error(r) for r in results if r.status not in ("PASS", "SKIPPED")))
    effective_success = bool(ratchet["gate_passed"]) if (ratchet and ratchet.get("enforced")) else all_passed
    summary: dict[str, Any] = {
        "total": len(results),
        "passed": sum(1 for r in results if r.status == "PASS"),
        "skipped": sum(1 for r in results if r.status == "SKIPPED"),
        "failed": sum(1 for r in results if r.status not in ("PASS", "SKIPPED")),
        "all_passed": all_passed,
        "success": effective_success,
        "p50_seconds": _percentile_seconds(durations, 0.50),
        "p95_seconds": _percentile_seconds(durations, 0.95),
        "error_code_counts": error_counts,
    }
    if ratchet is not None:
        summary["ratchet"] = dict(ratchet)
    return {
        "suite": "financial_reporting_temporal_scenarios",
        "version_ref": args.version_ref,
        "app_url": args.app_url,
        "run_at": datetime.now(UTC).isoformat(),
        "summary": summary,
        "results": [asdict(r) for r in results],
    }


def _save_reports(args: argparse.Namespace, report_data: dict[str, Any]) -> None:
    safe_report = sanitize_for_json(report_data)
    if args.json_report:
        write_utf8_atomic(args.json_report, json.dumps(safe_report, indent=2))

    if args.output_summary:
        summary_data = sanitize_for_json(extract_summary_data(safe_report))
        write_utf8_atomic(args.output_summary, json.dumps(summary_data, indent=2))


def _print_summary(
    results: list[CaseResult],
    report_data: dict[str, Any],
    json_report_path: Path | None,
) -> None:
    for r in results:
        print(f"{r.status} | {r.case_id.upper()}: {r.case_name} ({r.duration_seconds:.2f}s)")
        if r.error_message:
            print(f"  Error: {r.error_message}")
    s = report_data["summary"]
    print(f"Total: {len(results)} | Passed: {s['passed']} | Skipped: {s['skipped']} | Failed: {s['failed']}")
    if json_report_path:
        print(f"Report saved to: {json_report_path}")


def _run_succeeded(results: list[CaseResult], allow_skip: bool) -> bool:
    if any(r.status not in ("PASS", "SKIPPED") for r in results):
        return False
    if not allow_skip and any(r.status == "SKIPPED" for r in results):
        return False
    return any(r.status == "PASS" for r in results)


def _check_sdk_version(repo_root: Path = REPO_ROOT) -> str | None:
    """Warn if installed infra2-sdk differs from the locked backend pin (#2885)."""
    try:
        _, _, filename = read_sdk_pin(repo_root)
    except (FileNotFoundError, OSError, ValueError):
        return None
    pinned = filename.removeprefix("infra2_sdk-").removesuffix("-py3-none-any.whl")
    try:
        installed = importlib.metadata.version("infra2-sdk")
    except importlib.metadata.PackageNotFoundError:
        installed = "not installed"
    if installed == pinned:
        return None
    message = (
        f"Warning: infra2-sdk version mismatch: pinned={pinned}, installed={installed}. "
        "Run 'cd apps/backend && uv sync --frozen'."
    )
    print(message, file=sys.stderr)
    return message


def main(argv: Sequence[str] | None = None) -> int:
    _check_sdk_version()
    args = _parse_args(argv)
    case_arg = args.case if args.case is not None else ("" if (args.domain or args.flow) else "all")
    runner = ScenarioBenchmarkRunner(
        base_url=args.app_url,
        timeout=args.timeout,
        verify=not args.insecure,
        replay_mode=args.cassette,
    )
    runner.verify_ui = args.verify_ui
    try:
        results = _dispatch_cases(runner, case_arg, domain_arg=args.domain, flow_arg=args.flow)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if not results:
        print("Error: No valid benchmark cases selected.", file=sys.stderr)
        return 2
    all_passed = _run_succeeded(results, args.allow_skip)
    core_case_ids = {f"case_{i}" for i in range(1, 7)}
    is_full_suite = (
        not args.domain
        and not args.flow
        and core_case_ids.issubset({r.case_id for r in results})
    )
    ratchet_policy = _load_scenario_ratchet_policy() if is_full_suite else None
    ratchet = evaluate_scenario_ratchet(results, ratchet_policy)
    report_data = _build_report_data(args, results, all_passed, ratchet=ratchet)
    _save_reports(args, report_data)
    _print_summary(results, report_data, args.json_report)
    if is_full_suite and ratchet_policy is not None:
        return 0 if ratchet["gate_passed"] else 1
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
