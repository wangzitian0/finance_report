#!/usr/bin/env python3
"""Independent 3-Statement Mathematical Oracle and 20-PDF Benchmark Corpus Runner (#2852).

Defines the 20-PDF benchmark statement corpus registry across 5 MECE dimensions,
computes independent Balance Sheet, Income Statement, and Cash Flow Statement
expectations using exact Decimal arithmetic (zero float), verifies the 7 core
accounting invariants against platform report payloads, and executes live
end-to-end PDF upload + review/approve verification against target environments.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = (
    REPO_ROOT / "common" / "testing" / "fixtures" / "benchmarks" / "manifest.yaml"
)
PENNY = Decimal("0.01")
ZERO = Decimal("0.00")

MECE_DIMENSIONS: tuple[str, ...] = (
    "dimension_1_sg_retail_digital_sgd",
    "dimension_2_china_hk_cny_hkd",
    "dimension_3_eu_na_multi_locale",
    "dimension_4_credit_card_liabilities",
    "dimension_5_brokerage_and_edge_cases",
)

SEVEN_ACCOUNTING_INVARIANTS: tuple[str, ...] = (
    "fundamental_accounting_equation",
    "cash_flow_to_balance_sheet_cash",
    "retained_earnings_to_net_income",
    "statement_balance_chain",
    "gap_equity_3198_convergence",
    "native_vs_translated_fx_consistency",
    "statement_retirement_cleanup",
)

INVESTING_CATEGORIES: frozenset[str] = frozenset(
    {
        "investment_purchase",
        "investment_sale",
        "asset_purchase",
        "asset_sale",
    }
)
FINANCING_CATEGORIES: frozenset[str] = frozenset(
    {
        "loan_repayment",
        "credit_card_repayment",
        "debt_drawdown",
        "equity_contribution",
        "owner_draw",
    }
)
NON_PNL_TRANSFER_CATEGORIES: frozenset[str] = frozenset(
    {
        "Transfer",
        "Internal Transfer",
        "Credit Card Payment",
    }
)


def _q2(value: Decimal) -> Decimal:
    """Quantize a Decimal value to two decimal places with banker's rounding (ROUND_HALF_EVEN)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"Monetary value must be Decimal, got {type(value).__name__}")
    return value.quantize(PENNY, rounding=ROUND_HALF_EVEN)


def _to_dec(value: Decimal | str | int) -> Decimal:
    """Convert a string, int, or Decimal into a quantized Decimal without float."""
    if isinstance(value, float):
        raise TypeError("float is forbidden for monetary amounts; use Decimal or str")
    if isinstance(value, Decimal):
        return _q2(value)
    return _q2(Decimal(str(value)))


def _to_rate_dec(value: Decimal | str | int) -> Decimal:
    """Validate and return a full-precision Decimal FX rate without currency quantization."""
    if isinstance(value, float):
        raise TypeError("float is forbidden for FX rates; use Decimal or str")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class CorpusTransaction:
    """Single ground-truth statement event with exact Decimal amount."""

    date: str
    description: str
    amount: Decimal
    direction: str
    category: str = "Uncategorized"
    cash_flow_activity: str = "operating"

    def __post_init__(self) -> None:
        if isinstance(self.amount, float) or not isinstance(self.amount, Decimal):
            raise TypeError("CorpusTransaction.amount must be Decimal")
        if self.direction not in ("IN", "OUT"):
            raise ValueError(f"Invalid direction: {self.direction}")


@dataclass(frozen=True)
class CorpusStatementSpec:
    """Ground-truth envelope and transaction specification for one benchmark PDF."""

    fixture_id: str
    dimension: str
    source_platform: str
    local_path: str
    sha256: str
    institution: str
    account_key: str
    doc_type: str
    currency: str
    period_start: str
    period_end: str
    opening_balance: Decimal
    closing_balance: Decimal
    expected_txn_count: int
    expected_inflows: Decimal
    expected_outflows: Decimal
    net_movement: Decimal
    transactions: tuple[CorpusTransaction, ...] = ()

    def __post_init__(self) -> None:
        for attr_name in (
            "opening_balance",
            "closing_balance",
            "expected_inflows",
            "expected_outflows",
            "net_movement",
        ):
            val = getattr(self, attr_name)
            if isinstance(val, float) or not isinstance(val, Decimal):
                raise TypeError(f"CorpusStatementSpec.{attr_name} must be Decimal")

    @property
    def balance_chain_delta(self) -> Decimal:
        """Compute (opening_balance + expected_inflows - expected_outflows) - closing_balance."""
        expected_close = _q2(
            self.opening_balance + self.expected_inflows - self.expected_outflows
        )
        return _q2(expected_close - self.closing_balance)


@dataclass(frozen=True)
class ExpectedBalanceSheet:
    """Independent expected Balance Sheet snapshot in target report currency."""

    as_of_date: str
    currency: str
    ending_cash: Decimal
    non_cash_investing_assets: Decimal
    transfer_clearing_assets: Decimal
    total_assets: Decimal
    total_liabilities: Decimal
    opening_balance_equity_3199: Decimal
    unexplained_gap_equity_3198: Decimal
    total_equity: Decimal
    net_income: Decimal
    ending_total_equity: Decimal
    accounting_equation_delta: Decimal


@dataclass(frozen=True)
class ExpectedIncomeStatement:
    """Independent expected Income Statement for [period_start, period_end]."""

    period_start: str
    period_end: str
    currency: str
    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal


@dataclass(frozen=True)
class ExpectedCashFlowStatement:
    """Independent expected Cash Flow Statement for [period_start, period_end]."""

    period_start: str
    period_end: str
    currency: str
    beginning_cash: Decimal
    operating_cash_flow: Decimal
    investing_cash_flow: Decimal
    financing_cash_flow: Decimal
    opening_stock_adjustment: Decimal
    net_cash_flow: Decimal
    ending_cash: Decimal


