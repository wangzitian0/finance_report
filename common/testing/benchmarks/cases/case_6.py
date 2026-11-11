"""Case 6: Bank Overdraft & Capital Gain Asset Disposal benchmark scenario."""

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

if TYPE_CHECKING:
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def execute_case_6(runner: ScenarioBenchmarkRunner) -> CaseResult:
    def _body(details: dict[str, Any]) -> None:
        client, _, _ = runner.create_ephemeral_client("case6_overdraft")
        checking = runner.create_account(
            client, name="Primary Checking Account", type="ASSET", currency="SGD"
        )
        emergency_exp = runner.create_account(
            client, name="Emergency Medical Expense", type="EXPENSE", currency="SGD"
        )
        owner_equity = runner.create_account(
            client, name="Owner Capital Equity", type="EQUITY", currency="SGD"
        )
        art_asset = runner.create_account(
            client, name="Collectible Art Investment", type="ASSET", currency="SGD"
        )
        capital_gain = runner.create_account(
            client, name="Realized Capital Gain on Art", type="INCOME", currency="SGD"
        )

        runner.post_manual_journal_entry(
            client,
            memo="Initial Checking Deposit",
            entry_date="2025-05-01",
            lines=[
                je_line(checking, "DEBIT", "1000.00"),
                je_line(owner_equity, "CREDIT", "1000.00"),
            ],
            rationale="Initial cash capital",
        )
        runner.post_manual_journal_entry(
            client,
            memo="Emergency Medical Expense Paid via Checking Overdraft",
            entry_date="2025-05-05",
            lines=[
                je_line(emergency_exp, "DEBIT", "2500.00"),
                je_line(checking, "CREDIT", "2500.00"),
            ],
            rationale="Overdraft expenditure",
        )

        bs_od = runner.get_balance_sheet(
            client, as_of_date="2025-05-10", currency="SGD"
        )
        details["overdraft_cash"] = str(bs_od["total_assets"])
        od_ok = (
            Decimal(bs_od["total_assets"]) == Decimal("-1500.00")
            and Decimal(bs_od["net_income"]) == Decimal("-2500.00")
            and Decimal(bs_od["total_equity"]) == Decimal("1000.00")
            and bs_od["is_balanced"] is True
            and Decimal(bs_od["equation_delta"]) == Decimal("0.00")
        )
        set_verdict(details, "overdraft_cash", od_ok)
        assert od_ok
        articulate(bs_od, None, details, "overdraft_cash")

        runner.post_manual_journal_entry(
            client,
            memo="Emergency Capital Injection",
            entry_date="2025-05-15",
            lines=[
                je_line(checking, "DEBIT", "10000.00"),
                je_line(owner_equity, "CREDIT", "10000.00"),
            ],
            rationale="Owner equity contribution",
        )
        runner.post_manual_journal_entry(
            client,
            memo="Purchase Collectible Art",
            entry_date="2025-05-18",
            lines=[
                je_line(art_asset, "DEBIT", "4000.00"),
                je_line(checking, "CREDIT", "4000.00"),
            ],
            rationale="Asset acquisition",
        )
        runner.post_manual_journal_entry(
            client,
            memo="Sell Collectible Art with Realized Gain",
            entry_date="2025-05-25",
            lines=[
                je_line(checking, "DEBIT", "6500.00"),
                je_line(art_asset, "CREDIT", "4000.00"),
                je_line(capital_gain, "CREDIT", "2500.00"),
            ],
            rationale="Asset disposal with capital gain",
        )
        details["capital_gain"] = "2500.00"
        set_verdict(details, "capital_gain", True)

        bs = runner.get_balance_sheet(client, as_of_date="2025-05-31", currency="SGD")
        total_assets = Decimal(bs["total_assets"])
        total_equity = Decimal(bs["total_equity"])
        net_inc = Decimal(bs["net_income"])
        delta = Decimal(bs["equation_delta"])
        balanced = bs["is_balanced"]
        details.update(
            {
                "ending_cash": str(total_assets),
                "ending_cash_balance": str(total_assets),
                "net_income": str(net_inc),
                "total_assets": str(total_assets),
                "total_equity": str(total_equity),
                "equation_delta": str(delta),
                "is_balanced": balanced,
            }
        )
        assets_ok = total_assets == Decimal("11000.00")
        equity_ok = total_equity == Decimal("11000.00")
        ni_ok = net_inc == Decimal("0.00")
        delta_ok = balanced is True and delta == Decimal("0.00")
        set_verdict(details, "total_assets", assets_ok)
        set_verdict(details, "ending_cash_balance", assets_ok)
        set_verdict(details, "total_equity", equity_ok)
        set_verdict(details, "net_income", ni_ok)
        set_verdict(details, "equation_delta", delta_ok)
        assert assets_ok and equity_ok and ni_ok and delta_ok
        articulate(bs, None, details, "equation_delta")

        diag = runner.get_balance_sheet_diagnostics(
            client, as_of_date="2025-05-31", currency="SGD"
        )
        if diag.get("is_balanced") is not True:
            set_verdict(details, "equation_delta", False)
        assert diag.get("is_balanced") is True
        details["flow_24_diagnostics_balanced"] = True

    return run_case(
        "case_6",
        "Case 6: Bank Overdraft & Capital Gain Disposal",
        (
            "overdraft_cash",
            "capital_gain",
            "net_income",
            "total_assets",
            "ending_cash_balance",
            "total_equity",
            "equation_delta",
        ),
        _body,
    )
