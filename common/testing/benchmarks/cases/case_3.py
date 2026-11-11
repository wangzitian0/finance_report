"""Case 3: Credit Card Liability & Non-P&L Repayment Clearance benchmark scenario."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from common.testing.benchmarks.case_types import CaseResult
from common.testing.benchmarks.cases._helpers import (
    articulate,
    je_line,
    run_case,
    set_verdict,
)
from common.testing.benchmarks.statement_generators import (
    generate_credit_card_repayment_bank_csv,
)

if TYPE_CHECKING:
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def execute_case_3(runner: ScenarioBenchmarkRunner) -> CaseResult:
    def _body(details: dict[str, Any]) -> None:
        client, _, _ = runner.create_ephemeral_client("case3_card_liability")
        cc_acc = runner.create_account(
            client, name="Citi Rewards Visa Card", type="LIABILITY", currency="SGD"
        )
        exp_acc = runner.create_account(
            client,
            name="Card Operating Expenses - Dining & SaaS",
            type="EXPENSE",
            currency="SGD",
        )

        runner.post_manual_journal_entry(
            client,
            memo="Monthly credit card purchases for dining and software",
            lines=[
                je_line(exp_acc, "DEBIT", "1200.00"),
                je_line(cc_acc, "CREDIT", "1200.00"),
            ],
            entry_date="2025-04-10",
            rationale="Benchmark credit card liability incurrence",
        )
        details["card_spend_recorded"] = "1200.00"
        set_verdict(details, "card_spend_recorded", True)

        stmt_id = runner.upload_statement(
            client,
            generate_credit_card_repayment_bank_csv(
                opening_balance=Decimal("10000.00")
            ),
            "dbs_bank_cc_repayment.csv",
            institution="DBS Bank",
        )
        runner.wait_for_statement_parsed(client, stmt_id)
        runner.adjudicate_unmatched_items(
            client,
            stmt_id,
            non_pnl_intent="card_repayment",
            non_pnl_counter_account_id=cc_acc["id"],
        )
        runner.approve_statement(client, stmt_id)
        details["bank_repayment"] = "1200.00"
        set_verdict(details, "bank_repayment", True)

        bs = runner.get_balance_sheet(client, as_of_date="2025-04-30")
        inc = runner.get_income_statement(
            client, start_date="2025-04-01", end_date="2025-04-30"
        )
        total_assets = Decimal(bs["total_assets"])
        total_liab = Decimal(bs["total_liabilities"])
        total_eq = Decimal(bs["total_equity"])
        delta = Decimal(bs["equation_delta"])
        balanced = bs["is_balanced"]
        total_inc = Decimal(inc["total_income"])
        total_exp = Decimal(inc["total_expenses"])
        net_inc = Decimal(inc["net_income"])

        details.update(
            {
                "ending_bank_cash": str(total_assets),
                "credit_card_liability_cleared": str(total_liab),
                "total_assets": str(total_assets),
                "total_equity": str(total_eq),
                "total_liabilities": str(total_liab),
                "total_income": str(total_inc),
                "total_expenses": str(total_exp),
                "net_income": str(net_inc),
                "equation_delta": str(delta),
                "is_balanced": balanced,
            }
        )
        set_verdict(
            details, "credit_card_liability_cleared", total_liab == Decimal("0.00")
        )
        set_verdict(details, "ending_bank_cash", total_assets == Decimal("8800.00"))
        set_verdict(
            details,
            "net_income",
            total_inc == Decimal("0.00")
            and total_exp == Decimal("1200.00")
            and net_inc == Decimal("-1200.00"),
        )
        set_verdict(
            details,
            "equation_delta",
            balanced is True
            and delta == Decimal("0.00")
            and total_eq == Decimal("10000.00"),
        )
        assert (
            balanced is True
            and delta == Decimal("0.00")
            and total_assets == Decimal("8800.00")
            and total_liab == Decimal("0.00")
            and total_eq == Decimal("10000.00")
            and total_inc == Decimal("0.00")
            and total_exp == Decimal("1200.00")
            and net_inc == Decimal("-1200.00")
        )
        articulate(bs, inc, details, "equation_delta")

        recon_run = runner.run_reconciliation(client)
        assert "matches_created" in recon_run
        accepted = runner.accept_reconciliation_matches(client)
        assert accepted >= 0

        rounding_acc = runner.create_account(
            client,
            name="DBS Rounding Verification Account",
            type="ASSET",
            currency="SGD",
        )
        adj = runner.post_reconciliation_adjustment(
            client,
            account_id=rounding_acc["id"],
            bank_balance="0.02",
            book_balance="0.00",
        )
        assert (
            Decimal(str(adj["difference"])) == Decimal("0.02")
            and adj.get("journal_entry_id") is not None
        )
        bs_after = runner.get_balance_sheet(client, as_of_date="2025-04-30")
        post_ok = bs_after["is_balanced"] is True and Decimal(
            str(bs_after["equation_delta"])
        ) == Decimal("0.00")
        if not post_ok:
            set_verdict(details, "equation_delta", False)
        assert post_ok
        details.update(
            {
                "flow_15_matches_created": int(recon_run["matches_created"]),
                "flow_16_matches_accepted": int(accepted),
                "flow_18_adjustment_difference": str(adj["difference"]),
            }
        )

    return run_case(
        "case_3",
        "Case 3: Credit Card Liability & Non-P&L Repayment Clearance",
        (
            "card_spend_recorded",
            "bank_repayment",
            "credit_card_liability_cleared",
            "ending_bank_cash",
            "net_income",
            "equation_delta",
        ),
        _body,
    )
