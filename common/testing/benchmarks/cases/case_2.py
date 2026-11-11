"""Case 2: Multi-PII Household Operations and Category Reconciliation benchmark scenario."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from common.testing.benchmarks.case_types import CaseResult
from common.testing.benchmarks.cases._helpers import (
    articulate,
    check_verdict,
    run_case,
    set_verdict,
)
from common.testing.benchmarks.statement_generators import (
    generate_household_wife_operations_csv,
    generate_standard_operations_csv,
)

if TYPE_CHECKING:
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def execute_case_2(runner: ScenarioBenchmarkRunner) -> CaseResult:
    def _body(details: dict[str, Any]) -> None:
        client, _, _ = runner.create_ephemeral_client("case2_household")

        h_id = runner.upload_statement(
            client,
            generate_standard_operations_csv(Decimal("10000.00")),
            "husband_dbs_operations.csv",
            institution="DBS Bank",
        )
        h_data = runner.wait_for_statement_parsed(client, h_id)
        details["household_husband_cash"] = str(h_data["closing_balance"])
        check_verdict(
            details,
            "household_husband_cash",
            Decimal(h_data["opening_balance"]) == Decimal("10000.00")
            and Decimal(h_data["closing_balance"]) == Decimal("12800.00"),
        )
        runner.adjudicate_unmatched_items(client, h_id)
        runner.approve_statement(client, h_id)

        w_id = runner.upload_statement(
            client,
            generate_household_wife_operations_csv(Decimal("5000.00")),
            "wife_scb_operations.csv",
            institution="Standard Chartered Bank",
        )
        w_data = runner.wait_for_statement_parsed(client, w_id)
        details["household_wife_cash"] = str(w_data["closing_balance"])
        check_verdict(
            details,
            "household_wife_cash",
            Decimal(w_data["opening_balance"]) == Decimal("5000.00")
            and Decimal(w_data["closing_balance"]) == Decimal("8100.00"),
        )
        runner.adjudicate_unmatched_items(client, w_id)
        runner.approve_statement(client, w_id)

        checks = runner.run_stage2_consistency_checks(client, h_id)
        assert "total" in checks
        batch_res = runner.batch_approve_matches(client)
        assert "approved_count" in batch_res

        h_txns = h_data.get("transactions") or []
        if h_txns and h_txns[0].get("id"):
            assert isinstance(
                runner.list_transaction_anomalies(client, str(h_txns[0]["id"])), list
            )

        bad_id = runner.upload_statement(
            client,
            generate_standard_operations_csv(Decimal("999.00")),
            "corrupted_triage_scan.csv",
            institution="Triage Bank",
        )
        runner.wait_for_statement_parsed(client, bad_id)
        rejected = runner.reject_statement(
            client, bad_id, notes="Corrupted scan discarded during Stage-1 triage"
        )
        assert rejected.get("status") == "rejected"

        bs = runner.get_balance_sheet(client, as_of_date="2025-04-30")
        inc = runner.get_income_statement(
            client, start_date="2025-04-01", end_date="2025-04-30"
        )
        cfs = runner.get_cash_flow(
            client, start_date="2025-04-01", end_date="2025-04-30"
        ).get("summary", {})
        total_assets = Decimal(bs["total_assets"])
        total_equity = Decimal(bs["total_equity"])
        delta = Decimal(bs["equation_delta"])
        balanced = bs["is_balanced"]
        total_inc = Decimal(inc["total_income"])
        total_exp = Decimal(inc["total_expenses"])
        net_inc = Decimal(inc["net_income"])
        beg_cash = Decimal(cfs.get("beginning_cash", "0"))
        net_cash = Decimal(cfs.get("net_cash_flow", "0"))
        end_cash = Decimal(cfs.get("ending_cash", "0"))

        details.update(
            {
                "opening_balance": str(beg_cash),
                "closing_balance": str(end_cash),
                "total_assets": str(total_assets),
                "total_equity": str(total_equity),
                "total_income": str(total_inc),
                "total_expenses": str(total_exp),
                "net_income": str(net_inc),
                "beginning_cash": str(beg_cash),
                "ending_cash": str(end_cash),
                "equation_delta": str(delta),
                "is_balanced": balanced,
                "flow_8_checks_ran": True,
                "flow_9_rejected_status": str(rejected["status"]),
                "flow_12_batch_approved_count": int(batch_res["approved_count"]),
                "flow_29_anomalies_checked": True,
            }
        )
        set_verdict(details, "total_income", total_inc == Decimal("8500.00"))
        set_verdict(details, "total_expenses", total_exp == Decimal("2600.00"))
        set_verdict(details, "net_income", net_inc == Decimal("5900.00"))
        set_verdict(
            details,
            "ending_cash",
            end_cash == Decimal("20900.00")
            and beg_cash == Decimal("15000.00")
            and net_cash == Decimal("5900.00")
            and total_assets == Decimal("20900.00"),
        )
        set_verdict(
            details,
            "equation_delta",
            balanced is True
            and delta == Decimal("0.00")
            and total_equity == Decimal("15000.00"),
        )
        assert (
            balanced is True
            and delta == Decimal("0.00")
            and total_assets == Decimal("20900.00")
            and total_equity == Decimal("15000.00")
            and total_inc == Decimal("8500.00")
            and total_exp == Decimal("2600.00")
            and net_inc == Decimal("5900.00")
            and beg_cash == Decimal("15000.00")
            and net_cash == Decimal("5900.00")
            and end_cash == Decimal("20900.00")
        )
        articulate(bs, inc, details, "equation_delta")

    return run_case(
        "case_2",
        "Case 2: Multi-PII Household Operations & Category Reconciliation",
        (
            "household_husband_cash",
            "household_wife_cash",
            "total_income",
            "total_expenses",
            "net_income",
            "ending_cash",
            "equation_delta",
        ),
        _body,
    )
