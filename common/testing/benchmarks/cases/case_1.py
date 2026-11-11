"""Case 1: Consecutive 4-Month Rollforward and Q1 Articulation benchmark scenario."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from common.testing.benchmarks.case_types import CaseResult
from common.testing.benchmarks.cases._helpers import (
    articulate,
    check_verdict,
    run_case,
    set_verdict,
)
from common.testing.benchmarks.statement_generators import (
    generate_consecutive_month1_csv,
    generate_consecutive_month2_csv,
    generate_consecutive_month3_csv,
    generate_consecutive_month4_csv,
)

if TYPE_CHECKING:
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )

M1_EXPECTED_OPENING = Decimal("15450.75")
M1_EXPECTED_CLOSING = Decimal("15271.23")
M2_EXPECTED_OPENING = Decimal("15271.23")
M2_EXPECTED_CLOSING = Decimal("18250.00")
M3_EXPECTED_OPENING = Decimal("18250.00")
M3_EXPECTED_CLOSING = Decimal("21300.00")
M4_EXPECTED_OPENING = Decimal("21300.00")
M4_EXPECTED_CLOSING = Decimal("24200.00")


def _upload_month1_statement(
    runner: ScenarioBenchmarkRunner,
    client: httpx.Client,
    details: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], str, str]:
    m1_id = runner.upload_statement(
        client,
        generate_consecutive_month1_csv(),
        "scb_month1_replay.csv",
        institution="Standard Chartered Bank",
    )
    m1_data = runner.wait_for_statement_parsed(client, m1_id)
    if details is not None:
        details["m1_closing_balance"] = str(m1_data["closing_balance"])
    check_verdict(
        details,
        "m1_closing_balance",
        Decimal(m1_data["opening_balance"]) == M1_EXPECTED_OPENING
        and Decimal(m1_data["closing_balance"]) == M1_EXPECTED_CLOSING,
        f"M1 balances ({m1_data['opening_balance']} -> {m1_data['closing_balance']})",
    )
    runner.adjudicate_unmatched_items(client, m1_id)
    runner.approve_statement(client, m1_id)
    m1_refreshed = client.get(f"/api/statements/{m1_id}").json()
    return (
        m1_id,
        m1_data,
        m1_refreshed.get("account_id"),
        m1_refreshed.get("institution") or "Standard Chartered Bank",
    )


def _ingest_chained_months(
    runner: ScenarioBenchmarkRunner,
    client: httpx.Client,
    m1_closing: Decimal,
    m1_account_id: str,
    m1_institution: str,
    details: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    specs = (
        (
            "m2",
            generate_consecutive_month2_csv,
            M2_EXPECTED_OPENING,
            M2_EXPECTED_CLOSING,
        ),
        (
            "m3",
            generate_consecutive_month3_csv,
            M3_EXPECTED_OPENING,
            M3_EXPECTED_CLOSING,
        ),
        (
            "m4",
            generate_consecutive_month4_csv,
            M4_EXPECTED_OPENING,
            M4_EXPECTED_CLOSING,
        ),
    )
    prev_closing = m1_closing
    parsed_months: list[dict[str, Any]] = []
    for tag, gen, exp_open, exp_close in specs:
        stmt_id = runner.upload_statement(
            client,
            gen(opening_balance=exp_open),
            f"scb_month{tag[1]}_replay.csv",
            account_id=m1_account_id,
            institution=m1_institution,
        )
        data = runner.wait_for_statement_parsed(client, stmt_id)
        opening = Decimal(data["opening_balance"])
        closing = Decimal(data["closing_balance"])
        if details is not None:
            details[f"{tag}_opening_balance"] = str(data["opening_balance"])
            details[f"{tag}_closing_balance"] = str(data["closing_balance"])
        check_verdict(
            details,
            f"{tag}_closing_balance",
            opening == prev_closing
            and opening == exp_open
            and closing == exp_close
            and data.get("balance_validated") is True,
            f"{tag.upper()} rollforward mismatch: {opening} -> {closing}",
        )
        runner.adjudicate_unmatched_items(client, stmt_id)
        runner.approve_statement(client, stmt_id)
        prev_closing = closing
        parsed_months.append(data)
    return parsed_months[0], parsed_months[1], parsed_months[2]


def _verify_flow_7_and_24_mismatch_and_diagnostics(
    runner: ScenarioBenchmarkRunner, client: httpx.Client
) -> tuple[bool, bool]:
    tampered_csv = (
        "Date,Description,Amount,Currency,Statement Opening Balance,Statement Closing Balance\n"
        "2025-04-29,TAMPERED DEPOSIT,500.00,SGD,1000.00,9999.00\n"
    ).encode("utf-8")
    bad_id = runner.upload_statement(
        client,
        tampered_csv,
        "tampered_dbs_2025_04_mismatch.csv",
        institution="DBS Bank",
    )
    bad_stmt = runner.wait_for_statement_parsed(client, bad_id)
    if bad_stmt.get("balance_validated") is not False:
        raise RuntimeError(
            f"Expected balance_validated=False for tampered statement {bad_id}, got: {bad_stmt}"
        )
    runner.assert_approval_blocked_by_balance_mismatch(client, bad_id)
    dq_pending = runner.get_data_quality_health(
        client, as_of_date="2025-04-30", currency="SGD"
    )
    if not any(
        item.get("id") == "review_pending_statements"
        for item in dq_pending.get("action_items", [])
    ):
        raise RuntimeError(
            f"Expected review_pending_statements in data-quality action_items while statement {bad_id} is pending, got: {dq_pending}"
        )
    runner.reject_statement(
        client,
        bad_id,
        notes="Tampered closing balance rejected by Flow 7 Stage-1 defense",
    )
    return True, True


def execute_case_1(runner: ScenarioBenchmarkRunner) -> CaseResult:
    def _body(details: dict[str, Any]) -> None:
        client, _, _ = runner.create_ephemeral_client("case1")
        _, m1_data, m1_account_id, m1_institution = _upload_month1_statement(
            runner, client, details=details
        )
        _ingest_chained_months(
            runner,
            client,
            Decimal(m1_data["closing_balance"]),
            m1_account_id,
            m1_institution,
            details=details,
        )
        f7, f24 = _verify_flow_7_and_24_mismatch_and_diagnostics(runner, client)
        details["flow_7_mismatch_blocked"] = f7
        details["flow_24_pending_triage_verified"] = f24

        bs_q1 = runner.get_balance_sheet(client, as_of_date="2025-03-31")
        inc_q1 = runner.get_income_statement(
            client, start_date="2025-01-01", end_date="2025-03-31"
        )
        cf_q1 = runner.get_cash_flow(
            client, start_date="2025-01-01", end_date="2025-03-31"
        ).get("summary", {})
        q1_assets = Decimal(bs_q1["total_assets"])
        q1_ni = Decimal(inc_q1["net_income"])
        q1_beg = Decimal(cf_q1.get("beginning_cash", "0"))
        q1_net = Decimal(cf_q1.get("net_cash_flow", "0"))
        q1_end = Decimal(cf_q1.get("ending_cash", "0"))
        details["q1_net_income"] = str(q1_ni)
        details["q1_assets"] = str(q1_assets)
        check_verdict(
            details,
            "q1_net_income",
            q1_ni == Decimal("5849.25")
            and q1_beg == Decimal("15450.75")
            and q1_net == Decimal("5849.25")
            and q1_end == Decimal("21300.00")
            and q1_assets == Decimal("21300.00")
            and bs_q1["is_balanced"] is True
            and Decimal(bs_q1["equation_delta"]) == Decimal("0.00"),
            "Q1 checkpoint mismatch",
        )
        articulate(bs_q1, inc_q1, details, "q1_net_income")

        bs_m4 = runner.get_balance_sheet(client, as_of_date="2025-04-30")
        inc_4m = runner.get_income_statement(
            client, start_date="2025-01-01", end_date="2025-04-30"
        )
        cf_4m = runner.get_cash_flow(
            client, start_date="2025-01-01", end_date="2025-04-30"
        ).get("summary", {})
        total_assets = Decimal(bs_m4["total_assets"])
        total_equity = Decimal(bs_m4["total_equity"])
        cum_ni = Decimal(inc_4m["net_income"])
        beg_cash = Decimal(cf_4m.get("beginning_cash", "0"))
        net_cash = Decimal(cf_4m.get("net_cash_flow", "0"))
        end_cash = Decimal(cf_4m.get("ending_cash", "0"))
        delta = Decimal(bs_m4["equation_delta"])
        balanced = bs_m4["is_balanced"]
        details.update(
            {
                "total_assets": str(total_assets),
                "total_equity": str(total_equity),
                "cumulative_net_income": str(cum_ni),
                "beginning_cash": str(beg_cash),
                "ending_cash": str(end_cash),
                "equation_delta": str(delta),
                "is_balanced": balanced,
            }
        )
        set_verdict(
            details,
            "cumulative_net_income",
            cum_ni == Decimal("8749.25")
            and beg_cash == Decimal("15450.75")
            and net_cash == Decimal("8749.25")
            and end_cash == Decimal("24200.00"),
        )
        set_verdict(
            details,
            "equation_delta",
            balanced is True
            and delta == Decimal("0.00")
            and total_assets == Decimal("24200.00")
            and total_equity == Decimal("15450.75"),
        )
        assert (
            balanced is True
            and delta == Decimal("0.00")
            and total_assets == Decimal("24200.00")
            and total_equity == Decimal("15450.75")
            and cum_ni == Decimal("8749.25")
            and beg_cash == Decimal("15450.75")
            and net_cash == Decimal("8749.25")
            and end_cash == Decimal("24200.00")
        )
        articulate(bs_m4, inc_4m, details, "equation_delta")

        cov = str(
            runner.get_report_coverage(client, as_of_date="2025-04-30")[
                "coverage_start"
            ]
        )
        assert cov == "2025-01-01"
        details["coverage_start"] = cov

        diag = runner.get_balance_sheet_diagnostics(client, as_of_date="2025-04-30")
        assert (
            diag.get("is_balanced") is True
            and str(diag.get("primary_category") or "").lower() == "balanced"
        )
        details["flow_24_diagnostics_balanced"] = True

        lineage = runner.get_account_lineage(
            client, account_id=str(m1_account_id), as_of_date="2025-04-30"
        )
        lines = lineage.get("lines", [])
        assert len(lines) > 0
        details["flow_27_lineage_lines"] = len(lines)

    return run_case(
        "case_1",
        "Case 1: Consecutive 4-Month Rollforward & Q1 Articulation",
        (
            "m1_closing_balance",
            "m2_closing_balance",
            "m3_closing_balance",
            "m4_closing_balance",
            "q1_net_income",
            "cumulative_net_income",
            "equation_delta",
        ),
        _body,
    )