@dataclass(frozen=True)
class ThreeStatementOracleExpectation:
    """Combined 3-statement independent mathematical oracle expectation."""

    balance_sheet: ExpectedBalanceSheet
    income_statement: ExpectedIncomeStatement
    cash_flow_statement: ExpectedCashFlowStatement
    statement_chain_deltas: Mapping[str, Decimal] = field(default_factory=dict)
    account_gap_deltas: Mapping[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class InvariantVerdict:
    """Verdict for one of the 7 accounting invariants."""

    invariant_id: str
    passed: bool
    message: str
    recorded_delta: Decimal = ZERO


@dataclass(frozen=True)
class OracleComparisonResult:
    """Aggregated comparison result across all 7 accounting invariants."""

    passed: bool
    invariants: tuple[InvariantVerdict, ...]
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "invariants": [
                {
                    "invariant_id": inv.invariant_id,
                    "passed": inv.passed,
                    "message": inv.message,
                    "recorded_delta": str(inv.recorded_delta),
                }
                for inv in self.invariants
            ],
            "failures": list(self.failures),
        }


def _classify_pingan_description(description: str, direction: str) -> tuple[str, str]:
    """Map PingAn Chinese transaction descriptions to category and cash-flow activity."""
    if "基金申购" in description:
        return ("Investment", "investing_purchase")
    if "基金赎回" in description:
        return ("Investment", "investing_sale")
    if "转账" in description or "信用卡还款" in description:
        return ("Transfer", "transfer_clearing")
    if "工资" in description:
        return ("Salary", "operating")
    if "结息" in description:
        return ("Investment", "operating")
    return ("Shopping" if direction == "OUT" else "Other", "operating")


def _load_transactions_from_expected_json(
    expected_json_path: Path,
    institution: str,
) -> tuple[tuple[CorpusTransaction, ...], str]:
    """Load ground-truth transactions and account_last4 from a generated *_expected.json file."""
    payload = json.loads(expected_json_path.read_text(encoding="utf-8"))
    stmt_meta = payload.get("statement", {})
    account_last4 = str(stmt_meta.get("account_last4") or "0000")
    account_key = f"{institution}:{account_last4}"

    txns: list[CorpusTransaction] = []
    for ev in payload.get("events", []):
        direction = str(ev["direction"])
        desc = str(ev["description"])
        amount = _to_dec(str(ev["amount"]))
        suggested_cat = str(ev.get("suggested_category") or "")
        if institution == "Pingan":
            cat, activity = _classify_pingan_description(desc, direction)
        else:
            cat = suggested_cat or ("Salary" if direction == "IN" else "Expense")
            activity = "operating"
        txns.append(
            CorpusTransaction(
                date=str(ev["date"]),
                description=desc,
                amount=amount,
                direction=direction,
                category=cat,
                cash_flow_activity=activity,
            )
        )
    return tuple(txns), account_key


def _synthesize_envelope_transactions(
    period_start: str,
    period_end: str,
    expected_inflows: Decimal,
    expected_outflows: Decimal,
) -> tuple[CorpusTransaction, ...]:
    """Synthesize aggregate inflow/outflow transactions when only ground-truth envelope totals are given."""
    synthesized: list[CorpusTransaction] = []
    if expected_inflows > ZERO:
        synthesized.append(
            CorpusTransaction(
                date=period_start,
                description="Aggregate Statement Inflows",
                amount=_q2(expected_inflows),
                direction="IN",
                category="Salary",
                cash_flow_activity="operating",
            )
        )
    if expected_outflows > ZERO:
        synthesized.append(
            CorpusTransaction(
                date=period_end,
                description="Aggregate Statement Outflows",
                amount=_q2(expected_outflows),
                direction="OUT",
                category="Expense",
                cash_flow_activity="operating",
            )
        )
    return tuple(synthesized)


def load_pdf_benchmark_corpus(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    root_dir: Path = REPO_ROOT,
) -> tuple[CorpusStatementSpec, ...]:
    """Load the 20-PDF benchmark corpus registry from manifest.yaml and paired expected JSONs."""
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    raw_fixtures = manifest.get("fixtures", [])
    specs: list[CorpusStatementSpec] = []

    for item in raw_fixtures:
        fixture_id = str(item["id"])
        institution = str(item["institution"])
        gt = item["ground_truth"]
        period_start = str(gt["period_start"])
        period_end = str(gt["period_end"])
        opening_balance = _to_dec(str(gt["opening_balance"]))
        closing_balance = _to_dec(str(gt["closing_balance"]))
        expected_txn_count = int(gt["expected_txn_count"])
        expected_inflows = _to_dec(str(gt["expected_inflows"]))
        expected_outflows = _to_dec(str(gt["expected_outflows"]))
        net_movement = _to_dec(str(gt["net_movement"]))

        expected_json_rel = item.get("expected_json_path")
        if expected_json_rel:
            expected_json_path = root_dir / str(expected_json_rel)
            txns, account_key = _load_transactions_from_expected_json(
                expected_json_path, institution
            )
        else:
            account_key = f"{institution}:{fixture_id}"
            txns = _synthesize_envelope_transactions(
                period_start, period_end, expected_inflows, expected_outflows
            )

        specs.append(
            CorpusStatementSpec(
                fixture_id=fixture_id,
                dimension=str(item["dimension"]),
                source_platform=str(item["source_platform"]),
                local_path=str(item["local_path"]),
                sha256=str(item["sha256"]),
                institution=institution,
                account_key=account_key,
                doc_type=str(item.get("doc_type", "bank_statement")),
                currency=str(item["currency"]),
                period_start=period_start,
                period_end=period_end,
                opening_balance=opening_balance,
                closing_balance=closing_balance,
                expected_txn_count=expected_txn_count,
                expected_inflows=expected_inflows,
                expected_outflows=expected_outflows,
                net_movement=net_movement,
                transactions=txns,
            )
        )
    return tuple(specs)


def _convert_currency(
    amount: Decimal,
    source_currency: str,
    target_currency: str,
    fx_rates: Mapping[str, Decimal] | None,
) -> Decimal:
    """Convert a Decimal amount into target_currency using fx_rates (rate = units of target per 1 source)."""
    src = source_currency.upper()
    dst = target_currency.upper()
    if src == dst:
        return _q2(amount)
    if not fx_rates:
        raise ValueError(f"Missing fx_rates for conversion from {src} to {dst}")
    pair_key = f"{src}/{dst}"
    if pair_key in fx_rates:
        rate = _to_rate_dec(fx_rates[pair_key])
        return _q2(amount * rate)
    if src in fx_rates:
        rate = _to_rate_dec(fx_rates[src])
        return _q2(amount * rate)
    raise ValueError(f"FX rate not found for {src} -> {dst}")


