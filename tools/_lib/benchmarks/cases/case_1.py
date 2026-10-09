"""
Case 1: Consecutive 4-Month Rollforward and Q1 Articulation benchmark scenario.
"""

from __future__ import annotations

import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from tools._lib.benchmarks.case_types import CaseResult
from tools._lib.benchmarks.oracles import (
    assert_ai_advisor_semantic_grounding,
    assert_triple_accounting_articulation,
)
from tools._lib.benchmarks.statement_generators import (
    generate_consecutive_month1_csv,
    generate_consecutive_month2_csv,
    generate_consecutive_month2_pdf,
    generate_consecutive_month3_csv,
    generate_consecutive_month3_pdf,
    generate_consecutive_month4_csv,
    generate_consecutive_month4_pdf,
)

if TYPE_CHECKING:
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )

REPO_ROOT = Path(__file__).resolve().parents[4]


def _upload_month1_statement(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[str, dict[str, Any], str, str]:
    if getattr(runner, "cassette_mode", "off") == "replay":
        print("  [2/9] Uploading Month 1 (Jan 2025) statement via replay cassette...")
        m1_bytes = generate_consecutive_month1_csv()
        m1_id = runner.upload_statement(
            client,
            m1_bytes,
            "scb_month1_replay.csv",
            institution="Standard Chartered Bank",
        )
    else:
        m1_fixture = (
            REPO_ROOT
            / "common/testing/fixtures/benchmarks/bankstatemently/bsb_001_straits_capital.pdf"
        )
        if not m1_fixture.exists():
            raise FileNotFoundError(
                f"Month 1 fixture not found: {m1_fixture}. Run tools/sync_benchmark_fixtures.py first."
            )

        print("  [2/9] Uploading Month 1 (Jan 2025) statement...")
        m1_id = runner.upload_statement(
            client, m1_fixture.read_bytes(), "bsb_001_straits_capital.pdf"
        )

    m1_data = runner.wait_for_statement_parsed(client, m1_id)
    print(
        f"        M1 parsed: Opening={m1_data['opening_balance']}, "
        f"Closing={m1_data['closing_balance']}, Txns={len(m1_data.get('transactions', []))}"
    )

    runner.adjudicate_unmatched_items(client, m1_id)
    m1_app = runner.approve_statement(client, m1_id)
    print(f"        M1 approved successfully (status={m1_app['status']})")

    m1_refreshed = client.get(f"/api/statements/{m1_id}").json()
    m1_account_id = m1_refreshed.get("account_id")
    m1_institution = m1_refreshed.get("institution") or "Standard Chartered Bank"
    print(f"        M1 Account ID: {m1_account_id} (Institution: {m1_institution})")
    return m1_id, m1_data, m1_account_id, m1_institution


def _ingest_chained_months(
    runner: ScenarioBenchmarkRunner,
    client: httpx.Client,
    temp_dir: Path,
    m1_closing: Decimal,
    m1_account_id: str,
    m1_institution: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    is_replay = getattr(runner, "cassette_mode", "off") == "replay"

    # Month 2
    if is_replay:
        m2_bytes = generate_consecutive_month2_csv(opening_balance=m1_closing)
        m2_filename = "scb_month2_replay.csv"
    else:
        m2_tmp_pdf = temp_dir / "case1_m2_scb.pdf"
        m2_bytes = generate_consecutive_month2_pdf(
            m2_tmp_pdf, opening_balance=m1_closing
        )
        m2_filename = "scb_month2_chained.pdf"

    print(
        f"  [3/9] Uploading Month 2 (Feb 2025) chained statement linked to account {m1_account_id}..."
    )
    m2_id = runner.upload_statement(
        client,
        m2_bytes,
        m2_filename,
        account_id=m1_account_id,
        institution=m1_institution,
    )
    m2_data = runner.wait_for_statement_parsed(client, m2_id)
    print(
        f"        M2 parsed: Opening={m2_data['opening_balance']}, "
        f"Closing={m2_data['closing_balance']}, Txns={len(m2_data.get('transactions', []))}"
    )
    m2_opening = Decimal(m2_data["opening_balance"])
    assert m2_opening == m1_closing, (
        f"Balance chain break: M1 closing ({m1_closing}) != M2 opening ({m2_opening})"
    )
    assert m2_data.get("balance_validated") is True, (
        f"M2 balance not validated: {m2_data}"
    )
    runner.adjudicate_unmatched_items(client, m2_id)
    m2_app = runner.approve_statement(client, m2_id)
    print(f"        M2 approved successfully (status={m2_app['status']})")

    # Month 3
    m2_closing = Decimal(m2_data["closing_balance"])
    if is_replay:
        m3_bytes = generate_consecutive_month3_csv(opening_balance=m2_closing)
        m3_filename = "scb_month3_replay.csv"
    else:
        m3_tmp_pdf = temp_dir / "case1_m3_scb.pdf"
        m3_bytes = generate_consecutive_month3_pdf(
            m3_tmp_pdf, opening_balance=m2_closing
        )
        m3_filename = "scb_month3_chained.pdf"

    print(
        f"  [4/9] Uploading Month 3 (Mar 2025) chained statement linked to account {m1_account_id}..."
    )
    m3_id = runner.upload_statement(
        client,
        m3_bytes,
        m3_filename,
        account_id=m1_account_id,
        institution=m1_institution,
    )
    m3_data = runner.wait_for_statement_parsed(client, m3_id)
    print(
        f"        M3 parsed: Opening={m3_data['opening_balance']}, "
        f"Closing={m3_data['closing_balance']}, Txns={len(m3_data.get('transactions', []))}"
    )
    m3_opening = Decimal(m3_data["opening_balance"])
    assert m3_opening == m2_closing, (
        f"Balance chain break: M2 closing ({m2_closing}) != M3 opening ({m3_opening})"
    )
    assert m3_data.get("balance_validated") is True, (
        f"M3 balance not validated: {m3_data}"
    )
    runner.adjudicate_unmatched_items(client, m3_id)
    m3_app = runner.approve_statement(client, m3_id)
    print(f"        M3 approved successfully (status={m3_app['status']})")

    # Month 4
    m3_closing = Decimal(m3_data["closing_balance"])
    if is_replay:
        m4_bytes = generate_consecutive_month4_csv(opening_balance=m3_closing)
        m4_filename = "scb_month4_replay.csv"
    else:
        m4_tmp_pdf = temp_dir / "case1_m4_scb.pdf"
        m4_bytes = generate_consecutive_month4_pdf(
            m4_tmp_pdf, opening_balance=m3_closing
        )
        m4_filename = "scb_month4_chained.pdf"

    print(
        f"  [5/9] Uploading Month 4 (Apr 2025) chained statement linked to account {m1_account_id}..."
    )
    m4_id = runner.upload_statement(
        client,
        m4_bytes,
        m4_filename,
        account_id=m1_account_id,
        institution=m1_institution,
    )
    m4_data = runner.wait_for_statement_parsed(client, m4_id)
    print(
        f"        M4 parsed: Opening={m4_data['opening_balance']}, "
        f"Closing={m4_data['closing_balance']}, Txns={len(m4_data.get('transactions', []))}"
    )
    m4_opening = Decimal(m4_data["opening_balance"])
    assert m4_opening == m3_closing, (
        f"Balance chain break: M3 closing ({m3_closing}) != M4 opening ({m4_opening})"
    )
    assert m4_data.get("balance_validated") is True, (
        f"M4 balance not validated: {m4_data}"
    )
    runner.adjudicate_unmatched_items(client, m4_id)
    m4_app = runner.approve_statement(client, m4_id)
    print(f"        M4 approved successfully (status={m4_app['status']})")

    return m2_data, m3_data, m4_data


def _verify_q1_checkpoint(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[Decimal, Decimal]:
    print("  [6/9] Verifying Q1 Balance Sheet as of 2025-03-31...")
    bs_q1 = runner.get_balance_sheet(client, as_of_date="2025-03-31")
    q1_assets = Decimal(bs_q1["total_assets"])
    q1_delta = Decimal(bs_q1["equation_delta"])
    q1_balanced = bs_q1["is_balanced"]

    print(
        f"        Q1 Balance Sheet: Assets={q1_assets}, Delta={q1_delta}, Balanced={q1_balanced}"
    )
    assert q1_balanced is True, f"Q1 Balance sheet not balanced: delta={q1_delta}"
    assert q1_delta == Decimal("0.00"), f"Q1 equation delta not zero: {q1_delta}"
    assert q1_assets == Decimal("21300.00"), (
        f"Expected Q1 total assets 21300.00, got {q1_assets}"
    )

    print("  [7/9] Verifying Q1 Income Statement & Cash Flow...")
    inc_q1 = runner.get_income_statement(
        client, start_date="2025-01-01", end_date="2025-03-31"
    )
    q1_net_income = Decimal(inc_q1["net_income"])
    print(f"        Q1 Net Income={q1_net_income}")
    assert q1_net_income == Decimal("5849.25"), (
        f"Expected Q1 cumulative net income 5849.25, got {q1_net_income}"
    )

    cf_q1 = runner.get_cash_flow(client, start_date="2025-01-01", end_date="2025-03-31")
    cf_q1_s = cf_q1.get("summary", {})
    q1_beg_cash = Decimal(cf_q1_s.get("beginning_cash", "0"))
    q1_net_cash = Decimal(cf_q1_s.get("net_cash_flow", "0"))
    q1_end_cash = Decimal(cf_q1_s.get("ending_cash", "0"))
    assert q1_beg_cash == Decimal("15450.75"), f"Q1 beg cash: {q1_beg_cash}"
    assert q1_net_cash == Decimal("5849.25"), f"Q1 net cash: {q1_net_cash}"
    assert q1_end_cash == Decimal("21300.00"), f"Q1 end cash: {q1_end_cash}"
    assert q1_beg_cash + q1_net_cash == q1_end_cash, "Q1 cash rollforward mismatch"
    assert_triple_accounting_articulation(bs_q1, inc_q1)
    return q1_assets, q1_net_income


def _verify_month4_checkpoint(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, bool]:
    print("  [8/9] Verifying 4-Month Rollforward Balance Sheet as of 2025-04-30...")
    bs_m4 = runner.get_balance_sheet(client, as_of_date="2025-04-30")
    total_assets = Decimal(bs_m4["total_assets"])
    total_liabilities = Decimal(bs_m4["total_liabilities"])
    total_equity = Decimal(bs_m4["total_equity"])
    equation_delta = Decimal(bs_m4["equation_delta"])
    is_balanced = bs_m4["is_balanced"]

    print(
        f"        Month 4 Balance Sheet: Assets={total_assets}, Liab={total_liabilities}, "
        f"Equity={total_equity}, Delta={equation_delta}, Balanced={is_balanced}"
    )
    assert is_balanced is True, (
        f"Month 4 Balance sheet not balanced: delta={equation_delta}"
    )
    assert equation_delta == Decimal("0.00"), (
        f"Month 4 equation delta not zero: {equation_delta}"
    )
    assert total_assets == Decimal("24200.00"), (
        f"Expected Month 4 total assets 24200.00, got {total_assets}"
    )
    assert total_equity == Decimal("15450.75"), (
        f"Expected total equity (initial stock) 15450.75, got {total_equity}"
    )

    print("  [9/9] Verifying 4-Month Cumulative Income Statement & Cash Flow...")
    inc_4m = runner.get_income_statement(
        client, start_date="2025-01-01", end_date="2025-04-30"
    )
    cum_net_income = Decimal(inc_4m["net_income"])
    print(f"        4-Month Cumulative Net Income={cum_net_income}")
    assert cum_net_income == Decimal("8749.25"), (
        f"Expected 4-month net income 8749.25, got {cum_net_income}"
    )

    cf_4m = runner.get_cash_flow(client, start_date="2025-01-01", end_date="2025-04-30")
    cf_4m_s = cf_4m.get("summary", {})
    beg_cash = Decimal(cf_4m_s.get("beginning_cash", "0"))
    net_cash = Decimal(cf_4m_s.get("net_cash_flow", "0"))
    end_cash = Decimal(cf_4m_s.get("ending_cash", "0"))
    assert beg_cash == Decimal("15450.75"), f"4-Month beg cash: {beg_cash}"
    assert net_cash == Decimal("8749.25"), f"4-Month net cash: {net_cash}"
    assert end_cash == Decimal("24200.00"), f"4-Month end cash: {end_cash}"
    assert beg_cash + net_cash == end_cash, "4-Month cash rollforward mismatch"
    assert_triple_accounting_articulation(bs_m4, inc_4m)
    return (
        total_assets,
        total_equity,
        cum_net_income,
        beg_cash,
        end_cash,
        equation_delta,
        is_balanced,
    )


def execute_case_1(runner: ScenarioBenchmarkRunner) -> CaseResult:
    """
    Case 1: Consecutive 4-Month Rollforward & Q1 Articulation.
    """
    start_time = time.time()
    case_name = "Case 1: Consecutive 4-Month Rollforward & Q1 Articulation"
    print("\n=======================================================")
    print(f"🚀 RUNNING: {case_name}")
    print("=======================================================")

    try:
        client, user_email, _ = runner.create_ephemeral_client("case1")
        print(f"  [1/9] Registered test user: {user_email}")

        _, m1_data, m1_account_id, m1_institution = _upload_month1_statement(
            runner, client
        )
        m1_closing = Decimal(m1_data["closing_balance"])

        with tempfile.TemporaryDirectory() as td:
            temp_dir = Path(td)
            m2_data, m3_data, m4_data = _ingest_chained_months(
                runner, client, temp_dir, m1_closing, m1_account_id, m1_institution
            )

        q1_assets, q1_net_income = _verify_q1_checkpoint(runner, client)
        (
            total_assets,
            total_equity,
            cum_net_income,
            beg_cash,
            end_cash,
            equation_delta,
            is_balanced,
        ) = _verify_month4_checkpoint(runner, client)

        # Pillar 1: AI Semantic Grounding Oracle
        print("  [10/10] Verifying AI Advisor Grounding & Semantic Invariant...")
        advisor_answer = None
        try:
            advisor_answer = runner.query_ai_advisor(
                client,
                "What is my current net worth and are there any balance discrepancies?",
            )
            print(f"        AI Advisor response: {advisor_answer[:120]}...")
        except Exception as exc:
            if (
                "temporarily unavailable" in str(exc).lower()
                or "503" in str(exc)
                or "api key" in str(exc).lower()
            ):
                print(
                    f"        ⚠️ AI Advisor service unavailable in target environment: {exc}"
                )
            else:
                raise

        if advisor_answer is not None:
            assert_ai_advisor_semantic_grounding(
                advisor_answer,
                expected_figures=["24,200", "24200"],
            )

        duration = time.time() - start_time
        print(f"✅ {case_name} PASSED in {duration:.2f}s\n")
        return CaseResult(
            case_id="case_1",
            case_name=case_name,
            status="PASS",
            duration_seconds=duration,
            details={
                "m1_closing_balance": str(m1_closing),
                "month_1_ending_balance": str(m1_closing),
                "m2_opening_balance": str(m2_data["opening_balance"]),
                "month_2_opening_cash": str(m2_data["opening_balance"]),
                "m2_closing_balance": str(m2_data["closing_balance"]),
                "month_2_ending_balance": str(m2_data["closing_balance"]),
                "m3_opening_balance": str(m3_data["opening_balance"]),
                "month_3_opening_cash": str(m3_data["opening_balance"]),
                "m3_closing_balance": str(m3_data["closing_balance"]),
                "month_3_ending_balance": str(m3_data["closing_balance"]),
                "m4_opening_balance": str(m4_data["opening_balance"]),
                "month_4_opening_cash": str(m4_data["opening_balance"]),
                "m4_closing_balance": str(m4_data["closing_balance"]),
                "month_4_ending_balance": str(m4_data["closing_balance"]),
                "q1_net_income": str(q1_net_income),
                "q1_assets": str(q1_assets),
                "total_assets": str(total_assets),
                "month_4_assets": str(total_assets),
                "total_equity": str(total_equity),
                "cumulative_net_income": str(cum_net_income),
                "beginning_cash": str(beg_cash),
                "ending_cash": str(end_cash),
                "equation_delta": str(equation_delta),
                "is_balanced": is_balanced,
            },
        )
    except Exception as exc:
        duration = time.time() - start_time
        print(f"❌ {case_name} FAILED in {duration:.2f}s: {exc}\n")
        return CaseResult(
            case_id="case_1",
            case_name=case_name,
            status="FAIL",
            duration_seconds=duration,
            error_message=str(exc),
        )
