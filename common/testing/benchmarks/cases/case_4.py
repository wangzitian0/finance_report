"""Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet benchmark scenario."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from common.testing.benchmarks.case_types import CaseResult
from common.testing.benchmarks.cases._helpers import (
    articulate,
    check_verdict,
    je_line,
    run_case,
    set_verdict,
)
from common.testing.benchmarks.statement_generators import (
    generate_multicurrency_hkd_csv,
    generate_multicurrency_usd_csv,
    generate_standard_operations_csv,
)

if TYPE_CHECKING:
    from common.testing.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
    )


def execute_case_4(runner: ScenarioBenchmarkRunner) -> CaseResult:
    def _body(details: dict[str, Any]) -> None:
        client, _, _ = runner.create_ephemeral_client("case4")

        for tag, csv_bytes, fname, inst, curr in (
            (
                "sgd",
                generate_standard_operations_csv(Decimal("10000.00")),
                "operations_sgd.csv",
                "DBS Singapore",
                "SGD",
            ),
            (
                "usd",
                generate_multicurrency_usd_csv(Decimal("5000.00")),
                "operations_usd.csv",
                "Silicon Valley Bank",
                "USD",
            ),
            (
                "hkd",
                generate_multicurrency_hkd_csv(Decimal("20000.00")),
                "operations_hkd.csv",
                "HSBC Hong Kong",
                "HKD",
            ),
        ):
            stmt_id = runner.upload_statement(
                client, csv_bytes, fname, institution=inst, currency=curr
            )
            data = runner.wait_for_statement_parsed(client, stmt_id)
            details[f"{tag}_closing_balance"] = str(data["closing_balance"])
            check_verdict(
                details,
                f"{tag}_closing_balance",
                data.get("balance_validated") is True,
                f"{tag.upper()} balance invalid: {data}",
            )
            runner.adjudicate_unmatched_items(client, stmt_id)
            runner.approve_statement(client, stmt_id)

        bs_sgd = runner.get_balance_sheet(
            client, as_of_date="2025-04-30", currency="SGD"
        )
        bs_usd = runner.get_balance_sheet(
            client, as_of_date="2025-04-30", currency="USD"
        )
        assets_sgd = Decimal(bs_sgd["total_assets"])
        delta_sgd = Decimal(bs_sgd["equation_delta"])
        bal_sgd = bs_sgd["is_balanced"]
        assets_usd = Decimal(bs_usd["total_assets"])
        delta_usd = Decimal(bs_usd["equation_delta"])
        bal_usd = bs_usd["is_balanced"]

        details.update(
            {
                "currencies_consolidated": "SGD, USD, HKD",
                "total_assets_sgd": str(assets_sgd),
                "equation_delta_sgd": str(delta_sgd),
                "is_balanced_sgd": bal_sgd,
                "total_assets_usd": str(assets_usd),
                "equation_delta_usd": str(delta_usd),
                "is_balanced_usd": bal_usd,
                "equation_delta": str(delta_sgd),
                "is_balanced": bal_sgd,
            }
        )
        set_verdict(details, "total_assets_sgd", assets_sgd > Decimal("12800.00"))
        set_verdict(
            details,
            "equation_delta_sgd",
            bal_sgd is True and delta_sgd == Decimal("0.00"),
        )
        set_verdict(
            details,
            "equation_delta_usd",
            assets_usd > Decimal("0.00")
            and bal_usd is True
            and delta_usd == Decimal("0.00"),
        )
        assert (
            assets_sgd > Decimal("12800.00")
            and bal_sgd is True
            and delta_sgd == Decimal("0.00")
        )
        articulate(bs_sgd, None, details, "equation_delta_sgd")
        assert (
            assets_usd > Decimal("0.00")
            and bal_usd is True
            and delta_usd == Decimal("0.00")
        )
        articulate(bs_usd, None, details, "equation_delta_usd")

        fx_src = runner.create_account(
            client, name="USD Wire Outflow Clearing", type="ASSET", currency="SGD"
        )
        fx_tgt = runner.create_account(
            client, name="SGD Wire Receiving Account", type="ASSET", currency="SGD"
        )
        fx_gain = runner.create_account(
            client, name="Realized FX Gain on Wire", type="INCOME", currency="SGD"
        )
        runner.post_manual_journal_entry(
            client,
            memo="Multi-Currency Wire Transfer with Realized FX Gain",
            entry_date="2025-05-05",
            lines=[
                je_line(fx_tgt, "DEBIT", "1350.00"),
                je_line(fx_src, "CREDIT", "1340.00"),
                je_line(fx_gain, "CREDIT", "10.00"),
            ],
            rationale="OutflowValueInBase (1340.00) + RealizedGain (10.00) == InflowValueInBase (1350.00)",
        )
        bs_post = runner.get_balance_sheet(
            client, as_of_date="2025-05-31", currency="SGD"
        )
        post_ok = bs_post["is_balanced"] is True and Decimal(
            str(bs_post["equation_delta"])
        ) == Decimal("0.00")
        if not post_ok:
            set_verdict(details, "equation_delta_sgd", False)
        assert post_ok
        details.update(
            {
                "flow_17_realized_fx_gain_sgd": "10.00",
                "cta_variance_explained": (
                    "Translation variance between spot rate balance sheet items and period-average "
                    "net income is fully absorbed by the IAS 21 CTA equity reserve."
                ),
            }
        )

    return run_case(
        "case_4",
        "Case 4: Multi-National & Multi-Currency Consolidated Balance Sheet",
        (
            "sgd_closing_balance",
            "usd_closing_balance",
            "hkd_closing_balance",
            "total_assets_sgd",
            "equation_delta_sgd",
            "equation_delta_usd",
        ),
        _body,
    )