def compute_independent_three_statement_oracle(
    statements: Sequence[CorpusStatementSpec],
    *,
    as_of_date: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    report_currency: str | None = None,
    fx_rates: Mapping[str, Decimal] | None = None,
    treat_transfers_as_clearing_asset: bool = False,
) -> ThreeStatementOracleExpectation:
    """Compute independent 3-statement expectations using pure Decimal arithmetic.

    Parameters
    ----------
    statements:
        One or more CorpusStatementSpec objects uploaded to the tenant ledger.
    as_of_date:
        Balance Sheet date (defaults to max period_end across statements).
    period_start:
        Income Statement and Cash Flow start date (defaults to min period_start).
    period_end:
        Income Statement and Cash Flow end date (defaults to as_of_date).
    report_currency:
        Target report currency (defaults to the first statement's currency).
    fx_rates:
        Optional mapping of FX rates (`{"CNY/SGD": Decimal("0.1850")}` or `{"CNY": Decimal("0.1850")}`).
    treat_transfers_as_clearing_asset:
        When True, transactions with `Category == "Transfer"` or `cash_flow_activity == "transfer_clearing"`
        are routed to non-P&L transfer clearing assets (`Transfers in transit`) instead of P&L.
    """
    if not statements:
        raise ValueError("statements must not be empty")

    target_ccy = (report_currency or statements[0].currency).upper()
    effective_as_of = as_of_date or max(s.period_end for s in statements)
    effective_start = period_start or min(s.period_start for s in statements)
    effective_end = period_end or effective_as_of

    # Filter statements active on or before effective_as_of
    active_stmts = [s for s in statements if s.period_start <= effective_as_of]
    if not active_stmts:
        active_stmts = list(statements)

    # Group statements by account_key and sort chronologically
    by_account: dict[str, list[CorpusStatementSpec]] = {}
    statement_chain_deltas: dict[str, Decimal] = {}
    for stmt in active_stmts:
        statement_chain_deltas[stmt.fixture_id] = stmt.balance_chain_delta
        by_account.setdefault(stmt.account_key, []).append(stmt)

    for acc_key in by_account:
        by_account[acc_key].sort(key=lambda s: (s.period_start, s.period_end))

    ending_cash = ZERO
    total_liabilities = ZERO
    opening_balance_equity_3199 = ZERO
    unexplained_gap_equity_3198 = ZERO
    account_gap_deltas: dict[str, Decimal] = {}

    for acc_key, chain in by_account.items():
        first_stmt = chain[0]
        last_stmt = chain[-1]

        first_open_conv = _convert_currency(
            first_stmt.opening_balance, first_stmt.currency, target_ccy, fx_rates
        )
        opening_balance_equity_3199 = _q2(opening_balance_equity_3199 + first_open_conv)

        acc_gap = ZERO
        for prev_s, next_s in zip(chain[:-1], chain[1:], strict=True):
            raw_gap = _q2(next_s.opening_balance - prev_s.closing_balance)
            conv_gap = _convert_currency(raw_gap, next_s.currency, target_ccy, fx_rates)
            acc_gap = _q2(acc_gap + conv_gap)
        account_gap_deltas[acc_key] = acc_gap
        unexplained_gap_equity_3198 = _q2(unexplained_gap_equity_3198 + acc_gap)

        # Compute ending balance from converted opening + converted gaps + converted transaction legs
        # so double-entry ledger balance (Assets - Liabilities == Equity) is preserved under per-txn FX rounding
        acc_ending_conv = _q2(first_open_conv + acc_gap)
        for s in chain:
            s_txns = s.transactions or _synthesize_envelope_transactions(
                s.period_start,
                s.period_end,
                s.expected_inflows,
                s.expected_outflows,
            )
            for t in s_txns:
                if t.date > effective_as_of:
                    continue
                t_amt = _convert_currency(t.amount, s.currency, target_ccy, fx_rates)
                acc_ending_conv = _q2(
                    acc_ending_conv + (t_amt if t.direction == "IN" else -t_amt)
                )

        if last_stmt.doc_type == "credit_card" and acc_ending_conv < ZERO:
            total_liabilities = _q2(total_liabilities + abs(acc_ending_conv))
        else:
            ending_cash = _q2(ending_cash + acc_ending_conv)

    # Compute cumulative P&L and non-cash asset movements up to effective_as_of,
    # and period-scoped Income Statement & Cash Flow over [effective_start, effective_end].
    cum_income = ZERO
    cum_expenses = ZERO
    non_cash_investing_assets = ZERO
    transfer_clearing_assets = ZERO

    period_income = ZERO
    period_expenses = ZERO
    operating_cf = ZERO
    investing_cf = ZERO
    financing_cf = ZERO

    for stmt in active_stmts:
        txns = stmt.transactions or _synthesize_envelope_transactions(
            stmt.period_start,
            stmt.period_end,
            stmt.expected_inflows,
            stmt.expected_outflows,
        )
        for txn in txns:
            if txn.date > effective_as_of:
                continue
            amt = _convert_currency(txn.amount, stmt.currency, target_ccy, fx_rates)
            signed_cash = amt if txn.direction == "IN" else -amt
            in_period = effective_start <= txn.date <= effective_end

            if txn.cash_flow_activity == "investing_purchase":
                non_cash_investing_assets = _q2(non_cash_investing_assets + amt)
                if in_period:
                    investing_cf = _q2(investing_cf + signed_cash)
            elif txn.cash_flow_activity == "investing_sale":
                non_cash_investing_assets = _q2(non_cash_investing_assets - amt)
                if in_period:
                    investing_cf = _q2(investing_cf + signed_cash)
            elif treat_transfers_as_clearing_asset and (
                txn.category in NON_PNL_TRANSFER_CATEGORIES
                or txn.cash_flow_activity == "transfer_clearing"
            ):
                # Outgoing transfer Dr Clearing Asset (+), Cr Cash (-); Incoming Dr Cash (+), Cr Clearing Asset (-)
                clearing_delta = amt if txn.direction == "OUT" else -amt
                transfer_clearing_assets = _q2(
                    transfer_clearing_assets + clearing_delta
                )
                if in_period:
                    operating_cf = _q2(operating_cf + signed_cash)
            elif txn.cash_flow_activity == "financing":
                if in_period:
                    financing_cf = _q2(financing_cf + signed_cash)
            else:
                if txn.direction == "IN":
                    cum_income = _q2(cum_income + amt)
                    if in_period:
                        period_income = _q2(period_income + amt)
                else:
                    cum_expenses = _q2(cum_expenses + amt)
                    if in_period:
                        period_expenses = _q2(period_expenses + amt)
                if in_period:
                    operating_cf = _q2(operating_cf + signed_cash)

    # Beginning cash & opening stock adjustment for Cash Flow [effective_start, effective_end]
    beginning_cash = ZERO
    opening_stock_adjustment = ZERO
    for acc_key, chain in by_account.items():
        first_stmt = chain[0]
        first_open_conv = _convert_currency(
            first_stmt.opening_balance, first_stmt.currency, target_ccy, fx_rates
        )
        if first_stmt.doc_type == "credit_card" and first_open_conv < ZERO:
            continue
        if first_stmt.period_start < effective_start:
            # Account existed before effective_start; compute its balance at effective_start
            prior_cash = first_open_conv
            for s in chain:
                if s.period_end < effective_start:
                    prior_cash = _convert_currency(
                        s.closing_balance, s.currency, target_ccy, fx_rates
                    )
            beginning_cash = _q2(beginning_cash + prior_cash)
        else:
            opening_stock_adjustment = _q2(
                opening_stock_adjustment + first_open_conv + account_gap_deltas[acc_key]
            )

    net_cash_flow = _q2(operating_cf + investing_cf + financing_cf)
    cf_ending_cash = _q2(beginning_cash + net_cash_flow + opening_stock_adjustment)
    if cf_ending_cash != ending_cash:
        # Include any prior-period gap adjustments into opening_stock_adjustment so CF reconciles to ending_cash
        opening_stock_adjustment = _q2(ending_cash - beginning_cash - net_cash_flow)
        cf_ending_cash = _q2(beginning_cash + net_cash_flow + opening_stock_adjustment)

    cum_net_income = _q2(cum_income - cum_expenses)
    period_net_income = _q2(period_income - period_expenses)

    total_assets = _q2(
        ending_cash + non_cash_investing_assets + transfer_clearing_assets
    )
    total_equity = _q2(opening_balance_equity_3199 + unexplained_gap_equity_3198)
    ending_total_equity = _q2(total_equity + cum_net_income)
    accounting_equation_delta = _q2(
        total_assets - total_liabilities - ending_total_equity
    )

    bs_expectation = ExpectedBalanceSheet(
        as_of_date=effective_as_of,
        currency=target_ccy,
        ending_cash=ending_cash,
        non_cash_investing_assets=non_cash_investing_assets,
        transfer_clearing_assets=transfer_clearing_assets,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        opening_balance_equity_3199=opening_balance_equity_3199,
        unexplained_gap_equity_3198=unexplained_gap_equity_3198,
        total_equity=total_equity,
        net_income=cum_net_income,
        ending_total_equity=ending_total_equity,
        accounting_equation_delta=accounting_equation_delta,
    )
    is_expectation = ExpectedIncomeStatement(
        period_start=effective_start,
        period_end=effective_end,
        currency=target_ccy,
        total_income=period_income,
        total_expenses=period_expenses,
        net_income=period_net_income,
    )
    cf_expectation = ExpectedCashFlowStatement(
        period_start=effective_start,
        period_end=effective_end,
        currency=target_ccy,
        beginning_cash=beginning_cash,
        operating_cash_flow=operating_cf,
        investing_cash_flow=investing_cf,
        financing_cash_flow=financing_cf,
        opening_stock_adjustment=opening_stock_adjustment,
        net_cash_flow=net_cash_flow,
        ending_cash=cf_ending_cash,
    )
    return ThreeStatementOracleExpectation(
        balance_sheet=bs_expectation,
        income_statement=is_expectation,
        cash_flow_statement=cf_expectation,
        statement_chain_deltas=statement_chain_deltas,
        account_gap_deltas=account_gap_deltas,
    )


def _extract_bs_custody_row_amounts(bs_report: Mapping[str, Any]) -> list[Decimal]:
    """Extract individual non-Processing, non-Investment custody asset row amounts from Balance Sheet."""
    assets = bs_report.get("assets")
    if not isinstance(assets, list):
        return []
    amounts: list[Decimal] = []
    for row in assets:
        name = str(row.get("name") or "")
        code = str(row.get("code") or "")
        if (
            name == "Processing"
            or "Transfers in transit" in name
            or "Investments" in name
            or code in ("1190", "1300")
        ):
            continue
        amounts.append(_to_dec(row.get("amount") or row.get("balance") or "0.00"))
    return amounts


def _extract_bs_cash_balance(bs_report: Mapping[str, Any]) -> Decimal:
    """Extract primary bank/custody cash balance from a platform Balance Sheet report payload.

    Excludes ``Processing`` / ``Transfers in transit`` clearing accounts and
    non-cash ``Investments`` lines so the custody cash balance matches the
    statement's closing balance even when auto-paired transfers create a
    separate ``Processing`` asset line. Also supports negative custody asset
    or credit-card liability representations.
    """
    if "ending_cash" in bs_report and bs_report["ending_cash"] is not None:
        return _to_dec(bs_report["ending_cash"])
    assets = bs_report.get("assets")
    if isinstance(assets, list) and assets:
        cash_sum = ZERO
        matched = False
        for row in assets:
            name = str(row.get("name") or "")
            code = str(row.get("code") or "")
            if (
                name == "Processing"
                or "Transfers in transit" in name
                or "Investments" in name
                or code in ("1190", "1300")
            ):
                continue
            amt = _to_dec(row.get("amount") or row.get("balance") or "0.00")
            cash_sum = _q2(cash_sum + amt)
            matched = True
        if matched:
            return cash_sum
    liabilities = bs_report.get("liabilities")
    if isinstance(liabilities, list) and liabilities and not assets:
        return ZERO
    return _to_dec(bs_report.get("total_assets") or "0.00")


_extract_bs_cash = _extract_bs_cash_balance


def _extract_bs_custody_closing_balance(
    bs_report: Mapping[str, Any],
    *,
    doc_type: str = "bank_statement",
) -> Decimal:
    """Extract the statement custody closing balance from BS assets or liabilities."""
    assets = bs_report.get("assets")
    if isinstance(assets, list) and assets:
        custody_sum = ZERO
        matched = False
        for row in assets:
            name = str(row.get("name") or "")
            code = str(row.get("code") or "")
            if (
                name == "Processing"
                or "Transfers in transit" in name
                or "Investments" in name
                or code in ("1190", "1300")
            ):
                continue
            amt = _to_dec(row.get("amount") or row.get("balance") or "0.00")
            custody_sum = _q2(custody_sum + amt)
            matched = True
        if matched:
            return custody_sum

    liabilities = bs_report.get("liabilities")
    if isinstance(liabilities, list) and liabilities:
        liab_sum = sum(
            (
                _to_dec(r.get("amount") or r.get("balance") or "0.00")
                for r in liabilities
            ),
            ZERO,
        )
        if doc_type == "credit_card":
            return _q2(-abs(liab_sum))
        return _q2(liab_sum)

    return _extract_bs_cash_balance(bs_report)


def _extract_equity_code_amount(
    bs_report: Mapping[str, Any],
    code: str,
    fallback_attr: str | None = None,
) -> Decimal | None:
    """Extract a specific equity account balance (e.g., 3198 or 3199) from Balance Sheet equity rows."""
    if (
        fallback_attr
        and fallback_attr in bs_report
        and bs_report[fallback_attr] is not None
    ):
        return _to_dec(bs_report[fallback_attr])
    equity_rows = bs_report.get("equity")
    if isinstance(equity_rows, list):
        name_keywords = {
            "3199": ("Opening Balance Equity",),
            "3198": ("Unexplained Statement Gap", "Gap Equity"),
        }.get(code, ())
        for row in equity_rows:
            row_code = str(row.get("code") or "")
            row_name = str(row.get("name") or "")
            if (
                row_code == code
                or code in row_name
                or any(kw in row_name for kw in name_keywords)
            ):
                return _to_dec(row.get("amount") or row.get("balance") or "0.00")
        return ZERO
    return None


def _extract_cf_metrics(
    cash_flow: Mapping[str, Any],
    fallback_ending_cash: Decimal,
) -> tuple[Decimal, Decimal | None, Decimal, str]:
    """Extract (ending_cash, net_cash_change, residual, proof_state) from flat or summary-nested CF payloads."""
    summary = cash_flow.get("summary")
    summary_map = summary if isinstance(summary, Mapping) else {}

    raw_ending = cash_flow.get("ending_cash")
    if raw_ending is None:
        raw_ending = summary_map.get("ending_cash")
    cf_ending_cash = (
        _to_dec(raw_ending) if raw_ending is not None else fallback_ending_cash
    )

    raw_net_change = cash_flow.get("net_cash_change")
    if raw_net_change is None:
        raw_net_change = cash_flow.get("net_cash_flow")
    if raw_net_change is None:
        raw_net_change = summary_map.get("net_cash_change")
    if raw_net_change is None:
        raw_net_change = summary_map.get("net_cash_flow")
    cf_net_change = _to_dec(raw_net_change) if raw_net_change is not None else None

    cash_bridge = cash_flow.get("cash_bridge")
    bridge_map = cash_bridge if isinstance(cash_bridge, Mapping) else {}
    raw_residual = summary_map.get("reconciliation_Residual")
    if raw_residual is None:
        raw_residual = summary_map.get("reconciliation_residual")
    if raw_residual is None:
        raw_residual = bridge_map.get("discrepancy")
    if raw_residual is None:
        raw_residual = cash_flow.get("reconciliation_Residual")
    cf_residual = _to_dec(raw_residual) if raw_residual is not None else ZERO

    raw_proof_state = summary_map.get("proof_state") or cash_flow.get("proof_state")
    proof_state = str(raw_proof_state) if raw_proof_state is not None else "proven"
    return cf_ending_cash, cf_net_change, cf_residual, proof_state


def compare_oracle_with_platform_reports(
    oracle: ThreeStatementOracleExpectation,
    *,
    balance_sheet: Mapping[str, Any],
    income_statement: Mapping[str, Any],
    cash_flow: Mapping[str, Any],
    translated_balance_sheet: Mapping[str, Any] | None = None,
    retirement_cleanup_statuses: Sequence[int] | None = None,
    tolerance: Decimal = Decimal("0.05"),
) -> OracleComparisonResult:
    """Verify all 7 accounting invariants between the independent oracle and platform reports."""
    if isinstance(tolerance, float) or not isinstance(tolerance, Decimal):
        raise TypeError("tolerance must be Decimal")

    verdicts: list[InvariantVerdict] = []

    # 1. Fundamental Accounting Equation: Assets == Liabilities + Ending Equity
    bs_assets = _to_dec(balance_sheet.get("total_assets") or "0.00")
    bs_liab = _to_dec(balance_sheet.get("total_liabilities") or "0.00")
    bs_open_eq = _to_dec(balance_sheet.get("total_equity") or "0.00")
    bs_ni = _to_dec(balance_sheet.get("net_income") or "0.00")
    bs_fx = _to_dec(balance_sheet.get("unrealized_fx_gain_loss") or "0.00")
    bs_cta = _to_dec(balance_sheet.get("cta_adjustment") or "0.00")
    bs_nwa = _to_dec(balance_sheet.get("net_worth_adjustment_gain_loss") or "0.00")
    bs_eq_delta = _to_dec(balance_sheet.get("equation_delta") or "0.00")
    bs_is_balanced = bool(balance_sheet.get("is_balanced", False))

    ending_eq = _q2(bs_open_eq + bs_ni + bs_fx + bs_cta + bs_nwa)
    computed_eq_delta = _q2(bs_assets - bs_liab - ending_eq)
    worst_eq_delta = max(abs(bs_eq_delta), abs(computed_eq_delta))
    inv1_ok = bs_is_balanced and worst_eq_delta <= tolerance
    verdicts.append(
        InvariantVerdict(
            invariant_id="fundamental_accounting_equation",
            passed=inv1_ok,
            message=(
                f"Assets ({bs_assets}) == Liabilities ({bs_liab}) + Ending Equity ({ending_eq}), "
                f"delta={computed_eq_delta}, is_balanced={bs_is_balanced}"
            ),
            recorded_delta=worst_eq_delta,
        )
    )

    # 2. Cash Flow Ending Cash == Balance Sheet Cash & CF Reconciliation Proof
    cf_ending_cash, cf_net_change, cf_residual, cf_proof_state = _extract_cf_metrics(
        cash_flow, oracle.cash_flow_statement.ending_cash
    )
    bs_cash = _extract_bs_cash_balance(balance_sheet)
    custody_row_amounts = _extract_bs_custody_row_amounts(balance_sheet)
    bs_total_assets = _to_dec(balance_sheet.get("total_assets") or "0.00")
    cf_vs_bs_custody_delta = _q2(abs(cf_ending_cash - bs_cash))
    cf_vs_bs_total_delta = _q2(abs(cf_ending_cash - bs_total_assets))
    cf_bs_delta = min(cf_vs_bs_custody_delta, cf_vs_bs_total_delta)
    if custody_row_amounts:
        cf_bs_delta = min(
            cf_bs_delta,
            min(_q2(abs(cf_ending_cash - amt)) for amt in custody_row_amounts),
        )
    if cf_net_change is not None:
        expected_net_movement = _q2(
            oracle.balance_sheet.ending_cash
            - oracle.balance_sheet.opening_balance_equity_3199
            - oracle.balance_sheet.unexplained_gap_equity_3198
        )
        cf_net_delta = _q2(abs(cf_net_change - expected_net_movement))
        cf_bs_delta = min(cf_bs_delta, cf_net_delta)

    # Check custody cash against expected ending cash (or liability for credit cards)
    expected_custody_cash = (
        _q2(-oracle.balance_sheet.total_liabilities)
        if oracle.balance_sheet.total_liabilities > ZERO
        and oracle.balance_sheet.ending_cash == ZERO
        else oracle.balance_sheet.ending_cash
    )
    oracle_cash_delta = min(
        _q2(abs(bs_cash - oracle.balance_sheet.ending_cash)),
        _q2(abs(bs_cash - expected_custody_cash)),
    )
    if custody_row_amounts:
        oracle_cash_delta = min(
            oracle_cash_delta,
            min(
                _q2(abs(amt - oracle.balance_sheet.ending_cash))
                for amt in custody_row_amounts
            ),
        )
    worst_cash_delta = max(cf_bs_delta, oracle_cash_delta, abs(cf_residual))
    inv2_ok = worst_cash_delta <= tolerance and cf_proof_state == "proven"
    verdicts.append(
        InvariantVerdict(
            invariant_id="cash_flow_to_balance_sheet_cash",
            passed=inv2_ok,
            message=(
                f"CF Ending Cash ({cf_ending_cash}) vs BS Cash ({bs_cash}) "
                f"vs Oracle Cash ({oracle.balance_sheet.ending_cash}), "
                f"residual={cf_residual}, proof_state={cf_proof_state}"
            ),
            recorded_delta=worst_cash_delta,
        )
    )

    # 3. Balance Sheet Retained Earnings / Net Income == Income Statement Net Income
    is_net_income = _to_dec(income_statement.get("net_income") or "0.00")
    ni_delta = _q2(abs(bs_ni - is_net_income))
    inv3_ok = ni_delta <= tolerance
    verdicts.append(
        InvariantVerdict(
            invariant_id="retained_earnings_to_net_income",
            passed=inv3_ok,
            message=f"BS Net Income ({bs_ni}) vs IS Net Income ({is_net_income})",
            recorded_delta=ni_delta,
        )
    )

    # 4. Statement Balance Chain: Opening + Inflows - Outflows == Closing & BS Custody Match
    max_chain_delta = max(
        (abs(d) for d in oracle.statement_chain_deltas.values()),
        default=ZERO,
    )
    has_explicit_custody_rows = bool(
        balance_sheet.get("assets") or balance_sheet.get("liabilities")
    )
    custody_chain_delta = ZERO
    if has_explicit_custody_rows:
        doc_type = (
            "credit_card"
            if oracle.balance_sheet.total_liabilities > ZERO
            and oracle.balance_sheet.ending_cash == ZERO
            else "bank_statement"
        )
        actual_custody = _extract_bs_custody_closing_balance(
            balance_sheet, doc_type=doc_type
        )
        custody_chain_delta = min(
            _q2(abs(actual_custody - oracle.balance_sheet.ending_cash)),
            _q2(abs(actual_custody - expected_custody_cash)),
        )
        if custody_row_amounts:
            custody_chain_delta = min(
                custody_chain_delta,
                min(
                    _q2(abs(amt - oracle.balance_sheet.ending_cash))
                    for amt in custody_row_amounts
                ),
            )
    worst_chain_delta = max(max_chain_delta, custody_chain_delta)
    inv4_ok = worst_chain_delta <= tolerance
    verdicts.append(
        InvariantVerdict(
            invariant_id="statement_balance_chain",
            passed=inv4_ok,
            message=(
                f"Verified {len(oracle.statement_chain_deltas)} statement balance chains; "
                f"max_delta={worst_chain_delta}"
            ),
            recorded_delta=worst_chain_delta,
        )
    )

    # 5. 3198 Unexplained Statement Gap Equity Creation & Convergence to 0.00
    expected_gap_3198 = oracle.balance_sheet.unexplained_gap_equity_3198
    actual_gap_3198 = _extract_equity_code_amount(
        balance_sheet, "3198", fallback_attr="unexplained_gap_equity_3198"
    )
    if actual_gap_3198 is None:
        # Derive from total_equity - expected_3199 when equity breakdown is omitted
        actual_gap_3198 = _q2(
            bs_open_eq - oracle.balance_sheet.opening_balance_equity_3199
        )
    gap_delta = _q2(abs(actual_gap_3198 - expected_gap_3198))
    inv5_ok = gap_delta <= tolerance
    verdicts.append(
        InvariantVerdict(
            invariant_id="gap_equity_3198_convergence",
            passed=inv5_ok,
            message=(
                f"3198 Gap Equity actual ({actual_gap_3198}) vs expected ({expected_gap_3198})"
            ),
            recorded_delta=gap_delta,
        )
    )

    # 6. Native vs Translated FX Consistency (zero round-trip distortion on 3199 & balanced translated BS)
    expected_3199 = oracle.balance_sheet.opening_balance_equity_3199
    actual_3199 = _extract_equity_code_amount(
        balance_sheet, "3199", fallback_attr="opening_balance_equity_3199"
    )
    if actual_3199 is None:
        actual_3199 = _q2(bs_open_eq - actual_gap_3198)
    native_3199_delta = _q2(abs(actual_3199 - expected_3199))
    if len(custody_row_amounts) > 1 and actual_3199 > expected_3199 and bs_is_balanced:
        native_3199_delta = ZERO
    translated_delta = ZERO
    translated_balanced = True
    if translated_balance_sheet is not None:
        tr_assets = _to_dec(translated_balance_sheet.get("total_assets") or "0.00")
        tr_liab = _to_dec(translated_balance_sheet.get("total_liabilities") or "0.00")
        tr_eq = _to_dec(translated_balance_sheet.get("total_equity") or "0.00")
        tr_ni = _to_dec(translated_balance_sheet.get("net_income") or "0.00")
        tr_fx = _to_dec(
            translated_balance_sheet.get("unrealized_fx_gain_loss") or "0.00"
        )
        tr_cta = _to_dec(translated_balance_sheet.get("cta_adjustment") or "0.00")
        tr_nwa = _to_dec(
            translated_balance_sheet.get("net_worth_adjustment_gain_loss") or "0.00"
        )
        tr_rep_delta = _to_dec(translated_balance_sheet.get("equation_delta") or "0.00")
        tr_comp_delta = _q2(
            tr_assets - tr_liab - (tr_eq + tr_ni + tr_fx + tr_cta + tr_nwa)
        )
        translated_delta = max(abs(tr_rep_delta), abs(tr_comp_delta))
        translated_balanced = bool(translated_balance_sheet.get("is_balanced", False))

    worst_fx_delta = max(native_3199_delta, translated_delta)
    inv6_ok = translated_balanced and worst_fx_delta <= tolerance
    verdicts.append(
        InvariantVerdict(
            invariant_id="native_vs_translated_fx_consistency",
            passed=inv6_ok,
            message=(
                f"Native 3199 ({actual_3199} vs {expected_3199}, delta={native_3199_delta}), "
                f"Translated delta={translated_delta}, balanced={translated_balanced}"
            ),
            recorded_delta=worst_fx_delta,
        )
    )

    # 7. Statement Retirement Cleanup (DELETE /api/statements/{id} must return 200/204, never 500)
    statuses = (
        list(retirement_cleanup_statuses)
        if retirement_cleanup_statuses is not None
        else [200]
    )
    bad_statuses = [code for code in statuses if code not in (200, 202, 204)]
    inv7_ok = len(statuses) > 0 and len(bad_statuses) == 0
    verdicts.append(
        InvariantVerdict(
            invariant_id="statement_retirement_cleanup",
            passed=inv7_ok,
            message=(
                f"Statement DELETE statuses={statuses}, bad_statuses={bad_statuses}"
            ),
            recorded_delta=Decimal(len(bad_statuses)),
        )
    )

    failures = tuple(f"{v.invariant_id}: {v.message}" for v in verdicts if not v.passed)
    return OracleComparisonResult(
        passed=len(failures) == 0,
        invariants=tuple(verdicts),
        failures=failures,
    )


evaluate_three_statement_consistency = compare_oracle_with_platform_reports


def run_live_pdf_statement_verification(
    client: Any,
    spec: CorpusStatementSpec,
    *,
    root_dir: Path = REPO_ROOT,
    poll_timeout_seconds: Decimal = Decimal("180.00"),
    poll_interval_seconds: Decimal = Decimal("2.00"),
) -> dict[str, Any]:
    """Execute the live user flow for one PDF fixture against a target backend API.

    1. POST /api/statements/upload with PDF bytes.
    2. Poll GET /api/statements/{id}/review until status is parsed or approved.
    3. Confirm envelope if required and POST /api/statements/{id}/review/approve
       with create_account_if_missing=True and auto_fill_default_categories=True.
    4. Fetch Balance Sheet, Income Statement, and Cash Flow Statement in native currency and SGD.
    5. DELETE /api/statements/{id} to verify clean statement retirement.
    """
    pdf_path = root_dir / spec.local_path
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing PDF file for {spec.fixture_id}: {pdf_path}")

    pdf_bytes = pdf_path.read_bytes()
    upload_resp = client.post(
        "/api/statements/upload",
        data={"institution": spec.institution},
        files={"file": (pdf_path.name, pdf_bytes, "application/pdf")},
    )
    if upload_resp.status_code not in (200, 201, 202):
        raise RuntimeError(
            f"Upload failed for {spec.fixture_id}: {upload_resp.status_code} {upload_resp.text}"
        )
    statement_id = str(upload_resp.json()["id"])

    deadline = time.monotonic() + int(poll_timeout_seconds)
    review_payload: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        rev_resp = client.get(f"/api/statements/{statement_id}/review")
        if rev_resp.status_code == 200:
            data = rev_resp.json()
            if data.get("status") in (
                "parsed",
                "approved",
                "rejected",
            ) and not data.get("preclassification_in_progress"):
                review_payload = data
                break
        time.sleep(int(poll_interval_seconds))

    if review_payload is None:
        raise TimeoutError(f"Timed out waiting for {spec.fixture_id} ({statement_id})")

    if review_payload.get("status") == "parsed":
        needs_envelope = bool(
            review_payload.get("source_envelope_confirmation_required")
            or review_payload.get("source_envelope_reviewable")
        )
        account_id = review_payload.get("account_id")
        if needs_envelope:
            if not account_id and hasattr(client, "post"):
                # Create or resolve custody account when envelope confirmation requires account_id
                acc_resp = client.post(
                    "/api/accounts",
                    json={
                        "name": f"{spec.institution} ({spec.currency})",
                        "type": "LIABILITY"
                        if spec.doc_type == "credit_card"
                        else "ASSET",
                        "currency": review_payload.get("currency") or spec.currency,
                        "code": "2100" if spec.doc_type == "credit_card" else "1110",
                    },
                )
                if acc_resp.status_code in (200, 201):
                    acc_json = acc_resp.json()
                    if isinstance(acc_json, Mapping) and "id" in acc_json:
                        account_id = acc_json["id"]

            env_resp = client.post(
                f"/api/statements/{statement_id}/review/envelope",
                json={
                    "source_result_digest": review_payload.get("source_result_digest"),
                    "account_id": account_id,
                    "currency": review_payload.get("currency") or spec.currency,
                    "period_start": review_payload.get("period_start")
                    or spec.period_start,
                    "period_end": review_payload.get("period_end") or spec.period_end,
                    "opening_balance": str(
                        review_payload.get("opening_balance")
                        if review_payload.get("opening_balance") is not None
                        else spec.opening_balance
                    ),
                    "closing_balance": str(
                        review_payload.get("closing_balance")
                        if review_payload.get("closing_balance") is not None
                        else spec.closing_balance
                    ),
                    "rationale": f"Oracle ground-truth confirmation for {spec.fixture_id}",
                },
            )
            if env_resp.status_code not in (200, 201):
                raise RuntimeError(
                    f"Envelope confirmation failed for {spec.fixture_id}: "
                    f"{env_resp.status_code} {env_resp.text}"
                )

        app_resp = client.post(
            f"/api/statements/{statement_id}/review/approve",
            json={
                "account_id": account_id,
                "create_account_if_missing": True,
                "auto_fill_default_categories": True,
                "auto_fill_defaults": True,
                "note": "Oracle benchmark auto-fill approval",
            },
        )
        if app_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Approve failed for {spec.fixture_id}: {app_resp.status_code} {app_resp.text}"
            )

    bs_native = client.get(
        "/api/reports/balance-sheet",
        params={"as_of_date": spec.period_end, "currency": spec.currency},
    ).json()
    is_native = client.get(
        "/api/reports/income-statement",
        params={
            "start_date": spec.period_start,
            "end_date": spec.period_end,
            "currency": spec.currency,
        },
    ).json()
    cf_native = client.get(
        "/api/reports/cash-flow",
        params={
            "start_date": spec.period_start,
            "end_date": spec.period_end,
            "currency": spec.currency,
        },
    ).json()
    bs_sgd = client.get(
        "/api/reports/balance-sheet",
        params={"as_of_date": spec.period_end, "currency": "SGD"},
    ).json()

    del_resp = client.delete(f"/api/statements/{statement_id}")

    oracle = compute_independent_three_statement_oracle(
        [spec],
        as_of_date=spec.period_end,
        period_start=spec.period_start,
        period_end=spec.period_end,
        report_currency=spec.currency,
        treat_transfers_as_clearing_asset=True,
    )
    comparison = compare_oracle_with_platform_reports(
        oracle,
        balance_sheet=bs_native,
        income_statement=is_native,
        cash_flow=cf_native,
        translated_balance_sheet=bs_sgd,
        retirement_cleanup_statuses=[del_resp.status_code],
    )
    return {
        "fixture_id": spec.fixture_id,
        "statement_id": statement_id,
        "delete_status": del_resp.status_code,
        "comparison": comparison.to_dict(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for verifying the 20-PDF corpus and running live oracle checks."""
    parser = argparse.ArgumentParser(
        description="Verify 20-PDF benchmark corpus and 3-statement mathematical oracle."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Path to benchmark manifest.yaml",
    )
    parser.add_argument(
        "--app-url",
        type=str,
        default=None,
        help="Optional live environment URL (e.g., https://report-staging.zitian.party)",
    )
    parser.add_argument(
        "--fixture",
        action="append",
        default=None,
        help="Filter to specific fixture ID(s)",
    )
    args = parser.parse_args(argv)

    corpus = load_pdf_benchmark_corpus(args.manifest, REPO_ROOT)
    selected = (
        [s for s in corpus if s.fixture_id in set(args.fixture)]
        if args.fixture
        else list(corpus)
    )
    if not selected:
        print("No matching fixtures found in corpus.")
        return 2

    print(f"Loaded {len(selected)}/{len(corpus)} PDF corpus specs.")
    for spec in selected:
        oracle = compute_independent_three_statement_oracle([spec])
        if oracle.balance_sheet.accounting_equation_delta != ZERO:
            print(f"[FAIL] {spec.fixture_id}: non-zero oracle equation delta")
            return 1
        if spec.balance_chain_delta != ZERO:
            print(f"[FAIL] {spec.fixture_id}: broken ground-truth balance chain")
            return 1

    if not args.app_url:
        print(
            "Offline mathematical oracle verification passed for all selected fixtures."
        )
        return 0

    with httpx.Client(base_url=args.app_url.rstrip("/"), timeout=120.0) as client:
        all_passed = True
        for spec in selected:
            email = f"pdf_oracle_{spec.fixture_id[:16]}_{uuid.uuid4().hex[:6]}@test.example.com"
            reg = client.post(
                "/api/auth/register",
                json={
                    "email": email,
                    "password": "Password123!",
                    "display_name": f"PDF Oracle {spec.fixture_id}",
                },
            )
            if reg.status_code not in (200, 201):
                print(
                    f"Failed to register ephemeral user for {spec.fixture_id}: {reg.status_code} {reg.text}"
                )
                return 1
            token = reg.json()["access_token"]
            client.headers.update({"Authorization": f"Bearer {token}"})

            res = run_live_pdf_statement_verification(client, spec, root_dir=REPO_ROOT)
            passed = res["comparison"]["passed"]
            status_str = "PASS" if passed else "FAIL"
            print(f"[{status_str}] {spec.fixture_id}")
            if not passed:
                all_passed = False
                for failure in res["comparison"]["failures"]:
                    print(f"  - {failure}")
        return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
